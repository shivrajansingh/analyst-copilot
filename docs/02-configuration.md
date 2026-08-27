# Configuration

Settings come from a `.env` file. See `.env.example` for a template with every
option and a comment explaining it.

Two separate configs, on purpose:

- `analyst_copilot.config.settings` — the **pipeline**: models, retrieval, agents
- `analyst_copilot.api.config` — the **process**: port, upload limits, workers.
  Everything here is prefixed `API_`, so the two can never clash.

---

## You must set these

### The chat model

| Variable | What it is |
|---|---|
| `OPENAI_URL` | Chat completions URL. May end in `/v1/chat/completions` |
| `OPENAI_API_KEY` | Your key |
| `OPENAI_MODEL` | Model id |

Any OpenAI-compatible endpoint works. The model must support **tool calling** —
the reader agents and the planner depend on it.

### The embedding model

| Variable | What it is |
|---|---|
| `EMBEDDING_BASE_URL` | OpenAI-compatible base URL, including `/v1` |
| `EMBEDDING_API_KEY` | Your key. `ollama` is fine for a local Ollama |
| `EMBEDDING_MODEL` | Model id |

**Chat and embeddings are separate models.** `OPENAI_MODEL` is never used for
embeddings.

If you leave `EMBEDDING_*` unset, the URL is worked out in this order:

```
EMBEDDING_BASE_URL  →  {OLLAMA_URL}/v1  →  OPENAI_URL stripped back to /v1
```

⚠️ **Changing the embedding model invalidates every index.** The same page text
maps to a different vector space, so everything has to be rebuilt before it can
be searched.

---

## Retrieval

These have measured defaults. Read [document
retrieval](07-hybrid-retrieval.md) before changing them.

| Setting | Default | What it does |
|---|---|---|
| `retrieval_max_chars_per_page` | 2500 | How much of a page gets embedded |
| `hybrid_candidate_pool` | 80 | Pages taken from each retriever before blending |
| `hybrid_bm25_weight` | **0.1** | How much the word search counts |
| `hybrid_vector_weight` | **0.9** | How much the meaning search counts |
| `hybrid_rrf_weight` | **0.0** | Rank-based blending. **0 means off** |
| `hybrid_weighted_weight` | 1.0 | Score-based blending |
| `hybrid_rrf_k` | 60 | Unused while RRF is off |
| `hybrid_statement_boost` | 1.25 | Bonus for pages titled like the statement asked about |

The three bold values are the result of a measurement, not a preference.
Rank-based blending was scoring **36%** where its own embedding half scored
**58%**, and switching it off moved the end-to-end score from **+1 to +7**.

## Answering

| Setting | Default | What it does |
|---|---|---|
| `qa_top_k` | 5 | Pages shown to the model |
| `qa_max_evidence_chars` | 2200 | How much of each page it sees |
| `qa_temperature` | 0.0 | |
| `evidence_page_tolerance` | 2 | How far a citation may move to land on the page holding the proof |

## The planner

| Setting | Default | What it does |
|---|---|---|
| `planner_enabled` | true | Off means every message is treated as a document question |
| `planner_scope_documents` | true | Off means every file is read on every deep search |
| `planner_scope_requires_year` | true | Only narrow when the question names a year |
| `planner_min_confidence` | 0.8 | Below this, search everything |
| `planner_widen_on_empty` | true | **Off removes the safety net** |

## The agents

| Setting | Default | What it does |
|---|---|---|
| `agent_enabled` | true | The harness answers `/chat` |
| `agent_validate_answers` | true | Tier 2, the checker |
| `agent_deep_search` | true | Tier 3. Off means refuse instead of reading everything |
| `agent_pages_per_shard` | 10 | Pages per reader agent |
| `agent_max_concurrency` | 8 | Readers at a time |
| `agent_max_shards` | 0 | Cap on readers per question. 0 = no cap |
| `agent_decompose` | true | Split questions that ask several things |
| `agent_max_parts` | 4 | Most parts one question can become |
| `agent_history_turns` | 6 | Chat turns shown to the models |

## Chat history

| Variable | What it is |
|---|---|
| `DATABASE_URL` | Postgres. Leave it unset and questions still work, they just are not saved |

---

Every setting above can be set as an environment variable in upper case, so you
can try one without touching code:

```bash
HYBRID_BM25_WEIGHT=0.3 PLANNER_SCOPE_DOCUMENTS=false \
  PYTHONPATH=src python scripts/eval/run_practice.py --limit 10
```
