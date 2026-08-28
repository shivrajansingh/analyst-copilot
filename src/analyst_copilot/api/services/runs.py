"""In-flight answers, so one of them can be stopped by name.

A streaming answer is already cancellable by dropping the connection, and that
path is the fast one: no round trip, no id, nothing to look up. This registry
exists for the cases where dropping the connection is not enough or not
possible — nginx sits in front of this service and buffering decides how quickly
a disconnect is noticed, and an analyst who left the tab on another machine
still wants the fan-out to stop.

Deliberately in-process. There is one API process today, and a run's cancel token
is a `threading.Event` belonging to that process's threads — a registry in Redis
would hand back a token that cannot signal anything. What would move to Redis if
this were scaled out is the *message* ("run X should stop"), not the token, and
routing that message is why callers go through a registry rather than a global
dict.
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass
from typing import Dict, Tuple

from analyst_copilot.agent.cancellation import CancelToken

#: How long a run stays cancellable after it was started. Long enough to cover
#: the slowest deep search several times over; short enough that an abandoned
#: entry from a crashed stream is not a leak.
RUN_TTL_SECONDS = 15 * 60


@dataclass(frozen=True)
class Run:
    """One answer in flight."""

    run_id: str
    user_id: str
    token: CancelToken
    started_at: float


class RunRegistry:
    """The runs this process is currently answering, keyed by id."""

    def __init__(self, ttl_seconds: float = RUN_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._runs: Dict[str, Run] = {}

    def start(self, user_id: str) -> Tuple[str, CancelToken]:
        """Register a new run and return its id and its stop signal."""
        run = Run(
            run_id=f"run_{secrets.token_hex(6)}",
            user_id=user_id,
            token=CancelToken(),
            started_at=time.monotonic(),
        )
        with self._lock:
            self._sweep()
            self._runs[run.run_id] = run
        return run.run_id, run.token

    def cancel(self, user_id: str, run_id: str) -> bool:
        """
        Stop a run. False if it is unknown, finished, or somebody else's.

        Another user's run is indistinguishable from one that never existed, on
        purpose: a run id is a capability, and confirming that one exists would
        leak that somebody is asking a question.
        """
        with self._lock:
            run = self._runs.get(run_id)
            if run is None or run.user_id != user_id:
                return False
        # Outside the lock: setting an Event can wake threads, and nothing here
        # needs the registry held while that happens.
        run.token.cancel()
        return True

    def finish(self, run_id: str) -> None:
        """Forget a run that has ended, however it ended. Idempotent."""
        with self._lock:
            self._runs.pop(run_id, None)

    def __len__(self) -> int:  # pragma: no cover - diagnostics
        with self._lock:
            return len(self._runs)

    # -- internals ---------------------------------------------------------- #
    def _sweep(self) -> None:
        """Drop expired entries. Called under the lock, on the write path."""
        cutoff = time.monotonic() - self._ttl
        stale = [
            run_id for run_id, run in self._runs.items() if run.started_at < cutoff
        ]
        for run_id in stale:
            self._runs.pop(run_id, None)
