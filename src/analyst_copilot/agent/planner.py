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
from analyst_copilot.llm.base import ChatClient
from analyst_copilot.services.qa.parser import load_json_object

logger = logging.getLogger(__name__)


class PlanKind(str, Enum):
    SMALLTALK = "smalltalk"        # a greeting, thanks, anything sociable
    CAPABILITY = "capability"      # about the assistant itself
    CORPUS_META = "corpus_meta"    # about the document set, not its contents
    DOCUMENT = "document"          # needs the documents read

    @property
    def needs_documents(self) -> bool:
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

**question** — the message rewritten so it stands on its own, using the earlier
turns. "and the year before?" becomes "What was 3M's capital expenditure in
FY2017?". If the message already stands alone, repeat it unchanged. Never add a
constraint the analyst did not ask for.

**documents** — which documents could hold the answer. Rules:

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
{"kind": "...", "question": "...", "documents": [...], "confidence": 0.0, "reason": "..."}

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
        if self._chat is None:
            return self._fallback(message, "no planner model configured")

        try:
            raw = self._chat.complete(
                messages=[
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": build_prompt(message, cards, history)},
                ],
                temperature=0.0,
                max_tokens=800,
            )
        except Exception as exc:  # noqa: BLE001 - a dead planner must not lose the question
            logger.warning("planning failed, treating as a document question: %s", exc)
            return self._fallback(message, f"planner unavailable: {exc}")

        payload = load_json_object(raw) or {}
        try:
            kind = PlanKind(str(payload.get("kind") or "").strip().lower())
        except ValueError:
            return self._fallback(
                message, f"unrecognised plan kind {payload.get('kind')!r}"
            )

        question = str(payload.get("question") or "").strip() or message
        reason = str(payload.get("reason") or "").strip()
        confidence = _as_float(payload.get("confidence"))
        documents = self._reconcile_scope(
            proposed=payload.get("documents"),
            question=question,
            message=message,
            cards=cards,
            confidence=confidence,
        )
        return Plan(
            kind=kind,
            question=question,
            documents=documents,
            confidence=confidence,
            reason=reason,
        )

    # -- scoping ------------------------------------------------------------ #
    def _reconcile_scope(
        self,
        proposed: object,
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

        names = [
            name for name in (proposed if isinstance(proposed, list) else []) if name in known
        ]
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


def _as_float(value: object) -> float:
    try:
        return min(1.0, max(0.0, float(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
