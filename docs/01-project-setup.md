# Project setup

## What is where

```text
src/analyst_copilot/
├── config/          settings from environment variables
├── parsing/         any document format → Markdown pages
├── embeddings/      the embedding client
├── llm/             the chat client
├── retrieval/       BM25, embeddings, and blending the two
├── agent/           the planner and the three answering tiers
├── collections/     filing sets: many documents searched together
├── services/
│   ├── indexing/    parse, build indexes, save
│   └── qa/          tier 1: retrieve, ask, verify
└── api/             the HTTP service
```

Other places:

| Path | What it holds |
|---|---|
| `ui/` | The React app |
| `tests/` | 281 tests, all offline |
| `scripts/examples/` | Runnable demos |
| `scripts/eval/` | Answer the practice questions and grade them |
| `filings/` | The documents themselves. Not in git |
| `storage/` | Markdown and indexes we generated. Not in git |
| `data/practice-questions.jsonl` | The answer key. In git, because grading needs it |

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt pytest
export PYTHONPATH=src
```

Python 3.9 or newer. You also need a `.env` file with your provider keys — see
[configuration](02-configuration.md).

## Get the documents

`filings/` is empty in a fresh clone. It holds 338 MB of filings that came with
the challenge, and no commit should carry that.

```bash
unzip analyst-copilot-data.zip     # gives you filings/ and the practice questions
```

Nothing in `scripts/eval/` runs without it.

## Run the tests

```bash
PYTHONPATH=src pytest
```

All 281 run offline. No provider, no network, no documents needed.

| Test file | Covers |
|---|---|
| `test_parsing.py`, `test_multiformat.py` | Reading documents |
| `test_bm25.py`, `test_hybrid.py`, `test_scoring.py` | Retrieval |
| `test_qa.py` | Tier 1 |
| `test_agent_tools.py` | Pages, tools, the calculator |
| `test_agent_runtime.py` | The agent loop and readers |
| `test_agent_verification.py` | Proving computed answers |
| `test_agent_planner.py` | The planner and its safety guards |
| `test_agent_pipeline.py` | Which tier runs, and the escapes |
| `test_api.py`, `test_conversations.py`, `test_collections.py` | The HTTP contract |

## Run the whole thing

The simplest way is Docker — see [running the stack](15-docker.md).

```bash
cp .env.example .env      # then fill in your keys
docker compose -f docker-compose.yml up --build
```

## Demos

```bash
PYTHONPATH=src python scripts/examples/parse_filing_example.py
PYTHONPATH=src python scripts/examples/bm25_search_example.py
PYTHONPATH=src python scripts/examples/hybrid_search_example.py
PYTHONPATH=src python scripts/examples/qa_example.py
PYTHONPATH=src python scripts/examples/ask.py filings/3M_2018_10K.htm "What was FY2018 capex?"
```

The last one indexes the file first if it has not been indexed yet.
