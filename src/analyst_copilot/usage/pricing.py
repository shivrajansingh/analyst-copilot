"""What a thousand tokens costs, and the refusal to guess when nobody said.

Two sources, in order: whatever the deployment configured, then a small table
of published rates for models we can name with confidence. A model that matches
neither is **unpriced** -- its tokens are counted and reported, and no dollar
figure is produced for it.

That refusal is the whole point. This service runs against an OpenAI-compatible
gateway, and a gateway can put any model behind any name at any margin. A cost
invented from a rate we assumed is worse than no cost at all: an analyst can
act on a number, and a wrong number about money is acted on confidently.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional, Sequence, Tuple, Union

from analyst_copilot.usage.models import MICRO


@dataclass(frozen=True)
class Price:
    """USD per million tokens."""

    input_per_mtok: float
    output_per_mtok: float
    #: Rate for input the provider served from cache. Defaults to the full
    #: input rate, which is the conservative reading when nobody said otherwise.
    cached_input_per_mtok: Optional[float] = None

    def micro_usd(self, input_tokens: int, output_tokens: int, cached_input_tokens: int = 0) -> int:
        """
        Cost in integer micro-dollars.

        tokens x (USD per million tokens) is already micro-dollars, which is why
        this arithmetic has no division in it and cannot drift.
        """
        cached = min(cached_input_tokens, input_tokens)
        fresh = input_tokens - cached
        cached_rate = (
            self.cached_input_per_mtok
            if self.cached_input_per_mtok is not None
            else self.input_per_mtok
        )
        return round(
            fresh * self.input_per_mtok
            + cached * cached_rate
            + output_tokens * self.output_per_mtok
        )

    def at(self, when: Optional[datetime] = None) -> "Price":
        """The rate in force at `when`. A flat rate is the same at every hour."""
        return self


@dataclass(frozen=True)
class Schedule:
    """
    The hours, in UTC, when a peak rate applies.

    Windows are half-open `[start, end)` in whole UTC hours, which is how every
    provider that does this states them. A window that wraps midnight is written
    as it reads -- `(22, 2)` means 22:00-23:59 and 00:00-01:59.
    """

    windows: Tuple[Tuple[int, int], ...] = ()

    def is_peak(self, when: Optional[datetime] = None) -> bool:
        if not self.windows:
            return False
        hour = (when or datetime.now(timezone.utc)).astimezone(timezone.utc).hour
        for start, end in self.windows:
            if start <= end:
                if start <= hour < end:
                    return True
            elif hour >= start or hour < end:  # wraps midnight
                return True
        return False

    @classmethod
    def parse(cls, text: str) -> "Schedule":
        """
        Read `"01-04,06-10"` as two UTC windows.

        Malformed input yields an empty schedule rather than an exception: a
        typo in a price window must not stop the service answering questions,
        and an empty schedule degrades to the off-peak rate, which is the
        rate that is correct more of the time.
        """
        windows = []
        for chunk in (text or "").split(","):
            chunk = chunk.strip()
            if not chunk or "-" not in chunk:
                continue
            start_text, _, end_text = chunk.partition("-")
            try:
                start, end = int(start_text), int(end_text)
            except ValueError:
                continue
            if 0 <= start <= 24 and 0 <= end <= 24 and start != end:
                windows.append((start % 24, end % 24))
        return cls(tuple(windows))


@dataclass(frozen=True)
class TieredPrice:
    """
    A rate that changes with the clock.

    Some providers charge more during their busy hours -- DeepSeek through
    OpenCode Zen doubles between 01:00-04:00 and 06:00-10:00 UTC. Reporting one
    of the two rates around the clock would be wrong by a factor of two for
    seven hours a day, which is exactly the kind of confidently wrong number
    this module exists to refuse.

    The rate is resolved per call, at the moment the call is recorded, so a run
    that straddles a boundary is billed the way the provider bills it.
    """

    off_peak: Price
    peak: Price
    schedule: Schedule = Schedule()

    def at(self, when: Optional[datetime] = None) -> Price:
        return self.peak if self.schedule.is_peak(when) else self.off_peak


#: Anything that can answer "what is the rate right now".
Rate = Union[Price, TieredPrice]


#: Published list prices, USD per million tokens. Only models whose rate is
#: public and stable belong here -- anything served through a reselling gateway
#: is priced by configuration, not by this table.
PUBLISHED: Dict[str, Price] = {
    "gpt-4o": Price(2.50, 10.00, 1.25),
    "gpt-4o-mini": Price(0.15, 0.60, 0.075),
    "gpt-4.1": Price(2.00, 8.00, 0.50),
    "gpt-4.1-mini": Price(0.40, 1.60, 0.10),
    "text-embedding-3-small": Price(0.02, 0.0),
    "text-embedding-3-large": Price(0.13, 0.0),
}


def published_price(model: str) -> Optional[Price]:
    """The list price for a model we can name, ignoring any provider prefix."""
    if not model:
        return None
    name = model.strip().lower()
    if name in PUBLISHED:
        return PUBLISHED[name]
    # "openai/gpt-4o-mini" and "openai/gpt-4o-mini:free" both name a model we know.
    tail = name.rsplit("/", 1)[-1].split(":", 1)[0]
    return PUBLISHED.get(tail)


class PriceBook:
    """
    Prices for this deployment: configuration first, published rates second.

    Built from settings rather than read per call, so a rate cannot change
    underneath a run that has already reported half its cost. What *can* change
    within a run is which tier of a rate applies -- that is resolved per call
    against the clock, because it is how the provider bills.
    """

    def __init__(
        self,
        chat_model: str = "",
        chat_price: Optional[Rate] = None,
        embedding_model: str = "",
        embedding_price: Optional[Rate] = None,
    ) -> None:
        self._configured: Dict[str, Rate] = {}
        if chat_model and chat_price:
            self._configured[chat_model.strip().lower()] = chat_price
        if embedding_model and embedding_price:
            self._configured[embedding_model.strip().lower()] = embedding_price

    def rate(self, model: str) -> Optional[Rate]:
        """The configured or published rate for a model, before the clock is applied."""
        return self._configured.get((model or "").strip().lower()) or published_price(model)

    def price(self, model: str, when: Optional[datetime] = None) -> Optional[Price]:
        """The rate in force for `model` at `when`, or None when it has no price."""
        found = self.rate(model)
        return None if found is None else found.at(when)

    def micro_usd(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cached_input_tokens: int = 0,
        when: Optional[datetime] = None,
    ) -> Optional[int]:
        """Micro-dollars for one call, or None when the model has no price."""
        price = self.price(model, when)
        if price is None:
            return None
        return price.micro_usd(input_tokens, output_tokens, cached_input_tokens)


def from_settings(settings=None) -> PriceBook:
    """
    The price book this deployment configured.

    A peak rate is optional. Set only the base rates and the price is flat; add
    `*_PEAK_*` and a window, and the base rates become the off-peak tier.
    """
    if settings is None:
        from analyst_copilot.config.settings import get_settings

        settings = get_settings()

    def price(input_value: float, output_value: float, cached_value: float) -> Optional[Price]:
        # A rate of zero is a legitimate answer -- a locally hosted model costs
        # nothing -- so the test is "was anything set", not "is it non-zero".
        if input_value < 0 or output_value < 0 or cached_value < 0:
            return None
        if input_value == 0 and output_value == 0 and cached_value == 0:
            return None
        return Price(input_value, output_value, cached_value if cached_value > 0 else None)

    base = price(
        settings.chat_price_input,
        settings.chat_price_output,
        settings.chat_price_cached_input,
    )
    peak = price(
        settings.chat_price_peak_input,
        settings.chat_price_peak_output,
        settings.chat_price_peak_cached_input,
    )
    schedule = Schedule.parse(settings.chat_price_peak_hours_utc)

    chat: Optional[Rate] = base
    if base is not None and peak is not None and schedule.windows:
        chat = TieredPrice(off_peak=base, peak=peak, schedule=schedule)

    return PriceBook(
        chat_model=settings.openai_model,
        chat_price=chat,
        embedding_model=settings.resolved_embedding_model,
        embedding_price=price(settings.embedding_price_input, 0.0, 0.0),
    )


__all__ = [
    "MICRO",
    "PUBLISHED",
    "Price",
    "PriceBook",
    "Rate",
    "Schedule",
    "TieredPrice",
    "from_settings",
    "published_price",
]
