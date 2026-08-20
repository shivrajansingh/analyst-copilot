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
| Demos / tests | Done | Parse, embed, BM25, hybrid; pytest coverage for core paths |
| Full-filing smoke test | Done | `3M_2018_10K` capex question ranks printed page **60** first |

Docs for completed work live in [`docs/`](docs/README.md).

---

## Remaining (required for the product)

### 1. Question-answering pipeline

**What:** Given a filing + question, retrieve evidence, call the chat LLM (`OPENAI_URL` / `hy3`), return answer + document + page, or abstain.

**How to complete:**
1. Add `src/analyst_copilot/llm/` — OpenAI-compatible chat client (same pattern as embeddings).
2. Add `src/analyst_copilot/services/qa/` — `QuestionAnsweringService`:
   - load or build hybrid indices for the selected filing
   - `HybridSearcher.search(..., top_k=5)`
   - prompt the LLM with question + retrieved page snippets + instruction to cite `printed_page`
   - require JSON: `{answer, page, evidence_snippet, confidence}` or `{not_found: true}`
3. Add a **verifier** (`services/qa/verifier.py`):
   - numbers in the answer must appear in the cited page text
   - if verification fails → **“not found in this filing”**
4. Demo: `scripts/examples/qa_example.py` on the 3M capex question.

### 2. Abstention / “not found in this filing”

**What:** Spec requires an explicit decline when evidence is weak. Wrong confident answers score **−1**.

**How to complete:**
1. Thresholds: low fused score, LLM `not_found`, or verifier fail.
2. Never invent a number that is not on the cited page.
3. Add a negative test: question with no support in the filing → abstain.

### 3. Chat UI + “Add filing”

**What:** Product, not a CLI. Upload a new HTML filing, show processing status (≤ 10 minutes), then chat.

**How to complete:**
1. Backend API (FastAPI): `POST /filings` (upload + index), `GET /filings/{id}/status`, `POST /chat`.
2. Store job status: queued → parsing → embedding → ready / failed.
3. UI (Streamlit or simple HTML): filing selector, upload control, chat box, evidence (doc name + page + snippet).
4. Scope chat to **one selected filing** per question.

### 4. Evaluation on `practice-questions.jsonl`

**What:** 136 labeled questions. Need measured answer + page accuracy before the live session.

**How to complete:**
1. `scripts/eval/run_practice.py` — loop questions, run QA, compare answer + page to gold.
2. Score: +1 / 0 / −1 per the spec table.
3. Tune retrieval/prompt/verifier from the score; record what you kept vs dropped for the approach note.

### 5. README + one-page approach note

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
1. Chat LLM client
2. QA service + verifier + abstention
3. Eval loop on practice-questions.jsonl
4. Tune until abstention vs accuracy is sane
5. API + Add filing status + chat UI
6. README + APPROACH.md
```

Do not start the UI until QA + abstention work on the CLI/eval path. A pretty chat that guesses will score below zero.

---

## Current architecture (completed layers)

```text
Filing HTML
    → parsing (pages + printed_page)
    → BM25 index  +  vector index
    → hybrid search (expand → retrieve → RRF/weighted → statement boost)
    → [remaining] LLM answer + verify + UI
```
