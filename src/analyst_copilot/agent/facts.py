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


def thread_facts(history: Sequence[dict]) -> str:
    """
    Facts about this conversation, computed rather than read.

    The transcript analogue of `corpus_facts`, and it exists for the same reason:
    "what was the first question?" has an exact answer sitting in a list of rows,
    and answering it by reading 36 pages of a 10-K is the same category of mistake
    as counting documents by searching them.

    The same rule applies -- everything here is computed in Python and the model's
    only job is to say it in a sentence. It must not count the turns itself, and
    it has nothing to quote if it tries: the numbering is supplied.

    `history` excludes the message being answered, because the exchange is
    recorded only after the answer exists. So "the last question" means the one
    before this one, which is what an analyst means by it.
    """
    asked = [
        str(turn.get("content") or "").strip()
        for turn in history or []
        if turn.get("role") == "user" and str(turn.get("content") or "").strip()
    ]
    if not asked:
        return (
            "Questions asked so far in this conversation: 0\n"
            "No question has been asked yet in this conversation — the message "
            "being answered now is the first one. There is no earlier question to "
            "report, and nothing in any document can supply one."
        )

    lines: List[str] = [f"Questions asked so far in this conversation: {len(asked)}"]
    lines.append(f'The first question was: "{asked[0]}"')
    if len(asked) > 1:
        lines.append(f'The most recent question before this one was: "{asked[-1]}"')
    else:
        lines.append(
            "There has been only one question before this one, so it is both the "
            "first and the most recent."
        )
    lines.append("")
    lines.append("Every question asked, in order:")
    for index, question in enumerate(asked, start=1):
        lines.append(f'  {index}. "{question}"')
    return "\n".join(lines)


def thread_summary(history: Sequence[dict]) -> str:
    """
    The transcript answered in a sentence, with no model involved.

    The last resort for a `thread_meta` message: if the conversational reply asks
    for the document -- which no filing can satisfy -- this answers from the same
    computed facts rather than reading 189 pages to fail.
    """
    asked = [
        str(turn.get("content") or "").strip()
        for turn in history or []
        if turn.get("role") == "user" and str(turn.get("content") or "").strip()
    ]
    if not asked:
        return (
            "You have not asked anything yet in this conversation — this is your "
            "first message. Ask me about a figure, a policy or a trend in the "
            "selected filing and I will go and look."
        )
    parts = [
        f"You have asked {len(asked)} question{'' if len(asked) == 1 else 's'} "
        f"in this conversation so far."
    ]
    parts.append(f'The first was: "{asked[0]}"')
    if len(asked) > 1:
        parts.append(f'The most recent before this one was: "{asked[-1]}"')
    return " ".join(parts)
