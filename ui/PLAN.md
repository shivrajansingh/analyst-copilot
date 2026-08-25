# Analyst Copilot — Frontend Plan

**Status:** plan only. No code written yet.
**Scope:** a React application in `ui/`, a Postgres-backed API, and a Docker Compose
stack that runs the whole product.

---

## 1. What we are building

The backend answers analyst questions over one SEC filing and cites the page, or
declines. `AGENTS.md` grades a **product**, and the four graded surfaces are:

| Requirement | Where it lands |
|---|---|
| "Add filing" control with visible processing status, ≤10 min | Filing Library screen |
| A chat box for plain-English questions | Chat workspace |
| Evidence — document and page — on every answer | Evidence panel + inline citations |
| The ability to decline, stated plainly | A distinct, deliberate decline state |

On top of those, this round adds: per-index visibility (BM25 vs embeddings),
runtime provider configuration, demo authentication, Postgres, and chat history.

### The one product principle that drives the design

**A number the system cannot prove must never appear on screen.**

That is why the answer is not streamed token-by-token: the verifier runs *after*
the model replies, and an unverified figure rendering for even a second would
undermine the whole premise. Instead the UI shows a staged progress indicator
(*retrieving → reading → verifying*) and the answer appears atomically, already
proven. A decline is presented as a considered outcome, not an error.

---

## 2. Tech stack

| Concern | Choice | Why |
|---|---|---|
| Framework | React 18 + TypeScript, **Vite** | Fast builds, first-class TS, trivial to containerise |
| Routing | React Router 6 | Nested layouts fit the chat/library/settings split |
| Server state | **TanStack Query** | Polling job status, cache invalidation, retries — all the hard parts |
| Client state | Zustand (small stores) | Auth session, UI prefs, active filing. No Redux ceremony |
| Styling | **Tailwind CSS** + shadcn/ui (Radix) | Accessible primitives we own the source of; consistent tokens |
| Forms | react-hook-form + zod | One schema validates the form and types the payload |
| HTTP | Typed `fetch` wrapper (no axios) | Small; interceptors we control for auth + error mapping |
| Icons | lucide-react | Consistent, tree-shakeable |
| Dates | date-fns | Chat history grouping |
| Tests | Vitest + Testing Library + **MSW** | MSW lets every screen be tested against the real API contract, offline |
| Lint | ESLint + Prettier + `tsc --noEmit` in CI | |

**Deliberately not used:** Next.js (no SSR need — this is an authenticated SPA behind
an API), Redux (overkill), a component library we cannot restyle (MUI/AntD both fight
a custom design language).

---

## 3. Directory layout

```text
ui/
├── PLAN.md                     ← this file
├── Dockerfile                  multi-stage: node build → nginx serve
├── nginx.conf                  SPA fallback + /api proxy to the api service
├── index.html
├── package.json / tsconfig.json / vite.config.ts / tailwind.config.ts
└── src/
    ├── main.tsx, App.tsx, router.tsx
    ├── api/
    │   ├── client.ts           fetch wrapper: auth header, error → ApiError
    │   ├── types.ts            generated-by-hand mirrors of the API schemas
    │   └── endpoints/          auth.ts filings.ts chat.ts conversations.ts settings.ts jobs.ts
    ├── hooks/                  useAuth, useFilings, useJobPolling, useConversation …
    ├── stores/                 auth.store.ts, ui.store.ts
    ├── components/
    │   ├── ui/                 shadcn primitives (Button, Dialog, Badge, Toast…)
    │   ├── layout/             AppShell, Sidebar, TopBar, CommandPalette
    │   ├── chat/               MessageList, MessageBubble, Composer, FilingPicker,
    │   │                       AnswerCard, DeclineCard, ThinkingIndicator
    │   ├── evidence/           EvidencePanel, EvidenceCard, CitationChip,
    │   │                       PageViewer, RetrievalTrace, VerificationStrip
    │   ├── filings/            FilingTable, FilingRow, IndexBadge, AddFilingDropzone,
    │   │                       JobProgress, FilingDetail
    │   └── settings/           ProviderForm, ConnectionTest, ReindexWarning
    ├── pages/                  Login, Chat, Filings, FilingDetail, Settings, NotFound
    ├── lib/                    format.ts, cn.ts, constants.ts
    └── styles/                 globals.css (design tokens)
```

---

## 4. Screens

### 4.1 `/login` — demo authentication

```text
┌──────────────────────────────────────────────┐
│                                              │
│         ▮ Analyst Copilot                    │
│         Answers you can prove.               │
│                                              │
│   ┌────────────────────────────────────┐     │
│   │ Username  [ analyst            ]   │     │
│   │ Password  [ ••••••••           ]   │     │
│   │                                    │     │
│   │        [    Sign in    ]           │     │
│   │                                    │     │
│   │  ── or ─────────────────────────   │     │
│   │     [ Continue as demo user ]      │     │
│   │  demo / demo1234                   │     │
│   └────────────────────────────────────┘     │
└──────────────────────────────────────────────┘
```

Demo credentials are shown on screen and a one-click button fills and submits
them — a reviewer must never be blocked at the door.

### 4.2 `/chat` — the workspace

```text
┌────────────┬──────────────────────────────────────┬──────────────────┐
│ + New chat │  Filing: [ 3M_2018_10K        ▾ ]    │  EVIDENCE        │
│            │          134 pages · BM25 ✓ · Emb ✓  │                  │
│ TODAY      │ ──────────────────────────────────── │  ┌────────────┐  │
│ · 3M capex │                                      │  │ 3M_2018_10K│  │
│ · Nike rev │   ┌ you ─────────────────────────┐   │  │ page 60    │  │
│            │   │ What is FY2018 capex?        │   │  ├────────────┤  │
│ YESTERDAY  │   └──────────────────────────────┘   │  │ Purchases  │  │
│ · AMD seg  │                                      │  │ of property│  │
│ · Boeing   │   ┌ ANSWER ─────────── verified ─┐   │  │ , plant and│  │
│            │   │                              │   │  │ equipment  │  │
│ ─────────  │   │  $1,577 million              │   │  │ ▸(1,577)   │  │
│ ⚙ Settings │   │                              │   │  └────────────┘  │
│ 📚 Filings │   │  ▸ 3M_2018_10K · page 60     │   │                  │
│ 👤 demo    │   └──────────────────────────────┘   │  RETRIEVAL       │
│            │                                      │  ▸ p60  0.94 ★   │
│            │  ┌────────────────────────────────┐  │    p46  0.71     │
│            │  │ Ask about this filing…      ⏎ │  │    p39  0.66     │
│            │  └────────────────────────────────┘  │                  │
└────────────┴──────────────────────────────────────┴──────────────────┘
```

- **Filing is pinned to the conversation.** Picking a different filing starts a new
  conversation. A citation is only checkable against the document it names, so a
  thread that silently changes documents would produce uncheckable history.
- The picker shows index state inline, so an un-embedded filing is visibly unusable
  before the question is typed.
- Right panel is collapsible; on <1280px it becomes a slide-over sheet.

### 4.3 `/filings` — the library and the "Add filing" control

```text
┌──────────────────────────────────────────────────────────────────────┐
│  Filings                                    [ ⬆ Add filing ]         │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  ⬆  Drop a 10-K / 10-Q here, or click to browse (.htm, ≤32MB)  │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  ▶ NEWCO_2024_10K   embedding…  ███████████░░░░░  4:12 / 10:00       │
│                                                                      │
│  [All 78] [Ready 76] [Partial 1] [Failed 1]        🔍 [ search   ]   │
│  ┌──────────────────┬───────┬─────────┬────────────┬──────────────┐  │
│  │ Filing           │ Pages │ BM25    │ Embeddings │              │  │
│  ├──────────────────┼───────┼─────────┼────────────┼──────────────┤  │
│  │ 3M_2018_10K      │  134  │ ● ready │ ● ready    │  Chat  ⋯     │  │
│  │ 3M_2022_10K      │  131  │ ● ready │ ● ready    │  Chat  ⋯     │  │
│  │ AMCOR_2020_10K   │  122  │ ● ready │ ○ missing  │  Reindex ⋯   │  │
│  │ BROKEN_10K       │   —   │ ○ —     │ ✕ failed   │  Retry  ⋯    │  │
│  └──────────────────┴───────┴─────────┴────────────┴──────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
```

**BM25 and embeddings are shown as two independent badges**, because they genuinely
are two independent artefacts on disk and they fail independently — BM25 is local and
instant, embedding is a network call that can die halfway. A single "indexed" light
would hide the most common real failure: lexical index present, vectors missing.

Badge states: `ready` (green) · `building` (blue, animated) · `missing` (grey outline)
· `stale` (amber — built by a different parser version or embedding model) · `failed` (red).

`⋯` menu: Reindex · View detail · Remove index · Copy doc name.

### 4.4 `/filings/:docName` — detail

Two metadata cards side by side (BM25 / Embeddings) showing page count, parser
version, tokenizer or embedding model, dimensions, truncation cap, built-at and
size on disk. Below, a page browser for spot-checking what the parser produced —
the fastest way to explain a bad citation. A "Reindex" action with an explicit
warning when the current embedding model differs from the one the index was built with.

### 4.5 `/settings`

Tabs: **Providers** · **Retrieval** · **Account** · **About**

```text
  Chat model (LLM)                          Embedding model
  ┌────────────────────────────────┐        ┌────────────────────────────────┐
  │ Base URL  [https://…/v1      ] │        │ Base URL  [https://…/v1      ] │
  │ API key   [ ••••••••••••1234 ] │        │ API key   [ ••••••••••••9f2a ] │
  │ Model     [ deepseek-v4-flash] │        │ Model     [ qwen3-embedding-8b]│
  │                                │        │                                │
  │ [ Test connection ]  ✓ 412ms   │        │ [ Test connection ] ✓ 1.2s     │
  └────────────────────────────────┘        └────────────────────────────────┘

  ⚠ Changing the embedding model invalidates all 78 existing indices.
    They must be rebuilt before they can be searched.   [ Review impact ]
```

**The embedding-model warning is load-bearing.** Index metadata records the embedding
model, and an index built with a different one is silently wrong — the same page text
maps to a different vector space. The UI must make this consequence unmissable and
offer a bulk reindex path, not a shrug.

API keys are write-only: submitted in full, returned masked, never re-displayed.

---

## 5. Evidence design

Evidence gets four distinct treatments, escalating with how much the analyst wants
to interrogate the answer. This is deliberately *not* "a link under the text".

**1. Citation chip** — inline in the answer, monospace, clickable:
`▸ 3M_2018_10K · p.60`. Hover previews the snippet; click opens the panel.

**2. Answer card** — the answer sits on its own surface with a left accent border and
a `verified` marker in the corner. Figures render in JetBrains Mono so digits align
and cannot be confused with prose. This visually separates *what the filing says*
from any surrounding commentary.

**3. Evidence panel** — the right rail, three stacked sections:

```text
  ┌─ CITED PAGE ──────────────────┐   The exact snippet the verifier matched,
  │ 3M_2018_10K · page 60 of 134  │   highlighted inside its surrounding page
  │ ─────────────────────────────  │   text, so the figure is read in context
  │ …Purchases of property, plant  │   rather than out of it.
  │   and equipment ▸(1,577)…      │
  └───────────────────────────────┘
  ┌─ WHY THIS PAGE ───────────────┐   The five retrieved pages with fused,
  │ ★ p60  fused .94 bm25 .81 v .92│   BM25 and vector scores; the cited one
  │   p46  fused .71 bm25 .44 v .77│   starred. Turns retrieval from a black
  │   p39  fused .66 …             │   box into something an analyst can audit.
  └───────────────────────────────┘
  ┌─ VERIFICATION ────────────────┐   What the verifier actually checked.
  │ ✓ cited page was retrieved     │   This is the trust surface: it shows the
  │ ✓ figure traced to page text   │   guardrails ran, not just that they exist.
  │ ✓ snippet found on page        │
  └───────────────────────────────┘
```

**4. Decline card** — a distinct, calm surface. Not red, not an error:

```text
  ┌────────────────────────────────────────────────┐
  │  ⊘  Not found in this filing                   │
  │                                                │
  │  The evidence for this question is not in       │
  │  3M_2018_10K, or is not strong enough to cite.  │
  │                                                │
  │  Searched pages 86, 1, 43, 104, 105            │
  │  Reason: the model judged the excerpts          │
  │          insufficient                           │
  └────────────────────────────────────────────────┘
```

Showing *which pages were searched* is what makes a decline trustworthy rather than
lazy — the analyst can see the system looked, and where.

---

## 6. Design language

**Colour.** Neutral slate canvas, one indigo accent, semantic colours reserved for
state so they never decorate: `verified` emerald, `declined` amber, `failed` rose,
`building` blue. Light and dark themes from the same token set; dark is the default
for a tool people stare at all day.

**Type.** Inter for UI. **JetBrains Mono for every financial figure, page number and
snippet** — misreading `1,577` as `1.577` is the exact error this product exists to
prevent, and a monospace face with tabular figures makes that misreading harder.

**Space.** 8px scale. Generous line-height in evidence blocks (1.7) because they are
read closely, tighter in navigation.

**Motion.** Short (150–200ms) and functional: panel slide, badge pulse while building,
message enter. `prefers-reduced-motion` respected throughout.

**Accessibility.** Radix primitives give keyboard and screen-reader behaviour for free.
Beyond that: visible focus rings, `aria-live="polite"` on the thinking indicator and
job progress, AA contrast in both themes, full keyboard path through ask → read
evidence → open page.

---

## 7. API work required

### 7.1 Existing endpoints that change

| Endpoint | Change | Why |
|---|---|---|
| *all except* `/health`, `/auth/*` | Require `Authorization: Bearer` | Authentication |
| `GET /filings` | `indexed: bool` → `bm25: {…}` + `vector: {…}` objects | Two badges need two states |
| `GET /filings/{doc}/status` | Add `phase_started_at`, `queued_position` | Honest progress bar |
| `POST /chat` | Accept `conversation_id`; return `message_id`, `conversation_id`, `latency_ms` | Chat history |
| `POST /chat` | `retrieved_pages: int[]` → `retrieval: [{page, rank, fused_score, bm25_score, vector_score, cited}]` | The "why this page" panel. `ScoredPage` already carries these; they are dropped at the schema boundary today |
| `POST /filings` | Record uploader + original filename in Postgres | Attribution in the library |

### 7.2 New endpoints

**Auth**
```
POST   /api/v1/auth/login      {username, password} → {access_token, expires_in, user}
GET    /api/v1/auth/me         → {id, username, display_name, role}
POST   /api/v1/auth/logout     (token revocation list; client also drops it)
```

**Provider settings**
```
GET    /api/v1/settings/providers        → chat + embedding config, keys masked
PUT    /api/v1/settings/providers        → update (partial); returns masked
POST   /api/v1/settings/providers/test   {target: "chat"|"embedding"}
                                         → {ok, latency_ms, model, detail}
GET    /api/v1/settings/retrieval        → top_k, weights, rrf settings
PUT    /api/v1/settings/retrieval
```

**Conversations**
```
GET    /api/v1/conversations?doc_name=&limit=&cursor=
POST   /api/v1/conversations             {doc_name, title?}
GET    /api/v1/conversations/{id}        → conversation + messages + evidence
PATCH  /api/v1/conversations/{id}        {title}
DELETE /api/v1/conversations/{id}
```

**Filings**
```
GET    /api/v1/filings/{doc}             → detail: both index metadata blocks
POST   /api/v1/filings/{doc}/reindex     {targets: ["bm25","vector"]} → job
DELETE /api/v1/filings/{doc}             → drop indices
GET    /api/v1/filings/{doc}/pages/{n}   → {page, display_page, text, char_count}
POST   /api/v1/filings/reindex-all       → bulk job (after an embedding-model change)
```
`GET /filings/{doc}/pages/{n}` is what powers the Page Viewer — showing the cited
snippet inside its full page is the difference between a citation and a proof.

**Jobs**
```
GET    /api/v1/jobs?status=&limit=       → activity feed
```

### 7.3 Backend changes behind those endpoints

1. **Postgres + SQLAlchemy 2.0 + Alembic.** Sync engine with `psycopg3`; route handlers
   stay plain `def` so FastAPI runs them in its threadpool. Mixing an async driver with
   the synchronous QA pipeline would buy nothing and cost clarity.

2. **Move `IndexingJobManager` state into Postgres.** Today it is in-process, so job
   history dies on restart. The table becomes the source of truth; the thread pool
   stays as the executor.

3. **Runtime provider configuration.** `get_settings()` is `@lru_cache`d at import, so
   it cannot serve editable settings. Add a `ProviderResolver` that reads Postgres and
   falls back to env, then inject clients rather than letting them self-construct:
   `QuestionAnsweringService(chat_client=…)`, `VectorIndexBuilder(embedding_client=…)`,
   `HybridSearcher(vector_searcher=VectorSearcher(embedding_client=…))`.
   **All three constructors already accept injection — no core rewrite is needed.**

4. **`load_metadata(doc_name)` on both index stores.** The library screen needs page
   count, model and parser version for 78 filings; today the only way to read metadata
   is `load()`, which deserialises the entire pickle and the full vector array. This is
   a small, obviously-correct addition and the library is unusable without it.

5. **Encrypt provider API keys at rest** (Fernet, key from `APP_SECRET_KEY`) and never
   return them — masked only.

6. **Password hashing** with `passlib[bcrypt]`; JWT via `python-jose`. Demo user seeded
   by an Alembic data migration.

7. **Expose per-hit retrieval scores** in `ChatResponse` (schema-only change).

---

## 8. Database schema

```sql
users              id, username⚿, email, password_hash, display_name, role, created_at
provider_settings  id, scope, chat_base_url, chat_model, chat_api_key_enc,
                   embedding_base_url, embedding_model, embedding_api_key_enc,
                   updated_by → users, updated_at
retrieval_settings id, scope, top_k, bm25_weight, vector_weight, rrf_weight,
                   candidate_pool, updated_at
filings            doc_name⚿, original_filename, size_bytes, source_path,
                   uploaded_by → users, uploaded_at
indexing_jobs      id, doc_name, targets[], status, page_count, error,
                   budget_seconds, created_by, created_at, started_at, finished_at
conversations      id, user_id → users, doc_name, title, created_at, updated_at
messages           id, conversation_id → conversations (cascade), role, content,
                   created_at, found, page, evidence_snippet, retrieval jsonb,
                   abstention_reason, latency_ms, model
```

Indices on `conversations(user_id, updated_at desc)`, `messages(conversation_id, created_at)`,
`indexing_jobs(doc_name, created_at desc)`.

**The index artefacts stay on the filesystem.** Postgres stores *metadata and product
state*; the BM25 pickles and vector `.npz` files remain under `storage/` on a volume.
Moving hundreds of megabytes of float arrays into Postgres would buy nothing and make
every search slower.

---

## 9. Docker Compose

```text
                      ┌──────────────┐
  browser ─── :3000 ──│  ui (nginx)  │── /api/* proxy ──┐
                      └──────────────┘                  │
                                                        ▼
                      ┌──────────────┐          ┌──────────────┐
                      │  db (pg16)   │◀─────────│ api (uvicorn)│
                      └──────┬───────┘          └──────┬───────┘
                             │                         │
                        [pgdata]              [filings/] [storage/]
```

`docker-compose.yml` services:

| Service | Image / build | Notes |
|---|---|---|
| `db` | `postgres:16-alpine` | `pgdata` volume, `pg_isready` healthcheck |
| `migrate` | api image, `alembic upgrade head` | one-shot; `depends_on: db healthy` |
| `api` | `./` → `docker/api.Dockerfile` | `depends_on: migrate completed_successfully`; healthcheck on `/api/v1/health`; mounts `filings/` and `storage/` |
| `ui` | `./ui` → multi-stage node→nginx | serves the SPA, proxies `/api` to `api:8000` |

- `docker-compose.override.yml` for development: Vite dev server with HMR, uvicorn
  `--reload`, source bind-mounted. `docker compose up` gives hot reload; explicitly
  passing `-f docker-compose.yml` gives the production build.
- Secrets and provider defaults come from a root `.env` (git-ignored) with a committed
  `.env.example`.
- The UI container talks to `api` over the compose network, so **no API URL is baked
  into the JavaScript bundle** — the frontend always calls same-origin `/api`, which
  also removes CORS from the deployed path entirely.

---

## 10. Delivery phases

| Phase | Deliverable | Exit criterion |
|---|---|---|
| **0** | Compose stack + Postgres + Alembic + auth | `docker compose up` → log in as demo, `/health` green |
| **1** | App shell, filing library, add-filing + live job status | Upload a filing, watch it reach `ready`, both badges correct |
| **2** | Chat + answer card + evidence panel | Ask a question, get a cited answer and a page-level proof |
| **3** | Conversations, history sidebar, decline card | Reload the browser and the thread is intact |
| **4** | Settings: providers, connection test, reindex warning | Change a model from the UI and see it take effect |
| **5** | Polish: dark mode, empty/error/loading states, keyboard paths, a11y pass | — |

Phases 1 and 2 are the graded surfaces; everything else supports them.

---

## 11. Decisions and risks

**Decided**

- *One filing per conversation.* Citations are only checkable against a named document.
- *No token streaming.* Verification precedes display; see §1.
- *Two index badges, not one.* They are two artefacts that fail independently.
- *Index files stay on disk, Postgres holds product state.*
- *Same-origin `/api` via the nginx proxy.* No bundled API URL, no CORS in production.

**Risks**

| Risk | Mitigation |
|---|---|
| Changing the embedding model silently invalidates 78 indices | Explicit warning + impact review + bulk reindex before the setting is saved |
| Indexing a large 10-K may approach the 10-minute budget | Progress bar is drawn against `budget_seconds`; the API already flags `over_budget` |
| Demo auth mistaken for real auth | Label it in the UI and the README; short token lifetime; single seeded account |
| Provider keys entered in the UI are secrets | Encrypted at rest, masked in every response, never logged |
| First `docker compose up` embeds nothing — an empty library reads as broken | Ship an onboarding empty state that points at "Add filing"; optionally mount existing `storage/` so the 78 indices are there on first run |

---

## 12. Open questions for you

1. **Multi-user or single-tenant?** Are conversations private per user, or does the whole
   team see one shared history? Changes the queries and the sidebar.
2. **Should provider settings be global or per-user?** Global is simpler and matches "the
   firm configures its endpoints"; per-user allows a reviewer to try their own key.
3. **Mount the existing `storage/` into the container**, so the stack starts with all 78
   filings already searchable? Recommended for the live session.
4. **Retrieval settings in the UI** — worth exposing, given we know the current fusion
   config is costing recall, or keep the surface to providers only?
