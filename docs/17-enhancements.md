# What changed in this round

A summary of the enhancements added on top of the retrieval pipeline, what
measured failure each one closes, and what it measured afterwards. The deep
reference for the biggest of them is [Agent harness](16-agent-harness.md); this
document is the map and the numbers.

---

## Where it started

The system answered from the five pages retrieval selected. Measured on all 136
practice questions, tier 1 alone scored **+7** — 29 correct with location, 62
abstentions, 23 correct-answer-wrong-page, 22 confidently wrong — and retrieval
put the gold page in the top 5 for **58%** of questions.

Four things were wrong, and each one is an enhancement below:

| The failure | Why no prompt could fix it |
|---|---|
| 42% of questions unanswerable | The gold page was never retrieved. Nothing downstream can cite a page it was not shown. |
| 43 numerical-reasoning questions unprovable | A computed figure appears nowhere in a filing. The verifier required every number on the cited page, so a margin could never verify. |
| Right figure, wrong question | 23 answers were correct and cited the wrong page. Digit-tracing passes all of them, because it checks existence, not meaning. |
| "Hi" returned *"not found in this filing"* | Every message went to retrieval. The product read as a search box with a chat skin. |

---

## The enhancements

| # | Enhancement | Closes | Reference |
|---|---|---|---|
| 1 | [Whole-document deep search](#1-whole-document-deep-search) | The 58% recall ceiling | [16 §Tier 3](16-agent-harness.md#tier-3--deep-search) |
| 2 | [Answer validation](#2-answer-validation) | Right figure, wrong question | [16 §Tier 2](16-agent-harness.md#tier-2--validation) |
| 3 | [Derived-answer verification](#3-derived-answer-verification) | 43 unprovable computed answers | [16 §Verifying a computed answer](16-agent-harness.md#verifying-a-computed-answer) |
| 4 | [Partial findings](#4-partial-findings) | Answers spanning two statements | [16 §Partial findings](16-agent-harness.md#partial-findings-when-no-single-reader-can-answer) |
| 5 | [Intent routing](#5-intent-routing) | "Hi" searching a 10-K | [16 §Tier 0](16-agent-harness.md#tier-0--routing) |
| 6 | [Question decomposition](#6-question-decomposition) | Compound questions diluting retrieval | [16 §Tier 1](16-agent-harness.md#tier-1--decomposition) |
| 7 | [Streaming progress](#7-streaming-progress) | A minute of silence reading as a hang | [11 §Streaming](11-api.md#ask-a-question-streaming-progress) |
| 8 | [Evidence surfaces](#8-evidence-surfaces) | A computed figure with nothing to check | — |
| 9 | [Accent themes](#9-accent-themes) | A palette that read as decorative | [18](18-design-system.md) |

---

### 1. Whole-document deep search

The filing is sharded into slices of ten pages, one reader agent per slice, eight
concurrent. Readers may read **only** their own pages, so together they have read
the whole document and no two can report the same page. A synthesis agent then
adjudicates the candidates on authority.

Readers read the Markdown store, not the vector index — so they see pages **in
full**, past the 2,500-character embedding cap that hides ~13% of the corpus's
gold evidence.

**Measured:** reached pages the fast path could not, including the
registered-debt-securities question whose evidence sits at character 45,234 of a
47,221-character page — the case
[docs/07](07-hybrid-retrieval.md#known-limits) records as invisible to
retrieval. It cited the gold page there.

Be precise about what that did and did not buy: on that question and on the
quick-ratio one, the deep path found the **right page** and still produced a
**wrong answer** — an over-inclusive list, and the wrong balance-sheet date. Both
scored −1 until enhancement 2 was extended to cover them. Reaching a page is not
the same as reading it correctly.

### 2. Answer validation

A reader that did not write the answer sees the question, the answer and the
**whole** cited page, and rules `correct` / `incorrect` / `insufficient`. Only
`correct` serves; anything else escalates. An unreachable validator serves,
because the fast answer already passed the deterministic evidence check.

**Measured:** turned a wrong *yes* into a correct *no* on a gold page for "Is 3M
capital-intensive based on FY2022 data?" — a two-point swing on one question from
the direction check alone.

### 3. Derived-answer verification

A computed figure is verified one level down, and all four conditions must hold:
every input traces to the page it was read from; the arithmetic is re-run
deterministically from the recorded expression; the numbers in that expression
are the recorded inputs; and the result agrees with what the answer states.

**Measured:** Activision FY2019 fixed asset turnover — **24.26** against a gold
of 24.26, cited page 69 of gold [68, 69], three inputs traced. Previously an
abstention by construction.

### 4. Partial findings

Non-overlapping slices buy independence and cost something: a question needing
two statements gets a complete answer from nobody. A reader that cannot answer
now hands over what it *did* read (`found: false, partial: true`, figures in
`inputs` with their pages), and synthesis combines them — and may read any page
itself to fill a gap.

**Measured:** the FY2017-FY2019 average-capex-as-%-of-revenue question, which
previously read all 126 pages and returned nothing, returns **1.9%** against a
gold of 1.9%, cited to a gold page, from **six partials and zero complete
findings**.

### 5. Intent routing

Every message is classified before anything is retrieved. Common greetings match
literally, with no model call. Ambiguity resolves toward the document, because
answering a real question from nothing is the worse error. A conversational reply
carries no citation and no verified badge, so it cannot be mistaken for something
the filing proves.

### 6. Question decomposition

A message asking several things becomes several questions, each retrieved,
answered and **cited separately**. Composition is done in code, not by a model: a
model asked to merge four answers rewrites their figures, and a figure that
changes after verification is unverified again.

### 7. Streaming progress

`POST /chat/stream` emits `stage` events then exactly one `answer` event. What
streams is **progress, not tokens** — verification runs after the model replies,
so streaming an answer would put an unproven figure on screen.

### 8. Evidence surfaces

A derived answer needs a different kind of proof, so the evidence rail gained a
**"Computed, not quoted"** section: every input with the page it was read from,
and the expression the verifier re-evaluated. An analyst asked to trust a number
that no page contains has to be able to see where it came from.

Also: a `full read` badge when tier 3 answered, and a decline that says *"all 126
pages were read in full by 13 agents"* rather than just "no match" — a much
stronger statement of diligence.

### 9. Accent themes

The accent is chosen in Settings and stored per browser, defaulting to slate.
Green, amber and red stay reserved for state. See
[Design system](18-design-system.md).

---

## What it measured

First 10 practice questions, same code and corpus, judged with
`score.py --judge`:

| | Fast path alone | Harness, first cut | Harness, after validating deep answers |
|---|---:|---:|---:|
| **Rubric score** | **+2** | **−1** | **+1** |
| +1 correct answer and location | 3 | 3 | **4** |
| 0 correct answer, wrong page | 2 | 2 | 2 |
| 0 abstained | 4 | 1 | 1 |
| **−1 confidently wrong** | **1** | **4** | **3** |

Read that honestly. **The first cut was three points worse than the pipeline it
was meant to improve.** Removing a recall ceiling does not earn a mark; it earns
the *opportunity* to answer, and an answer that is not right costs double. None
of the four −1s was a fabrication — every figure traced to its cited page, and
two of them landed on the correct gold page and were still wrong.

Validating deep answers recovered two points. It is still one point behind, for
the same reason: the harness answers where the fast path abstained, and three of
those are wrong.

## What is still wrong

| | |
|---|---|
| **Abstention, not recall, is the next fix** | Two of the three remaining −1s are answers the system should have declined. |
| **An answer that disclaims its own evidence** | One is served `found: true` while its text reads *"the provided excerpts do not report a quick ratio for Q2 FY2023"*. Catching that is deterministic, not a judgement. |
| **The full 136 are not re-baselined** | Every number above is a 10-question sample. The standing +7 is tier 1 only. |
| **Compound questions are under-scored** | The key gives one gold page per question; the harness returns one citation per part, so `score.py` reads the primary and ignores the rest. |

Tracked in [`../PLAN.md`](../PLAN.md).

## What it costs

| | Tier 1 | Tier 1+2 | Tier 3 |
|---|---:|---:|---:|
| Latency | ~3s | ~15s | 60-290s |
| Model calls | 1 | 2-4 | 15-40 |
| Relative cost | 1× | ~2× | ~50× |
| Recall ceiling | 58% | 58% | **100%** |

Tier 3 runs only when the cheaper tiers could not produce an answer that survived
checking. The 290s figure is real — the partial-findings run over 126 pages,
where synthesis also had to read pages to complete the picture.

## Tests

256, all offline. `ScriptedChat` replays fixed tool-calling turns so the agent
loop is reproducible; `tests/offline_harness.py` builds the real pipeline with
its two model-calling collaborators stubbed, so the HTTP contract tests exercise
the actual brain rather than a mock of it.

```bash
PYTHONPATH=src pytest tests/test_agent_tools.py        # corpus, tools, calculator
PYTHONPATH=src pytest tests/test_agent_runtime.py      # the loop, the reader, partials
PYTHONPATH=src pytest tests/test_agent_verification.py # derived answers
PYTHONPATH=src pytest tests/test_agent_pipeline.py     # tier boundaries
```
