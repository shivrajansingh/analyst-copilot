"""Answering from what this thread already said, or admitting it cannot.

The cheapest answer to "what was that capex figure again" is the one already on
screen. Searching the filing a second time costs seconds and money to reproduce
a number the assistant proved ten seconds ago.

That is the whole case for this module, and it is a narrow one. Everything else
here exists to stop it becoming something worse. `prompts.format_history` trims
the transcript to six turns of 400 characters deliberately, because a model shown
a full transcript will answer a *new* question from an old turn's figures, and
that is how a citation ends up attached to a number it never proved. Recall needs
the full transcript, so it has to buy that safety back another way:

- **A recalled answer reuses the earlier answer's citation.** It never mints one.
  The page it shows is the page that was actually retrieved and verified.
- **No citation, no recall.** A turn that declined, or answered conversationally,
  or was itself recalled, cannot be a source. Only a turn with `found` true and a
  page can be restated.
- **Restate, never derive.** The prompt forbids arithmetic, comparison and
  combining turns. "Is that up or down" is a new question with no verifier behind
  it on this path, so it belongs in retrieval.
- **Abstaining is free.** Every failure -- no source, an unusable index, a dead
  model, unparseable output -- returns `found=False`, and the caller runs the
  ordinary search. The worst case is one wasted call.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from analyst_copilot.llm.base import ChatClient
from analyst_copilot.services.qa.parser import load_json_object

logger = logging.getLogger(__name__)


@dataclass
class HistoryTurn:
    """
    One stored turn, with the outcome the API kept alongside it.

    `page` and `doc_name` are what make a turn quotable. A turn that carries
    neither is still shown to the model as context but can never be cited, and
    `citable` is the single place that rule is decided.
    """

    role: str
    content: str
    found: Optional[bool] = None
    page: Optional[int] = None
    doc_name: str = ""

    @property
    def citable(self) -> bool:
        return (
            self.role == "assistant"
            and bool(self.found)
            and self.page is not None
            and bool(self.content.strip())
        )


def turns_from(history: Sequence[dict]) -> List[HistoryTurn]:
    """Read stored turns. Unknown keys are ignored; missing ones are not fatal."""
    turns: List[HistoryTurn] = []
    for row in history or []:
        content = str(row.get("content") or "").strip()
        if not content:
            continue
        page = row.get("page")
        turns.append(
            HistoryTurn(
                role=str(row.get("role") or ""),
                content=content,
                found=row.get("found"),
                page=int(page) if isinstance(page, int) else None,
                doc_name=str(row.get("doc_name") or ""),
            )
        )
    return turns


@dataclass
class Recollection:
    """What the thread could offer. `found` false means: go and search."""

    found: bool = False
    answer: str = ""
    #: The turn restated. Always citable when `found` is true.
    source: Optional[HistoryTurn] = None
    reason: str = ""
    raw: str = ""
    error: Optional[str] = None


class RecallPayload(BaseModel):
    """
    The shape the recall model must return.

    `source` is an index into the citable turns the prompt numbered, not into the
    transcript, so the model cannot cite a turn that was never offered. Strict for
    the same reason `PlanPayload` is: a repaired answer teaches nothing about the
    prompt.
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    found: bool = False
    source: Optional[int] = None
    answer: str = ""
    reason: str = ""


SYSTEM = """You are given a conversation between an analyst and a filing assistant,
and the analyst's newest message. You decide one thing: has this thread **already
answered** the newest message?

You are not answering the question. You are finding the answer that is already
written, and restating it.

Say yes only when a numbered earlier answer contains what is being asked for. The
analyst is asking to be told again — the same question, the same question in
different words, or "say that again".

Say no to everything else. In particular, say no when:

- the message asks about a period, a segment or a topic no earlier answer covers;
- answering would need arithmetic, a comparison, a trend, or two answers combined
  — "is that up or down", "what's the difference", "how did it change";
- answering would need more detail than the earlier answer gave — "tell me more",
  "what else did it say";
- the earlier turn declined, or was unsure, or was a greeting.

Saying no is free. The assistant will go and read the filing, which is what it is
for. Saying yes wrongly puts a figure in front of an analyst with a page number
that does not prove it, which is the one failure this product exists to prevent.

**answer** — the earlier answer restated, as a direct reply to the newest message.
Keep the figure, the units and the wording. Do not round, convert, recompute or
embellish. Do not write a page number into the text; the page comes from the turn
you cited.

Return JSON only, no markdown fences:
{"found": true, "source": <the number of the answer you are restating>, "answer": "...", "reason": "..."}
{"found": false, "source": null, "answer": "", "reason": "why the thread cannot answer it"}"""


def build_prompt(message: str, turns: Sequence[HistoryTurn], citable: Sequence[HistoryTurn]) -> str:
    """
    The transcript, with the quotable answers numbered.

    Every turn is shown, so the message can be understood in context. Only the
    citable ones get a number, and only a number can be cited -- the model is
    never given a way to name a turn it is not allowed to use.
    """
    index = {id(turn): number for number, turn in enumerate(citable, start=1)}
    lines: List[str] = []
    for turn in turns:
        who = "Analyst" if turn.role == "user" else "Assistant"
        number = index.get(id(turn))
        tag = f"[answer {number}]" if number else "[not quotable]"
        lines.append(f"{who} {tag}: {turn.content}")

    quotable = (
        "\n".join(
            f"  {number}. {turn.content[:200]}"
            for number, turn in enumerate(citable, start=1)
        )
        or "  (none — no earlier answer carries a page, so nothing can be restated)"
    )
    return (
        "Conversation so far:\n"
        + "\n".join(lines)
        + "\n\nAnswers you may restate, by number:\n"
        + quotable
        + f"\n\nThe analyst's newest message:\n{message}\n\nReturn JSON only."
    )


class HistoryAnswerer:
    """Restates an answer this thread already gave, or declines to."""

    def __init__(self, chat_client: Optional[ChatClient] = None, max_tokens: int = 700) -> None:
        self._chat = chat_client
        self._max_tokens = max_tokens

    def recall(self, message: str, history: Sequence[dict]) -> Recollection:
        """Look for the answer in the thread. Never raises."""
        turns = turns_from(history)
        citable = [turn for turn in turns if turn.citable]
        if not citable:
            # Nothing in this thread can be cited, so there is nothing to restate.
            # Not worth a model call to confirm.
            return Recollection(reason="no earlier answer in this thread carries a page")
        if self._chat is None:
            return Recollection(reason="no recall model configured")

        try:
            raw = self._chat.complete(
                messages=[
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": build_prompt(message, turns, citable)},
                ],
                temperature=0.0,
                max_tokens=self._max_tokens,
            )
        except Exception as exc:  # noqa: BLE001 - a dead recall must fall through, not fail
            logger.warning("recall failed, falling through to retrieval: %s", exc)
            return Recollection(reason=f"recall unavailable: {exc}", error=str(exc))

        obj = load_json_object(raw)
        if obj is None:
            return Recollection(
                reason="recall returned no JSON object", raw=raw, error="no JSON object"
            )
        try:
            payload = RecallPayload.model_validate(obj)
        except ValidationError as exc:
            reason = "; ".join(
                f"{'.'.join(str(part) for part in error.get('loc', ())) or '(root)'}: "
                f"{error.get('msg', 'invalid')}"
                for error in exc.errors()
            )
            logger.warning("recall output rejected (%s): %s", reason, raw[:400])
            return Recollection(reason=f"invalid recall: {reason}", raw=raw, error=reason)

        if not payload.found:
            return Recollection(reason=payload.reason or "not answered in this thread", raw=raw)

        # The three ways a "yes" is still a no. Each of them would otherwise put an
        # unproven figure on screen under a real page number.
        if payload.source is None or not 1 <= payload.source <= len(citable):
            return Recollection(
                reason=f"cited answer {payload.source} does not exist", raw=raw,
                error="source out of range",
            )
        if not payload.answer:
            return Recollection(reason="recall returned no answer text", raw=raw)

        return Recollection(
            found=True,
            answer=payload.answer,
            source=citable[payload.source - 1],
            reason=payload.reason,
            raw=raw,
        )
