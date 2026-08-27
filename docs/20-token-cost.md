# What an answer cost

**Meter:** [`src/analyst_copilot/usage/`](../src/analyst_copilot/usage/)
**Strip:** [`ui/src/components/chat/UsageStrip.tsx`](../ui/src/components/chat/UsageStrip.tsx)
**Mock:** [`docs/mocks/token-cost.html`](mocks/token-cost.html)

Every answer reports the tokens it spent, broken down by the stage that spent
them. A deep run makes 37 model calls across seven stages and costs roughly
fifty times a fast one; before this, the only visible difference was that it
took a minute.

---

## Two refusals

Everything else here follows from these.

**No price is better than a wrong price.** A cost appears only when a rate is
configured for the model, or the model is one of the handful whose list price
ships in `pricing.py`. Otherwise the answer reports `priced: false`, `cost_usd:
null`, and the UI says *no price configured* beside the token count. This
service talks to an OpenAI-compatible gateway, which can put any model behind
any name at any margin — a dollar figure invented from an assumed rate is worse
than none, because an analyst will act on it.

**An estimate never looks like a measurement.** The provider's own `usage` is
preferred. When a response omits it, tokens are counted locally and the call is
flagged `estimated`; the flag propagates to the run and the UI renders a `~` and
says why. This is the same rule as the rest of the product: a figure that has
not been checked must not render like one that has.

Configure prices with `CHAT_PRICE_INPUT`, `CHAT_PRICE_OUTPUT`,
`CHAT_PRICE_CACHED_INPUT` and `EMBEDDING_PRICE_INPUT`, in USD per million
tokens. Zero is a legitimate value for a model you host yourself; unset is not
the same fact and is reported differently.

---

## Rates that change with the clock

Some providers charge more during their busy hours, and one number cannot
describe that. DeepSeek through OpenCode Zen doubles between **01:00–04:00 and
06:00–10:00 UTC**:

| | input | output | cached read |
|---|---|---|---|
| off-peak | $0.22 | $0.66 | $0.007 |
| peak | $0.44 | $1.32 | $0.014 |

Configuring either rate alone would be wrong by a factor of two for seven hours
of every day — the same failure the "no guessed price" rule exists to prevent,
arrived at from the other direction. So `TieredPrice` holds both, and
`Schedule` says which is in force:

```dotenv
CHAT_PRICE_INPUT=0.22          # the base rates are the OFF-PEAK tier
CHAT_PRICE_OUTPUT=0.66
CHAT_PRICE_CACHED_INPUT=0.007
CHAT_PRICE_PEAK_INPUT=0.44
CHAT_PRICE_PEAK_OUTPUT=1.32
CHAT_PRICE_PEAK_CACHED_INPUT=0.014
CHAT_PRICE_PEAK_HOURS_UTC=01-04,06-10
```

Peak pricing is opt-in: with no window set the rate is flat, whatever the peak
rates say. Windows are half-open `[start, end)` in whole UTC hours and may wrap
midnight (`22-02`). A malformed window degrades to off-peak rather than raising
— a typo in a price must not stop the service answering questions.

**The tier is resolved per call, as it is recorded**, not once per run. A deep
run takes a minute and can straddle 04:00; the provider bills each call at the
rate in force when it was made, and so does this.

Two consequences worth expecting rather than debugging:

- The same question costs twice as much at 02:00 UTC as at 14:00. That is
  correct, not a bug.
- Doubling is not exact to the micro-dollar. Each tier rounds on its own, so
  $0.013894 off-peak pairs with $0.027789 peak. Each is right for its own tier.

### Cached input is the cheap half

At $0.007 against $0.22, a cached read costs ~3% of a fresh one — and the deep
path re-sends a long system prompt to thirty-one readers. Whether the provider
actually serves them from cache is visible in `cached_input_tokens`, which is
reported in the strip's footnote when it is non-zero.

---

## Why the meter is a context variable

Three facts about this service ruled out the obvious designs:

- **The chat client is an `lru_cache`'d singleton.** One instance serves every
  request at once, so a counter on the client would bill two analysts together.
- **The pipeline runs off the event loop in a worker thread**, and the deep path
  fans out into a pool of its own.
- **The call sites are scattered** — router, splitter, fast path, checker,
  thirty-one readers, adjudicator, and the query embedding.

So `UsageMeter` lives in a `ContextVar`, bound inside `AnalystAgent.answer`
rather than at the caller — the pipeline body runs in a thread whose context is
not reliably the caller's. Each call site names its stage:

```python
with metering.stage(Stage.ROUTING.value, "Understood the question"):
    routing = self._intents().route(message, context)
```

The label is prose, written where the counts are known: only the orchestrator
can compose `"Read all 118 pages · 31 agents"`.

### The one gap, closed by hand

`ThreadPoolExecutor` starts its workers with an **empty context**. A bare
`pool.submit(reader.read, ...)` would lose every reader — which is most of what
a deep run costs — and report a total that was quietly, hugely wrong. So the
fan-out in `orchestrator._fan_out` submits through a copied context:

```python
context_for_reader = copy_context()
pool.submit(context_for_reader.run, reader.read, ...)
```

**Any future pool that makes model calls must do the same.** Both halves of that
are asserted in `tests/test_usage.py` — the copied-context pool records all 31,
and the bare one records nothing — so the guard cannot rot silently.

---

## Money is an integer

Cost is carried as **integer micro-dollars** everywhere below the formatting
layer, and stored that way in `messages.cost_micro_usd`. A run is dozens of
additions whose interesting digits sit at the fifth decimal place, which is
exactly where a float drifts. `tokens × (USD per million tokens)` is already
micro-dollars, so the arithmetic has no division in it to lose digits in.

A null cost is not a zero. "Nobody configured a rate" and "it was free" are
different facts, and only one of them should sum.

---

## The shape on the wire

`usage` on the `ChatResponse`, beside `latency_ms`:

```jsonc
"usage": {
  "input_tokens": 54294, "output_tokens": 2954, "total_tokens": 57248,
  "calls": 38, "cost_usd": 0.017909, "priced": true, "estimated": false,
  "models": ["deepseek-v4-flash", "qwen/qwen3-embedding-8b"],
  "stages": [
    {"stage": "routing", "label": "Understood the question", "calls": 1,
     "input_tokens": 412, "output_tokens": 18, "cost_usd": 0.000131},
    …
  ]
}
```

Stages appear in the order the run happened. Their token and cost totals sum to
the headline — a breakdown that does not add up makes an analyst distrust a
number that is correct, so it is asserted in the tests.

The figure is **final, not live**. It arrives with the answer rather than
accruing on screen, for the same reason the answer does not stream. The one
exception is a stop: a `cancelled` event carries the same `usage` object, because
a run that proved nothing was still paid for, and that is the moment the number
matters most.

The full `ChatResponse` is already persisted in `messages.result`, so stored
history re-renders the strip verbatim. The three extra columns
(`input_tokens`, `output_tokens`, `cost_micro_usd`, migration
`0002_message_usage`) exist so *"what has this thread cost?"* is a query rather
than a JSON unwrap.

---

## The strip

A footer on `AnswerCard`, below the citations and the agent trail — the cost is
a property of the answer, not a headline, and a card must not open with a price.
Collapsed by default:

```
⌄ ◎ 57,272 tokens · $0.0179              38 calls · deepseek-v4-flash
```

Expanded, one row per stage with calls, input, output and cost. The row's own
background is its **share of the run's cost**, so the reader fan-out that
dominates a deep run is visible without a chart or a second colour.

Costs render to four decimals in the headline and six in the table: the headline
is read at a glance, the rows are compared against each other, and `$0.0001`
would collapse four distinct stages into one number.

**No state colour appears here.** `verified`, `declined`, `failed` and
`building` mean the system proved, declined, errored, or is indexing — a cost is
none of those, so the strip is ink and accent only. See
[Design system](18-design-system.md).

[`docs/mocks/token-cost.html`](mocks/token-cost.html) is the pixel reference:
six states across both themes and all five accents, with a spec overlay. Open it
in a browser before changing the strip's spacing.
