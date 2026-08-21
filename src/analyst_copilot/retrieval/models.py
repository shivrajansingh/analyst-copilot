"""Data models for retrieval and search results."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from analyst_copilot.parsing.models import Page


@dataclass(frozen=True)
class ScoredPage:
    """A filing page ranked by a retrieval score."""

    page: Page
    score: float
    rank: int
    bm25_score: Optional[float] = None
    vector_score: Optional[float] = None


@dataclass
class BM25IndexMetadata:
    """Serializable metadata for a persisted BM25 index."""

    doc_name: str
    source_path: str
    page_count: int
    tokenizer_version: str = "v1"
    parser_version: str = "unknown"


@dataclass
class VectorIndexMetadata:
    """Serializable metadata for a persisted vector index."""

    doc_name: str
    source_path: str
    page_count: int
    embedding_model: str
    dimensions: int
    max_chars_per_page: int
    parser_version: str = "unknown"


@dataclass
class SearchResult:
    """Container for ranked pages returned by a search."""

    query: str
    doc_name: str
    hits: List[ScoredPage] = field(default_factory=list)

    @property
    def top_hit(self) -> Optional[ScoredPage]:
        return self.hits[0] if self.hits else None
