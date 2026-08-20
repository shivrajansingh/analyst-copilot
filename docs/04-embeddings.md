# Embeddings

**Module:** `analyst_copilot.embeddings`

One client implements the OpenAI embeddings API. Ollama is supported as `{host}/v1` + `POST /v1/embeddings`. There is no separate `/api/embed` client.

## Types

- `EmbeddingClient` (`base.py`): `embed_texts`, `embed_query`, `model_name`, `dimensions`
- `OpenAICompatibleEmbeddingClient` (`openai.py`): official `openai` SDK, batched requests
- `get_embedding_client()`: factory

## Behavior

- Base URL and model come from `Settings.resolved_*`.
- Batch size default 32.
- Vectors are returned as `list[list[float]]`.
- Dimensions are inferred from the first response.

## Demo

```bash
PYTHONPATH=src python scripts/examples/embedding_example.py
```

This parses `3M_2018_10K.htm`, embeds a subset of pages (cash-flow region), and ranks by cosine similarity against a capex query.

Chat (`OPENAI_MODEL=hy3`) is **not** used here. Embedding model and chat model are separate.
