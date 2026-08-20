"""In-memory BM25 index over filing pages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from rank_bm25 import BM25Okapi

from analyst_copilot.parsing.models import Page
from analyst_copilot.retrieval.models import BM25IndexMetadata


@dataclass
class BM25Index:
    """BM25 index aligned to parsed filing pages."""

    metadata: BM25IndexMetadata
    pages: List[Page]
    tokenized_corpus: List[List[str]]
    model: BM25Okapi

    @property
    def doc_name(self) -> str:
        return self.metadata.doc_name
