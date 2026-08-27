"""The per-run meter: who spent what, while a dozen threads spend it at once.

The hard part is not the arithmetic, it is knowing which run a call belongs to.
Three facts about this service decide the design:

* the chat client is an `lru_cache`'d singleton, so one instance serves every
  request at once -- a counter on the client would bill two analysts together;
* the pipeline runs off the event loop in a worker thread, and the deep path
  fans out into a pool of its own;
* the call sites are scattered across the router, the splitter, the fast path,
  the checker, thirty-one readers and the adjudicator.

So the meter is held in a `ContextVar`. Starlette copies the context into the
thread it runs the pipeline in, which covers everything except the fan-out --
`ThreadPoolExecutor` does not propagate context to its workers. That one gap is
closed explicitly at the one place it exists, in `orchestrator._fan_out`, by
submitting `copy_context().run(...)`. **Any future pool that makes model calls
must do the same or its spend will silently vanish from the total.**

Recording never raises. Same rule as the trace channel: metering is not
load-bearing, and a `usage` payload a gateway shaped oddly must not end a
sixty-second fan-out.
"""

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from contextvars import ContextVar
from typing import Dict, Iterator, Optional, Tuple

from analyst_copilot.usage.models import StageUsage, Usage, UsageReport
from analyst_copilot.usage.pricing import PriceBook

logger = logging.getLogger(__name__)

#: Where a call is charged when nothing said. Real, not a catch-all for bugs:
#: a client used outside the pipeline genuinely has no stage.
UNATTRIBUTED = ("other", "Other model calls")

_METER: ContextVar[Optional["UsageMeter"]] = ContextVar("usage_meter", default=None)
_STAGE: ContextVar[Tuple[str, str]] = ContextVar("usage_stage", default=UNATTRIBUTED)


class UsageMeter:
    """
    Everything one answer spent, aggregated by stage as it happens.

    Shared across the reader pool, so every mutation is under a lock. The lock
    is held for the arithmetic only -- never across a model call.
    """

    def __init__(self, prices: Optional[PriceBook] = None) -> None:
        self._prices = prices or PriceBook()
        self._lock = threading.Lock()
        #: Insertion-ordered, so the report reads in the order the run happened.
        self._stages: Dict[str, StageUsage] = {}
        self._models: list[str] = []
        self._calls = 0

    def record(self, usage: Usage, stage: str = "", label: str = "") -> None:
        """Charge one call to a stage. Never raises."""
        try:
            key = stage or _STAGE.get()[0]
            text = label or (_STAGE.get()[1] if not stage else stage)
            # Priced now, not at report time. A provider whose rate changes with
            # the clock bills each call at the rate in force when it was made,
            # and a deep run can straddle that boundary.
            micro = self._prices.micro_usd(
                usage.model,
                usage.input_tokens,
                usage.output_tokens,
                usage.cached_input_tokens,
                when=datetime.now(timezone.utc),
            )
            with self._lock:
                entry = self._stages.get(key)
                if entry is None:
                    entry = StageUsage(stage=key, label=text)
                    self._stages[key] = entry
                elif text and not entry.label:
                    entry.label = text
                entry.calls += 1
                entry.input_tokens += usage.input_tokens
                entry.output_tokens += usage.output_tokens
                entry.cached_input_tokens += usage.cached_input_tokens
                entry.estimated = entry.estimated or usage.estimated
                if usage.model and usage.model not in entry.models:
                    entry.models.append(usage.model)
                if micro is None:
                    entry.priced = False
                else:
                    entry.micro_usd += micro
                self._calls += 1
                if usage.model and usage.model not in self._models:
                    self._models.append(usage.model)
        except Exception:  # noqa: BLE001 - metering is never load-bearing
            logger.debug("usage not recorded", exc_info=True)

    def report(self) -> UsageReport:
        """What the run has spent so far. Safe to call mid-run, as a stop does."""
        with self._lock:
            stages = [
                StageUsage(
                    stage=entry.stage,
                    label=entry.label,
                    calls=entry.calls,
                    input_tokens=entry.input_tokens,
                    output_tokens=entry.output_tokens,
                    cached_input_tokens=entry.cached_input_tokens,
                    micro_usd=entry.micro_usd,
                    models=list(entry.models),
                    priced=entry.priced,
                    estimated=entry.estimated,
                )
                for entry in self._stages.values()
            ]
            models = list(self._models)
            calls = self._calls

        return UsageReport(
            input_tokens=sum(entry.input_tokens for entry in stages),
            output_tokens=sum(entry.output_tokens for entry in stages),
            cached_input_tokens=sum(entry.cached_input_tokens for entry in stages),
            calls=calls,
            micro_usd=sum(entry.micro_usd for entry in stages),
            priced=all(entry.priced for entry in stages) if stages else True,
            estimated=any(entry.estimated for entry in stages),
            models=models,
            stages=stages,
        )

    @property
    def empty(self) -> bool:
        with self._lock:
            return self._calls == 0


# --------------------------------------------------------------------------- #
# context
# --------------------------------------------------------------------------- #
@contextmanager
def metering(meter: Optional[UsageMeter]) -> Iterator[Optional[UsageMeter]]:
    """Make `meter` the one that records for the duration of this block."""
    token = _METER.set(meter)
    try:
        yield meter
    finally:
        _METER.reset(token)


@contextmanager
def stage(key: str, label: str = "") -> Iterator[None]:
    """
    Charge every model call in this block to one stage.

    `label` is prose for the analyst and is built where the numbers are known --
    "Read all 118 pages · 31 agents" can only be written by the code that knows
    both counts.
    """
    token = _STAGE.set((key, label or key))
    try:
        yield
    finally:
        _STAGE.reset(token)


def current() -> Optional[UsageMeter]:
    """The meter this call belongs to, if the run is being metered."""
    return _METER.get()


def record(usage: Usage) -> None:
    """
    Charge one call to whichever run and stage this thread is inside.

    A no-op when nothing is metering, which is the normal case for a script or
    a test that does not care what it spent.
    """
    meter = _METER.get()
    if meter is None:
        return
    key, label = _STAGE.get()
    meter.record(usage, key, label)


def record_as(usage: Usage, stage: str, label: str = "") -> None:
    """
    Charge one call to a named stage, ignoring the block it happens inside.

    For work that is nested inside another stage but is genuinely its own line
    on the bill: the query embedding is issued from the middle of retrieval, but
    it is a different model at a different price, and folding it into retrieval
    would hide a cost the analyst can act on.
    """
    meter = _METER.get()
    if meter is None:
        return
    meter.record(usage, stage, label)
