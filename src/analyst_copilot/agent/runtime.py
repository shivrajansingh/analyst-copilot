"""The agent loop: a model, a set of tools, and a bounded conversation.

An agent here is not a personality. It is a model given tools, a strict brief,
and a **terminal tool** it must call to finish. That last part is the design
decision worth explaining.

The obvious way to end an agent run is to let the model stop calling tools and
write its answer as prose or JSON, then parse it. That fails in two ways that
matter for this product: the JSON is sometimes malformed, and — worse — a model
with nothing to report will happily write a paragraph explaining what it looked
for, which a parser then has to decide is or is not an answer. Making the report
a *tool call* moves the schema into the provider's own validation, so a finding
either arrives with the fields it must have or does not arrive at all. "I found
nothing" becomes an explicit, structured statement rather than an absence.

Everything is bounded: iterations, tool calls, and how much of a tool result
reaches the transcript. An agent that loops is a cost, not a bug report.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

from analyst_copilot.agent.tools.base import ToolRegistry, ToolResult
from analyst_copilot.llm.base import ChatClient, ChatTurn, ToolCall

logger = logging.getLogger(__name__)

# A tool result longer than this is truncated before it enters the transcript.
# `read_page` already windows its output; this is the backstop for a search that
# matches everything.
MAX_TOOL_RESULT_CHARS = 16000


@dataclass
class AgentRun:
    """What one agent run produced."""

    content: str = ""
    #: Arguments of the terminal tool call, when one was made.
    report: Optional[Dict[str, Any]] = None
    reported_tool: str = ""
    iterations: int = 0
    tool_calls: int = 0
    pages_read: int = 0
    exhausted: bool = False
    error: str = ""
    transcript: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.error

    @property
    def reported(self) -> bool:
        return self.report is not None


class AgentRuntime:
    """Runs one tool-using agent to completion, or to its bounds."""

    def __init__(
        self,
        chat_client: ChatClient,
        max_iterations: int = 8,
        max_tool_calls: int = 24,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> None:
        self._chat = chat_client
        self._max_iterations = max_iterations
        self._max_tool_calls = max_tool_calls
        self._temperature = temperature
        self._max_tokens = max_tokens

    def run(
        self,
        system: str,
        user: str,
        registry: ToolRegistry,
        terminal_tools: Sequence[str] = (),
        history: Optional[List[Dict[str, Any]]] = None,
        on_tool: Optional[Callable[[str, ToolResult], None]] = None,
    ) -> AgentRun:
        """
        Drive the conversation until the agent reports, or its bounds are hit.

        `terminal_tools` names the tool(s) that end the run. Their arguments are
        returned as `report` without being executed — the "tool" is the schema,
        not an action.
        """
        terminal = set(terminal_tools)
        messages: List[Dict[str, Any]] = [{"role": "system", "content": system}]
        messages.extend(history or [])
        messages.append({"role": "user", "content": user})

        specs = registry.specs()
        run = AgentRun(transcript=messages)

        for iteration in range(1, self._max_iterations + 1):
            run.iterations = iteration
            try:
                turn = self._chat.complete_with_tools(
                    messages=messages,
                    tools=specs,
                    temperature=self._temperature,
                    max_tokens=self._max_tokens,
                )
            except Exception as exc:  # noqa: BLE001 - one dead agent must not end a fan-out
                logger.warning("agent turn failed on iteration %d: %s", iteration, exc)
                run.error = f"{type(exc).__name__}: {exc}"
                return run

            messages.append(turn.message or {"role": "assistant", "content": turn.content})

            if not turn.wants_tools:
                run.content = turn.content.strip()
                if not run.content:
                    # No text and no tool call: the model has stalled. Say so
                    # rather than returning a silent success.
                    run.error = (
                        f"the model returned neither text nor a tool call "
                        f"(finish_reason={turn.finish_reason or 'unknown'})"
                    )
                return run

            stop = self._execute(turn, registry, terminal, messages, run, on_tool)
            if stop:
                return run
            if run.tool_calls >= self._max_tool_calls:
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "You have used your tool budget. Report now with the "
                            "evidence you have, or report that you found nothing."
                        ),
                    }
                )

        run.exhausted = True
        return run

    # -- internals ---------------------------------------------------------- #
    def _execute(
        self,
        turn: ChatTurn,
        registry: ToolRegistry,
        terminal: set,
        messages: List[Dict[str, Any]],
        run: AgentRun,
        on_tool: Optional[Callable[[str, ToolResult], None]],
    ) -> bool:
        """
        Run this turn's tool calls. Returns True when the run should end.

        A terminal call ends the run, but only after the other calls in the same
        turn have been answered: a provider that batches `read_page` alongside
        the final report still needs a tool message for every call it made, or
        the transcript is invalid for any later request.
        """
        report: Optional[ToolCall] = None

        for call in turn.tool_calls:
            run.tool_calls += 1
            if call.name in terminal:
                report = call
                messages.append(_tool_message(call, "Reported."))
                continue

            result = registry.invoke(call.name, call.arguments)
            if on_tool is not None:
                on_tool(call.name, result)
            messages.append(_tool_message(call, _clip(result.content)))

        if report is None:
            return False

        parsed = _parse_report(report.arguments)
        if parsed is None:
            # The one case worth a retry: the schema was right but the JSON was
            # not, and the model can usually fix that when told.
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"The arguments you sent to {report.name} were not valid JSON. "
                        "Call it again with a well-formed JSON object."
                    ),
                }
            )
            return False

        run.report = parsed
        run.reported_tool = report.name
        run.content = turn.content.strip()
        return True


def _tool_message(call: ToolCall, content: str) -> Dict[str, Any]:
    return {
        "role": "tool",
        "tool_call_id": call.id,
        "name": call.name,
        "content": content,
    }


def _clip(text: str) -> str:
    if len(text) <= MAX_TOOL_RESULT_CHARS:
        return text
    return (
        text[:MAX_TOOL_RESULT_CHARS]
        + f"\n\n[...truncated at {MAX_TOOL_RESULT_CHARS:,} characters]"
    )


def _parse_report(arguments: Any) -> Optional[Dict[str, Any]]:
    if isinstance(arguments, dict):
        return arguments
    if arguments in (None, ""):
        return {}
    try:
        parsed = json.loads(arguments)
    except (TypeError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None
