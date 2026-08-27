"""The tool contract, and the registry that exposes tools to a model.

Two rules shape this module.

**A tool never raises at the model.** Bad arguments, a page that does not
exist, a malformed regular expression — all of them come back as ordinary tool
output saying what went wrong. A model that receives an error it can read will
correct itself on the next turn; an exception ends the run and loses the
question. The harness only sees an exception when the *harness* is broken.

**Tool output is written for a reader, not a parser.** Every result names the
document, the page and the line it came from, because the agent's next move is
usually to read around what it just found, and it can only do that if the
result told it where it was.
"""

from __future__ import annotations

import abc
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ToolResult:
    """What a tool hands back: text for the model, metadata for the harness."""

    content: str
    ok: bool = True
    meta: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def failure(cls, message: str) -> "ToolResult":
        return cls(content=f"ERROR: {message}", ok=False)


class Tool(abc.ABC):
    """One callable capability offered to an agent."""

    #: Function name the model calls.
    name: str = ""
    #: What the tool does, and when to reach for it. The model reads this.
    description: str = ""

    @property
    @abc.abstractmethod
    def parameters(self) -> Dict[str, Any]:
        """JSON Schema for the tool's arguments."""

    @abc.abstractmethod
    def run(self, **kwargs: Any) -> ToolResult:
        """Execute the tool. Must not raise for bad input — return a failure."""

    def spec(self) -> Dict[str, Any]:
        """The OpenAI-compatible tool definition."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description.strip(),
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    """The tools one agent may call, and the dispatch into them."""

    def __init__(self, tools: Optional[List[Tool]] = None) -> None:
        self._tools: Dict[str, Tool] = {}
        for tool in tools or []:
            self.add(tool)

    def add(self, tool: Tool) -> None:
        if not tool.name:
            raise ValueError(f"{type(tool).__name__} has no name")
        self._tools[tool.name] = tool

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)

    @property
    def names(self) -> List[str]:
        return list(self._tools)

    def specs(self) -> List[Dict[str, Any]]:
        return [tool.spec() for tool in self._tools.values()]

    def invoke(self, name: str, arguments: Any) -> ToolResult:
        """
        Run one tool call.

        `arguments` arrives as the JSON string the provider produced, so
        unparseable JSON is a normal outcome to report rather than a crash.
        """
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult.failure(
                f"No tool named {name!r}. Available tools: {', '.join(self._tools)}."
            )

        parsed = _parse_arguments(arguments)
        if parsed is None:
            return ToolResult.failure(
                f"Could not read the arguments for {name!r} as JSON. "
                "Send a JSON object matching the tool's schema."
            )

        try:
            return tool.run(**parsed)
        except TypeError as exc:
            # Wrong or missing argument names: the model can fix this itself.
            return ToolResult.failure(f"{name}: {exc}")
        except Exception as exc:  # noqa: BLE001 - a tool must never end the run
            return ToolResult.failure(f"{name} failed: {type(exc).__name__}: {exc}")


def _parse_arguments(arguments: Any) -> Optional[Dict[str, Any]]:
    if arguments is None or arguments == "":
        return {}
    if isinstance(arguments, dict):
        return arguments
    try:
        parsed = json.loads(arguments)
    except (TypeError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def schema(
    properties: Dict[str, Any],
    required: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """A JSON Schema object, with additional properties refused."""
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }
