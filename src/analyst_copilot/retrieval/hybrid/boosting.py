"""Boost pages that match canonical financial-statement titles."""

from __future__ import annotations

from typing import Dict, Sequence, Tuple

from analyst_copilot.parsing.models import Page

# (query triggers, page title phrases)
_STATEMENT_RULES: Sequence[Tuple[Tuple[str, ...], Tuple[str, ...]]] = (
    (
        ("cash flow", "capex", "capital expenditure"),
        ("consolidated statement of cash flow", "statement of cash flows"),
    ),
    (
        ("balance sheet", "financial position"),
        ("consolidated balance sheet", "statement of financial position"),
    ),
    (
        ("income statement", "net income", "net sales"),
        ("consolidated statement of income", "statement of operations"),
    ),
)


class StatementTitleBooster:
    """Raise scores for pages whose titles match the statement named in the query."""

    def __init__(self, multiplier: float = 1.25) -> None:
        if multiplier <= 0:
            raise ValueError("multiplier must be positive")
        self._multiplier = multiplier

    def apply(
        self,
        query: str,
        pages_by_index: Dict[int, Page],
        scores: Dict[int, float],
    ) -> Dict[int, float]:
        title_phrases = self._matching_titles(query.lower())
        if not title_phrases:
            return scores

        boosted: Dict[int, float] = {}
        for page_idx, score in scores.items():
            page = pages_by_index.get(page_idx)
            if page is not None and self._page_has_title(page.text, title_phrases):
                boosted[page_idx] = score * self._multiplier
            else:
                boosted[page_idx] = score
        return boosted

    @staticmethod
    def _matching_titles(query_lower: str) -> Tuple[str, ...]:
        titles: Tuple[str, ...] = ()
        for triggers, phrases in _STATEMENT_RULES:
            if any(trigger in query_lower for trigger in triggers):
                titles = titles + phrases
        return titles

    @staticmethod
    def _page_has_title(text: str, phrases: Sequence[str]) -> bool:
        haystack = text.lower()
        return any(phrase in haystack for phrase in phrases)
