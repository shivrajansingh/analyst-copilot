"""Abstract embedding client interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional


class EmbeddingClient(ABC):
    @property
    @abstractmethod
    def model_name(self) -> str:
        """Model identifier used for embedding requests."""

    @property
    @abstractmethod
    def dimensions(self) -> Optional[int]:
        """Embedding vector size when known ahead of time."""

    @abstractmethod
    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """Embed a batch of texts and return one vector per text."""

    def embed_query(self, text: str) -> List[float]:
        """Embed a single search query."""
        return self.embed_texts([text])[0]
