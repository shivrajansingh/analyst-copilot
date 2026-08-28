"""Facts about the document set, computed rather than read.

"How many documents do you have?" has an exact answer sitting in a manifest. It
went through retrieval and 189 pages of readers because nothing in the pipeline
distinguished a question *about* the filing set from a question *from* it.

Two rules here, and the second is the important one:

1. Everything is computed in Python. Counts, years, page totals.
2. **The model is given these facts and forbidden from calculating.** A model
   asked "how many documents" while looking at a list will usually count
   correctly and occasionally not, and there is no verifier on this path -- there
   is nothing to verify against, since the answer is not in any document. So the
   count arrives pre-computed and the model's only job is to say it in a sentence.

If a question cannot be answered from what is here, that is not a failure to
paper over: it falls through to a real search.
"""

from __future__ import annotations

from collections import Counter
from typing import List, Sequence

from analyst_copilot.agent.cards import DocumentCard


def corpus_facts(cards: Sequence[DocumentCard], collection: str = "") -> str:
    """
    Everything known about the document set, as facts a model may quote.

    Written as a flat block of already-computed values, so answering any of the
    common questions is quoting rather than counting.
    """
    if not cards:
        return "Documents loaded: 0. The filing set is empty."

    lines: List[str] = []
    if collection:
        lines.append(f"Filing set name: {collection}")
    lines.append(f"Number of documents loaded: {len(cards)}")

    total_pages = sum(card.page_count for card in cards)
    if total_pages:
        lines.append(f"Total pages across all documents: {total_pages}")

    companies = _unique(card.company for card in cards if card.company)
    if companies:
        lines.append(f"Companies: {', '.join(companies)}")

    years = sorted({card.fiscal_year for card in cards if card.fiscal_year}, reverse=True)
    if years:
        lines.append(f"Fiscal years of the documents themselves: {_join_numbers(years)}")

    reported = sorted({year for card in cards for year in card.covers}, reverse=True)
    if reported:
        # Not the same list as above, and the difference matters: a 2019 10-K
        # reports 2017 too, so the set answers questions about years no document
        # is named for.
        lines.append(f"Fiscal years with figures available: {_join_numbers(reported)}")

    kinds = Counter(card.doc_type for card in cards if card.doc_type)
    if kinds:
        lines.append(
            "Document types: "
            + ", ".join(f"{count} x {kind}" for kind, count in kinds.most_common())
        )

    undescribed = [card.doc_name for card in cards if not card.described]
    if undescribed:
        lines.append(
            "Documents whose period could not be read from their filename: "
            + ", ".join(undescribed)
        )

    lines.append("")
    lines.append("Each document:")
    for index, card in enumerate(cards, start=1):
        lines.append(f"  {index}. {card.describe()}")

    return "\n".join(lines)


def _unique(values) -> List[str]:
    seen: List[str] = []
    for value in values:
        if value not in seen:
            seen.append(value)
    return seen


def _join_numbers(values: Sequence[int]) -> str:
    return ", ".join(str(value) for value in values)
