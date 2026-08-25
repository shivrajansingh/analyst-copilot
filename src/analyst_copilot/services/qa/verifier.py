"""Verify that an LLM answer is supported by retrieved pages."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Sequence, Set

from analyst_copilot.retrieval.models import ScoredPage
from analyst_copilot.services.qa.models import LLMExtraction

_NUMBER_PATTERN = re.compile(r"-?\d{1,3}(?:,\d{3})*(?:\.\d+)?|-?\d+(?:\.\d+)?")


@dataclass
class VerificationResult:
    ok: bool
    reason: str
    page: Optional[int] = None
    evidence_snippet: str = ""


class AnswerVerifier:
    """Reject answers that are not grounded in retrieved evidence."""

    def verify(
        self,
        extraction: LLMExtraction,
        hits: Sequence[ScoredPage],
    ) -> VerificationResult:
        if extraction.not_found:
            return VerificationResult(ok=False, reason="model_abstain")

        if not extraction.answer:
            return VerificationResult(ok=False, reason="empty_answer")

        cited = self._resolve_cited_hit(extraction.page, hits)
        if cited is None:
            return VerificationResult(ok=False, reason="page_not_in_retrieval")

        page_text = cited.page.text
        if not numbers_supported_by_page(extraction.answer, page_text):
            return VerificationResult(ok=False, reason="number_not_on_page")

        snippet = extraction.evidence_snippet
        if snippet and not _snippet_supported(snippet, page_text):
            return VerificationResult(ok=False, reason="snippet_not_on_page")

        evidence = snippet if snippet else page_text[:280]
        return VerificationResult(
            ok=True,
            reason="ok",
            page=cited.page.citation_page,
            evidence_snippet=evidence,
        )

    @staticmethod
    def _resolve_cited_hit(
        page: Optional[int],
        hits: Sequence[ScoredPage],
    ) -> Optional[ScoredPage]:
        if not hits:
            return None
        if page is None:
            return hits[0]
        # Exact match only. The prompt labels each excerpt with its
        # citation_page, so a mismatch means the model cited a page it was not
        # shown. Fuzzy fallbacks (printed_page, page_index + 1) used to resolve
        # to a neighbouring page, which produced confident answers attached to
        # the wrong location -- the one outcome the rubric penalises.
        for hit in hits:
            if hit.page.citation_page == page:
                return hit
        return None


# Filings print one scale ("Dollars in millions"), questions ask for another
# ("answer in USD billions"), so a literal string match rejects correct answers:
# an answer of 8.738 is the page's 8,738 read in billions. Comparing significant
# digits instead is scale-free, and unlike a numeric tolerance it does not widen
# into a band that some number on a dense financial page always falls inside.
MIN_SIGNIFICANT_DIGITS = 3
MIN_SHARED_DIGITS = 2


def significant_digits(token: str) -> str:
    """'8,738' -> '8738'; '8.70' -> '87'; '0.096' -> '96'; '(1,577)' -> '1577'."""
    digits = re.sub(r"[^0-9]", "", token)
    return digits.strip("0") or ("0" if digits else "")


def _digit_forms(text: str) -> Set[str]:
    forms: Set[str] = set()
    for match in _NUMBER_PATTERN.finditer(text.replace("(", " ").replace(")", " ")):
        token = significant_digits(match.group(0))
        if len(token) >= MIN_SHARED_DIGITS:
            forms.add(token)
    return forms


def numbers_supported_by_page(answer: str, page_text: str) -> bool:
    """
    Whether the figures in an answer are traceable to figures on the cited page.

    An answer figure is supported when its significant digits are a prefix of a
    page figure's (or vice versa) -- 8.7 or 8.738 both trace to the page's 8,738,
    regardless of the unit the question asked for. At least one side must carry
    MIN_SIGNIFICANT_DIGITS, so a bare "65" cannot be waved through by whatever
    two-digit figure happens to sit on a page full of numbers.

    An answer with no figures at all is left to the snippet check.
    """
    answer_forms = _digit_forms(answer)
    if not answer_forms:
        return True
    page_forms = _digit_forms(page_text)
    for a in answer_forms:
        for p in page_forms:
            shorter, longer = (a, p) if len(a) <= len(p) else (p, a)
            if len(longer) >= MIN_SIGNIFICANT_DIGITS and longer.startswith(shorter):
                return True
    return False


def _snippet_supported(snippet: str, page_text: str) -> bool:
    compact_snippet = _compact(snippet)
    compact_page = _compact(page_text)
    if len(compact_snippet) < 12:
        return True
    if compact_snippet[:80] in compact_page:
        return True
    words = [w for w in snippet.lower().split() if len(w) > 3][:8]
    if not words:
        return True
    return sum(1 for w in words if w in page_text.lower()) >= max(3, len(words) // 2)


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text.lower())
