"""What the harness is doing, while it does it.

Separate from `StageEvent` on purpose. A stage is a *milestone* — "reading the
whole filing", "12 of 31 readers done" — and there are a handful of them. A trace
is the fine-grained record underneath: which agent is running, what it just said
it was about to look for, which tool it called. There are hundreds, and a caller
should be able to take the milestones without the firehose.

Everything here is real. The thought text is what the model actually wrote, the
tool name is a call that actually happened, and an agent's status is its actual
outcome. Nothing is synthesised to fill a gap — a quiet run looks quiet, because
a progress display that invents activity is worse than one that admits there is
none.

Deliberately *not* carried: tool arguments and tool results. They are large, they
are the least interesting part to watch, and a tool result is document text that
has not been verified yet — putting it on screen would leak exactly the
unverified figures the product exists to withhold.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Dict, Optional

# Thought text is truncated before it leaves the process: this is a progress
# feed, not a transcript, and 13 readers thinking out loud is a lot of bytes.
MAX_THOUGHT_CHARS = 240


class TraceKind(str, Enum):
    THOUGHT = "thought"  # text the model wrote of its own accord
    TOOL = "tool"        # a tool call, by name only
    AGENT = "agent"      # an agent's lifecycle


class AgentStatus(str, Enum):
    RUNNING = "running"
    FOUND = "found"      # reported a complete answer
    PARTIAL = "partial"  # reported figures it could not finish with
    EMPTY = "empty"      # read its pages, nothing there
    FAILED = "failed"


@dataclass
class TraceEvent:
    """One thing that happened, addressed to whichever agent did it."""

    kind: TraceKind
    #: Who: "reader 7", "synthesis", "validator". Empty for the top level.
    agent: str = ""
    text: str = ""
    tool: str = ""
    status: Optional[AgentStatus] = None

    def to_dict(self) -> Dict[str, object]:
        payload: Dict[str, object] = {"kind": self.kind.value}
        if self.agent:
            payload["agent"] = self.agent
        if self.text:
            payload["text"] = self.text
        if self.tool:
            payload["tool"] = self.tool
        if self.status is not None:
            payload["status"] = self.status.value
        return payload


TraceCallback = Callable[[TraceEvent], None]


def thought(agent: str, text: str) -> TraceEvent:
    """A model's own words, trimmed to one readable line."""
    flattened = " ".join(text.split())
    if len(flattened) > MAX_THOUGHT_CHARS:
        flattened = flattened[:MAX_THOUGHT_CHARS].rstrip() + "…"
    return TraceEvent(kind=TraceKind.THOUGHT, agent=agent, text=flattened)


def tool_call(agent: str, tool: str) -> TraceEvent:
    return TraceEvent(kind=TraceKind.TOOL, agent=agent, tool=tool)


def agent_status(agent: str, status: AgentStatus) -> TraceEvent:
    return TraceEvent(kind=TraceKind.AGENT, agent=agent, status=status)


def emit(callback: Optional[TraceCallback], event: TraceEvent) -> None:
    """
    Report an event, and never let reporting break the work.

    A trace callback runs inside a reader's thread and pushes onto a queue that a
    disconnected client may have stopped draining. That must not end a fan-out.
    """
    if callback is None:
        return
    try:
        callback(event)
    except Exception:  # noqa: BLE001 - progress reporting is never load-bearing
        pass


def scoped(callback: Optional[TraceCallback], agent: str) -> Optional[TraceCallback]:
    """
    A callback that stamps every event with the agent that produced it.

    Readers do not know their own name — they are handed a shard, not an
    identity — so the label is applied here by whoever spawned them.
    """
    if callback is None:
        return None

    def relabel(event: TraceEvent) -> None:
        if not event.agent:
            event.agent = agent
        emit(callback, event)

    return relabel
