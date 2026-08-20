# Analyst Copilot

Backend for question-answering over SEC annual and quarterly filings.

- **Plan (done vs remaining):** [PLAN.md](PLAN.md)
- **Implementation docs:** [docs/README.md](docs/README.md)
- **Challenge spec:** [AGENTS.md](AGENTS.md)

## What works today

Parse a filing into pages, index with BM25 + embeddings, hybrid-search the right page, then ask the chat LLM. A verifier checks that cited numbers appear on that page. If evidence is weak, the system returns **not found in this filing**.

There is no chat UI yet (see PLAN.md).

## Project layout

```text
large-documents-llm-system/
├── AGENTS.md
├── PLAN.md
├── docs/                     # Guides for completed layers
├── data/
│   ├── practice-questions.jsonl
│   └── questions-by-doc.json # [{doc_path, questions}]
├── filings/
├── scripts/examples/
├── src/analyst_copilot/
│   ├── config/
│   ├── parsing/
│   ├── embeddings/           # OpenAI-compatible /v1/embeddings
│   ├── llm/                  # OpenAI-compatible /v1/chat/completions
│   ├── retrieval/            # BM25, vector, hybrid
│   └── services/
│       ├── indexing/
│       └── qa/               # Retrieve → LLM → verify / abstain
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

Copy environment variables into `.env` (not committed):

```env
# Chat LLM (QA pipeline)
OPENAI_URL=https://your-provider/v1/chat/completions
OPENAI_API_KEY=...
OPENAI_MODEL=...

# Embeddings (OpenAI-compatible, including Ollama at host/v1)
EMBEDDING_BASE_URL=http://localhost:11434/v1
EMBEDDING_API_KEY=ollama
EMBEDDING_MODEL=bge-m3
```

**Embedding URL resolution:** `EMBEDDING_BASE_URL` → `{OLLAMA_URL}/v1` → `{OPENAI_URL}` stripped to `/v1`.

Chat and embeddings use **separate** models and URLs. `OPENAI_MODEL` is not used for embeddings.

## Examples

```bash
PYTHONPATH=src python scripts/examples/parse_filing_example.py
PYTHONPATH=src python scripts/examples/embedding_example.py
PYTHONPATH=src python scripts/examples/bm25_search_example.py
PYTHONPATH=src python scripts/examples/hybrid_search_example.py
PYTHONPATH=src python scripts/examples/hybrid_search_full_filing.py
PYTHONPATH=src python scripts/examples/qa_example.py
PYTHONPATH=src python scripts/examples/build_questions_by_doc.py
PYTHONPATH=src python scripts/eval/run_practice.py --limit 5
```

`qa_example.py` loads (or builds) indices for `3M_2018_10K`, runs hybrid search, calls the chat model, and prints the verified answer plus page — or **not found in this filing**.

Eval all 136 questions (writes `data/eval-results.json` after each item):

```bash
PYTHONPATH=src python scripts/eval/run_practice.py
```

```bash
PYTHONPATH=src pytest
```

## QA pipeline

1. Hybrid retrieve top pages for the selected filing.
2. Prompt the chat model with those excerpts; require JSON (`answer`, `page`, `evidence_snippet`, or `not_found`).
3. Verify: cited page must be in the retrieved set; numbers in the answer must appear on that page.
4. Otherwise abstain: **not found in this filing**.

Details: [docs/09-qa-pipeline.md](docs/09-qa-pipeline.md).

## Parsing strategy

SEC HTML is split on `page-break-after: always` markers (present in most filings). Each segment is converted to plain text. Printed footer page numbers are detected when present. Filings without page breaks fall back to fixed-size text chunks.
