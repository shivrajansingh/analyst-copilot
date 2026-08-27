"""Token usage and what it cost, for one answer.

    from analyst_copilot import usage

    meter = usage.UsageMeter(usage.prices_from_settings())
    with usage.metering(meter):
        with usage.stage("routing", "Understood the question"):
            ...            # every model call in here is charged to `routing`
    report = meter.report()

See `meter.py` for why this is a context variable rather than an argument, and
for the one place that has to propagate it by hand.
"""

from analyst_copilot.usage.estimate import count_messages, count_text, count_tools
from analyst_copilot.usage.meter import (
    UNATTRIBUTED,
    UsageMeter,
    current,
    metering,
    record,
    record_as,
    stage,
)
from analyst_copilot.usage.models import MICRO, ModelUsage, StageUsage, Usage, UsageReport
from analyst_copilot.usage.pricing import (
    Price,
    PriceBook,
    Schedule,
    TieredPrice,
    published_price,
)
from analyst_copilot.usage.pricing import from_settings as prices_from_settings

__all__ = [
    "MICRO",
    "ModelUsage",
    "Price",
    "PriceBook",
    "Schedule",
    "TieredPrice",
    "StageUsage",
    "UNATTRIBUTED",
    "Usage",
    "UsageMeter",
    "UsageReport",
    "count_messages",
    "count_text",
    "count_tools",
    "current",
    "metering",
    "prices_from_settings",
    "published_price",
    "record",
    "record_as",
    "stage",
]
