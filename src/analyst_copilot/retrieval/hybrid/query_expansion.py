"""Expand analyst questions with financial-statement synonyms."""

from __future__ import annotations

from typing import List, Sequence, Tuple

SynonymGroup = Tuple[str, ...]

# If the query contains any phrase in a group, the rest of the group is appended.
_SYNONYM_GROUPS: Sequence[SynonymGroup] = (
    (
        "capital expenditure",
        "capital expenditures",
        "capex",
        "capital spending",
        "purchases of property plant and equipment",
        "property plant and equipment",
        "pp&e",
    ),
    (
        "cash flow statement",
        "consolidated statement of cash flows",
        "statement of cash flows",
        "cash flows from investing",
    ),
    (
        "balance sheet",
        "consolidated balance sheet",
        "statement of financial position",
    ),
    (
        "income statement",
        "consolidated statement of income",
        "statement of operations",
        "net sales",
    ),
    (
        "effective tax rate",
        "provision for income taxes",
        "income tax expense",
    ),
)


class FinancialQueryExpander:
    """Append SEC line-item wording that analysts often omit from questions."""

    def expand(self, query: str) -> str:
        lowered = query.lower()
        extras: List[str] = []
        for group in _SYNONYM_GROUPS:
            if any(phrase in lowered for phrase in group):
                extras.extend(phrase for phrase in group if phrase not in lowered)

        if not extras:
            return query
        return f"{query} {' '.join(extras)}"
