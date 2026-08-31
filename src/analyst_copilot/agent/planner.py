"""One decision, taken before any work happens: what does this message need?

This replaces the router. The router decided the same thing from 125 hardcoded
tokens -- 49 greeting phrases, 15 capability phrases, 61 finance terms and a magic
word count -- and each of those was a guess about how an analyst would phrase
something. The guesses leaked: "how many pages does this filing have" was read as
a question *from* the filing because "filing" was on the finance list, and it was
answered by searching 189 pages for a number that lives in a manifest.

A word list cannot classify intent. It can only approximate it. So the planner
asks a model, once, with everything needed to answer well: the message, the recent
turns, and a one-line card per document.

It decides four things:

  kind        which path runs at all
  question    the message rewritten to stand on its own
  documents   which documents could hold the answer
  confidence  how sure it is, where unsure means "do not narrow"

**No decision here is final.** Every branch has a way out, because a planner that
cannot be overruled is a single point of failure in front of the whole product:

  smalltalk / capability  ->  the reply may say "this needs the document"
  corpus_meta             ->  facts that cannot answer fall through to a search
  document, scoped        ->  a scoped search that finds nothing widens

That is the whole reason a model is allowed to make this call. A wrong guess costs
seconds, not an answer.

The one thing it must never do is narrow past what is provably needed. Document
cards are filename-derived hints, so `_reconcile_scope` re-adds any document that
covers a year the question names, whatever the model proposed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Sequence

from analyst_copilot.agent.cards import (
    DocumentCard,
    describe_cards,
    documents_covering,
    years_mentioned,
)
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from analyst_copilot.llm.base import ChatClient
from analyst_copilot.services.qa.parser import load_json_object

logger = logging.getLogger(__name__)


class PlanKind(str, Enum):
    SMALLTALK = "smalltalk"        # a greeting, thanks, anything sociable
    CAPABILITY = "capability"      # about the assistant itself
    CORPUS_META = "corpus_meta"    # about the document set, not its contents
    THREAD_META = "thread_meta"    # about this conversation, not its subject
    HISTORY = "history"            # already answered earlier in this thread
    DOCUMENT = "document"          # needs the documents read

    @property
    def needs_documents(self) -> bool:
        """
        Whether the documents must be searched to answer.

        `history` is False here and still reaches retrieval most of the time:
        the recall step is allowed to fail, and a failed recall becomes a
        `document` plan. This property is about what the *plan* claims, not what
        the run ends up doing.
        """
        return self is PlanKind.DOCUMENT


@dataclass
class Plan:
    kind: PlanKind
    #: The message rewritten to stand alone. Equal to the message when it already did.
    question: str
    #: Documents worth searching. Empty means "all of them".
    documents: List[str] = field(default_factory=list)
    confidence: float = 0.0
    reason: str = ""
    #: True when the model was never asked -- a fallback, not a heuristic.
    assumed: bool = False

    @property
    def scoped(self) -> bool:
        return bool(self.documents)


class PlanPayload(BaseModel):
    """
    The shape the planner model must return. Strict on purpose.

    This is the contract the system prompt describes, written down where it can
    be checked. Anything that does not fit -- a `kind` outside the enum, a
    confidence of 1.4 or `"high"`, `documents` as a bare string -- is a
    ValidationError, and `Planner` falls back to searching everything. Repairing
    off-spec output silently would make the prompt untunable: you would never see
    which edit stopped the model returning what it was asked for.

    The one thing normalised before validation is `question`, which `Planner`
    fills from the analyst's message when the model omits it. That is a default,
    not a repair -- a message that already stands alone is its own resolution.
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    kind: PlanKind
    question: str = Field(min_length=1)
    documents: List[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""

    @field_validator("documents", mode="before")
    @classmethod
    def _reject_bare_string(cls, value: object) -> object:
        # `"documents": "3M_2018_10K"` would otherwise validate as a list of
        # characters. A scope of 13 one-letter filenames matches nothing and the
        # search silently returns empty, so refuse it and search everything.
        if isinstance(value, str):
            raise ValueError("documents must be a list, not a string")
        return value

    @field_validator("documents")
    @classmethod
    def _drop_blanks(cls, value: List[str]) -> List[str]:
        return [name for name in (item.strip() for item in value) if name]


@dataclass
class PlanAttempt:
    """
    One planning call with its working shown.

    `Planner.plan` returns only the `plan`, which is all the pipeline needs. This
    carries the rest -- the prompt sent, the text that came back, and why it was
    rejected if it was -- so the prompt and the validator can be tuned against
    what the model actually said rather than against the fallback it produced.
    """

    plan: Plan
    prompt: str = ""
    raw: str = ""
    payload: Optional[PlanPayload] = None
    error: Optional[str] = None

    @property
    def validated(self) -> bool:
        return self.payload is not None


SYSTEM = """You decide what work an analyst's message needs, before any work is done.

You are looking at a financial-filing assistant. It can search the documents it
holds, cite the page an answer came from, and decline when the evidence is not
there. You decide which of four things this message needs.

**kind** — one of:

- `smalltalk` — a greeting, thanks, an apology, anything sociable. "Hi",
  "thanks, that helps".
- `capability` — about the assistant itself: what it can do, how it works, what
  formats it takes, why it declined.
- `corpus_meta` — about the **document set**, not about what is inside the
  documents. How many documents there are, what they are called, which years or
  companies they cover, how many pages one has. The answer is in a list of files,
  not in a filing.
- `thread_meta` — about **this conversation itself**, not about anything in a
  filing. What was asked, when, how many times, in what order. "what was the
  first question", "what did I just ask", "how many questions have I asked",
  "what have we talked about". The answer is in the list of messages on screen.
  No document can contain it, and if nothing has been asked yet the honest answer
  is that nothing has been asked yet.
- `history` — **this thread has already answered it.** The analyst is asking for
  an answer you can point at in the turns above: the same question again, the
  same question reworded, or a request to restate one. "what was that capex
  figure again", "say that again", "what did you tell me about the segments".
- `document` — anything that needs a document read to answer. Every question
  about a figure, a policy, a risk, a segment, a trend, a person or a date. Also
  every follow-up that only makes sense against an earlier turn.

The line between `corpus_meta` and `document` is *what the question is about*:

    "how many documents do you have"        -> corpus_meta  (about the set)
    "which years do these filings cover"    -> corpus_meta  (about the set)
    "how many pages is the 2018 10-K"       -> corpus_meta  (about the set)
    "what was revenue in 2018"              -> document     (inside a filing)
    "how many segments does 3M report"      -> document     (inside a filing)
    "how many employees does it have"       -> document     (inside a filing)

Note the last three: "how many" does not make something corpus_meta. Counting
segments or employees means reading a filing.

Keep `thread_meta` and `history` apart. `thread_meta` is about the *questions*;
`history` is about the *answers*:

    "what was the 1st question"             -> thread_meta  (about the transcript)
    "what did I just ask you"               -> thread_meta  (about the transcript)
    "how many things have I asked"          -> thread_meta  (about the transcript)
    "what was that capex figure again"      -> history      (restating an answer)

A `thread_meta` message must never be sent to the documents. Searching a 10-K for
what the analyst typed two minutes ago cannot succeed, and reading every page to
fail is the worst outcome the planner can produce.

`history` is the narrowest of the five and the easiest to over-use. It means the
answer is **already written above**, not that the message refers to something
above:

    "what was that capex figure again"      -> history      (restating an answer)
    "sorry, repeat the segment count"       -> history      (restating an answer)
    "and the year before?"                  -> document     (a new year, never answered)
    "is that up or down?"                   -> document     (a comparison, never made)
    "tell me more about that"               -> document     (more than was said)

If you cannot point at the turn that already contains the answer, it is
`document`. A wrong `history` costs one wasted call and then searches anyway; it
is still the classification to be most careful with, because the analyst asked
to be told something and deserves the document, not a paraphrase of a paraphrase.

**question** — the message rewritten so it stands on its own, using the earlier
turns. "and the year before?" becomes "What was 3M's capital expenditure in
FY2017?". If the message already stands alone, repeat it unchanged. Never add a
constraint the analyst did not ask for.

**documents** — which documents could hold the answer. Rules:

- Give the document's **exact name**, copied from the start of its card line —
  `3M_2018_10K`, not `3M 2018 10-K`, and never the list number in front of it.
  A number or a paraphrase matches no document and is thrown away.
- Return an empty list to search everything. That is the right answer whenever
  you are not sure.
- Only narrow when the question names a period and the cards tell you which
  documents report that period. Use the "reports figures for" line: a 2019 10-K
  reports 2019, 2018 and 2017, so a 2017 question belongs to it.
- A document whose period is unknown can never be ruled out. Always include it.
- Comparisons need every document involved. "How did margin move from 2018 to
  2022" needs both.
- Never narrow to fewer documents than the question needs. Searching one document
  too many wastes time. Searching one too few loses the answer.

**confidence** — 0 to 1, for the narrowing. Below 0.8, return an empty
`documents` list instead.

Return JSON only, no markdown fences:
{"kind": "...", "question": "...", "documents": ["<exact document name>"], "confidence": 0.0, "reason": "..."}

When you cannot tell, choose `document` with an empty `documents` list. Searching
a filing for a greeting wastes a few seconds and then declines honestly.
Answering a real question without reading the filing invents something."""


def build_prompt(message: str, cards: Sequence[DocumentCard], history: str = "") -> str:
    prior = f"Earlier in this conversation:\n{history}\n\n" if history else ""
    return (
        f"{prior}Documents loaded in the current filing set:\n"
        f"{describe_cards(cards)}\n\n"
        f"Analyst's message:\n{message}\n\nReturn JSON only."
    )


class Planner:
    """Classifies a message, resolves it, and chooses which documents to search."""

    def __init__(
        self,
        chat_client: Optional[ChatClient] = None,
        scope_documents: bool = True,
        require_named_year: bool = True,
        min_confidence: float = 0.8,
    ) -> None:
        self._chat = chat_client
        self._scope_documents = scope_documents
        # The careful policy: narrow only when the question names a year, so the
        # scope can be checked against the cards rather than trusted.
        self._require_named_year = require_named_year
        self._min_confidence = min_confidence

    def plan(
        self,
        message: str,
        cards: Sequence[DocumentCard] = (),
        history: str = "",
    ) -> Plan:
        """Decide what this message needs. Never raises."""
        return self.explain(message, cards, history).plan

    def explain(
        self,
        message: str,
        cards: Sequence[DocumentCard] = (),
        history: str = "",
    ) -> PlanAttempt:
        """
        Plan, and keep the prompt, the raw reply and the validation error.

        The same code path `plan` takes -- this is not a debug mode that can drift
        from the real one. It only declines to throw the evidence away.
        """
        if self._chat is None:
            return PlanAttempt(
                plan=self._fallback(message, "no planner model configured"),
                error="no planner model configured",
            )

        prompt = build_prompt(message, cards, history)
        try:
            raw = self._chat.complete(
                messages=[
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
                max_tokens=800,
            )
        except Exception as exc:  # noqa: BLE001 - a dead planner must not lose the question
            logger.warning("planning failed, treating as a document question: %s", exc)
            return PlanAttempt(
                plan=self._fallback(message, f"planner unavailable: {exc}"),
                prompt=prompt,
                error=f"planner unavailable: {exc}",
            )

        obj = load_json_object(raw)
        if obj is None:
            reason = "planner returned no JSON object"
            logger.warning("%s: %s", reason, raw[:400])
            return PlanAttempt(
                plan=self._fallback(message, reason), prompt=prompt, raw=raw, error=reason
            )

        # The one normalisation: an omitted question means the message already
        # stood alone. Everything else must arrive as the prompt asked for it.
        obj.setdefault("question", message)
        if not str(obj.get("question") or "").strip():
            obj["question"] = message

        try:
            payload = PlanPayload.model_validate(obj)
        except ValidationError as exc:
            reason = _describe_validation_error(exc)
            logger.warning("planner output rejected (%s): %s", reason, raw[:400])
            return PlanAttempt(
                plan=self._fallback(message, f"invalid plan: {reason}"),
                prompt=prompt,
                raw=raw,
                error=reason,
            )

        documents = self._reconcile_scope(
            proposed=payload.documents,
            question=payload.question,
            message=message,
            cards=cards,
            confidence=payload.confidence,
        )
        plan = Plan(
            kind=payload.kind,
            question=payload.question,
            documents=documents,
            confidence=payload.confidence,
            reason=payload.reason,
        )
        return PlanAttempt(plan=plan, prompt=prompt, raw=raw, payload=payload)

    # -- scoping ------------------------------------------------------------ #
    def _reconcile_scope(
        self,
        proposed: Sequence[str],
        question: str,
        message: str,
        cards: Sequence[DocumentCard],
        confidence: float,
    ) -> List[str]:
        """
        Turn the model's document list into one that cannot lose the answer.

        Returns an empty list -- meaning "search everything" -- for anything the
        cards cannot confirm. The model may narrow the search; it may not narrow
        it past what the question provably needs.
        """
        known = [card.doc_name for card in cards]
        if not self._scope_documents or len(known) < 2:
            return []
        if confidence < self._min_confidence:
            return []

        names = [name for name in proposed if name in known]
        if not names or len(names) >= len(known):
            return []

        # The years the question is actually about, from the resolved form as well
        # as the original -- resolution is where a year usually appears.
        years = years_mentioned(question) or years_mentioned(message)
        if self._require_named_year and not years:
            return []

        # Whatever the model proposed, every document that reports a year the
        # question names goes back in. Cards are filename hints, and a hint must
        # not be able to exclude a document that demonstrably covers the period.
        required: List[str] = []
        for year in years:
            for name in documents_covering(cards, year):
                if name not in required:
                    required.append(name)

        combined = [name for name in known if name in set(names) | set(required)]
        if len(combined) >= len(known):
            return []  # nothing was actually excluded
        return combined

    @staticmethod
    def _fallback(message: str, reason: str) -> Plan:
        """
        What to do when planning is impossible.

        A document question over every document: the only choice that cannot lose
        an answer. Searching a filing for a greeting is a few wasted seconds.
        """
        return Plan(
            kind=PlanKind.DOCUMENT,
            question=message,
            documents=[],
            confidence=0.0,
            reason=reason,
            assumed=True,
        )


def _describe_validation_error(exc: ValidationError) -> str:
    """One line per rejected field, short enough to log and read in a table."""
    parts = []
    for error in exc.errors():
        field = ".".join(str(item) for item in error.get("loc", ())) or "(root)"
        parts.append(f"{field}: {error.get('msg', 'invalid')}")
    return "; ".join(parts) or "invalid plan"
