# Embeddings

**Code:** [`embeddings/`](../src/analyst_copilot/embeddings/)

One client, talking to any OpenAI-compatible `/v1/embeddings` endpoint. That
covers OpenAI, OpenRouter, a local Ollama at `{host}/v1`, and most others.

## Parts

| Thing | Job |
|---|---|
| `EmbeddingClient` (`base.py`) | The contract: `embed_texts`, `embed_query`, `model_name`, `dimensions` |
| `OpenAICompatibleEmbeddingClient` (`openai.py`) | The real one, using the official SDK |
| `get_embedding_client()` | Builds one from settings |

## How it behaves

- URL, key and model come from settings. See [configuration](02-configuration.md).
- Requests are batched, 32 texts at a time.
- Vector size is read from the first response, not configured.
- 120 second timeout, 2 retries.

## Two things worth knowing

**The chat model is not used here.** Embeddings and chat are separate models with
separate URLs and separate keys.

**Only part of each page is embedded.** Pages are cut to
`retrieval_max_chars_per_page` (2,500) first. That limit causes real problems and
they are measured in [vector retrieval](06-vector-retrieval.md).

## Demo

```bash
PYTHONPATH=src python scripts/examples/embedding_example.py
```

Parses a filing, embeds the pages around the cash flow statement, and ranks them
against a capex question.
