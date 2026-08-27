"""Abstract chat LLM client.

Two calling conventions, because the pipeline needs both:

`complete` is one question, one answer — the fast path's single extraction call
and every classification call in the harness. `complete_with_tools` is a turn of
a tool-using conversation, which is what an agent loop is made of.

Tool support is optional rather than abstract. A client that cannot offer tools
(a stub in a test, a provider without function calling) stays a valid
`ChatClient`; only the deep path needs the second method, and it fails with a
message that says so rather than with an AttributeError.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ToolCall:
    """One tool invocation the model asked for."""

    id: str
    name: str
    arguments: str = ""


@dataclass
class ChatTurn:
    """One assistant turn: text, tool calls, and the message to append back."""

    content: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)
    finish_reason: str = ""
    # The assistant message exactly as it must be appended to the transcript
    # before tool results are added. Providers are strict about this shape.
    message: Dict[str, Any] = field(default_factory=dict)

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


class ToolsUnsupported(RuntimeError):
    """This chat client cannot run a tool-calling conversation."""


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

    @property
    def supports_tools(self) -> bool:
        return False

    def complete_with_tools(
        self,
        messages: List[dict],
        tools: List[Dict[str, Any]],
        temperature: float = 0.0,
        max_tokens: int = 4096,
        tool_choice: Optional[str] = "auto",
    ) -> ChatTurn:
        """One turn of a tool-calling conversation."""
        raise ToolsUnsupported(
            f"{type(self).__name__} does not support tool calling, which the deep "
            "search path requires."
        )
