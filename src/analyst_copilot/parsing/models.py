"""Data models for parsed SEC filing content."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Page:
    """One logical page of extracted filing text."""

    doc_name: str
    page_index: int
    text: str
    printed_page: Optional[int] = None  # Footer page number when detected

    @property
    def citation_page(self) -> int:
        """Best page number to show in citations."""
        return self.printed_page if self.printed_page is not None else self.page_index + 1


@dataclass
class FilingDocument:
    """Parsed SEC filing with page-aligned text."""

    doc_name: str
    source_path: str
    pages: list[Page] = field(default_factory=list)

    @property
    def page_count(self) -> int:
        return len(self.pages)
