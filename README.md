# Analyst Copilot

Backend for question-answering over SEC annual and quarterly filings.

- **Plan (done vs remaining):** [PLAN.md](PLAN.md)
- **Implementation docs:** [docs/README.md](docs/README.md)
- **Challenge spec:** [AGENTS.md](AGENTS.md)

## What works today

Parse a filing into pages, index with BM25 + embeddings, hybrid-search the right page, then ask the chat LLM. A verifier checks that cited numbers appear on that page. If evidence is weak, the system returns **not found in this filing**. `scripts/eval/score.py` grades answers against the practice key on the challenge rubric.

There is no chat UI yet, and retrieval fusion plus the evidence window have known measured problems — see [PLAN.md](PLAN.md).

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

## Ask one question (index if needed)

```bash
python scripts/examples/ask.py filings/3M_2018_10K.htm "What is the FY2018 capital expenditure amount for 3M?"
```

If the filing is not indexed yet, the script embeds it first, then searches and prints the answer, page, and evidence. You can also pass a stem: `3M_2018_10K`.

## Run all questions (index each filing if needed)

```bash
python scripts/examples/run_all_questions.py
python scripts/examples/run_all_questions.py --limit 5
```

Reads `data/questions-by-doc.json`. For each document it embeds if needed, answers that filing’s questions, and updates `data/questions-by-doc-results.json` after every question. Re-running skips questions that already have answers.

## Examples

```bash
PYTHONPATH=src python scripts/examples/parse_filing_example.py
PYTHONPATH=src python scripts/examples/embedding_example.py
PYTHONPATH=src python scripts/examples/bm25_search_example.py
PYTHONPATH=src python scripts/examples/hybrid_search_example.py
PYTHONPATH=src python scripts/examples/hybrid_search_full_filing.py
PYTHONPATH=src python scripts/examples/qa_example.py
PYTHONPATH=src python scripts/examples/ask.py filings/3M_2018_10K.htm "What is FY2018 capex?"
PYTHONPATH=src python scripts/examples/build_questions_by_doc.py
PYTHONPATH=src python scripts/eval/run_practice.py --limit 5
```

`qa_example.py` loads (or builds) indices for `3M_2018_10K`, runs hybrid search, calls the chat model, and prints the verified answer plus page — or **not found in this filing**.

## Evaluate and score

Produce answers (writes after every question, safe to interrupt):

```bash
PYTHONPATH=src python scripts/eval/run_practice.py            # all 136
PYTHONPATH=src python scripts/eval/run_practice.py --limit 10
```

Grade them against the practice key using the challenge rubric
(+1 correct answer *and* location, 0 abstain, 0 right answer wrong page, −1 confidently wrong):

```bash
PYTHONPATH=src python scripts/eval/score.py --results data/eval-results.json
PYTHONPATH=src python scripts/eval/score.py --results data/eval-results.json --judge
```

Bare figures are checked arithmetically with scale-aware tolerance; prose answers
need `--judge` or they are reported as `unjudged` rather than counted as wrong.
Details: [docs/10-evaluation.md](docs/10-evaluation.md).

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

SEC HTML is split on `page-break-after: always`, matched on `<hr>`, `<p>` or `<div>` — `<hr>` accounts for 78 of the 79 filings, and matching only `<p>` sent nearly the whole corpus down the fallback path. Each segment becomes one page of plain text. Filings with no page-break markers at all (5, mostly short 8-Ks) fall back to fixed-size chunks.

Citations use the 0-based `page_index`, which matches the practice key's `evidence_page_num` (74% exact, 90% within ±1). Printed footer numbers are parsed but not cited — they disagree with gold in both directions. See [docs/03-html-parsing.md](docs/03-html-parsing.md).

Indices record `PARSER_VERSION`, so a parsing change makes stale indices report as absent and they rebuild automatically instead of being silently reused.
