"""In-memory vector index over filing page embeddings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from analyst_copilot.parsing.models import Page
from analyst_copilot.retrieval.models import VectorIndexMetadata


@dataclass
class VectorIndex:
    """Dense vector index aligned to parsed filing pages."""

    metadata: VectorIndexMetadata
    pages: List[Page]
    vectors: List[List[float]]

    @property
    def doc_name(self) -> str:
        return self.metadata.doc_name
