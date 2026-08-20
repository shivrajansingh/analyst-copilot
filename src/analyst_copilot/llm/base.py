"""Abstract chat LLM client."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List


class ChatClient(ABC):
    @property
    @abstractmethod
    def model_name(self) -> str:
        """Chat model identifier."""

    @abstractmethod
    def complete(
        self,
        messages: List[dict],
        temperature: float = 0.0,
        max_tokens: int = 800,
    ) -> str:
        """Return the assistant message text."""
