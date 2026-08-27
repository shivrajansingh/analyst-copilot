# Analyst Copilot — Plan

This file tracks delivery against `AGENTS.md`. It is the source of truth for **done vs remaining**.

---

## Goal

A chatbot that answers analyst questions over one SEC filing at a time, with a **page citation** on every answer, or a plain **“not found in this filing.”** Guessing is worse than abstaining.

---

## Completed

| Area | Status | Notes |
|------|--------|--------|
| Project layout | Done | `src/analyst_copilot/` package, scripts, tests, gitignore |
| Config / `.env` | Done | Chat vs embedding URLs; OpenAI-compatible embeddings |
| HTML parsing + pages | Done | Page breaks + printed footer numbers |
| Embeddings client | Done | Single `/v1/embeddings` client (Ollama or other) |
| BM25 retrieval | Done | Tokenize, build, search, persist |
| Vector retrieval | Done | Embed pages, cosine search, persist |
| Hybrid retrieval | Done | Query expansion + RRF + weighted fusion + statement boost |
| Indexing services | Done | `FilingIndexer` (BM25) and `HybridFilingIndexer` |
| QA pipeline | Done | Chat client, JSON extract, verifier, abstain |
| Abstention | Done | Low retrieval score, model not_found, number/page checks |
| Demos / tests | Done | Parse, embed, BM25, hybrid, QA unit tests |
| Eval runner | Done | `scripts/eval/run_practice.py` writes `data/eval-results.json` |
| Page-aligned citations | Done | Page-break split now matches `<hr>`/`<p>`/`<div>`; citations use 0-based `page_index` |
| Index invalidation | Done | `PARSER_VERSION` stamped in index metadata; stale indices rebuild automatically |
| Rubric scorer | Done | `scripts/eval/score.py` grades +1 / 0 / −1 against the practice key |
| Chat UI + "Add filing" | Done | React app in `ui/`, per-document job progress, evidence rail |
| HTTP API | Done | Filings, folders, chat, streaming chat, conversations |
| Chat history | Done | Postgres via Alembic; `db`/`migrate`/`api`/`ui` compose stack |
| Multi-format intake | Done | PDF/HTML/Word/Excel/CSV/Markdown, upload or by URL |
| **Agent harness** | Done | Route → split → tier 1 → validate → whole-document deep search |
| **Conversational replies** | Done | "Hi" is answered as a greeting, not searched for in a 10-K |
| **Derived-answer verification** | Done | A computed figure is proven through its inputs, not by appearing on a page |

Docs for completed work live in [`docs/`](docs/README.md).

---

## Measured baseline

> **This baseline is tier 1 only.** It was measured before the agent harness
> existed and is kept as the number the harness must be compared against, not as
> a description of what the system now does. Re-baselining is item 1 under
> Remaining.

Same 10 questions (4 filings), before and after the parsing/citation fixes.
Prose answers graded with `score.py --judge`.

| | Before | After |
|---|---|---|
| Rubric score | **0** | **+2** |
| Answered (not abstained) | 3 | 3 |
| Answer correct when it answers | 3/3 | 3/3 |
| **Location correct when answer correct** | **0/3** | **2/3** |
| Confidently wrong (−1) | 0 | 0 |

Every point gained came from citations, not from the model: the answers were
already right. `3M_2018_10K` capex went from citing page 60 to page 59 (gold 59),
and the FY2022 operating-margin answer from page 78 to page 26 (gold 26).

Two things this baseline says about where the remaining marks are:

- **7 of 10 still abstain, and all 7 are `model_abstain`** — the model receives
  excerpts and judges them insufficient. Not one abstention came from the
  verifier. That points at the evidence window (2b) rather than at verification.
- **Zero −1 answers.** Abstention is currently tuned conservatively enough that
  nothing is confidently wrong. Any change that converts abstentions into answers
  must be re-scored for −1, since each one costs twice what it gains.

Caveat: `--judge` uses the same chat model that produced the answers, so prose
grades carry a self-assessment bias. The three judged verdicts were spot-checked
by hand and hold up. A full run should re-check a sample.

Reproduce:

```bash
PYTHONPATH=src python scripts/eval/run_practice.py --limit 10 --output data/eval-after-fix.json
PYTHONPATH=src python scripts/eval/score.py --results data/eval-after-fix.json --judge
```

---

## Remaining (required for the product)

### 0. The harness has to earn its abstentions back

**Measured, first 10 practice questions, same code and same corpus:**

| | Fast path alone | Harness, first cut | Harness, deep answers validated |
|---|---:|---:|---:|
| Rubric score | **+2** | **−1** | **+1** |
| +1 correct answer and location | 3 | 3 | **4** |
| 0 correct answer, wrong page | 2 | 2 | 2 |
| 0 abstained | 4 | 1 | 1 |
| **−1 confidently wrong** | **1** | **4** | **3** |

The harness found more and abstained less, and the rubric charged twice as much
for what came with it. This is exactly the warning already recorded in
[docs/07](docs/07-hybrid-retrieval.md): *"a change that raised recall@5 from
4/10 to 7/10 lowered the rubric score, because better retrieval also converts
abstentions into confident wrong answers."*

**None of the four was a fabrication.** Every figure in every one traces to its
cited page, which is why the deterministic verifier passed them all:

| Question | What happened |
|---|---|
| "Is 3M capital-intensive?" | Answered *yes* from figures arguing *no* |
| Quick ratio "for Q2 FY2023" | Computed from the **March** balance sheet |
| "Which debt securities are registered?" | A count of *four*, one of which had matured |
| "What drove operating margin change?" | 0.3pp against a gold of 1.7% |

Two came out of the deep path, which was a gap: only fast answers faced the
second reader. Fixed — the deep path now faces the same check, and since there
is no tier after it, anything but `correct` abstains. The validator prompt now
leads with direction, period and the form asked for rather than with "is the
figure on the page".

**Measured after the fix: −1 → +1.** Two points recovered, and the derived
answer survived (Activision, gold 24.26, answered 24.26 from three traced
inputs), so passing the derivation to the validator did its job. The
capital-intensive question flipped from a wrong *yes* to a correct *no* on a gold
page — a two-point swing on one question from the direction check alone.

**It is still a point behind the pipeline it was meant to improve**, and for the
same reason: the harness answers where the fast path abstained, and three of
those answers are wrong. The three that remain:

| Question | What is still wrong |
|---|---|
| "What drove operating margin change FY2022?" | 0.3pp against a gold of 1.7%, cited page 20 against gold 26 |
| Quick ratio "for Q2 FY2023" | Served `found: true` with the text *"the provided excerpts do not report a quick ratio for Q2 FY2023"* — a non-answer that no check rejected |
| "Which debt securities are registered?" | Still a count of four rather than the three items, so the `form asked for` rule did not fire |

**The next move is abstention, not recall.** Two of the three are answers the
system should have declined, and the second is the clearest: an answer whose own
text says the evidence is absent must never be served as found. That is a
deterministic check, not a judgement — if the answer text disclaims its own
evidence, abstain.

### 1. Re-baseline the harness on all 136 questions

**What:** the standing number is **+7 over all 136 questions** (29 correct with
location, 62 abstentions, 23 correct-answer-wrong-page, 22 confidently wrong),
measured with tier 1 alone. Every claim about the harness has to be measured
against it on the same questions, with the −1 column watched at least as closely
as the +1 column.

```bash
PYTHONPATH=src python scripts/eval/run_practice.py --fast-only --output data/eval-fast-136.json
PYTHONPATH=src python scripts/eval/run_practice.py              --output data/eval-harness-136.json
PYTHONPATH=src python scripts/eval/score.py --results data/eval-harness-136.json --judge
```

The runner prints which tier answered each question, so a score change can be
attributed rather than assumed. Two things to check specifically:

- **Did the deep path convert abstentions into −1s?** It removes the recall
  ceiling, and a wrong answer costs twice what an abstention does. The
  deterministic verifier is what should prevent this; the eval is what proves it.
- **Did tier 2 escalate answers that were already right?** Every false
  `incorrect` costs a ~60s search for no gain.

### 2. Scoring a compound question

The practice key gives one gold page per question, and the harness now returns
one citation *per part*. A two-part answer is scored against a single gold page,
so `score.py` reads the primary citation and ignores the rest. That
under-reports a correctly answered compound question. Either extend the scorer
to accept any of an answer's citations, or record parts separately in the
results file.

### 3. Within-page chunking (still unfixed, now less load-bearing)

`retrieval_max_chars_per_page = 2500`; 73% of pages exceed it, and ~13% of gold
evidence blocks begin past the cap. The extreme case is `3M_2023Q2_10Q` page 1:
47,221 characters, of which 2,500 were embedded, with the gold evidence at
character 45,234.

The deep path is unaffected — readers read the Markdown store, in full — so this
no longer caps what the system can answer, only what **tier 1** can answer
cheaply. It is now a cost optimisation rather than a correctness fix: every
question tier 1 could have answered from a whole page is a ~50× saving.

Fix properly with within-page chunking (chunk after parse, cite the parent
page), not by raising the cap — real pages exceed any safe cap.

### 4. One-page approach note

`README.md` is done. `APPROACH.md` is not, and it is explicitly graded: one page
on what was tried, what was measured, what was kept and what was thrown away.

The material already exists and should be cited rather than re-argued:

- RRF disabled after measurement — [docs/07](docs/07-hybrid-retrieval.md) has the
  ablation table (+1 → +7).
- Printed footer page numbers parsed and then **not** used, because they disagree
  with gold in both directions — [docs/03](docs/03-html-parsing.md).
- Evidence-first verification replacing exact-page matching — 15 of 62 documents
  paginate differently between two readings of the same filing.
- Shortlist fan-out rejected in favour of reading every page —
  [docs/12](docs/12-multi-agent-retrieval.md) is the argument, and the departure
  from it is stated at the top.
- The statement-title boost, kept but **unproven**: it changed no outcome on the
  136-question sweep.

Write it once item 1's numbers exist, so the note reports a measurement rather
than an intention.

---

## Optional (improves score, not a separate product feature)

| Item | Why | How |
|------|-----|-----|
| Table-aware chunks | Line items split across HTML | Keep table rows with headers in `parsing/` |
| Reranker | Extra precision before LLM | Cross-encoder on hybrid top-20 |
| Multi-filing library | Spec allows “Add filing” repeatedly | Keep selector; still one filing per question |

---

## Suggested order for remaining work

```text
1. Re-baseline: --fast-only and full harness over all 136, then score.py --judge
2. Read the -1 column first. Tighten abstention before chasing +1s.
3. Fix compound-question scoring (2) so the harness is not under-credited
4. Within-page chunking (3) -- now a cost fix, not a correctness one
5. APPROACH.md, from the numbers step 1 produces
```

Parsing, citations, index invalidation, scoring, the product surfaces and the
harness are in place. Everything from here should be justified by a score delta,
and each accepted or rejected change recorded for the approach note.

---

## Current architecture (completed layers)

```text
Any supported document
    → parsing (Markdown pages, one file per segment)
    → BM25 index  +  vector index  +  Markdown store
    │
    message
    → route (greeting / capability / question)
    → split into one question per thing asked
    │
    ├─ TIER 1  hybrid search (expand → retrieve → weighted → boost) → LLM
    ├─ TIER 2  a second reader checks it against the whole cited page
    └─ TIER 3  every page read by ≤10-page reader agents → synthesis
    │
    → deterministic verification (direct figures, or a derivation's inputs)
    → answer + citation, or "not found in this filing"
    → API (chat, chat/stream) → React UI
    → eval runner + rubric scorer
```
