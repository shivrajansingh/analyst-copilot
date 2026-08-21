# Codebase Review — Analyst Copilot

**Date:** 2026-08-21
**Branch reviewed:** `fix/page-citations-and-rubric-scorer` (3 commits ahead of `main`, working tree clean)
**Scope:** full source tree (`src/analyst_copilot/`), scripts, tests, docs, eval artifacts, repo hygiene.

---

## 1. System overview

The project is a backend question-answering pipeline over SEC filings:

```text
Filing HTML
  → parsing/html_filing_parser.py     page-break split → Page[page_index, text, printed_page]
  → retrieval/bm25 + retrieval/vector two indices per filing, persisted under storage/
  → retrieval/hybrid                  query expansion → RRF + weighted fusion → statement boost
  → services/qa                       prompt LLM with top-5 excerpts → parse JSON → verify → abstain
  → scripts/eval                      run_practice.py (answers) + score.py (+1/0/−1 rubric)
```

Delivery status against the challenge spec (AGENTS.md):

| Required deliverable | Status |
|---|---|
| Parse filings into pages | Done |
| Retrieval (BM25 + vector + hybrid) | Done, hybrid measured worse than its parts |
| QA with evidence citation | Done |
| Abstention ("not found in this filing") | Done, conservative |
| Eval runner + rubric scorer | Done |
| **"Add filing" control with status** | **Missing** |
| **Chat UI** | **Missing** |
| README / approach note | Partial (README good; APPROACH.md absent) |

24 tests pass (`PYTHONPATH=src pytest`, ~26s).

---

## 2. Strengths

1. **Measurement-driven development.** PLAN.md records a before/after baseline (+2 over 10 questions), attributes every gained point to citation fixes rather than the model, and states honest caveats (the `--judge` path uses the same model that produced the answers). Root causes are diagnosed with data: RRF rank compression, gold evidence sitting past the truncation caps.

2. **Abstention-first verification.** `AnswerVerifier.verify` (src/analyst_copilot/services/qa/verifier.py:26) rejects answers whose cited page is not in the retrieved set and whose numbers do not appear literally on that page. Fuzzy page fallbacks were deliberately removed — verifier.py:67-71 documents that they produced confident answers on wrong pages, the one outcome the rubric penalises at −1. Current measured tally: zero −1.

3. **Index invalidation done right.** `PARSER_VERSION = "2"` (parsing/html_filing_parser.py:27) is stamped into index metadata; stale indices are treated as absent and rebuilt. A parsing fix can never be masked by old embeddings on disk. The bulk indexer extends this to embedding-model and truncation-config changes.

4. **Operational hygiene.**
   - `scripts/index_all.py`: skip-existing by default, `--overwrite`, `--dry-run` labelling each filing missing/stale/current, retries, per-filing timing vs the 10-minute budget.
   - `scripts/eval/run_practice.py` writes results after every question — interruptible and resumable.
   - `.env` gitignored and untracked; generated indices and eval outputs excluded from git.

5. **Careful scorer.** `scripts/eval/score.py` handles unit rescaling ($8.70B ≡ 8,738M) with relative tolerance, treats short numeric golds as arithmetically checkable and prose as `unjudged` unless `--judge` is passed, and emits per-question detail for debugging.

6. **Clean layering.** Config via pydantic-settings with sensible URL resolution; dataclasses for all models; dependency injection in constructors with settings fallbacks; no circular imports; consistent docstrings explaining *why*, not *what*.

---

## 3. Findings (severity-ordered)

### F1 — Verifier structurally blocks derived answers (High)

`verifier.py:42-44` requires every number in the answer to appear verbatim on the single cited page:

```python
numbers = extract_normalized_numbers(extraction.answer)
if numbers and not numbers.intersection(extract_normalized_numbers(page_text)):
    return VerificationResult(ok=False, reason="number_not_on_page")
```

43 of 136 practice questions are numerical reasoning; many gold answers are computed figures (`24.26%`, growth rates, margins) that appear nowhere in the filing. As written these can never verify — the pipeline converts would-be correct answers into abstentions (0 instead of +1). This is the largest score ceiling in the system.

**Recommendation:** verify the *inputs* (both operand numbers present across the cited page(s)) rather than the output figure, and/or allow multi-page citations matching the gold convention (34 gold records cite 2–3 pages). Decide with eval data, since loosening this gate is also the main −1 risk.

### F2 — Hybrid fusion worse than its own retrievers (High, measured)

Gold-page recall@5 on the diagnostic set: vector 5/10, BM25 4/10, **hybrid 3/10**. Concrete regressions: net-PP&E vector #1 → hybrid #20; capital-intensive #2 → #32; debt-securities BM25 #1 → #10.

Cause confirmed in code: `reciprocal_rank_fusion` (retrieval/hybrid/fusion.py:57-78) with `hybrid_rrf_k = 60` over a candidate pool of 80 compresses all ranks into 1/61 … 1/140 — a 2.3× spread. RRF degenerates into a head-count of retrievers, and `hybrid_rrf_weight = 0.6` lets that head-count outvote both retrievers' actual confidence (fusion.py:81-97 blends it back in after min-max normalisation).

**Recommendation:** build a repeatable recall@5 harness first (see F7), then A/B `rrf_k ∈ {10, 15, 20}` and weighted-fusion-only. Keep whichever wins on gold-page recall@5; record the loser for the approach note.

### F3 — Evidence window discards the answer text (High, measured)

Two truncation caps cut off gold evidence:
- embedding input: `retrieval_max_chars_per_page = 2500` (config/settings.py:58, applied in retrieval/vector/text.py:12);
- LLM prompt: `qa_max_evidence_chars = 2200` (settings.py:70, applied in services/qa/prompts.py:35).

On three of ten diagnostic questions the gold evidence began at character 2587, 2587 and 2037 — past the cap. Clearest failure: BM25 ranked the debt-securities gold page **#1** and the model still abstained because the evidence sat at char 2587 of a 2200-char window.

**Recommendation:** chunk within page after parsing (e.g. ~1200-char chunks with overlap), retrieve chunks, cite the parent `page_index`. Raising the caps is a stop-gap; real pages exceed any safe cap.

### F4 — Dead abstention gate (Medium)

`qa_min_retrieval_score = 0.25` (config/settings.py:69, enforced at services/qa/service.py:63) can never fire. `combine_fusion_scores` min-max normalises both inputs, so the argmax page always receives ≥ `rrf_weight × 1.0 = 0.6`. The gate is dead code and misleading to anyone tuning it.

**Recommendation:** delete it, or gate on a pre-normalisation signal (e.g. raw vector cosine of the top hit).

### F5 — Required product surface entirely missing (High for delivery)

No API, no UI. The spec grades a product: "Add filing" upload with visible processing status (≤ 10 min), chat box, evidence (doc + page) on every answer, plain decline. None exists; everything is CLI scripts.

**Recommendation:** FastAPI with `POST /filings` (background indexing job: queued → parsing → embedding → ready/failed), `GET /filings/{id}/status`, `POST /chat`; thin Streamlit or HTML front end scoped to one filing per question. The existing `HybridFilingIndexer` / `QuestionAnsweringService` already expose everything needed — this is glue work, but it is graded glue.

### F6 — Numeric scoring fragility (Low)

`numeric_match` takes gold's **first** number as the headline figure (scripts/eval/score.py:77). Multi-figure golds ("$1.2B, up 5% from $1.1B") can be mis-checked against the wrong target. Also, scale search accepts any of 1…1e9 multipliers, so a wrong-unit answer within tolerance passes — acceptable for now, worth a comment.

### F7 — Retrieval quality has no repeatable harness (Medium)

Gold-page recall@5 numbers live only in PLAN.md prose, computed ad hoc. Before touching fusion (F2) or chunking (F3), this measurement should be a script (it needs only `practice-questions.jsonl` + the indices, no LLM calls) so every change gets an instant before/after. It would also make a natural regression test.

### F8 — Runner errors masquerade as abstentions (Low)

`run_practice.py:80-93` catches exceptions and stores them as `found=False` answers with reason `runner_error:*`. The scorer counts these as abstained (0) — indistinguishable from genuine abstentions in the headline tally, though the reasons breakdown does surface them. An infra failure should be visible as a failure, not silently folded into the safest rubric bucket.

### F9 — Unmerged branch (Housekeeping)

Three commits of finished, tested work (parser fix, scorer, bulk indexer) sit on `fix/page-citations-and-rubric-scorer`, diverging further from `main` as work continues. Merge to `main` to keep the submission history clean.

---

## 4. Module notes

| Module | Assessment |
|---|---|
| `parsing/` | Solid. `<hr>/<p>/<div>` break matching covers 78/79 filings; fallback chunking (3500 chars) destroys page alignment for the remaining 5 (mostly short 8-Ks) — acceptable, but citations from those filings are meaningless. `_detect_printed_page_number` matches *any* trailing number (a year, a table cell), not just footers — harmless while `printed_page` is reference-only. `citation_page` = 0-based index matches gold 74% exact / 90% ±1; decision documented in parsing/models.py:18-33. |
| `retrieval/bm25/` | Clean tokenise/build/search/persist split. No issues found. |
| `retrieval/vector/` | Truncation issue tracked as F3; otherwise clean. |
| `retrieval/hybrid/` | Fusion issues tracked as F2/F4. `FinancialQueryExpander.expand` concatenates *all* synonyms of every matched group into one query string (query_expansion.py:48-56) — plausibly dilutes BM25 scoring; never ablated. `StatementTitleBooster` multiplies post-normalisation scores by 1.25 — fine, but interacts with the dead gate in F4. |
| `services/indexing/` | Good: version-stamped metadata, load-or-build logic, timing report. |
| `services/qa/` | Prompt requires strict JSON with `not_found` semantics; parser handles fences/stray text. Verifier strengths and flaws covered above (F1). `service.py` is small and readable; error path converts LLM client errors to abstention (`llm_error:*`) — same visibility caveat as F8. |
| `llm/`, `embeddings/` | Thin OpenAI-compatible clients; separate chat vs embedding config is handled correctly (`OPENAI_MODEL` never leaks into embeddings). |
| `scripts/eval/score.py` | Thoughtful; see F6. Self-judge bias acknowledged in PLAN.md — spot-checks recommended on any full run. |

## 5. Tests

379 lines across 5 files (parsing, bm25, vector/hybrid, qa, data). Unit coverage of fusion maths, verifier rejection paths, and parser page-splitting is real and fast. Gaps:

- no end-to-end retrieval-quality regression (F7's harness);
- no test that a stale `PARSER_VERSION` index is actually treated as absent (invalidation logic is load-bearing and untested);
- verifier tests cover rejection but not the accept path's snippet-tolerance heuristics (`_snippet_supported` word-overlap fallback).

## 6. Repo hygiene

Good: `.env` untracked, generated storage/eval outputs ignored, docs numbered per layer, PLAN.md maintained as the done/remaining source of truth. Minor: `data/questions-by-doc.json` (derived from the practice key by script) is committed alongside its generator — fine either way, just keep them in sync.

---

## 7. Priorities

1. **Merge the branch** — finished work shouldn't drift from `main`.
2. **Recall@5 harness script** (F7) — cheap, unlocks measured decisions everywhere else.
3. **Fusion fix** (F2) — likely the cheapest points: several currently-abstaining questions already have the gold page at vector/BM25 rank ≤ 2.
4. **Within-page chunking** (F3) — fixes the abstain-despite-rank-1 class.
5. **Verifier policy for derived answers** (F1) — biggest ceiling; decide with eval data given the −1 risk.
6. **API + UI** (F5) — required deliverable, zero progress; start early because it's independent of retrieval quality.
7. Delete or fix the dead gate (F4); fold F6/F8 fixes in opportunistically.

**Bottom line:** the foundation is well-engineered and unusually honest about its own weaknesses — the risks are (a) the verifier ceiling and (b) spending the remaining time on retrieval tuning while the graded product surface doesn't exist.
