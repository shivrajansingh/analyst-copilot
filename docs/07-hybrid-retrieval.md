# Document retrieval

**Modules:** `analyst_copilot.retrieval.{bm25,vector,hybrid}`
**Entry point:** `HybridSearcher.search` — [`hybrid/searcher.py:56`](../src/analyst_copilot/retrieval/hybrid/searcher.py#L56)

How a question becomes the five pages the language model is allowed to read.
Component references live in [BM25 retrieval](05-bm25-retrieval.md) and
[Vector retrieval](06-vector-retrieval.md); this document is the end-to-end
logic, the reasoning behind each step, and what each one measures.

---

## Why retrieval decides the score

The challenge rubric pays **+1 only for a correct answer with a correct
location**. A citation can only be correct if the page carrying the evidence
was retrieved in the first place — so **gold-page recall@5 is a hard ceiling on
the achievable score**. No prompt, model or verifier can recover a page that
never reached the context window.

That makes recall@5 the primary metric for this layer, and it is measured
directly against the practice key.

---

## The pipeline

```text
question
   │
   ├─ 1. expand        FinancialQueryExpander        analyst wording → filing wording
   │
   ├─ 2. retrieve      BM25Searcher      ──┐         top 80 candidates, lexical
   │                   VectorSearcher    ──┤         top 80 candidates, semantic
   │                                       │
   ├─ 3. fuse          weighted_fusion   ←─┘         normalise, then 0.1 / 0.9
   │                   (RRF available, currently off)
   │
   ├─ 4. boost         StatementTitleBooster         ×1.25 on matching statement titles
   │
   └─ 5. rank          rank_by_score                 top 5 → ScoredPage[]
                                                     → qa_max_evidence_chars each
```

---

## Stage 0 — what is indexed

The unit of retrieval is a **page**, produced by the parser splitting on
`page-break-{after,before}: always`. See [HTML parsing](03-html-parsing.md).

The page is the unit because the page is what gets cited. Retrieving something
smaller would mean citing something the practice key does not describe;
retrieving something larger would mean a citation an analyst cannot check.

Two indices are built per filing and stored side by side under `storage/`:

| Index | Built from | Sees | Cost |
|---|---|---|---|
| BM25 | tokenized page text | **the whole page** | local, instant |
| Vector | one embedding per page | **the first `retrieval_max_chars_per_page` characters** | one network call per batch |

**That asymmetry matters and is a live source of failure — see [Known limits](#known-limits).**

---

## Stage 1 — query expansion

[`hybrid/query_expansion.py:48`](../src/analyst_copilot/retrieval/hybrid/query_expansion.py#L48)

Analysts ask for "capex". The filing says *Purchases of property, plant and
equipment*. BM25 matches literal words, so without help the two never meet.

`FinancialQueryExpander` holds synonym groups; if the query contains any phrase
in a group, the remaining phrases in that group are appended:

| Trigger | Appended |
|---|---|
| capex, capital expenditure | purchases of property plant and equipment, pp&e, capital spending |
| cash flow statement | consolidated statement of cash flows, cash flows from investing |
| balance sheet | consolidated balance sheet, statement of financial position |
| income statement, net sales | consolidated statement of income, statement of operations |
| effective tax rate | provision for income taxes, income tax expense |

The **expanded** query goes to both retrievers. The **original** query is what
the statement booster reads in stage 4, so expansion cannot accidentally trigger
a boost the analyst did not ask for.

Measured: expansion lifts BM25 gold-page recall@5 from **0/10 to 2/10** on the
diagnostic set and leaves dense recall unchanged — it helps the retriever that
matches literal strings, which is the one it was written for.

> **Known weakness.** `expand` appends *every* synonym of *every* matched group
> into one string, which dilutes BM25 term weighting on long queries. Never
> ablated properly. Worth measuring before trusting it further.

---

## Stage 2 — the two retrievers

Both are asked for `hybrid_candidate_pool` (80) pages, not 5. Fusion needs a
deep pool: a page ranked 40th by one retriever and 2nd by the other should still
be reachable.

### 2a. BM25 — lexical

[`bm25/searcher.py`](../src/analyst_copilot/retrieval/bm25/searcher.py) ·
`rank_bm25.BM25Okapi`

Tokenizer ([`tokenization.py`](../src/analyst_copilot/retrieval/tokenization.py))
lowercases, **strips commas inside numbers** (`1,577` → `1577`) and keeps
alphanumeric runs. The comma rule is the important one: without it, a filing's
`1,577` and a question's `1577` are different tokens.

Scores are unbounded (typically 0–50 here). Zero-score pages are dropped.

**Strength:** exact line items, tickers, defined terms — `1.500% Notes due 2026`.
**Weakness:** length sensitivity. BM25 normalises by document length, and these
"documents" range from 200 to 47,000 characters. A long page dilutes badly.

### 2b. Vector — semantic

[`vector/searcher.py`](../src/analyst_copilot/retrieval/vector/searcher.py)

The expanded query is embedded with the same model used at index time, then
cosine similarity is computed against every page vector. Scores are 0–1.

**Strength:** paraphrase. *"Is this business capital-intensive?"* matches a
capital-spending table that shares no words with the question.
**Weakness:** it only ever saw the first 2,500 characters of each page.

---

## Stage 3 — fusion

[`hybrid/fusion.py`](../src/analyst_copilot/retrieval/hybrid/fusion.py)

Two rankings must become one, and **the scores are not comparable**: BM25 `48.91`
against cosine `0.585` says nothing. Whichever scale is larger would win outright.

### Weighted fusion — what runs today

[`fusion.py:24`](../src/analyst_copilot/retrieval/hybrid/fusion.py#L24)

Min-max normalise each retriever's scores into 0–1, then take a weighted sum:

```
fused = hybrid_bm25_weight × bm25_norm  +  hybrid_vector_weight × vector_norm
      = 0.1 × bm25_norm                 +  0.9 × vector_norm
```

A page missing from one retriever contributes 0 from it rather than being
dropped, so a page found by only one retriever can still surface.

Worked example, real scores from `3M_2018_10K`, "FY2018 capital expenditure":

| page | bm25 | vector | fused | rank |
|---:|---:|---:|---:|---:|
| 38 | 42.60 | 0.734 | 0.963 | #1 |
| 46 | 33.87 | 0.730 | 0.888 | #2 |
| 57 | 31.78 | 0.701 | 0.701 | #3 |
| 59 | 34.12 | 0.686 | 0.624 | #4 |
| 48 | **48.91** | 0.585 | **0.100** | **#5** |

Page 48 has the strongest BM25 score of the five and finishes last. At 0.1/0.9
the lexical signal barely moves the outcome — which is the policy the
measurements below argued for.

### Reciprocal Rank Fusion — present, disabled

[`fusion.py:57`](../src/analyst_copilot/retrieval/hybrid/fusion.py#L57)

RRF ignores scores entirely and uses only rank position:
`score = Σ 1 / (k + rank)`. Immune to scale mismatch, but it discards
*confidence* — a retriever certain about its #1 gets no more say than one that
listed the page 40th.

`combine_fusion_scores` ([`fusion.py:81`](../src/analyst_copilot/retrieval/hybrid/fusion.py#L81))
blends RRF with weighted fusion. **`hybrid_rrf_weight` is now `0.0`**, so this
term is inert and `fused_score` is pure weighted fusion.

**Why it was turned off.** With `rrf_k = 60` over a pool of 80, every rank maps
into `1/61 … 1/140` — a 2.3× spread across the entire ranking. RRF degenerated
into a head-count of retrievers, and at weight 0.6 that head-count outvoted both
retrievers' actual confidence. Critically, RRF weights the two retrievers
**equally**, so the configured 0.45/0.55 split was effectively dragged to ~48/52:
a retriever with 16% recall was getting half the vote against one with 58%.

Tuning `rrf_k` to 10 or 20 did not fix it. Removing the term did.

---

## Stage 4 — statement title boost

[`hybrid/boosting.py:34`](../src/analyst_copilot/retrieval/hybrid/boosting.py#L34)

If the **original** question names a financial statement, pages whose text
contains that statement's canonical title are multiplied by
`hybrid_statement_boost` (1.25).

| Question mentions | Boosted page titles |
|---|---|
| cash flow, capex, capital expenditure | *Consolidated Statement of Cash Flows* |
| balance sheet, financial position | *Consolidated Balance Sheet* |
| income statement, net income, net sales | *Consolidated Statement of Income / Operations* |

This is why a `fused_score` can exceed 1.0 — the boost is applied after
normalisation.

> **Honest note.** On the 136-question sweep the boost changed **no** outcome:
> `vector_only` and `vector+boost` scored identically at every k tested. It is
> retained because it is cheap and targeted, but it is currently unproven and a
> candidate for removal.

---

## Stage 5 — top-k and the evidence window

`rank_by_score` takes `qa_top_k` (5) pages. Each becomes a `ScoredPage` carrying
`page`, `score` (fused), `rank`, `bm25_score` and `vector_score` — all of which
the API surfaces so the UI can show *why* a page was cited.

The QA layer then truncates each page to `qa_max_evidence_chars` (2,200) when
building the prompt. **This is a second, independent truncation** — a page can
be retrieved and still have its evidence cut off before the model sees it. See
[QA pipeline](09-qa-pipeline.md).

---

## Measured performance

Gold-page recall@5 and @10 over **all 136 practice questions**, computed with no
LLM calls by replaying stored BM25 and vector scores through each fusion policy:

| Configuration | recall@5 | recall@10 |
|---|---:|---:|
| BM25 alone | 16.2% | 26.5% |
| **Previous shipped** (RRF 0.6 + weighted, bm25 0.45) | **36.0%** | 50.0% |
| weighted only, bm25 0.45 | 44.9% | 61.0% |
| vector alone | 58.1% | 66.2% |
| **Current** (RRF off, bm25 0.1 / vector 0.9) | **58.1%** | 66.2% |
| weighted only, bm25 0.2 | 58.1% | **66.9%** |
| perfect per-question router (oracle) | 61.8% | 73.5% |

Two conclusions the numbers force:

1. **The old fusion destroyed a third of the retrieval it already had** — 36%
   against 58% for the dense component it contained.
2. **BM25's marginal contribution is roughly one question in 136.** It uniquely
   finds 5 questions that vector misses at k=5, but fusion converts only 1. It is
   kept at weight 0.1 rather than removed, because this measurement is taken over
   whole pages — the regime that most penalises BM25 — and that regime is what
   within-page chunking will change.

End-to-end, `config/settings.py` records the rubric score moving from **+1 to +7**
across the 136 questions when RRF was disabled.

---

## Known limits

**1. The embedding window discards evidence.** `retrieval_max_chars_per_page` is
2,500. Measured across 20 filings / 2,252 pages, **73% of pages exceed it**. Of
the gold evidence blocks that could be located on their cited page, ~13% begin
past the cap.

The extreme case: `3M_2023Q2_10Q` page 1 is **47,221 characters**, of which 2,500
were embedded, and the gold evidence for the registered-debt-securities question
sits at character **45,234**. Semantic search could never find it, and BM25 was
diluted across 47k characters of cover page. The API exposes this via
`GET /filings/{doc}/pages/{n}` (`embedded_chars`, `truncated`) and the UI draws
the boundary in the page text.

The fix is within-page chunking — chunk after parsing, retrieve chunks, cite the
parent `page_index` — not a larger cap, since real pages exceed any safe cap.

**2. Page granularity penalises BM25.** Lexical scoring over 47,000-character
"documents" is not a fair test of lexical retrieval. Re-measure BM25's weight
after chunking lands, not before.

**3. Retrieval is per-filing.** Both indices are scoped to one document, and
`search` refuses mismatched indices. Cross-filing search is out of scope: a
citation is only checkable against the document it names.

---

## Configuration

All in [`config/settings.py`](../src/analyst_copilot/config/settings.py).

| Setting | Default | Effect |
|---|---|---|
| `retrieval_max_chars_per_page` | 2500 | How much of a page is embedded. Changing it invalidates every vector index. |
| `hybrid_candidate_pool` | 80 | Pages pulled from each retriever before fusion |
| `hybrid_bm25_weight` | 0.1 | Lexical share of the weighted sum |
| `hybrid_vector_weight` | 0.9 | Semantic share |
| `hybrid_rrf_weight` | 0.0 | RRF share of the final blend. **0 = disabled** |
| `hybrid_weighted_weight` | 1.0 | Weighted-fusion share of the final blend |
| `hybrid_rrf_k` | 60 | RRF rank damping. Inert while `hybrid_rrf_weight` is 0 |
| `hybrid_statement_boost` | 1.25 | Multiplier for matching statement titles |
| `qa_top_k` | 5 | Pages passed to the model |

Every one is overridable by environment variable, so a sweep needs no code change:

```bash
HYBRID_BM25_WEIGHT=0.3 HYBRID_VECTOR_WEIGHT=0.7 \
  PYTHONPATH=src python scripts/eval/run_practice.py --limit 10
```

---

## Re-measuring after a change

Recall@5 needs no LLM and is the fast gate:

```bash
PYTHONPATH=src python scripts/eval/run_practice.py --output data/eval-new.json
PYTHONPATH=src python scripts/eval/score.py --results data/eval-new.json --judge
```

**Recall is a gate, not a verdict.** A change that raised recall@5 from 4/10 to
7/10 on a small sample *lowered* the rubric score, because better retrieval also
converts abstentions into confident wrong answers, which cost −1 apiece. Judge
retrieval changes on recall first, then confirm on the full 136-question rubric
before keeping them.

## Demos and tests

```bash
PYTHONPATH=src python scripts/examples/hybrid_search_full_filing.py
PYTHONPATH=src pytest tests/test_hybrid.py
```

`hybrid_search_full_filing.py` reuses saved indices, so fusion changes can be
tested without re-embedding.
