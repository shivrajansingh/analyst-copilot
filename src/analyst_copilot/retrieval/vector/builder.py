"""Build vector indices from parsed filing pages."""

from __future__ import annotations

from typing import Optional

from analyst_copilot.config.settings import get_settings
from analyst_copilot.embeddings import get_embedding_client
from analyst_copilot.embeddings.base import EmbeddingClient
from analyst_copilot.parsing.models import FilingDocument
from analyst_copilot.retrieval.models import VectorIndexMetadata
from analyst_copilot.retrieval.vector.index import VectorIndex
from analyst_copilot.retrieval.vector.text import truncate_page_text


class VectorIndexBuilder:
    """Embed filing pages and construct a vector index."""

    def __init__(self, embedding_client: Optional[EmbeddingClient] = None) -> None:
        self._embedding_client = embedding_client or get_embedding_client()

    def build(self, document: FilingDocument) -> VectorIndex:
        if not document.pages:
            raise ValueError(f"No pages to index for document: {document.doc_name}")

        page_texts = [truncate_page_text(page.text) for page in document.pages]
        vectors = self._embedding_client.embed_texts(page_texts)
        dimensions = self._embedding_client.dimensions or len(vectors[0])

        settings = get_settings()
        metadata = VectorIndexMetadata(
            doc_name=document.doc_name,
            source_path=document.source_path,
            page_count=len(document.pages),
            embedding_model=self._embedding_client.model_name,
            dimensions=dimensions,
            max_chars_per_page=settings.retrieval_max_chars_per_page,
        )

        return VectorIndex(
            metadata=metadata,
            pages=list(document.pages),
            vectors=vectors,
        )
