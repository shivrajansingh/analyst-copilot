"""OpenAI-compatible chat completions client."""

from __future__ import annotations

from typing import Dict, List, Optional

from openai import OpenAI

from analyst_copilot.config.settings import get_settings
from analyst_copilot.llm.base import ChatClient


class OpenAICompatibleChatClient(ChatClient):
    """Chat client using POST /v1/chat/completions."""

    def __init__(self) -> None:
        settings = get_settings()
        if not settings.openai_api_key or not settings.chat_base_url:
            raise ValueError("OPENAI_URL and OPENAI_API_KEY must be set for chat completions")

        default_headers: Optional[Dict[str, str]] = None
        if "ngrok" in settings.chat_base_url:
            default_headers = {"ngrok-skip-browser-warning": "true"}

        self._model = settings.openai_model
        self._client = OpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.chat_base_url,
            default_headers=default_headers,
        )
        self._base_url = settings.chat_base_url

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def base_url(self) -> str:
        return self._base_url

    def complete(
        self,
        messages: List[dict],
        temperature: float = 0.0,
        max_tokens: int = 800,
    ) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        content = response.choices[0].message.content
        if content:
            return content
        # Some models spend the token budget on hidden reasoning and leave content empty.
        finish = response.choices[0].finish_reason
        raise ValueError(
            f"Chat completion returned empty content (finish_reason={finish}). "
            "Increase qa_max_tokens if the model uses reasoning tokens."
        )
