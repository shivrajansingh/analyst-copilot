"""OpenAI-compatible chat completions client."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from openai import OpenAI

from analyst_copilot.config.settings import get_settings
from analyst_copilot.llm.base import ChatClient, ChatTurn, ToolCall
from analyst_copilot import usage as metering


class OpenAICompatibleChatClient(ChatClient):
    """Chat client using POST /v1/chat/completions."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        """
        A client for one model on one endpoint.

        The arguments exist so a second model can be addressed without a second
        class. Everything omitted falls back to the chat configuration, so
        `OpenAICompatibleChatClient()` is what it always was.
        """
        settings = get_settings()
        base_url = base_url or settings.chat_base_url
        api_key = api_key or settings.openai_api_key
        model = model or settings.openai_model
        if not api_key or not base_url:
            raise ValueError("OPENAI_URL and OPENAI_API_KEY must be set for chat completions")

        default_headers: Optional[Dict[str, str]] = None
        if "ngrok" in base_url:
            default_headers = {"ngrok-skip-browser-warning": "true"}

        self._model = model
        self._client = OpenAI(
            api_key=api_key,
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
        self._meter(response, messages, None)
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
        self._meter(response, messages, tools)
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

    # ----------------------------------------------------------------- #
    # metering
    # ----------------------------------------------------------------- #
    def _meter(
        self,
        response: Any,
        messages: List[dict],
        tools: Optional[List[Dict[str, Any]]],
    ) -> None:
        """
        Charge this call to whatever run and stage the caller is inside.

        The provider's own numbers are preferred and an estimate is the
        fallback, because a gateway is free to omit `usage` and several do.
        What is never done is passing an estimate off as a measurement -- the
        `estimated` flag travels with the figure all the way to the screen.

        Wrapped whole: a malformed `usage` payload is a reporting problem, and a
        reporting problem must not lose an answer that has already been paid for.
        """
        try:
            reported = getattr(response, "usage", None)
            input_tokens = int(getattr(reported, "prompt_tokens", 0) or 0)
            output_tokens = int(getattr(reported, "completion_tokens", 0) or 0)

            if input_tokens or output_tokens:
                details = getattr(reported, "prompt_tokens_details", None)
                cached = int(getattr(details, "cached_tokens", 0) or 0)
                metering.record(
                    metering.Usage(
                        model=self._model,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        cached_input_tokens=cached,
                    )
                )
                return

            # Nothing reported. Count what we sent and what came back.
            text = ""
            for choice in getattr(response, "choices", None) or []:
                message = getattr(choice, "message", None)
                text += getattr(message, "content", None) or ""
                for call in getattr(message, "tool_calls", None) or []:
                    function = getattr(call, "function", None)
                    text += getattr(function, "arguments", None) or ""
            metering.record(
                metering.Usage(
                    model=self._model,
                    input_tokens=(
                        metering.count_messages(messages) + metering.count_tools(tools)
                    ),
                    output_tokens=metering.count_text(text),
                    estimated=True,
                )
            )
        except Exception:  # noqa: BLE001 - metering is never load-bearing
            pass
