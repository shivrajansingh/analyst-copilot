"""Stopping a run, all the way down.

The harness is synchronous and spends its time inside threads: the API runs
`AnalystAgent.answer` in a threadpool, and the deep path spawns a pool of its own
with one reader per shard. Nothing in `asyncio` can interrupt either of those.
Cancelling the task that awaits the pipeline abandons the *result*; the readers
keep reading, and every one of their calls is billed to answer a question nobody
is waiting for.

So cancellation here is cooperative and explicit: one `threading.Event` per run,
shared by every thread the run owns, checked at seams that already exist. The
rule for where a checkpoint goes is *immediately before anything that costs money
or a minute* — a model call, a shard, a tier. Between checkpoints the run is
uninterruptible, which bounds the waste after a stop at one in-flight call per
running agent rather than at whatever the fan-out had left to do.

`Cancelled` is not an error. Nothing failed, the analyst changed their mind, and
callers that turn exceptions into failure messages must special-case it.
"""

from __future__ import annotations

import threading
from typing import Optional


class Cancelled(Exception):
    """
    The run was stopped by whoever asked for it.

    Deliberately not a subclass of anything the harness catches broadly. Every
    `except Exception` in the agent path — a reader that crashed, a deep search
    that failed, a fast path that fell over — exists to convert a failure into an
    abstention, and a stop is neither a failure nor an abstention.
    """


class CancelToken:
    """A stop signal shared by every thread working on one run."""

    __slots__ = ("_event",)

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        """Ask the run to stop. Idempotent, and safe from any thread."""
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        """The checkpoint. Cheap enough to call in a loop."""
        if self._event.is_set():
            raise Cancelled()


class _NeverCancelled(CancelToken):
    """
    The token for a run nobody can stop — `POST /chat`, scripts, tests.

    A null object rather than `Optional[CancelToken]` everywhere: the checkpoints
    are dense by design, and `if cancel is not None` at each of them would be
    noise at exactly the places that need to stay readable.
    """

    __slots__ = ()

    def cancel(self) -> None:  # pragma: no cover - a no-op by construction
        pass

    @property
    def cancelled(self) -> bool:
        return False

    def raise_if_cancelled(self) -> None:
        pass


#: Shared and immutable: it holds no state that could differ between runs.
NEVER = _NeverCancelled()


def token_or_never(cancel: Optional[CancelToken]) -> CancelToken:
    """Normalise a caller's optional token, so callees never test for None."""
    return cancel if cancel is not None else NEVER
