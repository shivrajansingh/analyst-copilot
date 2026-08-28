"""What an answer cost: the meter, the price book, and the estimator.

The three things worth pinning down are the three that would be wrong silently:
money that drifts, a fan-out whose spend disappears into worker threads, and an
estimate that passes for a measurement.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context

import pytest

from analyst_copilot import usage
from analyst_copilot.usage.pricing import Price, PriceBook, published_price


# --------------------------------------------------------------------------- #
# pricing
# --------------------------------------------------------------------------- #
def test_cost_is_exact_micro_dollars_not_a_drifting_float():
    """
    54,294 in and 2,954 out at $0.27/$1.10 is $0.017909 and nothing else.

    Computed as tokens x (USD per million), which is already micro-dollars, so
    there is no division to lose digits in.
    """
    price = Price(0.27, 1.10)
    assert price.micro_usd(54_294, 2_954) == 17_909


def test_summing_thirty_seven_calls_does_not_drift():
    """A deep run is dozens of additions at the fifth decimal place."""
    price = Price(0.27, 1.10)
    parts = [price.micro_usd(1_467, 79) for _ in range(37)]
    assert sum(parts) == price.micro_usd(1_467, 79) * 37


def test_cached_input_is_priced_at_its_own_rate_when_one_is_set():
    price = Price(2.50, 10.00, cached_input_per_mtok=1.25)
    # 1000 input of which 400 cached: 600 x 2.50 + 400 x 1.25 + 100 x 10.00
    assert price.micro_usd(1_000, 100, cached_input_tokens=400) == 1_500 + 500 + 1_000


def test_cached_input_falls_back_to_the_full_rate_when_nobody_said():
    """The conservative reading. Under-charging is the error that hides money."""
    price = Price(2.50, 10.00)
    assert price.micro_usd(1_000, 0, cached_input_tokens=400) == 2_500


def test_an_unknown_model_is_unpriced_rather_than_guessed():
    """
    The rule this whole feature turns on.

    A gateway can put any model behind any name at any margin, so a rate nobody
    configured produces no number at all.
    """
    book = PriceBook()
    assert book.price("deepseek-v4-flash") is None
    assert book.micro_usd("deepseek-v4-flash", 10_000, 500) is None


def test_a_configured_rate_beats_the_published_table():
    """A deployment reselling gpt-4o at its own margin says so, and is believed."""
    book = PriceBook(chat_model="gpt-4o", chat_price=Price(1.00, 2.00))
    assert book.micro_usd("gpt-4o", 1_000_000, 0) == 1_000_000


def test_a_provider_prefix_still_finds_a_published_model():
    assert published_price("openai/gpt-4o-mini") == published_price("gpt-4o-mini")
    assert published_price("openai/gpt-4o-mini:free") is not None


# --------------------------------------------------------------------------- #
# the meter
# --------------------------------------------------------------------------- #
def _book() -> PriceBook:
    return PriceBook(chat_model="m", chat_price=Price(0.27, 1.10))


def test_stages_are_reported_in_the_order_the_run_happened():
    meter = usage.UsageMeter(_book())
    with usage.metering(meter):
        for key, label in (
            ("routing", "Understood the question"),
            ("retrieving", "Read the retrieved pages"),
            ("validating", "Checked the answer"),
        ):
            with usage.stage(key, label):
                usage.record(usage.Usage(model="m", input_tokens=100, output_tokens=10))

    assert [entry.stage for entry in meter.report().stages] == [
        "routing",
        "retrieving",
        "validating",
    ]


def test_the_stage_label_is_the_prose_the_call_site_wrote():
    meter = usage.UsageMeter(_book())
    with usage.metering(meter), usage.stage("deep_search", "Read all 118 pages · 31 agents"):
        usage.record(usage.Usage(model="m", input_tokens=1, output_tokens=1))
    assert meter.report().stages[0].label == "Read all 118 pages · 31 agents"


def test_stage_totals_sum_to_the_report_total():
    """
    The invariant the expanded table asserts on screen.

    A breakdown whose rows do not add up to the headline is worse than no
    breakdown: it makes an analyst distrust a number that is correct.
    """
    meter = usage.UsageMeter(_book())
    with usage.metering(meter):
        with usage.stage("routing", "Understood the question"):
            usage.record(usage.Usage(model="m", input_tokens=412, output_tokens=18))
        with usage.stage("deep_search", "Read every page"):
            for _ in range(31):
                usage.record(usage.Usage(model="m", input_tokens=1_229, output_tokens=71))

    report = meter.report()
    assert report.input_tokens == sum(entry.input_tokens for entry in report.stages)
    assert report.output_tokens == sum(entry.output_tokens for entry in report.stages)
    assert report.micro_usd == sum(entry.micro_usd for entry in report.stages)
    assert report.calls == sum(entry.calls for entry in report.stages) == 32


def test_one_unpriced_model_makes_the_whole_run_unpriced():
    """
    A total that silently omits half its calls is worse than one that admits it
    cannot be computed.
    """
    meter = usage.UsageMeter(_book())
    with usage.metering(meter):
        with usage.stage("retrieving", "Read the retrieved pages"):
            usage.record(usage.Usage(model="m", input_tokens=100, output_tokens=10))
        with usage.stage("embedding", "Embedded the query"):
            usage.record(usage.Usage(model="some-embedder", input_tokens=24))

    report = meter.report()
    assert report.priced is False
    assert report.cost_usd is None
    assert report.to_dict()["cost_usd"] is None
    # The priced stage still reports its own cost. Only the total is withheld.
    priced = {entry.stage: entry.priced for entry in report.stages}
    assert priced == {"retrieving": True, "embedding": False}


def test_one_estimated_call_marks_the_whole_run_estimated():
    meter = usage.UsageMeter(_book())
    with usage.metering(meter):
        with usage.stage("routing", "Understood the question"):
            usage.record(usage.Usage(model="m", input_tokens=400, output_tokens=20))
        with usage.stage("retrieving", "Read the retrieved pages"):
            usage.record(
                usage.Usage(model="m", input_tokens=6_000, output_tokens=200, estimated=True)
            )
    assert meter.report().estimated is True


def test_record_as_charges_its_own_stage_from_inside_another():
    """The query embedding is issued from the middle of retrieval, and is its own line."""
    meter = usage.UsageMeter(_book())
    with usage.metering(meter), usage.stage("retrieving", "Read the retrieved pages"):
        usage.record(usage.Usage(model="m", input_tokens=6_240, output_tokens=214))
        usage.record_as(
            usage.Usage(model="m", input_tokens=24), "embedding", "Embedded the query"
        )
    assert [entry.stage for entry in meter.report().stages] == ["retrieving", "embedding"]


def test_recording_outside_a_metered_run_is_a_no_op():
    """A script or a test that does not care what it spent must still run."""
    usage.record(usage.Usage(model="m", input_tokens=1_000, output_tokens=100))


def test_a_malformed_record_never_raises_into_the_pipeline():
    """
    Metering is not load-bearing. A gateway that shapes `usage` oddly must not
    end a sixty-second fan-out.
    """
    meter = usage.UsageMeter(_book())
    meter.record(usage.Usage(model="m", input_tokens=None, output_tokens=1))  # type: ignore[arg-type]
    assert meter.report().calls == 0


def test_two_runs_at_once_do_not_bill_each_other():
    """
    The reason this is a context variable and not a counter on the chat client:
    the client is an lru_cache'd singleton shared by every request.
    """
    first = usage.UsageMeter(_book())
    second = usage.UsageMeter(_book())
    ready = threading.Barrier(2)

    def run(meter: usage.UsageMeter, tokens: int) -> None:
        with usage.metering(meter), usage.stage("routing", "Understood the question"):
            ready.wait(timeout=5)
            usage.record(usage.Usage(model="m", input_tokens=tokens, output_tokens=0))

    threads = [
        threading.Thread(target=run, args=(first, 1_000)),
        threading.Thread(target=run, args=(second, 7_000)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert first.report().input_tokens == 1_000
    assert second.report().input_tokens == 7_000


def test_a_pool_that_copies_its_context_records_every_worker():
    """
    The gap the orchestrator closes by hand.

    `ThreadPoolExecutor` starts its workers with an empty context, so a fan-out
    that submits bare callables loses the readers -- which is most of what a
    deep run costs. `copy_context().run(...)` is what keeps them.
    """
    meter = usage.UsageMeter(_book())
    with usage.metering(meter), usage.stage("deep_search", "Read every page"):
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [
                pool.submit(
                    copy_context().run,
                    usage.record,
                    usage.Usage(model="m", input_tokens=1_000, output_tokens=50),
                )
                for _ in range(31)
            ]
            for future in futures:
                future.result()

    report = meter.report()
    assert report.calls == 31
    assert report.input_tokens == 31_000


def test_a_pool_without_the_copied_context_records_nothing():
    """The failure this guards against, asserted so the guard cannot rot."""
    meter = usage.UsageMeter(_book())
    with usage.metering(meter), usage.stage("deep_search", "Read every page"):
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [
                pool.submit(
                    usage.record,
                    usage.Usage(model="m", input_tokens=1_000, output_tokens=50),
                )
                for _ in range(4)
            ]
            for future in futures:
                future.result()

    assert meter.report().calls == 0


def test_the_meter_can_be_read_mid_run_which_is_what_a_stop_does():
    meter = usage.UsageMeter(_book())
    with usage.metering(meter), usage.stage("deep_search", "Read every page"):
        usage.record(usage.Usage(model="m", input_tokens=14_760, output_tokens=842))
        assert meter.empty is False
        assert meter.report().total_tokens == 15_602
        usage.record(usage.Usage(model="m", input_tokens=1_000, output_tokens=0))
    assert meter.report().total_tokens == 16_602


# --------------------------------------------------------------------------- #
# estimation
# --------------------------------------------------------------------------- #
def test_estimating_counts_the_tool_schemas_too():
    """
    Not a rounding error: a reader carries its tool definitions on every turn,
    and leaving them out under-reports the stage that spends the most.
    """
    messages = [{"role": "user", "content": "what were net sales in 2022?"}]
    tools = [
        {
            "type": "function",
            "function": {
                "name": "read_page",
                "description": "Read one page of the filing.",
                "parameters": {"type": "object", "properties": {"page": {"type": "integer"}}},
            },
        }
    ]
    bare = usage.count_messages(messages)
    assert usage.count_messages(messages) + usage.count_tools(tools) > bare


def test_estimating_counts_tool_call_arguments():
    """An agent turn that calls a tool has sent those arguments."""
    plain = [{"role": "assistant", "content": ""}]
    calling = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "function": {
                        "name": "read_page",
                        "arguments": '{"page": 58, "doc_name": "3M_2022_10K.htm"}',
                    }
                }
            ],
        }
    ]
    assert usage.count_messages(calling) > usage.count_messages(plain)


def test_an_empty_string_costs_nothing():
    assert usage.count_text("") == 0


@pytest.mark.parametrize("text", ["hello", "a" * 400])
def test_counting_is_always_at_least_one_token_for_real_text(text):
    assert usage.count_text(text) >= 1


# --------------------------------------------------------------------------- #
# capture: what the client does with a provider's response
# --------------------------------------------------------------------------- #
class _Details:
    def __init__(self, cached: int) -> None:
        self.cached_tokens = cached


class _Reported:
    def __init__(self, prompt: int, completion: int, cached: int = 0) -> None:
        self.prompt_tokens = prompt
        self.completion_tokens = completion
        self.prompt_tokens_details = _Details(cached)


class _Message:
    def __init__(self, content: str = "") -> None:
        self.content = content
        self.tool_calls = []


class _Choice:
    def __init__(self, content: str = "") -> None:
        self.message = _Message(content)


class _Response:
    def __init__(self, content: str = "", reported=None) -> None:
        self.choices = [_Choice(content)]
        self.usage = reported


def _client(model: str = "m"):
    """
    The real client without its constructor.

    `__init__` needs a reachable provider and builds an SDK object; the metering
    path needs neither, and stubbing the SDK instead would test the stub.
    """
    from analyst_copilot.llm.openai import OpenAICompatibleChatClient

    client = object.__new__(OpenAICompatibleChatClient)
    client._model = model  # noqa: SLF001 - constructing without the network
    return client


def test_the_client_believes_the_provider_when_it_reports_usage():
    meter = usage.UsageMeter(_book())
    with usage.metering(meter), usage.stage("routing", "Understood the question"):
        _client()._meter(
            _Response("done", _Reported(412, 18, cached=100)),
            [{"role": "user", "content": "x" * 10_000}],
            None,
        )

    report = meter.report()
    assert (report.input_tokens, report.output_tokens) == (412, 18)
    assert report.cached_input_tokens == 100
    # The message was 10,000 characters. Nothing was counted locally, so nothing
    # is marked estimated.
    assert report.estimated is False


def test_the_client_counts_locally_when_the_provider_says_nothing():
    """
    And says so. An estimate rendered identically to a measurement is the same
    class of dishonesty as an unverified figure.
    """
    meter = usage.UsageMeter(_book())
    with usage.metering(meter), usage.stage("routing", "Understood the question"):
        _client()._meter(
            _Response("a fairly long answer about net sales", None),
            [{"role": "user", "content": "what were net sales in fiscal 2022?"}],
            None,
        )

    report = meter.report()
    assert report.estimated is True
    assert report.input_tokens > 0
    assert report.output_tokens > 0


def test_a_broken_usage_payload_is_swallowed_not_raised():
    """A gateway shaping `usage` oddly must not lose an answer already paid for."""
    class Hostile:
        choices = []

        @property
        def usage(self):
            raise RuntimeError("gateway said no")

    meter = usage.UsageMeter(_book())
    with usage.metering(meter), usage.stage("routing", "Understood the question"):
        _client()._meter(Hostile(), [], None)
    assert meter.report().calls == 0


# --------------------------------------------------------------------------- #
# plumbing: the meter reaches the call sites
# --------------------------------------------------------------------------- #
def test_the_pipeline_binds_the_meter_around_a_conversational_reply():
    """
    The binding happens inside `AnalystAgent.answer`, not at the caller, because
    the pipeline runs in a worker thread and the caller's context is not
    reliably the one this body runs in.
    """
    from analyst_copilot.agent import AnalystAgent
    from analyst_copilot.llm.base import ChatClient
    from tests.offline_harness import StubPlanner

    class RecordingChat(ChatClient):
        """Stands in for the real client's own metering, which is tested above."""

        @property
        def model_name(self) -> str:
            return "m"

        def complete(self, messages, temperature=0.0, max_tokens=800):
            usage.record(usage.Usage(model="m", input_tokens=286, output_tokens=44))
            return "Hello. Ask me about a filing."

    agent = AnalystAgent(
        qa_service=object(), chat_client=RecordingChat(), planner=StubPlanner()
    )
    meter = usage.UsageMeter(_book())
    answer = agent.answer("Hi", doc_name="anything", meter=meter)

    assert answer.mode.value == "conversational"
    report = meter.report()
    assert [entry.stage for entry in report.stages] == ["conversational"]
    assert report.stages[0].label == "Answered directly"
    assert report.total_tokens == 330
    assert report.cost_usd == round((286 * 0.27 + 44 * 1.10) / 1e6, 6)


def test_an_unmetered_answer_still_works():
    """Every script in `scripts/` calls the pipeline without a meter."""
    from analyst_copilot.agent import AnalystAgent
    from analyst_copilot.llm.base import ChatClient
    from tests.offline_harness import StubPlanner

    class Chat(ChatClient):
        @property
        def model_name(self) -> str:
            return "m"

        def complete(self, messages, temperature=0.0, max_tokens=800):
            usage.record(usage.Usage(model="m", input_tokens=1, output_tokens=1))
            return "Hello."

    agent = AnalystAgent(
        qa_service=object(), chat_client=Chat(), planner=StubPlanner()
    )
    assert agent.answer("Hi", doc_name="anything").mode.value == "conversational"


# --------------------------------------------------------------------------- #
# peak pricing: a rate that changes with the clock
# --------------------------------------------------------------------------- #
from datetime import datetime, timezone  # noqa: E402 - grouped with its own tests

from analyst_copilot.usage.pricing import Schedule, TieredPrice  # noqa: E402

#: deepseek-v4-flash on OpenCode Zen, verified 27 Aug 2026.
FLASH = TieredPrice(
    off_peak=Price(0.22, 0.66, 0.007),
    peak=Price(0.44, 1.32, 0.014),
    schedule=Schedule.parse("01-04,06-10"),
)


def _utc(hour: int) -> datetime:
    return datetime(2026, 8, 27, hour, 30, tzinfo=timezone.utc)


@pytest.mark.parametrize("hour", [1, 2, 3, 6, 7, 8, 9])
def test_the_peak_window_is_half_open_and_inclusive_of_its_start(hour):
    assert FLASH.schedule.is_peak(_utc(hour)) is True


@pytest.mark.parametrize("hour", [0, 4, 5, 10, 11, 17, 23])
def test_everything_outside_the_window_is_off_peak(hour):
    assert FLASH.schedule.is_peak(_utc(hour)) is False


def test_a_window_that_wraps_midnight_is_read_as_written():
    overnight = Schedule.parse("22-02")
    assert overnight.is_peak(_utc(23)) is True
    assert overnight.is_peak(_utc(1)) is True
    assert overnight.is_peak(_utc(3)) is False


def test_a_malformed_window_degrades_to_off_peak_rather_than_raising():
    """
    A typo in a price window must not stop the service answering questions, and
    off-peak is the rate that is correct more of the time.
    """
    assert Schedule.parse("not-a-window").windows == ()
    assert Schedule.parse("").is_peak(_utc(2)) is False


def test_the_same_call_costs_twice_as_much_inside_the_window():
    """
    The reason a single configured number would not do.

    Not exactly twice: each tier rounds to the nearest micro-dollar on its own,
    and $0.013894 doubled is a hair under the $0.027789 the peak tier rounds to.
    That one micro-dollar is the correct answer for each tier taken separately,
    which is what the provider charges.
    """
    off = FLASH.at(_utc(12)).micro_usd(54_294, 2_954)
    on = FLASH.at(_utc(2)).micro_usd(54_294, 2_954)
    assert (off, on) == (13_894, 27_789)
    assert abs(on - off * 2) <= 1


def test_a_cached_read_is_the_bargain_the_provider_says_it_is():
    """$0.007 against $0.22: cached input is priced at ~3% of fresh input."""
    price = FLASH.at(_utc(12))
    fresh = price.micro_usd(10_000, 0)
    cached = price.micro_usd(10_000, 0, cached_input_tokens=10_000)
    assert (fresh, cached) == (2_200, 70)


def test_the_book_resolves_the_tier_at_the_moment_of_the_call():
    book = PriceBook(chat_model="deepseek-v4-flash", chat_price=FLASH)
    assert book.micro_usd("deepseek-v4-flash", 1_000_000, 0, when=_utc(12)) == 220_000
    assert book.micro_usd("deepseek-v4-flash", 1_000_000, 0, when=_utc(2)) == 440_000


def test_a_flat_price_answers_the_same_at_every_hour():
    """`.at()` exists so the book never has to ask which kind of rate it holds."""
    flat = Price(0.27, 1.10)
    assert flat.at(_utc(2)) is flat.at(_utc(14)) is flat


def test_settings_without_a_peak_window_stay_flat():
    """Peak pricing is opt-in; the two rates alone are not enough to switch it on."""
    from types import SimpleNamespace

    from analyst_copilot.usage.pricing import from_settings

    book = from_settings(
        SimpleNamespace(
            openai_model="m",
            chat_price_input=0.22,
            chat_price_output=0.66,
            chat_price_cached_input=0.007,
            chat_price_peak_input=0.44,
            chat_price_peak_output=1.32,
            chat_price_peak_cached_input=0.014,
            chat_price_peak_hours_utc="",
            resolved_embedding_model="e",
            embedding_price_input=0.01,
        )
    )
    assert isinstance(book.rate("m"), Price)
    assert book.micro_usd("m", 1_000_000, 0, when=_utc(2)) == 220_000


def test_settings_build_the_tiered_rate_this_deployment_actually_uses():
    from types import SimpleNamespace

    from analyst_copilot.usage.pricing import from_settings

    book = from_settings(
        SimpleNamespace(
            openai_model="deepseek-v4-flash",
            chat_price_input=0.22,
            chat_price_output=0.66,
            chat_price_cached_input=0.007,
            chat_price_peak_input=0.44,
            chat_price_peak_output=1.32,
            chat_price_peak_cached_input=0.014,
            chat_price_peak_hours_utc="01-04,06-10",
            resolved_embedding_model="qwen/qwen3-embedding-8b",
            embedding_price_input=0.01,
        )
    )
    assert isinstance(book.rate("deepseek-v4-flash"), TieredPrice)
    assert book.micro_usd("deepseek-v4-flash", 1_000_000, 0, when=_utc(7)) == 440_000
    assert book.micro_usd("deepseek-v4-flash", 1_000_000, 0, when=_utc(19)) == 220_000
    # The embedding model is flat and, at $0.01/M, nearly free at query volume.
    assert book.micro_usd("qwen/qwen3-embedding-8b", 24, 0) == 0
    assert book.micro_usd("qwen/qwen3-embedding-8b", 1_000_000, 0) == 10_000


def test_a_stage_records_which_model_spent_under_it():
    """
    The header can name one model, and `models[0]` named the wrong one.

    `models` on the report is in first-use order, and the query embedding runs
    before any chat call — so the run's first model is reliably the cheapest
    thing in it. Attribution belongs on the stage, where it is a fact rather
    than an inference.
    """
    book = PriceBook(
        chat_model="deepseek-v4-flash",
        chat_price=Price(0.22, 0.66),
        embedding_model="qwen/qwen3-embedding-8b",
        embedding_price=Price(0.01, 0.0),
    )
    meter = usage.UsageMeter(book)
    with usage.metering(meter), usage.stage("retrieving", "Read the retrieved pages"):
        usage.record_as(
            usage.Usage(model="qwen/qwen3-embedding-8b", input_tokens=26),
            "embedding",
            "Embedded the query",
        )
        usage.record(
            usage.Usage(model="deepseek-v4-flash", input_tokens=3_354, output_tokens=2_920)
        )

    report = meter.report()
    by_stage = {entry.stage: entry for entry in report.stages}
    assert by_stage["embedding"].models == ["qwen/qwen3-embedding-8b"]
    assert by_stage["retrieving"].models == ["deepseek-v4-flash"]
    # The cheapest stage is the one the run's model list starts with, which is
    # exactly why the header cannot use it.
    assert report.models[0] == "qwen/qwen3-embedding-8b"
    assert by_stage["embedding"].micro_usd < by_stage["retrieving"].micro_usd
    assert by_stage["embedding"].to_dict()["models"] == ["qwen/qwen3-embedding-8b"]


def test_a_stage_cheaper_than_a_micro_dollar_reports_zero_not_a_fraction():
    """
    26 tokens at $0.01/M is $0.00000026, and money is carried as integer
    micro-dollars — so this arrives as an exact zero and the UI, not the meter,
    is what must avoid calling it free.
    """
    book = PriceBook(embedding_model="e", embedding_price=Price(0.01, 0.0))
    meter = usage.UsageMeter(book)
    with usage.metering(meter), usage.stage("embedding", "Embedded the query"):
        usage.record(usage.Usage(model="e", input_tokens=26))

    entry = meter.report().stages[0]
    assert entry.micro_usd == 0
    assert entry.priced is True  # priced, and it still cost something
    assert entry.input_tokens == 26


# --------------------------------------------------------------------------- #
# by model: the split that can be checked against an invoice
# --------------------------------------------------------------------------- #
def _two_model_book() -> PriceBook:
    return PriceBook(
        chat_model="deepseek-v4-flash",
        chat_price=Price(0.22, 0.66),
        embedding_model="qwen/qwen3-embedding-8b",
        embedding_price=Price(0.01, 0.0),
    )


def test_spend_is_reported_by_model_as_well_as_by_stage():
    """
    Two views of one number, and neither is derived from the other.

    By stage answers "where did the time go"; by model answers "what will the
    provider charge me". Folding the second out of the first would mean reading
    a model off a stage, which is an inference — this is aggregated from the
    calls.
    """
    meter = usage.UsageMeter(_two_model_book())
    with usage.metering(meter):
        with usage.stage("retrieving", "Read the retrieved pages"):
            usage.record_as(
                usage.Usage(model="qwen/qwen3-embedding-8b", input_tokens=26),
                "embedding",
                "Embedded the query",
            )
            usage.record(
                usage.Usage(model="deepseek-v4-flash", input_tokens=4_281, output_tokens=575)
            )
        with usage.stage("validating", "Checked the answer"):
            usage.record(
                usage.Usage(model="deepseek-v4-flash", input_tokens=3_326, output_tokens=322)
            )

    report = meter.report()
    by_model = {entry.model: entry for entry in report.by_model}
    assert set(by_model) == {"deepseek-v4-flash", "qwen/qwen3-embedding-8b"}

    chat = by_model["deepseek-v4-flash"]
    assert chat.calls == 2
    assert chat.input_tokens == 4_281 + 3_326
    assert chat.output_tokens == 575 + 322
    assert chat.total_tokens == 8_504

    embed = by_model["qwen/qwen3-embedding-8b"]
    assert (embed.calls, embed.input_tokens, embed.output_tokens) == (1, 26, 0)

    # The two splits are the same money, counted two ways.
    assert sum(entry.micro_usd for entry in report.by_model) == report.micro_usd
    assert sum(entry.micro_usd for entry in report.stages) == report.micro_usd
    assert (
        sum(entry.total_tokens for entry in report.by_model)
        == report.total_tokens
    )


def test_one_unpriced_model_does_not_make_the_other_unpriced():
    """
    Per-model is where an unpriced model stays contained.

    The run's total is withheld -- a total missing half its calls is worse than
    none -- but the model that *is* priced still reports what it cost, because
    that figure is complete on its own.
    """
    book = PriceBook(chat_model="priced", chat_price=Price(0.22, 0.66))
    meter = usage.UsageMeter(book)
    with usage.metering(meter):
        with usage.stage("retrieving", "Read the retrieved pages"):
            usage.record(usage.Usage(model="priced", input_tokens=1_000, output_tokens=100))
        with usage.stage("embedding", "Embedded the query"):
            usage.record(usage.Usage(model="mystery", input_tokens=26))

    report = meter.report()
    assert report.priced is False and report.cost_usd is None
    by_model = {entry.model: entry for entry in report.by_model}
    assert by_model["priced"].priced is True
    assert by_model["priced"].to_dict()["cost_usd"] == round((1_000 * 0.22 + 100 * 0.66) / 1e6, 6)
    assert by_model["mystery"].priced is False
    assert by_model["mystery"].to_dict()["cost_usd"] is None


def test_by_model_survives_the_wire_shape():
    meter = usage.UsageMeter(_two_model_book())
    with usage.metering(meter), usage.stage("retrieving", "Read the retrieved pages"):
        usage.record(usage.Usage(model="deepseek-v4-flash", input_tokens=100, output_tokens=10))

    payload = meter.report().to_dict()
    assert payload["by_model"] == [
        {
            "model": "deepseek-v4-flash",
            "calls": 1,
            "input_tokens": 100,
            "output_tokens": 10,
            "cached_input_tokens": 0,
            "total_tokens": 110,
            "cost_usd": round((100 * 0.22 + 10 * 0.66) / 1e6, 6),
        }
    ]
