# HTTP API

A thin FastAPI shell over the pipeline. It imports `AnalystAgent`,
`QuestionAnsweringService` and `HybridFilingIndexer` and adds **no** retrieval,
prompting or verification logic of its own — every decision about an answer
still happens in `analyst_copilot.agent` and `analyst_copilot.services`.

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
└── routers/         health.py, filings.py, collections.py, conversations.py, chat.py
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
| `POST` | `/chat/stream` | The same answer, preceded by progress events (SSE) |

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

### Check `mode` before `found`

`/chat` answers messages, not only questions, so the response says which tier
produced it. See [Agent harness](16-agent-harness.md).

| `mode` | Meaning | `evidence` |
|---|---|---|
| `conversational` | Not a question about a document — a greeting, or a question about the assistant | `null`, and `found` is `true` |
| `fast` | Hybrid retrieval answered it and a second reader agreed | the cited page |
| `deep` | The cheap tiers could not prove an answer, so every page was read | the cited page |

A conversational reply is **neither an evidenced answer nor a decline**, which is
why `mode` is checked first. `found` is `true` because the message was answered;
there is simply nothing to cite. A client that branches on `found` alone will
render a greeting as if the filing proved it.

`"hi"` is a valid `question` — the request's minimum length is one character, not
three, because a greeting is a message to answer rather than a malformed request.

### Extra response fields

| Field | Meaning |
|---|---|
| `intent` | `smalltalk`, `capability` or `document_question` |
| `citations[]` | Every place the answer can be checked, one per answered part. `evidence` repeats the first. |
| `parts[]` | Set only when the question was split into several questions, each with its own answer and citation |
| `computation` | The arithmetic behind a derived figure, re-evaluated during verification |
| `inputs[]` | The figures a derived answer was computed from, each with the page it was read from |
| `validation` | What the checking step concluded, and why |
| `pages_read` / `shards_run` | Pages read and reader agents used by the deep path. `0` when it did not run. |

A derived answer is the case worth knowing about: an operating margin appears on
no page, so `evidence` cites where the argument lives while `inputs` and
`computation` are what actually prove it.

### Ask a question, streaming progress

Reading a whole filing takes about a minute, and a minute of silence reads as a
hang. `POST /chat/stream` returns the same `ChatResponse`, preceded by the
progress that produced it.

```bash
curl -N -X POST http://127.0.0.1:8000/api/v1/chat/stream \
  -H 'Content-Type: application/json' \
  -d '{"collection": "3M multi-year", "question": "What was FY2022 capex?"}'
```

```text
event: run
data: {"run_id":"run_9f2c1ab34d5e"}

event: stage
data: {"stage":"routing","detail":"reading the message"}

event: stage
data: {"stage":"deep_search","detail":"reader 4: nothing here","done":4,"total":13}

event: answer
data: {"doc_name":"3M_2022_10K","found":true,"mode":"deep", ...}
```

| Event | Payload | Notes |
|---|---|---|
| `run` | `{run_id}` | Exactly one, always **first**, before any work. Names the run so it can be stopped. |
| `stage` | `{stage, detail, done?, total?, part?, part_total?}` | Milestones. A handful per answer. `done`/`total` only while readers are fanning out. |
| `trace` | `{kind, agent?, text?, tool?, status?}` | The activity underneath. **Several hundred per answer.** |
| `answer` | The full `ChatResponse` | Exactly one, and always last |
| `error` | `{code, message}` | Instead of `answer`. The HTTP status is still `200` — the stream had already begun. |
| `cancelled` | `{stage, detail, elapsed_ms, done?, total?}` | Instead of `answer`, when the run was stopped. Where it got to, and nothing more. |

### `trace` events

Two event types rather than one because the volumes differ by two orders of
magnitude: a client that wants a progress bar should be able to read `stage` and
ignore this entirely.

| `kind` | Carries | Meaning |
|---|---|---|
| `thought` | `agent`, `text` | Text the model wrote of its own accord before calling a tool |
| `tool` | `agent`, `tool` | A tool call, **by name only** |
| `agent` | `agent`, `status` | One agent's lifecycle: `running` → `found` / `partial` / `empty` / `failed` |

```text
event: trace
data: {"kind":"agent","agent":"reader 7","status":"running"}

event: trace
data: {"kind":"thought","agent":"reader 7","text":"Page 60 has a cash flow line for PP&E purchases; reading it for the column headers."}

event: trace
data: {"kind":"tool","agent":"reader 7","tool":"read_page"}

event: trace
data: {"kind":"agent","agent":"reader 7","status":"found"}
```

`agent` is `reader N`, `synthesis` or `checker`. Thought text is truncated to 240
characters before it leaves the process — this is a progress feed, not a
transcript.

**Tool arguments and tool results are never sent.** They are large, they are the
least interesting part to watch, and a tool result is document text the verifier
has not seen: putting it on the wire would leak exactly the unverified figures
the API withholds everywhere else. There is a test asserting a `trace` payload
carries no other keys.

Everything on this channel is real. A quiet run looks quiet — nothing is
synthesised to fill a gap, because a progress feed that invents activity is worse
than one that admits there is none.

**Progress is streamed; the answer is not.** Verification runs after the model
replies, so streaming tokens would put an unproven figure on screen. The answer
arrives in one piece, already verified.

Three practical notes:

- It is a **POST**, so read it with `fetch` and a stream reader. `EventSource`
  cannot send a request body.
- A `:` keepalive comment is emitted every 15 seconds, so a proxy that closes
  idle connections does not kill a legitimate long answer.
- The response sets `X-Accel-Buffering: no`. Without it nginx would buffer the
  whole response and deliver every event at the end, which defeats the endpoint.
- Closing the reader **cancels the work** rather than leaving a fan-out of
  reader agents running for nobody. See below for what that means.

### Stop a run

```bash
curl -X POST http://127.0.0.1:8000/api/v1/chat/runs/run_9f2c1ab34d5e/cancel
# 202 {"run_id":"run_9f2c1ab34d5e","status":"cancelling"}
```

The stream ends with a `cancelled` event:

```text
event: cancelled
data: {"stage":"deep_search","detail":"reader 12: nothing here","elapsed_ms":13782,"done":12,"total":31}
```

**Accepted, not completed.** Cancellation is cooperative: the flag is checked
before every model call, every tool call and every shard, so the calls already in
flight finish and nothing new starts. The cost of a stop is therefore one
in-flight call per *running* reader — the concurrency cap — rather than whatever
the fan-out had left to do.

It has to work this way. The pipeline runs in a worker thread that spawns a
reader pool of its own, and nothing in `asyncio` can interrupt either: cancelling
the task that awaits the answer abandons the *result* while the readers keep
reading. What stops the work is the flag.

Two ways to set it, and both are worth having:

| | Latency | Why it exists |
|---|---|---|
| Hang up (close the reader / `AbortController`) | Instant, no round trip | The common case — a closed tab, a navigation, a stop button |
| `POST /chat/runs/{run_id}/cancel` | One request | How fast a hang-up is noticed depends on proxy buffering, which the service does not control; and an analyst may stop a run from a different tab |

A stopped run is **not persisted**: `record_exchange` never runs, so a thread
never gains a question with no answer under it. There is no partial answer
either, and there never will be — the answer is withheld until it is verified,
which is the same rule that keeps tokens from streaming.

`POST /chat` cannot be stopped. It has no channel to carry a stop and no run id
to name one by; a caller that needs to stop uses `/chat/stream`.

## Errors

Every failure has the same shape:

```json
{"error": {"code": "filing_not_indexed", "message": "…"}}
```

| Status | Code | When |
|---|---|---|
| 400 | `invalid_filing_name` | Filename yields no usable name, or file is empty |
| 404 | `filing_not_found` / `job_not_found` | Unknown filing or job |
| 404 | `run_not_found` | Cancelling a run that has finished, never existed, or belongs to another user |
| 409 | `filing_not_indexed` | A **document question** before the filing is ready. A greeting is still answered. |
| 413 | `file_too_large` | Upload exceeds `API_MAX_UPLOAD_BYTES` |
| 415 | `unsupported_file_type` | Not a supported document format |
| 422 | — | Request body failed validation (FastAPI default) |
| 502 | `upstream_unavailable` | Chat or embedding provider unreachable |
| 503 | `database_unavailable` | A conversations endpoint with no `DATABASE_URL` set |

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
