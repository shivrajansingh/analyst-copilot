"""QA result models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from analyst_copilot.parsing.models import SegmentKind
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
    # How the citation relates to what the model said: "exact", "adjusted",
    # "relocated" or "inferred". Surfaced rather than hidden, so a reader can
    # see when the system moved a citation onto the page bearing the evidence.
    location_match: Optional[str] = None
    cited_page: Optional[int] = None
    page_shift: int = 0
    # What the cited segment is called in its source: "page 61" for a filing,
    # "sheet 'Q4 Revenue'" for a workbook.
    location_label: Optional[str] = None
    segment_kind: Optional[SegmentKind] = None

    @property
    def location_adjusted(self) -> bool:
        """Whether the citation was moved off the page the model named."""
        return self.location_match in ("adjusted", "relocated")

    @property
    def display_location(self) -> str:
        """The place this answer came from, named the way the source names it."""
        if self.location_label:
            return f"{self.doc_name}, {self.location_label}"
        if self.page is not None:
            return f"{self.doc_name}, page {self.page}"
        return self.doc_name

    @property
    def display_text(self) -> str:
        if not self.found:
            return NOT_FOUND_MESSAGE
        return f"{self.answer}\n\nSource: {self.display_location}"
