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
| Bulk indexing | Done | `scripts/index_all.py` — skip-existing or `--overwrite`, retries, timing report |

Docs for completed work live in [`docs/`](docs/README.md).

---

## Measured baseline

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

### 1. Chat UI + “Add filing”

**What:** Product, not a CLI. Upload a new HTML filing, show processing status (≤ 10 minutes), then chat.

**How to complete:**
1. Backend API (FastAPI): `POST /filings` (upload + index), `GET /filings/{id}/status`, `POST /chat`.
2. Store job status: queued → parsing → embedding → ready / failed.
3. UI (Streamlit or simple HTML): filing selector, upload control, chat box, evidence (doc name + page + snippet).
4. Scope chat to **one selected filing** per question.

### 2. Retrieval and evidence-window fixes (measured, not yet fixed)

Diagnosed on 10 questions across 4 filings by checking whether the gold page is
in the retrieved set at all. Both items are measured, neither is fixed.

**2a. Hybrid fusion is worse than its own parts.** Gold-page recall@5:
vector 5/10, BM25 4/10, **hybrid 3/10**. Regressions: net-PP&E vector #1 →
hybrid #20; capital-intensive vector #2 → hybrid #32; debt-securities BM25 #1 →
hybrid #10.

Cause: RRF with `hybrid_rrf_k = 60` over a candidate pool of 80 compresses the
whole ranking into 1/61 … 1/140 — a 2.3× spread. RRF then behaves like a
head-count of retrievers rather than a ranking, so consensus-at-rank-15 outranks
confident-at-rank-1. `hybrid_rrf_weight = 0.6` lets that head-count outvote both
retrievers' actual confidence.

Try: `hybrid_rrf_k` 10–20, or drop RRF and keep weighted fusion alone. Measure
each against gold-page recall@5 before keeping it.

**2b. Truncation discards the evidence.** `retrieval_max_chars_per_page = 2500`
(embedding) and `qa_max_evidence_chars = 2200` (prompt). Gold evidence began at
character 2587, 2587 and 2037 on three of the ten questions — past the cap. The
clearest case: BM25 ranked the debt-securities gold page **#1** and the model
still abstained, because the evidence sat at character 2587 of a 2200-character
window.

Fix properly with within-page chunking (chunk after parse, cite the parent page)
rather than by raising the caps — real pages still exceed them.

**2c. `qa_min_retrieval_score = 0.25` is dead code.** `combine_fusion_scores`
min-max normalises, so the top hit always scores ≥ 0.4. The gate can never fire.
Either compare against a pre-normalisation score or delete it.

### 3. The verifier blocks derived answers by construction

43 questions are "Numerical reasoning" and 34 gold records cite 2–3 evidence
pages. The verifier requires every number in the answer to appear literally on
the single cited page, so a computed figure (`24.26`, `1.9%`) can never verify —
it appears nowhere in the filing.

This is the central tension: the verifier is the only thing standing between the
system and −1, but as written it converts most computed answers into 0. Options
to evaluate against the score: verify the *inputs* on cited pages instead of the
output figure; allow multi-page citations; or keep abstaining on derived metrics
and accept the ceiling.

### 4. README + one-page approach note

**What:** Submit runnable instructions and a one-page note (tried, measured, kept, thrown away).

**How to complete:**
1. Expand `README.md` with UI start commands and `.env` for **chat**.
2. Write `APPROACH.md` (one page) after eval numbers exist.

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
1. Full eval: run_practice.py (all 136), then score.py --judge   <- baseline number
2. Fix fusion (2a) and the evidence window (2b); re-score after each
3. Revisit the verifier for derived answers (3)
4. API + Add filing status + chat UI
5. README + APPROACH.md
```

Parsing, citations, index invalidation and scoring are in place. Everything from
step 2 on should be justified by a score delta, and each accepted or rejected
change recorded for the approach note.

---

## Current architecture (completed layers)

```text
Filing HTML
    → parsing (pages + printed_page)
    → BM25 index  +  vector index
    → hybrid search (expand → retrieve → RRF/weighted → statement boost)
    → LLM answer + verify / abstain
    → eval runner + rubric scorer
    → [remaining] UI + "Add filing"
```
