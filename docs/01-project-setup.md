# Project setup

## Package layout

The backend is an installable Python package under `src/analyst_copilot/`.

```text
src/analyst_copilot/
├── config/          # Settings from environment
├── parsing/         # Filing HTML → Page objects
├── embeddings/      # Embedding client
├── retrieval/       # BM25, vector, hybrid
└── services/        # Indexing workflows
```

Runnable demos live in `scripts/examples/`. Tests live in `tests/`. Generated indices go to `storage/` (gitignored).

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt pytest
export PYTHONPATH=src
```

Python 3.9+ is required (the current venv uses 3.9).

## Run tests

```bash
PYTHONPATH=src pytest
```

## Demos

| Script | Purpose |
|--------|---------|
| `scripts/examples/parse_filing_example.py` | Parse pages |
| `scripts/examples/embedding_example.py` | Embed a page subset |
| `scripts/examples/bm25_search_example.py` | Lexical search |
| `scripts/examples/hybrid_search_example.py` | Hybrid on a filing |
| `scripts/examples/hybrid_search_full_filing.py` | Full first filing + practice question |

`.env` is required for embedding/hybrid scripts. It is not committed.
