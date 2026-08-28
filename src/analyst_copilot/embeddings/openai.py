"""
OpenAI-compatible embedding client.

Works with any server that implements POST /v1/embeddings, including:
- Ollama (base URL → {OLLAMA_URL}/v1)
- OpenAI and other compatible providers
"""

from __future__ import annotations

from typing import Dict, List, Optional

from openai import OpenAI

from analyst_copilot.config.settings import get_settings
from analyst_copilot import usage as metering
from analyst_copilot.embeddings.base import EmbeddingClient


class OpenAICompatibleEmbeddingClient(EmbeddingClient):
    """Single embedding client using the OpenAI embeddings API format."""

    def __init__(self, batch_size: int = 32) -> None:
        settings = get_settings()
        self._model = settings.resolved_embedding_model
        self._batch_size = batch_size
        self._dimensions: Optional[int] = None

        default_headers: Optional[Dict[str, str]] = None
        base_url = settings.resolved_embedding_base_url
        if "ngrok" in base_url:
            default_headers = {"ngrok-skip-browser-warning": "true"}

        self._client = OpenAI(
            api_key=settings.resolved_embedding_api_key,
            base_url=base_url,
            default_headers=default_headers,
            timeout=120.0,
            max_retries=2,
        )
        self._base_url = base_url

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def dimensions(self) -> Optional[int]:
        return self._dimensions

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []

        all_vectors: List[List[float]] = []
        for start in range(0, len(texts), self._batch_size):
            batch = texts[start : start + self._batch_size]
            response = self._client.embeddings.create(
                model=self._model,
                input=batch,
            )
            self._meter(response, batch)
            vectors = [item.embedding for item in response.data]
            all_vectors.extend(vectors)
            if self._dimensions is None and vectors:
                self._dimensions = len(vectors[0])

        return all_vectors

    def _meter(self, response: object, batch: List[str]) -> None:
        """
        Charge this embedding call to the run that asked for it.

        Indexing a filing embeds thousands of pages and is not part of any
        answer, so this only lands anywhere when a run is metering -- which, in
        practice, means the one query embedding a question needs.

        Embeddings have no output tokens; the model returns vectors, and a
        vector is not billed by the token.
        """
        try:
            reported = getattr(response, "usage", None)
            tokens = int(getattr(reported, "prompt_tokens", 0) or 0)
            estimated = False
            if not tokens:
                tokens = sum(metering.count_text(text) for text in batch)
                estimated = True
            metering.record_as(
                metering.Usage(
                    model=self._model,
                    input_tokens=tokens,
                    output_tokens=0,
                    estimated=estimated,
                ),
                "embedding",
                "Embedded the query",
            )
        except Exception:  # noqa: BLE001 - metering is never load-bearing
            pass
