# HTTP API

A thin FastAPI shell over the existing pipeline. It imports
`QuestionAnsweringService` and `HybridFilingIndexer` and adds **no** retrieval,
prompting or verification logic of its own — every decision about an answer
still happens in `analyst_copilot.services`.

```bash
python scripts/serve_api.py            # http://127.0.0.1:8000, docs at /docs
python scripts/serve_api.py --reload
API_PORT=9000 python scripts/serve_api.py
```

## Layout

```text
src/analyst_copilot/api/
├── config.py        ApiSettings — API_* env vars only, separate from the pipeline's
├── errors.py        ApiError hierarchy + handlers; one error shape everywhere
├── schemas.py       request/response models (the wire contract)
├── jobs.py          IndexingJobManager — background "Add filing" work
├── filings.py       FilingService — upload rules, storage, indexed-state queries
├── dependencies.py  singletons wired through Depends (overridable in tests)
├── main.py          create_app() — middleware, routers, lifespan
└── routers/         health.py, filings.py, chat.py
```

Configuration is deliberately split. `analyst_copilot.config.settings` configures
the *pipeline* (model endpoints, retrieval weights) and is shared with the CLI
scripts. `analyst_copilot.api.config` configures the *process* (port, limits,
concurrency) under an `API_` prefix, so the two can never collide.

## Endpoints

All under `/api/v1`.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Models in use and how many filings are queryable |
| `POST` | `/filings` | **Add filing** — multipart upload, returns `202` + job |
| `GET` | `/filings` | Filings with an index on disk |
| `GET` | `/filings/{doc_name}/status` | Processing status for one filing |
| `GET` | `/jobs/{job_id}` | Processing status by job id |
| `POST` | `/chat` | Ask one question of one filing |

### Add a filing

```bash
curl -X POST http://127.0.0.1:8000/api/v1/filings -F 'file=@filings/NEWCO_2024_10K.htm'
```

```json
{"job_id": "8f2c…", "doc_name": "NEWCO_2024_10K", "status": "queued",
 "elapsed_seconds": 0.01, "budget_seconds": 600, "over_budget": false,
 "page_count": null, "error": null}
```

Indexing a 10-K takes minutes, so the upload returns immediately and the caller
polls. Status moves `queued → parsing → embedding → saving → ready`, or
`failed` with the error text. `budget_seconds` is the spec's 10-minute
per-filing limit and `over_budget` flags a breach, so a UI can show progress
against the requirement rather than an unbounded spinner.

Re-uploading a filing that is mid-index joins the job in flight instead of
embedding it twice. Uploads are streamed and size-checked as they arrive, and
the filename is reduced to its stem so a path cannot escape the storage root.

### Ask a question

```bash
curl -X POST http://127.0.0.1:8000/api/v1/chat -H 'Content-Type: application/json' \
  -d '{"doc_name": "3M_2018_10K", "question": "What is the FY2018 capital expenditure?"}'
```

```json
{"doc_name": "3M_2018_10K", "found": true, "answer": "1,577",
 "evidence": {"doc_name": "3M_2018_10K", "page": 59, "display_page": 60,
              "snippet": "Purchases of property, plant and equipment (PP&E) (1,577) …"},
 "retrieved_pages": [59, 45, 38, 48, 46], "abstention_reason": null}
```

`page` is the 0-based `citation_page` used everywhere else in the system and by
the practice key; `display_page` is the same page for humans.

**Declining is a `200`, not an error.** When the evidence is not there,
`found` is `false`, `answer` is `"not found in this filing"` and `evidence` is
`null`. A caller should never have to tell "no evidence" apart from "the service
broke".

Questions are scoped to one filing on purpose — a citation is only checkable
against the document it names.

## Errors

Every failure has the same shape:

```json
{"error": {"code": "filing_not_indexed", "message": "…"}}
```

| Status | Code | When |
|---|---|---|
| 400 | `invalid_filing_name` | Filename yields no usable name, or file is empty |
| 404 | `filing_not_found` / `job_not_found` | Unknown filing or job |
| 409 | `filing_not_indexed` | `/chat` before the filing is ready |
| 413 | `file_too_large` | Upload exceeds `API_MAX_UPLOAD_BYTES` |
| 415 | `unsupported_file_type` | Not `.htm` / `.html` |
| 422 | — | Request body failed validation (FastAPI default) |
| 502 | `upstream_unavailable` | Chat or embedding provider unreachable |

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `API_HOST` / `API_PORT` | `127.0.0.1` / `8000` | Bind address |
| `API_CORS_ORIGINS` | `["*"]` | Origins allowed to call the API |
| `API_MAX_UPLOAD_BYTES` | 32 MiB | Largest accepted filing (corpus max ≈ 16 MiB) |
| `API_MAX_CONCURRENT_INDEX_JOBS` | 2 | Indexing threads; embedding is network-bound |
| `API_INDEX_BUDGET_SECONDS` | 600 | The spec's per-filing limit, reported in status |
| `API_ROOT_PATH` | `""` | Set when served behind a path-prefixing proxy |

## Design notes

**Job state is in-process.** A restart loses the progress log but never a
finished index — the durable state is the index on disk, and
`/filings/{doc_name}/status` falls back to reading it, so a filing indexed
before the last restart still reports `ready`.

**The QA call runs off the event loop.** `QuestionAnsweringService.answer` is
synchronous and spends its time on network calls, so `/chat` dispatches it
through `run_in_threadpool` and the service stays responsive under concurrent
questions.

**Indexing failures are reported, not raised.** A job that dies marks itself
`failed` with the exception text; it never takes down a worker or the process.

## Tests

`tests/test_api.py` covers the contract offline — the indexer and QA service are
replaced through `app.dependency_overrides`, so no model is ever called:

```bash
PYTHONPATH=src pytest tests/test_api.py -q
```
