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
        numbers = extract_normalized_numbers(extraction.answer)
        if numbers and not numbers.intersection(extract_normalized_numbers(page_text)):
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
        for hit in hits:
            if hit.page.citation_page == page or hit.page.printed_page == page:
                return hit
            if hit.page.page_index + 1 == page:
                return hit
        return None


def extract_normalized_numbers(text: str) -> Set[str]:
    """Normalize $1,577.00 / (1577) / 1577.0 into comparable tokens."""
    found: Set[str] = set()
    for match in _NUMBER_PATTERN.finditer(text.replace("(", " ").replace(")", " ")):
        token = match.group(0).replace(",", "")
        if token in {"-", "."}:
            continue
        try:
            value = float(token)
        except ValueError:
            continue
        if value.is_integer():
            found.add(str(int(value)))
        else:
            found.add(f"{value:.4f}".rstrip("0").rstrip("."))
    return found


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
