# Analyst Copilot

Backend for question-answering over SEC annual and quarterly filings.

- **Plan (done vs remaining):** [PLAN.md](PLAN.md)
- **Implementation docs:** [docs/README.md](docs/README.md)
- **Challenge spec:** [AGENTS.md](AGENTS.md)

## What works today

Parse a filing into pages, index with BM25 + embeddings, hybrid-search the right page, then ask the chat LLM. A verifier checks that cited numbers appear on that page. If evidence is weak, the system returns **not found in this filing**. `scripts/eval/score.py` grades answers against the practice key on the challenge rubric.

There is an HTTP API (add filing, status, chat) but no browser UI yet, and retrieval fusion plus the evidence window have known measured problems — see [PLAN.md](PLAN.md).

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

## Index every filing

```bash
PYTHONPATH=src python scripts/index_all.py              # index whatever is missing (default)
PYTHONPATH=src python scripts/index_all.py --overwrite  # re-embed every filing
PYTHONPATH=src python scripts/index_all.py --dry-run    # show the plan, embed nothing
PYTHONPATH=src python scripts/index_all.py --only '3M*' --workers 4
```

Skipping is the default, so the script is safe to re-run and safe to interrupt — completed filings are kept. Failures are retried (`--retries`, default 3) and listed at the end; re-running picks them up.

An index counts as current only if it was built by this `PARSER_VERSION`, with this `EMBEDDING_MODEL`, at this `retrieval_max_chars_per_page`. Change any of those and the affected indices are rebuilt even without `--overwrite`. `--dry-run` labels each filing `missing`, `stale` or `current` so you can see what a run would cost before starting it.

Each run writes `storage/index-report.json` with per-filing page counts and timings, and flags any filing that exceeded the spec's 10-minute-per-filing budget.

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

## Run the API

```bash
python scripts/serve_api.py          # http://127.0.0.1:8000, interactive docs at /docs
```

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/filings` | Add a filing (multipart upload) — returns `202` + a job to poll |
| `GET` | `/api/v1/filings/{doc_name}/status` | `queued → parsing → embedding → saving → ready` / `failed` |
| `GET` | `/api/v1/filings` | Filings the service can answer from |
| `POST` | `/api/v1/chat` | Ask one question of one filing |
| `GET` | `/api/v1/health` | Models in use, filings indexed |

```bash
curl -X POST http://127.0.0.1:8000/api/v1/chat -H 'Content-Type: application/json' \
  -d '{"doc_name": "3M_2018_10K", "question": "What is the FY2018 capital expenditure?"}'
```

Declining is a normal `200` with `"found": false` and `"evidence": null`, not an
error. Details: [docs/11-api.md](docs/11-api.md).

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
3. Verify: cited page must be in the retrieved set; every figure in the answer must trace back to a figure on that page, comparing significant digits so a filing printed in millions still supports an answer given in billions.
4. Otherwise abstain: **not found in this filing**.

Details: [docs/09-qa-pipeline.md](docs/09-qa-pipeline.md).

## Parsing strategy

SEC HTML is split on `page-break-after: always` or `page-break-before: always`, matched on `<hr>`, `<p>` or `<div>`. `<hr>` accounts for 76 of the 79 filings; matching only `<p>` sent nearly the whole corpus down the fallback path. Each segment becomes one page of plain text. Only 3 filings — short 8-Ks with no page-break markers at all — fall back to fixed-size chunks.

Citations use the 0-based `page_index`, which matches the practice key's `evidence_page_num` (74% exact, 91% within ±1). Printed footer numbers are parsed but not cited — they disagree with gold in both directions. See [docs/03-html-parsing.md](docs/03-html-parsing.md).

Indices record `PARSER_VERSION`, so a parsing change makes stale indices report as absent and they rebuild automatically instead of being silently reused.
