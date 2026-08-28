"""A short description of each document, so the planner can choose between them.

The planner has to decide which document could hold an answer. It cannot do that
knowing only a filename, and it must not read pages -- that is the readers' job
and it costs minutes.

So each document gets a card: company, period, type, and which fiscal years its
figures cover. Built from the filename, because that is free and the corpus names
files consistently (`3M_2018_10K`, `3M_2023Q2_10Q`). No model call, no page reads.

**A card is a hint, not a fact.** Filenames are user-controlled. A file called
`document1.pdf` yields a card with nothing in it, and the planner is told that a
document it cannot describe must never be excluded -- only ranked lower. Guessing
wrong about a filename should cost nothing.

The `covers` field is the one that earns its keep. A 2019 10-K prints three years
of income statement and cash flow, so it answers questions about 2017 as well as
2019. A planner reasoning only from "this is the 2019 filing" would send a 2017
question to the wrong document, or to no document at all.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

# `3M_2018_10K`, `3M_2023Q2_10Q`, `FOOTLOCKER_2022_8K_dated-2022-05-20`
_NAME = re.compile(
    r"^(?P<company>.+?)[_\- ]"
    r"(?P<year>(?:19|20)\d{2})"
    r"(?:Q(?P<quarter>[1-4]))?"
    r"[_\- ]"
    r"(?P<kind>10[-_ ]?K|10[-_ ]?Q|8[-_ ]?K|20[-_ ]?F|ARS?)",
    re.IGNORECASE,
)

_KINDS = {
    "10K": "10-K",
    "10Q": "10-Q",
    "8K": "8-K",
    "20F": "20-F",
    "AR": "annual report",
    "ARS": "annual report",
}

# How many fiscal years of figures a filing reports.
#
# A 10-K's income statement and cash flow statement carry three years and its
# balance sheet two, so the filing answers questions about the two years before
# it as well as its own. A 10-Q carries the quarter and the prior-year quarter.
# An 8-K reports one event and covers nothing.
_YEARS_COVERED = {"10-K": 3, "20-F": 3, "annual report": 3, "10-Q": 2, "8-K": 1}


@dataclass
class DocumentCard:
    """What is known about one document without reading it."""

    doc_name: str
    page_count: int = 0
    company: Optional[str] = None
    fiscal_year: Optional[int] = None
    quarter: Optional[int] = None
    doc_type: Optional[str] = None
    #: Fiscal years whose figures this document reports, newest first.
    covers: List[int] = field(default_factory=list)

    @property
    def described(self) -> bool:
        """Whether anything was learned. An undescribed document is never excluded."""
        return self.fiscal_year is not None

    @property
    def period(self) -> str:
        if self.fiscal_year is None:
            return ""
        if self.quarter:
            return f"FY{self.fiscal_year} Q{self.quarter}"
        return f"FY{self.fiscal_year}"

    def describe(self) -> str:
        """One line for the planner's prompt."""
        parts = [f"{self.doc_name} ({self.page_count} pages)"]
        if self.company:
            parts.append(self.company)
        if self.period:
            parts.append(self.period)
        if self.doc_type:
            parts.append(self.doc_type)
        line = " — ".join(parts)
        if self.covers:
            years = ", ".join(str(year) for year in self.covers)
            line += f" — reports figures for {years}"
        if not self.described:
            line += " — period unknown, cannot be ruled out"
        return line

    def to_dict(self) -> Dict[str, object]:
        return {
            "doc_name": self.doc_name,
            "page_count": self.page_count,
            "company": self.company,
            "fiscal_year": self.fiscal_year,
            "quarter": self.quarter,
            "doc_type": self.doc_type,
            "covers": list(self.covers),
        }


def card_for(doc_name: str, page_count: int = 0) -> DocumentCard:
    """Read what a filename says about a document. Never raises."""
    card = DocumentCard(doc_name=doc_name, page_count=page_count)
    match = _NAME.search(doc_name)
    if not match:
        return card

    company = match.group("company").replace("_", " ").strip()
    card.company = company or None
    card.fiscal_year = int(match.group("year"))
    quarter = match.group("quarter")
    card.quarter = int(quarter) if quarter else None

    kind = re.sub(r"[-_ ]", "", match.group("kind")).upper()
    card.doc_type = _KINDS.get(kind)

    span = _YEARS_COVERED.get(card.doc_type or "", 1)
    card.covers = [card.fiscal_year - offset for offset in range(span)]
    return card


def cards_for(documents: Sequence[str], page_counts: Optional[Dict[str, int]] = None) -> List[DocumentCard]:
    counts = page_counts or {}
    return [card_for(name, counts.get(name, 0)) for name in documents]


def describe_cards(cards: Sequence[DocumentCard]) -> str:
    """The document list as the planner sees it."""
    if not cards:
        return "(no documents are loaded)"
    return "\n".join(f"  {index}. {card.describe()}" for index, card in enumerate(cards, start=1))


def documents_covering(cards: Sequence[DocumentCard], year: int) -> List[str]:
    """
    Which documents report figures for a fiscal year.

    Used for the one scoping decision that needs no model: a year that exactly one
    document covers can be scoped to it with certainty. Documents whose period is
    unknown are always included, because a card that knows nothing must not
    exclude anything.
    """
    return [
        card.doc_name
        for card in cards
        if year in card.covers or not card.described
    ]


_YEAR_IN_QUESTION = re.compile(r"\b(?:fy|cy|fiscal year)?\s?((?:19|20)\d{2})\b", re.IGNORECASE)


def years_mentioned(question: str) -> List[int]:
    """Fiscal years named in a question, in the order written."""
    seen: List[int] = []
    for match in _YEAR_IN_QUESTION.finditer(question):
        year = int(match.group(1))
        if year not in seen:
            seen.append(year)
    return seen
