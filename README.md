# Analyst Copilot

Question-answering over company filings, in whatever format the analyst has them.

- **Plan (done vs remaining):** [PLAN.md](PLAN.md)
- **Implementation docs:** [docs/README.md](docs/README.md)
- **Challenge spec:** [AGENTS.md](AGENTS.md)

## What works today

Parse a document — **PDF, HTML, Word, Excel, CSV or Markdown** — into Markdown
pages, then answer questions about it at the cheapest tier that can prove
itself:

| | | |
|---|---|---|
| **Tier 1** | BM25 + embeddings → hybrid search → chat LLM → deterministic verifier | ~3s |
| **Tier 2** | a second reader checks that answer against the **whole** cited page | ~15s |
| **Tier 3** | every page of the filing read by parallel agents, then adjudicated | ~60s |

Tier 1 can only answer from the five pages retrieval chose, and on the practice
key that set holds the gold page **58%** of the time — so tier 3 exists to
remove a ceiling no prompt can lift. It runs only when the cheap tiers cannot
produce an answer that survives checking. Details:
[docs/16-agent-harness.md](docs/16-agent-harness.md).

Either way the answer is attached to a page whose own text supports it, or the
system returns **not found in this filing**. `scripts/eval/score.py` grades
answers against the practice key on the challenge rubric.

**It also talks.** "Hi" gets a reply, not a search of a 10-K — every message is
classified before anything is retrieved, and a greeting is answered as a
greeting with nothing cited.

**Computed answers are provable.** An operating margin appears nowhere in a
filing; only the two figures behind it do. A derived figure is verified through
its **inputs** — each traced to the page it was read from, with the arithmetic
re-run exactly — so the 43 numerical-reasoning questions in the practice set are
no longer unanswerable by construction.

There is an HTTP API (add filing, status, chat, streaming chat) and a React UI
in [`ui/`](ui/).

### Supported formats

| Format | Extensions | Unit cited | Boundary from |
|---|---|---|---|
| PDF | `.pdf` | page | the file — pages are stored, not inferred |
| HTML | `.htm` `.html` `.xhtml` | page | `page-break: always` markers |
| Word | `.docx` | page or section | author page breaks; else headings |
| Excel | `.xlsx` `.xlsm` | sheet | one worksheet each; row blocks if large |
| CSV | `.csv` `.tsv` | table | the file; row blocks if large |
| Markdown / text | `.md` `.txt` | section | whole file, chunked only if oversized |

Every format is normalized to Markdown — tables stay tables, so a figure keeps
its year column — and stored one file per page under `storage/markdown/`.
A segment is only called a *page* when the source really has pages; a workbook
answer cites `sheet 'Q4 Revenue'`, not `page 4`. Details:
[docs/13-document-parsing.md](docs/13-document-parsing.md).

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
├── ui/                       # React frontend
├── src/analyst_copilot/
│   ├── config/
│   ├── parsing/              # format detection, one parser per format,
│   │   ├── parsers/          #   all normalized to Markdown
│   │   └── markdown_store.py #   storage/markdown/{doc}/page-001.md
│   ├── embeddings/           # OpenAI-compatible /v1/embeddings
│   ├── llm/                  # OpenAI-compatible /v1/chat/completions
│   ├── retrieval/            # BM25, vector, hybrid
│   ├── agent/                # The harness: route, validate, deep-search
│   │   ├── corpus.py         #   pages on disk, sharded ≤10 per reader
│   │   ├── tools/            #   list/search/read/read_lines/calculate
│   │   ├── reader.py         #   one agent, one slice, strict brief
│   │   ├── orchestrator.py   #   fan out, then adjudicate
│   │   ├── verification.py   #   proves a computed figure via its inputs
│   │   └── pipeline.py       #   the three tiers
│   └── services/
│       ├── indexing/
│       └── qa/               # Retrieve → LLM → verify / abstain
├── storage/                  # Generated Markdown + indices (gitignored)
└── tests/
```

## Run it with Docker

Two containers — the API and an nginx-served UI — and one compose file.

```bash
cp .env.example .env          # then fill in the provider keys
docker compose -f docker-compose.yml up --build
```

The app is on <http://localhost:3000>; the API is also published on
<http://127.0.0.1:8000> for `curl` and `/docs`. `docker compose up` without
`-f` instead brings up hot-reloading dev servers (uvicorn `--reload` and Vite
with HMR on 5173). `filings/` and `storage/` are bind-mounted, so uploads and
indices live on the host and survive the containers. Details:
[docs/15-docker.md](docs/15-docker.md).

## The corpus is not in the repository

`filings/` is gitignored. It is 338 MB of 10-Ks that arrived with the challenge
zip — input data that never changes and that no commit should carry. The
directory is still where the code expects it (`settings.filings_dir`), and it
doubles as the destination for documents added through the UI.

**A fresh clone has to repopulate it** before the tests or the eval scripts
will run:

```bash
unzip analyst-copilot-data.zip          # gives filings/ and practice-questions.jsonl
```

The practice key itself (`data/practice-questions.jsonl`) *is* committed — it is
small, it is the scoring authority, and nothing in `scripts/eval/` runs without
it.

## Setup (without Docker)

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

If the filing is not indexed yet, the script embeds it first, then searches and
prints the answer, page, and evidence. You can also pass a stem: `3M_2018_10K`.

There is no bulk-indexing step. Every entry point indexes what it needs on
demand — `QuestionAnsweringService` builds a document's indices the first time
a question is asked of it, and the API does the same per upload, reporting
progress against the spec's 10-minute budget as it goes.

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
| `POST` | `/api/v1/collections` | Create a filing |
| `POST` | `/api/v1/collections/{name}/documents` | Add **many** documents to a filing at once |
| `GET` | `/api/v1/collections/{name}/jobs` | Indexing progress, one row per document |
| `POST` | `/api/v1/filings` | Add a single filing (multipart upload) — returns `202` + a job to poll |
| `GET` | `/api/v1/filings/{doc_name}/status` | `queued → parsing → embedding → saving → ready` / `failed` |
| `GET` | `/api/v1/filings` | Filings the service can answer from |
| `POST` | `/api/v1/chat` | Ask one question of one **filing** (or one document) |
| `POST` | `/api/v1/chat/stream` | The same answer, preceded by progress events (SSE) |
| `GET` | `/api/v1/conversations` | The caller's chat threads, newest first |
| `POST` | `/api/v1/conversations` | Start a thread (pinned to one filing) |
| `GET` | `/api/v1/conversations/{id}` | A thread with all its messages |
| `PATCH` | `/api/v1/conversations/{id}` | Rename a thread |
| `DELETE` | `/api/v1/conversations/{id}` | Delete a thread and its messages |
| `GET` | `/api/v1/health` | Models in use, filings indexed |

```bash
curl -X POST http://127.0.0.1:8000/api/v1/chat -H 'Content-Type: application/json' \
  -d '{"collection": "3M multi-year", "question": "What is the FY2018 capital expenditure?"}'
```

Chat history lives in **Postgres** (the `db` service in the compose stack), not
the browser. `POST /chat` accepts a `conversation_id` and records the question
and the verified answer — or the decline — in the thread; the response then
carries `message_id`, `user_message_id` and `latency_ms`. Without a database
configured, questions are still answered, just not recorded.

## Filings

A **filing** here is a named set of documents, not a single file: a question is
rarely about one file, so a question is asked of the whole filing. Retrieval
ranks pages from every indexed document in it against each other; the answer
still cites exactly one document.

The code calls these *collections* (`/api/v1/collections`) because "filing"
already means a single 10-K throughout the pipeline.

```bash
curl -X POST http://127.0.0.1:8000/api/v1/collections \
  -H 'Content-Type: application/json' -d '{"name": "3M multi-year"}'

curl -X POST "http://127.0.0.1:8000/api/v1/collections/3M%20multi-year/documents" \
  -F "files=@filings/3M_2018_10K.htm" -F "files=@filings/3M_2022_10K.htm"
```

Each filing is mirrored on both sides: originals under `filings/{name}/`,
Markdown and indices under `storage/{name}/` — one directory per filing, holding
`markdown/`, `bm25/` and `vector_indices/`. A filing is searchable as soon as
one of its documents is ready. Details:
[docs/14-collections.md](docs/14-collections.md).

## Run the UI

```bash
cd ui && npm install && npm run dev     # http://localhost:5173
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
PYTHONPATH=src python scripts/eval/run_practice.py                  # all 136, full harness
PYTHONPATH=src python scripts/eval/run_practice.py --limit 10
PYTHONPATH=src python scripts/eval/run_practice.py --fast-only      # tier 1 alone
```

`--fast-only` runs the retrieval pipeline by itself. That is the +7 baseline, and
it is what any harness gain has to be measured against — the runner prints which
tier answered each question so a score change can be attributed.

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

## How a question is answered

1. **Route.** Greeting, question about the assistant, or question about the
   document? Common greetings match literally and cost no model call. On any
   doubt the message is treated as a document question — answering a real
   question from nothing is the worse error.
2. **Split.** A message asking several things becomes several questions, each
   retrieved, answered and **cited separately**. Composition is done in code, so
   no figure is rewritten after it was verified.
3. **Tier 1.** Hybrid retrieve the top pages, prompt the chat model for JSON
   (`answer`, `page`, `evidence_snippet`, or `not_found`), then verify
   **evidence first**: score every retrieved page for whether it supports the
   answer — figures traced by significant digits, so a filing printed in
   millions still supports an answer given in billions — and cite the page that
   actually carries the evidence. The page the model named is a hint.
4. **Tier 2.** A reader that did not write the answer sees the question, the
   answer and the *whole* cited page, and rules `correct` / `incorrect` /
   `insufficient`. This catches what digit-tracing cannot: the right figure for
   the wrong fiscal year, a segment instead of the consolidated total, half of a
   compound question.
5. **Tier 3.** If tier 1 abstained or tier 2 doubted it, the filing is sharded
   into slices of ten pages, one reader agent per slice, eight at a time. Readers
   may read **only** their own pages — so together they have read the whole
   document and no two can report the same page. A synthesis agent then
   adjudicates the candidates on authority, not on which figure looks nicest.
6. **Verify, always.** The deterministic verifier is the last word on both
   answering tiers. Agents propose; it disposes.
7. **Otherwise abstain:** **not found in this filing**.

### Flexible location, strict evidence

The page number is the least reliable link in the chain: the same document paginates differently as filed HTML and as the filer's own PDF, and 15 of 62 documents in the practice corpus disagree by one or two pages between the two. So verification finds the page and reports what it did:

| `location_match` | Meaning |
|---|---|
| `exact` | The model's page carries the evidence |
| `adjusted` | A page within `evidence_page_tolerance` (2) does; the citation moved there |
| `relocated` | A distant page carries the quote verbatim; the citation moved there |
| `inferred` | The model named no page; the best-supported one was used |

This does not loosen the guard against a wrong answer. An answer is still only ever attached to a page whose own text supports its figures — the change is that the system looks for that page instead of requiring the model to guess its number. Re-anchoring moves a citation; it never changes an answer.

Details: [docs/09-qa-pipeline.md](docs/09-qa-pipeline.md).

## HTML parsing strategy

SEC HTML is split on `page-break-after: always` or `page-break-before: always`, matched on `<hr>`, `<p>` or `<div>`. `<hr>` accounts for 76 of the 79 filings; matching only `<p>` sent nearly the whole corpus down the fallback path. Each segment becomes one page of plain text. Only 3 filings — short 8-Ks with no page-break markers at all — fall back to fixed-size chunks.

Citations use the 0-based `page_index`, which matches the practice key's `evidence_page_num` (74% exact, 91% within ±1). Printed footer numbers are parsed but not cited — they disagree with gold in both directions. See [docs/03-html-parsing.md](docs/03-html-parsing.md).

Indices record `PARSER_VERSION`, so a parsing change makes stale indices report as absent and they rebuild automatically instead of being silently reused.
