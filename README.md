# Analyst Copilot

Backend for question-answering over SEC annual and quarterly filings.

## Project layout

```text
large-documents-llm-system/
├── AGENTS.md                 # Challenge specification
├── filings/                  # SEC HTML filings (input data)
├── practice-questions.jsonl  # Dev benchmark with answers + evidence
├── pyproject.toml
├── requirements.txt
├── scripts/
│   └── examples/             # Runnable demos (no UI)
├── src/
│   └── analyst_copilot/      # Application package
│       ├── config/           # Settings from .env
│       ├── parsing/          # HTML → page-aligned text
│       ├── embeddings/       # OpenAI-compatible /v1/embeddings client
│       ├── retrieval/        # BM25 + vector search (later)
│       └── services/         # Indexing / QA pipeline (later)
├── storage/                  # Generated indices (gitignored)
└── tests/
```

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt pytest
export PYTHONPATH=src
```

Or, with a recent pip version:

```bash
pip install -e ".[dev]"
```

Copy environment variables into `.env`:

```env
# Embeddings — OpenAI-compatible API (Ollama, OpenAI, proxies, etc.)
# Ollama: set OLLAMA_URL + OLLAMA_EMBEDDING_MODEL (auto-mapped to /v1/embeddings)
OLLAMA_URL=http://localhost:11434
OLLAMA_EMBEDDING_MODEL=bge-m3

# Or set explicitly (overrides Ollama defaults):
# EMBEDDING_BASE_URL=http://localhost:11434/v1
# EMBEDDING_API_KEY=ollama
# EMBEDDING_MODEL=bge-m3

# Chat LLM (later phase — separate from embeddings)
OPENAI_URL=https://your-provider/v1/chat/completions
OPENAI_API_KEY=...
OPENAI_MODEL=...
```

**Embedding URL resolution:** `EMBEDDING_BASE_URL` → `{OLLAMA_URL}/v1` → `{OPENAI_URL}` stripped to `/v1`.

Ollama implements the OpenAI embeddings format at `POST /v1/embeddings`; no separate Ollama embed API is required.

## Examples

Parse a filing and inspect page metadata:

```bash
PYTHONPATH=src python scripts/examples/parse_filing_example.py
```

Parse + embed + similarity search demo:

```bash
PYTHONPATH=src python scripts/examples/embedding_example.py
```

Run tests:

```bash
pytest
```

## Parsing strategy

SEC HTML is split on `page-break-after: always` markers (present in most filings). Each segment is converted to plain text. Printed footer page numbers are detected when present. Filings without page breaks fall back to fixed-size text chunks.
