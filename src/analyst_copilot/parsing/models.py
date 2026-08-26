"""Data models for parsed document content."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from analyst_copilot.parsing.formats import DocumentFormat


class SegmentKind(str, Enum):
    """What one unit of retrieval actually is in the source document."""

    PAGE = "page"        # A real page: PDF page, HTML page break, Word page break
    SHEET = "sheet"      # One worksheet of a workbook
    TABLE = "table"      # A delimited file read as a single table
    SECTION = "section"  # A logical part: a heading span, or a block of rows

    @property
    def is_page(self) -> bool:
        return self is SegmentKind.PAGE


@dataclass
class Page:
    """
    One segment of a parsed document: the unit that is embedded and cited.

    Named `Page` because for the paginated formats that the corpus is made of
    it is exactly a page. `segment_kind` says when it is not -- a worksheet or a
    block of CSV rows -- so a citation can name the thing an analyst can look up
    rather than a page number the source never had.

    `text` holds the Markdown normalization. Every format converges on it, so
    everything downstream -- tokenizer, embedder, prompt, verifier -- reads one
    representation and never learns where the document came from.
    """

    doc_name: str
    page_index: int
    text: str
    printed_page: Optional[int] = None  # Footer page number when detected
    segment_kind: SegmentKind = SegmentKind.PAGE
    segment_label: Optional[str] = None
    source_format: DocumentFormat = DocumentFormat.HTML

    @property
    def citation_page(self) -> int:
        """
        Canonical page number for citations and scoring.

        This is the 0-based ordinal of the segment within the document, which is
        the convention the practice key uses for `evidence_page_num`.

        `printed_page` is deliberately NOT used here: footer numbers land at the
        end of one segment in some filings and the start of the next in others,
        so against gold they are off by +1 (50 blocks) or -1 (44 blocks) with no
        consistent direction. They are retained for reference only.
        """
        return self.page_index

    @property
    def display_page(self) -> int:
        """1-based page number for human-facing text."""
        return self.page_index + 1

    @property
    def citation_label(self) -> str:
        """
        How this segment should be named in an answer.

        A page gets a page number. A worksheet gets its sheet name, because
        "page 4 of a spreadsheet" is not a place anyone can go and look.
        """
        if self.segment_label:
            return self.segment_label
        if self.segment_kind.is_page:
            return f"page {self.display_page}"
        return f"{self.segment_kind.value} {self.display_page}"


@dataclass
class FilingDocument:
    """A parsed document, normalized to Markdown segments."""

    doc_name: str
    source_path: str
    pages: List[Page] = field(default_factory=list)
    source_format: DocumentFormat = DocumentFormat.HTML
    # How the parser arrived at these boundaries: "page-break", "pdf-page",
    # "worksheet", "fallback-chunk". Recorded so an operator reading a manifest
    # can tell a real pagination from a synthesized one.
    segmentation: str = "unknown"

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def is_paginated(self) -> bool:
        return bool(self.pages) and self.pages[0].segment_kind.is_page
