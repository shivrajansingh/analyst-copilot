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

Docs for completed work live in [`docs/`](docs/README.md).

---

## Remaining (required for the product)

### 1. Chat UI + “Add filing”

**What:** Product, not a CLI. Upload a new HTML filing, show processing status (≤ 10 minutes), then chat.

**How to complete:**
1. Backend API (FastAPI): `POST /filings` (upload + index), `GET /filings/{id}/status`, `POST /chat`.
2. Store job status: queued → parsing → embedding → ready / failed.
3. UI (Streamlit or simple HTML): filing selector, upload control, chat box, evidence (doc name + page + snippet).
4. Scope chat to **one selected filing** per question.

### 2. Score eval results against the gold key

**What:** `run_practice.py` produces model answers. You still need +1 / 0 / −1 vs `data/practice-questions.jsonl`.

**How to complete:**
1. Compare `answer.text` and `answer.page` to gold `answer` and `evidence_page_num`.
2. Tune retrieval/prompt/verifier from the score; record what you kept vs dropped for the approach note.

### 3. README + one-page approach note

**What:** Submit runnable instructions and a one-page note (tried, measured, kept, thrown away).

**How to complete:**
1. Expand `README.md` with UI start commands and `.env` for **chat**.
2. Write `APPROACH.md` (one page) after eval numbers exist.

---

## Optional (improves score, not a separate product feature)

| Item | Why | How |
|------|-----|-----|
| Table-aware chunks | Line items split across HTML | Keep table rows with headers in `parsing/` |
| Within-page chunking | 2500-char truncate can drop PP&E rows | Chunk after parse; cite same printed page |
| Reranker | Extra precision before LLM | Cross-encoder on hybrid top-20 |
| Multi-filing library | Spec allows “Add filing” repeatedly | Keep selector; still one filing per question |

---

## Suggested order for remaining work

```text
1. Run eval (all 136 or --limit N) and inspect data/eval-results.json
2. Score against gold; tune abstention vs accuracy
3. API + Add filing status + chat UI
4. README + APPROACH.md
```

QA + verifier + abstention are implemented on the CLI path. Next is measured eval, then UI.

---

## Current architecture (completed layers)

```text
Filing HTML
    → parsing (pages + printed_page)
    → BM25 index  +  vector index
    → hybrid search (expand → retrieve → RRF/weighted → statement boost)
    → LLM answer + verify / abstain
    → [remaining] eval harness + UI
```
