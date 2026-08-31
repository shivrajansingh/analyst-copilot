# Stopping a run

**Status:** implemented
**Mock:** [`docs/mocks/stop-button.html`](mocks/stop-button.html) — open it in a browser
**Touches:** [`api/routers/chat.py`](../src/analyst_copilot/api/routers/chat.py),
[`agent/pipeline.py`](../src/analyst_copilot/agent/pipeline.py),
[`agent/orchestrator.py`](../src/analyst_copilot/agent/orchestrator.py),
[`agent/runtime.py`](../src/analyst_copilot/agent/runtime.py),
[`ui/src/pages/Chat.tsx`](../ui/src/pages/Chat.tsx),
[`ui/src/components/chat/Composer.tsx`](../ui/src/components/chat/Composer.tsx)

---

## The problem

The deep path reads every page of a 10-K with 31 parallel readers and takes about
a minute. Right now an analyst who asks the wrong question, or who reads the
first trace line and realises they meant *2023* rather than *2022*, has exactly
one way out: close the tab. There is no way to say "stop".

There is a second, quieter problem, and it is the one that makes this more than
a button. **Closing the tab today does not stop the work.** The stream's `finally`
cancels the producing coroutine:

```python
finally:
    if not task.done():
        task.cancel()
```

but the pipeline does not run in that coroutine. It runs in a worker thread via
`run_in_threadpool`, and that thread has spawned a `ThreadPoolExecutor` of its
own. Cancelling an `asyncio` task never interrupts a thread. The readers keep
reading, the synthesiser still runs, and every one of those LLM calls is billed
to answer a question nobody is waiting for.

So the requirement — *the whole process in any case should be stopped* — is not
satisfied by hiding the answer. It is satisfied by a cancellation signal that
reaches the innermost reader thread.

---

## The shape

```text
  Composer (Stop)  ──abort()──▶  fetch AbortSignal
        │                              │
        │  POST /chat/runs/{id}/cancel │ (fallback: proxy hid the disconnect,
        │                              │  or the analyst stopped from another tab)
        ▼                              ▼
   RunRegistry ─────────────▶ CancelToken (threading.Event)
                                       │
        ┌──────────────────────────────┼──────────────────────────────┐
        ▼                              ▼                              ▼
   pipeline seams              orchestrator pool             runtime, per LLM call
   (every _emit)          shutdown(cancel_futures=True)     raise_if_cancelled()
```

One `threading.Event` per run, checked at seams that already exist. Nothing new
has to be threaded through the interesting code — every place that reports
progress is already a place that can notice it should stop.

---

## Server

### 1. `CancelToken` — `agent/cancellation.py` (new)

```python
class Cancelled(Exception):
    """The analyst stopped this run. Not an error; nothing failed."""

class CancelToken:
    def __init__(self) -> None: self._event = threading.Event()
    def cancel(self) -> None: self._event.set()
    @property
    def cancelled(self) -> bool: return self._event.is_set()
    def raise_if_cancelled(self) -> None:
        if self._event.is_set(): raise Cancelled()
```

A `NullToken` that never cancels keeps `cancel=None` call sites free of `if`s.

### 2. Checkpoints

Cancellation is cooperative, so the only question is how *dense* the checkpoints
are. The rule: **check immediately before anything that costs money or a
minute**, and at every seam that already exists.

| Where | Check | Why there |
|---|---|---|
| `pipeline`, at each stage boundary | `raise_if_cancelled()` | The seams already exist. The check is at the emit *site* rather than inside `_emit`, which swallows exceptions on purpose so progress reporting can never break an answer |
| `runtime.py`, before each `chat()` call | `raise_if_cancelled()` | The unit of spend. A stopped run must not start turn *n+1* |
| `ShardReader.read`, on entry and per tool loop | `raise_if_cancelled()` | A reader that has not begun exits at zero cost |
| `orchestrator._fan_out`, in the `as_completed` loop | `token.cancelled` → `pool.shutdown(wait=False, cancel_futures=True)` | Drops every queued shard instantly; typically 23 of 31 |
| `QuestionAnsweringService`, `AnswerValidator`, `verify_agent_answer` | on entry | Tier boundaries |

Worst case cost after Stop is **one in-flight LLM call per running reader** —
the concurrency cap, not the shard count. Nothing new is started.

### 3. `RunRegistry` — `api/services/runs.py` (new)

`run_id → (user_id, CancelToken, created_at)`, in-process, TTL-swept at 15
minutes. Single-process today; if the API is ever scaled out, this moves to
Redis pub/sub, which is why cancel goes through a registry rather than a
module-level dict.

### 4. Wire-level changes to `/chat/stream`

- A new **first event**, before any stage: `event: run` / `data: {"run_id": "..."}`.
  The client needs the id before it can be cancelled, and it is available before
  any work starts.
- A new **terminal event**: `event: cancelled` /
  `data: {"stage": "deep_search", "elapsed_ms": 12400, "done": 12, "total": 31}`.
  The stream ends after it, exactly as it does after `answer` and `error`.
- The generator's `finally` now sets the token as well as cancelling the task —
  so a closed tab really does stop the work, which it does not today.

`Cancelled` is caught in `produce()` alongside `ApiError` and turned into that
event. **A cancelled turn is not persisted**: `record_exchange` is skipped, so a
half-finished run never becomes a message in the thread's history.

### 5. `POST /chat/runs/{run_id}/cancel`

Returns `202` if the token was set, `404` if the run is unknown or belongs to
another user. Idempotent. It exists because SSE disconnect detection depends on
buffering behaviour we do not fully control (nginx sits in front of this), and
because "stop it from my phone" is a real thing analysts do.

Why both paths and not just this one? The abort is instant and needs no round
trip; the endpoint is the guarantee. Belt, and braces.

### 6. `POST /chat` (non-streaming)

Unchanged. It has no channel to carry a stop and no run id to name — a client
that wants to cancel uses the streaming endpoint. Documented, not fixed.

---

## Client

### `Composer` — one slot, two verbs

The send button becomes the stop button. Same position, same size, so nothing
moves under the cursor: `ArrowUp` on accent → `Square` on `failed-soft` with a
`failed` border. Never two buttons; an analyst should not have to aim.

| State | Button | Textarea | Trigger |
|---|---|---|---|
| `idle` | Send (accent, disabled under 3 chars) | enabled | — |
| `running` | **Stop** (square, failed) | enabled — the next question can be typed while this one runs | submit |
| `stopping` | Stop, spinner, disabled, "Stopping…" | enabled | click Stop / `Esc` |
| `idle` | Send | enabled | `cancelled` event arrives |

`Esc` while running stops, matching every other chat product. The composer's
textarea stops being `disabled` during a run — a disabled field steals focus and
makes `Esc` land nowhere.

`stopping` is a real state and not a lie about latency: the server is unwinding
in-flight calls, and showing "Stopping…" for the ~1s that takes is more honest
than a UI that claims to have stopped something it has not.

### `Chat.tsx`

- One `AbortController` per run in a ref. `stop()` calls
  `chatApi.cancelRun(runId)` (fire and forget), then aborts after a short grace
  period — long enough for the server's `cancelled` event, which is the better
  ending because it says *where* the run stopped. The captured controller is
  aborted, never `abortRef.current`: by then it may belong to the next question.
- `askStreaming` gains `onRun` and resolves to a discriminated result —
  `{status: 'answered', answer}` or `{status: 'cancelled', at}` — rather than
  throwing. A stop is not an error and must not land in the red
  `Something went wrong` card.
- The user's message **stays** in the thread. Only the assistant turn is replaced,
  by a `StoppedCard`.

### `StoppedCard` — a new component

```
■  Stopped
   Reading every page · 12 of 31 pages read · 12.4s
   Nothing was verified, so nothing is shown.
   [ Ask again ]
   ▸ Thinking · 47 steps
```

The middle line is the point. Because this product never streams an unverified
answer, a stopped run has **no partial answer to show** — and saying that
plainly is better than an empty card that reads as a failure. What survives is
the trail: the collected `TraceEvent`s stay in the card behind a disclosure, so
sixty seconds of reading is not thrown away. "Ask again" refills the composer
with the question, since most stops are followed by a reworded one.

Colour: `line-strong` and `ink-muted`. Not `failed` — nothing failed, and red
would train analysts to read their own decision as a bug.

---

## What this is not

- **Not a pause/resume.** A stopped run is discarded, not parked. Resuming would
  mean persisting half a fan-out, and the evidence it holds has not been
  verified.
- **Not a partial answer.** See above; this is the same rule that keeps tokens
  from streaming.
- **Not a per-agent stop.** The trace panel shows 31 readers and the temptation
  is a per-reader kill. An answer adjudicated over a subset that the analyst
  hand-picked is not an answer anybody can check.

---

## Tests

| Test | Asserts |
|---|---|
| `test_cancel_stops_fan_out` | With the token set mid-run, the reader pool submits no further shards and `Cancelled` propagates |
| `test_cancel_emits_cancelled_event` | The SSE stream ends with `cancelled` and never emits `answer` |
| `test_cancelled_run_is_not_persisted` | `record_exchange` is not called; the conversation gains no assistant message |
| `test_cancel_endpoint_is_scoped` | Another user's `run_id` is a 404 |
| `test_cancel_is_idempotent` | Two cancels, one `202` and one `404`; no exception |
| `test_disconnect_cancels_token` | Dropping the reader sets the token — the bug this document opens with |
| `test_llm_calls_stop_after_cancel` | A counting fake `chat()` records no calls after the token is set, beyond one per running reader |

All of the above are in `tests/test_cancellation.py`. The HTTP ones run against a
real uvicorn server on an ephemeral port rather than `TestClient`, and that is
forced by the subject: the test client reads an ASGI response to completion
before handing it back, so under it there is no such thing as a stream in
progress to stop, and no way to hang up on one halfway through.
