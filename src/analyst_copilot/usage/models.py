"""What one model call cost, and what a run cost in total.

Money is counted in **integer micro-dollars** everywhere below the formatting
layer. A deep run makes 37 calls and the interesting digits sit at the fourth
and fifth decimal place; floats accumulated over that many additions drift
exactly where an analyst would be reading. `1_000_000` micro-dollars is a
dollar, and the conversion happens once, at the edge.

`estimated` is not decoration. A provider that omits `usage` leaves us counting
tokens ourselves, and a locally counted figure rendered identically to a
measured one is the same class of dishonesty this product exists to avoid --
so the flag travels with the number all the way to the screen.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

#: Micro-dollars in a dollar.
MICRO = 1_000_000


@dataclass(frozen=True)
class Usage:
    """Tokens spent by one call to one model."""

    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    #: Input tokens the provider served from its own cache, when it says so.
    #: A subset of `input_tokens`, priced lower where a rate is configured.
    cached_input_tokens: int = 0
    #: True when the provider did not report usage and we counted locally.
    estimated: bool = False

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class StageUsage:
    """Everything spent under one stage of the pipeline, across every agent."""

    stage: str
    label: str
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    micro_usd: int = 0
    #: Which models spent under this stage, in first-use order. Almost always
    #: one -- but the caller should not have to infer it from the run's model
    #: list, which is what forced the UI to guess which model a row belonged to.
    models: List[str] = field(default_factory=list)
    #: False when any model in this stage has no configured price. A stage that
    #: is partly priced is reported as unpriced: a total that silently omits
    #: half its calls is worse than one that admits it cannot be computed.
    priced: bool = True
    estimated: bool = False

    def to_dict(self) -> Dict[str, object]:
        return {
            "stage": self.stage,
            "label": self.label,
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "cost_usd": round(self.micro_usd / MICRO, 6) if self.priced else None,
            "models": list(self.models),
            "estimated": self.estimated,
        }


@dataclass
class ModelUsage:
    """Everything one model spent, across every stage that used it.

    Aggregated from the calls themselves rather than derived from the stage
    breakdown. A stage happens to use one model today, but reading a model off
    a stage is an inference, and this is the number an analyst checks against a
    provider's bill.
    """

    model: str
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    micro_usd: int = 0
    priced: bool = True

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def to_dict(self) -> Dict[str, object]:
        return {
            "model": self.model,
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": round(self.micro_usd / MICRO, 6) if self.priced else None,
        }


@dataclass
class UsageReport:
    """What one answer cost, in total and by stage."""

    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    calls: int = 0
    micro_usd: int = 0
    #: False if any call in the run had no configured price. See StageUsage.
    priced: bool = True
    #: True if any call in the run was counted locally rather than reported.
    estimated: bool = False
    models: List[str] = field(default_factory=list)
    stages: List[StageUsage] = field(default_factory=list)
    #: The same spend split by model rather than by stage. A run uses a chat
    #: model and an embedding model at a hundredth of the price, and only this
    #: split can be checked against a provider's invoice.
    by_model: List[ModelUsage] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def cost_usd(self) -> Optional[float]:
        return round(self.micro_usd / MICRO, 6) if self.priced else None

    def to_dict(self) -> Dict[str, object]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "total_tokens": self.total_tokens,
            "calls": self.calls,
            "cost_usd": self.cost_usd,
            "priced": self.priced,
            "estimated": self.estimated,
            "models": list(self.models),
            "stages": [stage.to_dict() for stage in self.stages],
            "by_model": [entry.to_dict() for entry in self.by_model],
        }
