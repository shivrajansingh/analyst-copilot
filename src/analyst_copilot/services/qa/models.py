"""QA result models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from analyst_copilot.retrieval.models import SearchResult


NOT_FOUND_MESSAGE = "not found in this filing"


@dataclass
class LLMExtraction:
    """Parsed structured output from the chat model."""

    not_found: bool
    answer: str = ""
    page: Optional[int] = None
    evidence_snippet: str = ""
    confidence: Optional[float] = None
    raw_text: str = ""


@dataclass
class QAAnswer:
    """Final user-facing answer after verification."""

    question: str
    doc_name: str
    answer: str
    found: bool
    page: Optional[int] = None
    evidence_snippet: str = ""
    retrieval: Optional[SearchResult] = None
    abstention_reason: Optional[str] = None
    llm_extraction: Optional[LLMExtraction] = None

    @property
    def display_text(self) -> str:
        if not self.found:
            return NOT_FOUND_MESSAGE
        location = f"{self.doc_name}, page {self.page}" if self.page is not None else self.doc_name
        return f"{self.answer}\n\nSource: {location}"
