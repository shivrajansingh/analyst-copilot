from analyst_copilot.embeddings.base import EmbeddingClient
from analyst_copilot.embeddings.openai import OpenAICompatibleEmbeddingClient

__all__ = [
    "EmbeddingClient",
    "OpenAICompatibleEmbeddingClient",
    "get_embedding_client",
]


def get_embedding_client() -> EmbeddingClient:
    """Return the unified OpenAI-compatible embedding client."""
    return OpenAICompatibleEmbeddingClient()
