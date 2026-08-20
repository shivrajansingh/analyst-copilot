# Configuration

Settings load from `.env` via `analyst_copilot.config.settings.Settings` (`pydantic-settings`).

## Chat (not used yet)

| Variable | Role |
|----------|------|
| `OPENAI_URL` | Chat completions URL (may include `/v1/chat/completions`) |
| `OPENAI_API_KEY` | API key |
| `OPENAI_MODEL` | Chat model id (e.g. `hy3`) |

`chat_base_url` strips `/chat/completions` so a later LLM client can call `/chat/completions` on the base.

## Embeddings

Preferred explicit variables:

| Variable | Role |
|----------|------|
| `EMBEDDING_BASE_URL` | OpenAI-compatible base, including `/v1` |
| `EMBEDDING_API_KEY` | Key (`ollama` is fine for Ollama) |
| `EMBEDDING_MODEL` | Embedding model id |

Fallback if `EMBEDDING_*` is unset: `OLLAMA_URL` → `{host}/v1`, then `OPENAI_URL`.

Resolution is implemented in `Settings.resolved_embedding_base_url`, `resolved_embedding_api_key`, and `resolved_embedding_model`.

Ngrok hosts get header `ngrok-skip-browser-warning: true` in the embedding client.

## Retrieval knobs

| Setting | Default | Meaning |
|---------|---------|---------|
| `retrieval_max_chars_per_page` | 2500 | Truncate page text before embed |
| `hybrid_candidate_pool` | 80 | Top pages kept from each retriever |
| `hybrid_bm25_weight` | 0.45 | Lexical share of weighted fusion |
| `hybrid_vector_weight` | 0.55 | Dense share of weighted fusion |
| `hybrid_rrf_k` | 60 | RRF smoothing constant |
| `hybrid_rrf_weight` | 0.6 | Blend weight for RRF vs weighted scores |
| `hybrid_weighted_weight` | 0.4 | Blend weight for min-max fusion |
| `hybrid_statement_boost` | 1.25 | Multiplier for matching statement titles |

These are code defaults in `settings.py`; they can later be exposed as env vars if needed.
