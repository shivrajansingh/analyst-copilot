# The agent harness

**Modules:** `analyst_copilot.agent.*`
**Entry point:** `AnalystAgent.answer` — [`agent/pipeline.py`](../src/analyst_copilot/agent/pipeline.py)

How a message becomes a proven answer, an honest refusal, or a reply to a
greeting. This document is the tier boundaries, the tools, and what each part
exists to fix.

---

## Why there is a second answering path at all

The retrieval pipeline ([Document retrieval](07-hybrid-retrieval.md)) answers
from the five pages it selected. Measured on all 136 practice questions, that
set contains the gold evidence page **58% of the time**. The other 42% are not
hard questions — they are *unreachable* ones. No prompt, model or verifier can
cite a page that was never retrieved.

Three failures fall out of the measured +7 run, and each one is a tier here:

| Measured failure | Count | What fixes it |
|---|---:|---|
| Gold page never retrieved | ~57 questions | Read every page (tier 3) |
| Right figure, wrong question or wrong page | 23 | A second reader that checks meaning (tier 2) |
| Confidently wrong | 22 | A verifier that can prove derived figures, and abstain otherwise |
| A derived figure can never verify | 43 numerical-reasoning questions | Verify the **inputs**, not the result |

And one failure that was not about score at all: typing "Hi" retrieved five
pages of a 10-K and replied *"not found in this filing"*.

---

## The shape

```text
message
  │
  ├─ 0. route          IntentRouter            smalltalk / capability / question
  │                    └─ not a question? answer it conversationally and stop
  │
  ├─ 1. split          QuestionDecomposer      one question per thing asked
  │
  │  ... for each part:
  │
  ├─ 2. TIER 1         QuestionAnsweringService   hybrid retrieval → LLM → verify
  │                    ~3s, unchanged from before
  │
  ├─ 3. TIER 2         AnswerValidator         a reader that did not write the
  │                    ~4s                     answer checks it against the
  │                                            WHOLE cited page
  │                    └─ verdict `correct`? serve it and stop
  │
  ├─ 4. TIER 3         DeepSearchOrchestrator  every page read by parallel
  │                    ~60s                    agents, then adjudicated
  │
  └─ 5. verify         verify_agent_answer     deterministic, always last
                       → answer + citation, or "not found in this filing"
```

**The deterministic verifier never moves.** Agents propose; it disposes. Nothing
reaches an analyst that a page's own text does not support, however many agents
voted for it.

---

## Tier 0 — routing

[`agent/router.py`](../src/analyst_copilot/agent/router.py)

Every message is classified before anything is retrieved.

- **Greetings cost nothing.** `hi`, `thanks`, `what can you do` and about forty
  others are matched literally, with no model call. Matching is on the whole
  normalised message, never a substring — `"hi, what was capex?"` is a question,
  and a `contains` rule would route it to small talk and answer it from nothing.
- **Ambiguity resolves toward the document.** Misrouting a greeting wastes a few
  seconds; misrouting a real question answers it from nothing. The prompt says
  so, and so does the fallback when the classifier is unreachable.

A conversational reply is told what the assistant is and which documents are
loaded, and told explicitly **not to state a figure from a filing** — nothing on
this path has been through retrieval or verification. It is rendered as plain
prose with no citation and no verified badge, so it cannot be mistaken for
something the filing proves.

## Tier 1 — decomposition

[`agent/decompose.py`](../src/analyst_copilot/agent/decompose.py)

*"What was FY2022 capex, and how did it change from FY2021, and what drove the
change?"* is three questions sharing one question mark. Embedded whole, the
query vector lands between a cash-flow statement, a year-on-year table and a
paragraph of commentary, and ranks none of them well.

Each part is retrieved, answered and **cited separately**, then composed. Two
rules keep it from doing harm:

- Each part must stand alone. Parts are researched independently, so the
  company, the fiscal year and the units are carried into every one.
- Splitting is the exception. A cheap pre-filter means single questions never
  pay for a model call, and on any doubt the question is returned unchanged.

Composition is done **in code, not by a model**: a model asked to merge four
answers rewrites their figures, and a figure that changes after verification is
unverified again.

## Tier 2 — validation

[`agent/validator.py`](../src/analyst_copilot/agent/validator.py)

Tier 1's verifier checks that the answer's digits trace to the cited page. That
catches a fabricated number. It does not catch the two failures that cost the
most marks, because both are about *meaning*:

- **Right figure, wrong question** — the wrong fiscal year, a segment instead of
  the consolidated total. Every figure traces. The answer is still not the answer.
- **Half an answer** — a compound question answered in one part reads as
  complete and verifies cleanly.

So a reader that did not write the answer is shown the question, the answer and
the **whole cited page** — not the 2,200-character excerpt the writer saw — and
asked whether the answer is right. It has the calculator and the read tools, so
it re-does the arithmetic rather than eyeballing it.

| Verdict | Effect |
|---|---|
| `correct` | Serve the fast answer |
| `incorrect` | Escalate to tier 3 |
| `insufficient` | Escalate to tier 3 |
| `unchecked` | **Serve** — see below |

`unchecked` serving is deliberate. When validation itself is broken, the fast
answer has already passed the deterministic evidence check, and escalating every
question to a full document read because of a provider hiccup would turn a blip
into a 60-second response for everyone.

The asymmetry is the point: a false `incorrect` costs a slow second search, a
false `correct` puts a wrong figure in front of an analyst.

## Tier 3 — deep search

[`agent/orchestrator.py`](../src/analyst_copilot/agent/orchestrator.py)

Every page is read. There is no shortlist, so there is no recall ceiling.

```text
126-page filing
  → 13 shards of ≤10 pages          shards never straddle two documents
  → 13 reader agents, 8 concurrent  each may read ONLY its own pages
  → candidates (found=true only)
  → 1 synthesis agent               sees candidates, never raw pages
  → deterministic verification
```

**Readers cannot overlap.** Every page belongs to exactly one reader, so the
readers together have read the whole document *and* two agents can never report
the same figure from the same page and inflate a consensus that was never
independent. Asked for a page outside its slice, a tool replies with the range
the reader does hold.

That matters because the predicted failure of full fan-out is precision, not
recall. A filing prints its important figures several times over — a measured
example: asked for 3M's FY2018 capex, reader 6 found `(1,577)` in the
consolidated statement of cash flows *and* reader 13 found the same figure in
the five-year selected data. Both are correct; only one is the right citation.
Resolving that is the synthesis agent's entire job, and it is why the
[authority policy](#the-authority-policy) lives in its prompt.

Synthesis sees **candidate findings, not pages**, so its input stays small
however large the filing. It can read any page to check a finding, and it does
when two disagree. A single non-partial candidate skips synthesis entirely:
there is nothing to adjudicate, and a call over one finding only adds a chance
to paraphrase it wrongly.

If synthesis fails, the strongest single candidate is used rather than
discarding a whole fan-out — the verifier still gates it.

### Deep search needs no embeddings

Readers read the Markdown store, not the vector index. So the deep path works on
a document that has been parsed but never embedded, and — more importantly — it
reads pages **in full**. The vector index only ever saw the first
`retrieval_max_chars_per_page` (2,500) characters of each page, which is where
13% of the corpus's gold evidence hides. The 47,221-character page of
`3M_2023Q2_10Q` whose evidence sits at character 45,234 is invisible to
retrieval and ordinary reading to an agent.

---

## The tools

[`agent/tools/`](../src/analyst_copilot/agent/tools/)

| Tool | What it does |
|---|---|
| `list_pages` | The pages in scope, with each page's own heading and size |
| `search_document` | Every matching line, with page and line number |
| `read_page` | One page in full, windowed for long pages |
| `read_lines` | A numbered line range, so a table row arrives with its header |
| `calculate` | Exact arithmetic |
| `report_finding` / `submit_answer` / `report_validation` | Terminal schemas |

Three decisions worth stating:

**Page numbers are the ones a human sees.** Every tool argument and every line
of output uses the 1-based number `list_pages` prints, which is what the
citation label says. Internally citations are 0-based `page_index`. The
translation happens in exactly one place — where a reader's finding becomes a
citation — because a numbering that changes meaning halfway through a
conversation is how a correct answer gets cited to the wrong page.

**A tool never raises at the model.** Bad arguments, a missing page, a broken
regex: all come back as ordinary output saying what went wrong. A model that
reads an error corrects itself; an exception ends the run and loses the
question.

**Search normalises digit grouping.** A filing's `1,577` and a query's `1577`
are the same figure, and a search that misses on a comma is a search an analyst
cannot trust.

### Terminal tools

An agent finishes by *calling a tool*, not by writing prose. The obvious
alternative — let it stop calling tools and parse what it wrote — fails in two
ways that matter: the JSON is sometimes malformed, and a model with nothing to
report will happily write a paragraph explaining what it looked for, which a
parser then has to decide is or is not an answer.

Making the report a tool call moves the schema into the provider's own
validation. A finding arrives with its required fields or does not arrive, and
**"I found nothing" becomes a deliberate `found: false`** rather than an absence.

Prose instead of a report is not treated as evidence.

---

## Verifying a computed answer

[`agent/verification.py`](../src/analyst_copilot/agent/verification.py)

This is the change that unblocks a whole class of questions.

43 practice questions are numerical reasoning and 34 gold records cite two or
three pages. The original verifier required every number in the answer to appear
on the single cited page — so an operating margin of `24.3%`, or a fixed-asset
turnover of `24.26`, **could never verify**, because it appears nowhere in the
filing. Only its inputs do. Every such question was an abstention by
construction, and the marks were unreachable.

A derived answer is now verified one level down. All four conditions must hold:

1. every input figure's significant digits trace to the page it was read from —
   the same scale-free test used for a direct answer;
2. the arithmetic is re-run here, deterministically, from the recorded
   expression;
3. the numbers in that expression are the recorded inputs, so a real set of
   inputs cannot launder an unrelated calculation;
4. the recomputed result agrees with the figure the answer states, allowing
   rounding and rescaling.

Worked example, measured end to end:

```text
Q     What is the FY2019 fixed asset turnover ratio for Activision Blizzard?
      (revenue / average PP&E between FY2018 and FY2019)
gold  24.26, evidence pages 68 and 69

13 readers over 126 pages → 1 candidate
  answer      24.26
  computation 6489 / ((253 + 282) / 2)
  inputs      Total net revenues FY2019      6,489  page 69
              Property and equipment, net    253    page 68
              Property and equipment, net    282    page 68
  verified    DERIVED   (all three inputs traced; arithmetic re-run)
  cited       page 69
```

Each of the three ways to cheat is caught, and each is a test:

| Attempt | Result |
|---|---|
| An input that is not on its page | `input figures do not appear on the pages they were cited to` |
| Real inputs, unrelated computation | `the computation uses figures that are not among its recorded inputs` |
| Arithmetic that does not match the stated answer | `the answer does not state the computed result` |

Scale factors and rounding precision (`* 100`, `round(x, 2)`) are recognised as
structure rather than as figures read off a page.

The UI shows all of this — see `DerivationTrail`. An analyst asked to trust a
number that no page contains needs to see the inputs, their pages, and the
expression.

---

## Progress, and why the answer is not streamed

`POST /chat/stream` emits `stage` events, then exactly one `answer` event.

What streams is **progress, not tokens**. Verification runs after the model
replies, so streaming an answer would put an unproven figure on screen for a
second or two — the one thing this product exists to prevent. The answer arrives
atomically, already verified.

```text
event: stage   {"stage":"routing","detail":"reading the message"}
event: stage   {"stage":"retrieving","detail":"searching the filing"}
event: stage   {"stage":"validating","detail":"checking the answer"}
event: stage   {"stage":"escalating","detail":"reading the whole filing"}
event: stage   {"stage":"deep_search","detail":"reader 4: nothing here","done":4,"total":13}
event: stage   {"stage":"synthesizing","detail":"2 of 13 readers found something"}
event: answer  {...the full ChatResponse...}
```

It is a POST, so it is read with `fetch` and a stream reader rather than
`EventSource` — the request carries a body. A keepalive comment every 15s keeps
an idle connection from being closed mid-read, and the API sets
`X-Accel-Buffering: no` so nginx does not hold every event until the end.
Closing the reader cancels the work rather than leaving a fan-out running for
nobody.

---

## The authority policy

The same figure appears in the income statement, in MD&A, in a segment footnote
and in the five-year selected data. Reading more of the document surfaces more
copies of it, so every agent that can cite is told which copy is authoritative:

- The question names a statement → cite that statement.
- A bare figure with no source named → cite the primary financial statement it
  is reported in, not a narrative page that repeats it.
- "What drove / why did / explain a change" → cite the management discussion,
  not the statement showing the total.
- What the company does, where it operates, what it sells → cite the business
  description, not a footnote that mentions it in passing.

---

## Configuration

All in [`config/settings.py`](../src/analyst_copilot/config/settings.py), all
overridable by environment variable.

| Setting | Default | Effect |
|---|---|---|
| `agent_enabled` | `true` | The harness answers `/chat`. |
| `agent_validate_answers` | `true` | Tier 2. Off = serve any verified fast answer. |
| `agent_deep_search` | `true` | Tier 3. Off = abstain instead of reading the filing. |
| `agent_pages_per_shard` | `10` | Pages one reader is responsible for. |
| `agent_max_concurrency` | `8` | Readers in flight. Bounded by the provider's rate limit, not local CPU. |
| `agent_max_shards` | `0` | Hard cap on readers per question. **0 = no cap.** A cap means the document was not fully read, and is logged as such. |
| `agent_reader_max_iterations` | `8` | Tool-calling turns per reader. |
| `agent_synthesis_max_iterations` | `10` | Turns for the adjudicator. |
| `agent_decompose` | `true` | Split compound questions. |
| `agent_max_parts` | `4` | Most parts one question may become. |
| `agent_history_turns` | `6` | Prior turns shown, so "and the year before?" resolves. |

---

## What it measured, and what that forced

First 10 practice questions, same code and same corpus, judged with
`score.py --judge`:

| | Fast path alone | Harness, first cut |
|---|---:|---:|
| **Rubric score** | **+2** | **−1** |
| +1 correct answer and location | 3 | 3 |
| 0 correct answer, wrong page | 2 | 2 |
| 0 abstained | 4 | 1 |
| **−1 confidently wrong** | **1** | **4** |

The harness found more and abstained less. The rubric charged twice as much for
what came with it, and the first cut was **three points worse than the pipeline
it was meant to improve**.

This is the failure already on record in
[Document retrieval](07-hybrid-retrieval.md): *"a change that raised recall@5
from 4/10 to 7/10 lowered the rubric score, because better retrieval also
converts abstentions into confident wrong answers."* Removing a recall ceiling
does not by itself earn a mark. It earns the *opportunity* to answer, and an
answer that is not right costs double.

**None of the four was a fabrication.** Every figure in every one traces to its
cited page, which is precisely why the deterministic verifier passed them:

| Question | Cited page | What was wrong |
|---|---|---|
| "Is 3M capital-intensive based on FY2022 data?" | — | Answered *yes* from figures arguing *no* |
| Quick ratio "for Q2 of FY2023" | **gold page** | Computed from the **March** balance sheet |
| "Which debt securities are registered?" | **gold page** | A count of *four*, one of which had matured |
| "What drove operating margin change?" | — | 0.3pp against a gold of 1.7% |

Two of the four landed on the *correct gold page* and were still wrong. That is
the sharpest statement of what digit-tracing cannot do: it proves a figure is on
a page, and it cannot tell whether that figure is the right one for the question.

Two changes came out of this, both in the [validator](#tier-2--validation):

1. **The deep path now faces the meaning check too.** Only fast answers did
   before, which was a gap — a deep answer got deterministic verification and
   nothing else. Since there is no tier after the deep path, anything but
   `correct` now **abstains**: every deep answer this catches is a −1 that
   becomes a 0.
2. **The check leads with direction, period and form**, not with "is the figure
   on the page". Does the conclusion follow from the figures? Is this the column
   the question asked about? Does a question asking *which* get the items rather
   than a count of them?

A derived answer's expression and inputs are passed to the validator along with
the page, and it is told the figure is *expected* to be absent from that page —
otherwise the check would reject the Activision `24.26` for the very reason
verifying-through-inputs exists.

**The open question is whether the check is strict enough to convert those −1s
without also rejecting what the deep path gets right.** That is a measurement,
not an argument, and it is item 0 in [PLAN.md](../PLAN.md).

---

## What it costs

Measured on this corpus with `deepseek-v4-flash`:

| | Tier 1 | Tier 1+2 | Tier 3 |
|---|---:|---:|---:|
| Latency | ~3s | ~15s | ~60-90s |
| Model calls | 1 | 2-4 | 15-40 |
| Relative cost | 1× | ~2× | ~50× |
| Recall ceiling | 58% | 58% | **100%** |

Tier 3 runs only when the cheaper tiers could not produce an answer that
survived checking, which is what makes the average cost bearable while the
ceiling is removed for the questions that need it.

A 306-segment filing (`JPMORGAN_2022_10K`) is 31 readers. At concurrency 8 that
is four waves.

---

## Tests

```bash
PYTHONPATH=src pytest tests/test_agent_tools.py        # corpus, tools, calculator
PYTHONPATH=src pytest tests/test_agent_runtime.py      # the loop and the reader
PYTHONPATH=src pytest tests/test_agent_verification.py # derived answers
PYTHONPATH=src pytest tests/test_agent_pipeline.py     # tier boundaries
```

Every one runs offline. `ScriptedChat` replays fixed tool-calling turns, so the
loop's behaviour is reproducible; `tests/offline_harness.py` builds the real
pipeline with the two model-calling collaborators stubbed, so the HTTP contract
tests exercise the actual brain rather than a mock of it.
