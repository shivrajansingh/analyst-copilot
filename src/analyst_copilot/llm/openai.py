"""OpenAI-compatible chat completions client."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from openai import OpenAI

from analyst_copilot.config.settings import get_settings
from analyst_copilot.llm.base import ChatClient, ChatTurn, ToolCall


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
            timeout=120.0,
            max_retries=2,
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

    @property
    def supports_tools(self) -> bool:
        return True

    def complete_with_tools(
        self,
        messages: List[dict],
        tools: List[Dict[str, Any]],
        temperature: float = 0.0,
        max_tokens: int = 4096,
        tool_choice: Optional[str] = "auto",
    ) -> ChatTurn:
        """
        One turn of a tool-calling conversation.

        Unlike `complete`, an empty `content` is a normal outcome here: a model
        that decided to call a tool has nothing to say yet, and treating that as
        an error would end every agent run on its first move.
        """
        request: Dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            request["tools"] = tools
            if tool_choice:
                request["tool_choice"] = tool_choice

        response = self._client.chat.completions.create(**request)
        choice = response.choices[0]
        message = choice.message

        calls = [
            ToolCall(
                id=call.id,
                name=call.function.name,
                arguments=call.function.arguments or "",
            )
            for call in (message.tool_calls or [])
            if getattr(call, "function", None) is not None
        ]

        # Rebuilt by hand rather than passed through: providers differ on which
        # extra fields they echo, and an unexpected key in the transcript is
        # rejected on the next request.
        assistant: Dict[str, Any] = {"role": "assistant", "content": message.content or ""}
        if calls:
            assistant["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": call.arguments},
                }
                for call in calls
            ]

        return ChatTurn(
            content=message.content or "",
            tool_calls=calls,
            finish_reason=choice.finish_reason or "",
            message=assistant,
        )
