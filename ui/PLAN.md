# Analyst Copilot — Frontend Plan

**Status:** the React app is built and running against the live API. A **filing**
is a named set of documents: create one, add documents of any supported format by
upload or by URL, and ask questions of the whole filing. The per-document library
screen is gone (§4.4). Chat history is in Postgres; what remains of the
persistence and deployment layer is real auth — the stack (`db`, `migrate`, `api`,
`ui`) is built and running.
**Scope:** a React application in `ui/`, a Postgres-backed API, and a Docker Compose
stack that runs the whole product.

See [§0 Where we are](#0-where-we-are) for done vs remaining.

---

## 0. Where we are

The app runs today: `npm run dev` in `ui/` against `scripts/serve_api.py`, and every
screen is wired to real data. What is missing is everything that has to survive a
restart or a second machine.

### Done

| Area | What exists |
|---|---|
| **Scaffold** | Vite + React 18 + TypeScript, path aliases, `tsc --noEmit` clean, 115 kB gzipped build |
| **Design system** | Token-only colour system (no hex in components), light + dark from one set, Inter + JetBrains Mono, motion with `prefers-reduced-motion` |
| **Primitives** | Button, Badge, Card, Input, Skeleton, Tooltip, Toast, Modal, Sheet, EmptyState — hand-written, all restylable |
| **API layer** | Typed `fetch` client, `ApiError` with codes, auth-header plumbing, TanStack Query hooks |
| **Login** | Demo auth with one-click entry, labelled in-UI as not a security boundary |
| **App shell** | Persistent rail ≥lg, drawer below, conversation history grouped by date, theme toggle |
| **Chat** | Filing picker showing per-index state, composer with suggestions and Enter/Shift+Enter, staged thinking indicator, answer card, decline card, error card |
| **Evidence** | Citation chip · answer card · cited page with **show-full-page** · retrieval trace with per-retriever score bars · verification strip · **page viewer modal** with both retrievers' scores and the embedding boundary drawn in the text |
| **Filings** | Dropzone with client-side type/size checks, job progress against the 600 s budget, filters, search, table with the two independent badges |
| **Filing detail** | Side-by-side BM25 / Embeddings metadata cards |
| **Settings** | Live provider readout (read-only) + the embedding-model invalidation warning |

**API changes already shipped** (`939e662`, `ca32f8d`):

- `GET /filings` reports `bm25` and `vector` state independently, with model, dimensions, parser version, size and build time
- `POST /chat` returns `retrieval[]` with rank, fused, BM25 and vector scores, and `cited`
- `GET /filings/{doc}/pages/{n}` returns page text, `char_count`, `embedded_chars`, `truncated`
- `load_metadata`, `is_stale`, `load_pages` on both index stores — 78 filings summarised in 0.08 s

### Remaining

Ordered by what blocks what.

| # | Work | Blocks |
|---|---|---|
| ~~R0a~~ | ~~Multi-format upload~~ — **done**. `AddDocumentsDropzone` accepts PDF / HTML / Word / Excel / CSV / Markdown, many at once, with magic-byte sniffing before a 64 MB file crosses the wire; `FetchByUrl` adds one by URL | — |
| ~~R0c~~ | ~~Non-page citations~~ — **done**. Every surface reads `evidence.label` / `hit.label`; nothing formats `page N` locally | — |
| ~~R0d~~ | ~~Adjusted-location disclosure~~ — **done**. `LocationNote` states it when the citation moved, as a note rather than a warning | — |
| ~~R0b~~ | ~~Per-document parsing progress~~ | — |
| ~~R0e~~ | ~~Markdown page viewer~~ | — |
| ~~R0f~~ | ~~Richer failed-document states~~ | — |
| ~~R1~~ | ~~Docker Compose: `db`, `migrate`, `api`, `ui` (nginx)~~ — **done**. `postgres:16-alpine` + a one-shot `alembic upgrade head` that the API waits for; `filings/` and `storage/` bind-mounted per §12 Q3 | — |
| ~~R2~~ | ~~Postgres + SQLAlchemy 2.0 + Alembic~~ — **done**. Schema per §8 (minus `doc_name`, renamed `collection` to match the filing model); demo users seeded by the initial migration | R3, R5, R6 |
| **R3** | **Real auth**: `/auth/login`, `/auth/me`, `/auth/logout`; bcrypt, JWT, seeded demo user. Multi-user per §12 Q1 | Replaces the localStorage session |
| ~~R4~~ | ~~Conversations: the five endpoints in §7.2, scoped per user~~ — **done**. `POST /chat` records the exchange when given a `conversation_id` and returns `message_id` / `user_message_id` / `latency_ms`; the UI's `conversations.store.ts` is now API-backed, history survives restarts and is per-user | — |
| **R5** | **Provider settings**: GET/PUT/test, global scope per §12 Q2, keys encrypted at rest and masked in responses | Makes `/settings` writable |
| **R6** | **Job persistence**: move `IndexingJobManager` state into Postgres; `GET /jobs` feed | Job history surviving restart |
| **R7** | **Reindex**: `POST /filings/{doc}/reindex`, `reindex-all`, `DELETE /filings/{doc}` | The bulk-rebuild path after an embedding-model change |
| ~~R8~~ | ~~Chat threading fields~~ — **done** alongside R4 | — |
| **R9** | **Frontend tests**: Vitest + Testing Library + MSW against the real contract | — |
| **R10** | **Polish**: full keyboard path, a11y audit, error/empty states on the remaining screens | — |

**Explicitly not doing:** retrieval settings in the UI (§12 Q4 — ship the recommended
config, do not expose the weights).

### The gap that matters

Auth is still a **localStorage-backed adapter** (`auth.store.ts`). Chat history
is not: it now lives in Postgres behind the `/conversations` endpoints, so it
survives a restart, a different browser, and is private per user (R4 landed;
R3 is the remaining swap). The UI is finished; the product is one auth
endpoint from complete.

---

## 1. What we are building

The backend answers analyst questions over one SEC filing and cites the page, or
declines. `AGENTS.md` grades a **product**, and the four graded surfaces are:

| Requirement                                                   | Where it lands                       |
| ------------------------------------------------------------- | ------------------------------------ |
| "Add filing" control with visible processing status, ≤10 min | Filing Library screen                |
| A chat box for plain-English questions                        | Chat workspace                       |
| Evidence — document and page — on every answer              | Evidence panel + inline citations    |
| The ability to decline, stated plainly                        | A distinct, deliberate decline state |

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

| Concern      | Choice                                     | Why                                                                    |
| ------------ | ------------------------------------------ | ---------------------------------------------------------------------- |
| Framework    | React 18 + TypeScript,**Vite**       | Fast builds, first-class TS, trivial to containerise                   |
| Routing      | React Router 6                             | Nested layouts fit the chat/library/settings split                     |
| Server state | **TanStack Query**                   | Polling job status, cache invalidation, retries — all the hard parts  |
| Client state | Zustand (small stores)                     | Auth session, UI prefs, active filing. No Redux ceremony               |
| Styling      | **Tailwind CSS** + shadcn/ui (Radix) | Accessible primitives we own the source of; consistent tokens          |
| Forms        | react-hook-form + zod                      | One schema validates the form and types the payload                    |
| HTTP         | Typed`fetch` wrapper (no axios)          | Small; interceptors we control for auth + error mapping                |
| Icons        | lucide-react                               | Consistent, tree-shakeable                                             |
| Dates        | date-fns                                   | Chat history grouping                                                  |
| Tests        | Vitest + Testing Library +**MSW**    | MSW lets every screen be tested against the real API contract, offline |
| Lint         | ESLint + Prettier +`tsc --noEmit` in CI  |                                                                        |

**Deliberately not used:** Next.js (no SSR need — this is an authenticated SPA behind
an API), Redux (overkill), a component library we cannot restyle (MUI/AntD both fight
a custom design language).

---

## 3. Directory layout

As built. `components/ui/` are hand-written primitives rather than a vendored
component library, so every surface stays restylable.

```text
ui/
├── PLAN.md                     ← this file
├── index.html
├── package.json / tsconfig.json / vite.config.ts / tailwind.config.ts
└── src/
    ├── main.tsx, App.tsx, router.tsx
    ├── api/
    │   ├── client.ts           fetch wrapper: auth header, error → ApiError
    │   ├── types.ts            hand-written mirrors of the API schemas
    │   └── endpoints/          collections.ts · chat.ts · pages.ts · health.ts
    ├── hooks/                  useCollections · usePage · useHealth
    ├── stores/                 auth.store · ui.store · conversations.store
    ├── components/
    │   ├── ui/                 Button Badge Card Input Skeleton Tooltip
    │   │                       Toast Modal Sheet EmptyState
    │   ├── layout/             AppShell · Sidebar
    │   ├── chat/               Composer · AnswerCard · DeclineCard
    │   │                       FilingPicker · ThinkingIndicator
    │   ├── evidence/           EvidencePanel · CitedPage · PageViewerModal
    │   │                       PageText · RetrievalTrace · VerificationStrip
    │   │                       CitationChip · LocationNote
    │   └── filings/            AddDocumentsDropzone · FetchByUrl
    │                           DocumentRow · JobProgress
    ├── pages/                  Login · Chat · Filings · Settings
    ├── lib/                    cn.ts · format.ts
    └── styles/                 globals.css (design tokens)
```

**Not yet present**, and listed in the original plan: `components/settings/`
(arrives with R5), and a test tree (R9).

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

### 4.3 `/filings` — the filing library and the "Add documents" control

```text
┌──────────────────────────────────────────────────────────────────────┐
│  Filings                                                             │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │ New filing [ Boeing 2020–2023            ]     [ + Create ]    │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  ▼ 3M multi-year               4 documents · all indexed  [Ask] [🗑] │
│    ┌──────────────────────────────────────────────────────────────┐  │
│    │  ⬆  Drop documents here — PDF · HTML · Word · Excel · CSV    │  │
│    │     Select several at once; each is indexed separately        │  │
│    └──────────────────────────────────────────────────────────────┘  │
│    ┌──────────────────────────────────────────────────────────────┐  │
│    │ ✓ ready   3M_2018_10K       HTML     134 pages           [×] │  │
│    │ ✓ ready   3M_2022_10K       HTML     131 pages           [×] │  │
│    │ ⟳ indexing segments         CSV        — tables          [×] │  │
│    │ ✕ failed  scan_2019         PDF        —                 [×] │  │
│    └──────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  ▶ Boeing 2022                 9 of 12 indexed            [Ask] [🗑] │
└──────────────────────────────────────────────────────────────────────┘
```

**A "filing" is a set of documents, not a file.** The product renamed folders to
filings: an analyst asks questions of *the Boeing 2022 filing*, which may hold the
10-K, two 10-Qs and a segment spreadsheet. The code still says `collections`,
because `filing` already names a single 10-K everywhere in the pipeline.

**Uploads always land in a filing.** A question is rarely about one file, so the
filing is the unit an analyst works with and the unit the upload targets. Documents
arrive by drag-and-drop or by URL.

**One progress row per document, not one per filing.** A filing of twelve documents
must say which one is slow and which has failed; a single bar covering all of them
says neither.

**Only the open filing polls.** Twelve collapsed filings polling their jobs would be
twelve requests a second for progress nobody is watching.

**`9 of 12 indexed` is shown, not hidden.** A filing is searchable as soon as one
document is ready — blocking on the slowest member helps nobody — but an analyst
asking against a partly-built filing should know the answer may not have seen
everything yet.

**The size column counts what the document actually has**: `134 pages` for a filing,
`4 sheets` for a workbook, `— tables` for a CSV still indexing. A workbook does not
have four pages, and a row that claims it does teaches the analyst to expect a page
number the citation will never give them.

### 4.4 Removed: the per-document library

There used to be a second screen listing every document indexed outside any
filing, with its own single-file "Add filing" control. It is gone, along with
the `/filings/:docName` detail view.

**Why.** Once a question is asked of a filing, a screen that lists loose
documents offers nothing an analyst can act on — its "Ask" button led to a chat
scope the API no longer accepts, and a button that goes nowhere is worse than no
button. Keeping both would also have meant teaching two mental models for the
same thing.

The backend endpoints it used (`GET/POST /api/v1/filings`) still exist, and
`POST /chat` still accepts a bare `doc_name` — that per-document path is what
`scripts/eval/` measures against. Nothing in the UI calls either.

**Two rules from that screen survive**, now applied to the document rows inside
a filing:

**"Units", not "Pages".** A row counts what the document actually has — `160
pages` for a PDF, `4 sheets` for a workbook, `12 parts` for a Word file with no
author page breaks. A workbook does not have four pages, and a row that claims
it does teaches the analyst to expect a page number the citation will never
give them.

**Type is shown because it changes what a citation means.** Two copies of the
same 10-K, one HTML and one PDF, paginate differently: measured across the
practice corpus, 15 of 62 documents disagree by one or two pages between the
filed HTML and the filer's own PDF. An analyst checking a citation against their
own copy needs to know which reading they are looking at.

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

### 5.0 Locations are named the way their source names them

Every surface that shows a location reads it from the API's `evidence.label`
rather than formatting `page N` itself. The backend already returns
`sheet 'Q4 Revenue'` for a workbook and `rows 402-601` for a block of CSV rows,
and `evidence.segment_kind` says which kind it is. A component that hardcodes
"page" is a bug on any non-paginated document.

### 5.0.1 When the citation moved, say so

The verifier is **evidence-first**: it finds which retrieved page actually
carries the evidence and cites that one, treating the page the model named as a
hint. `evidence.location_match` reports what happened:

| Value | Meaning | UI treatment |
|---|---|---|
| `exact` | The model's page carries the evidence | Nothing. This is the normal case |
| `adjusted` | A neighbouring page does; the citation moved there | Quiet note under the citation: *"located on page 60 — the model cited 61"* |
| `relocated` | A distant page carries it, word for word | Same note, and the retrieval trace marks both pages |
| `inferred` | The model named no page; the best-supported one was used | Same note, worded as *"page inferred from the evidence"* |

This is a disclosure, not a warning. Nothing is wrong when a citation is
adjusted — the same document paginates differently as filed HTML and as the
filer's own PDF, and the system is landing on the page that actually holds the
proof. But an analyst who sees the answer say page 60 while the reasoning said
61 must be able to find out why in one glance, or the discrepancy reads as a
bug. `page_shift` carries the distance; `model_cited_page` carries the original.

**Do not** style this as an error, and do not hide it behind a tooltip. It goes
in the evidence panel as plain text at normal weight.

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

## 5A. The document-processing workflow

Every uploaded document takes the same path, whatever it is. The UI's job is to
make each step legible, and to fail in a way that tells the analyst what to do.

```text
  upload ─→ detect ─→ parse ─→ Markdown ─→ segment ─→ store ─→ embed ─→ ready
             │         │                     │                  │
             │         │                     │                  └─ "embedding 84/160"
             │         │                     └─ "160 pages" / "4 sheets"
             │         └─ the slow step on PDFs: ~57s for 160 pages
             └─ wrong type is caught here, before a byte is uploaded
```

### 5A.1 Upload

The dropzone accepts **PDF, HTML, Word, Excel, CSV, Markdown and text**. Two
checks run in the browser before anything is sent:

- **Extension** against the list the API advertises. Do not hardcode it —
  `allowed_suffixes` comes from the parser registry and grows when a parser is
  added.
- **Magic bytes** on the first 8 bytes via `File.slice()`. A `.pdf` that does not
  start with `%PDF-` is rejected in the browser with a specific message, because
  the same rejection from the server costs a 64 MB round trip first.

Size cap is 64 MB — a filer's own PDF of a 10-K runs well past the 32 MB the
HTML corpus needed.

### 5A.2 Processing status

The job payload already carries `status`, `elapsed_seconds`, `budget_seconds`
and `over_budget`. What the UI adds for multi-format is **which phase, and how
big the document turned out to be**:

```text
  ▶ NEWCO_2024_10K   📕 pdf

     ✓ detected        pdf
     ⣾ parsing         118 / 190 pages          0:41
       embedding       —
       ─────────────────────────────────────────────
       ████████░░░░░░░░░░░░░░░░  0:41 / 10:00
```

Parsing deserves its own line because on a PDF it is no longer instant. A
160-page 10-K takes ~57s to parse before embedding starts, and a progress bar
that sits at zero for a minute reads as a hang. The segment count is not known
until parsing begins, so the total appears mid-flight — show `— pages` until it
does rather than guessing.

Phase names come from `JobStatus`: `queued → parsing → embedding → saving →
ready | failed`.

### 5A.3 Page-level Markdown, visible

Parsing writes one Markdown file per segment under
`storage/markdown/{doc}/page-001.md`, and `GET /filings/{doc}/pages/{n}` returns
it as `markdown` alongside the indexed `text`.

The page viewer renders the Markdown — **tables as tables**. This is the single
highest-value debugging surface in the product: when a citation looks wrong, the
question is always "what did the system actually read on that page", and a
rendered financial statement answers it in one look where a wall of flattened
prose does not.

Show `label`, `segment_kind`, `source_format` and the existing `embedded_chars`
truncation boundary in the same view.

### 5A.4 Error handling

Four failures, four different things for the analyst to do. Collapsing them into
"upload failed" is the failure mode to avoid.

| What happened | Where caught | Message | Action offered |
|---|---|---|---|
| Type we do not parse | Browser, then `415` | "PNG files aren't supported. Try PDF, HTML, Word, Excel or CSV." | List the accepted types |
| Extension lies about contents | Browser, then `415` | "This file is named .pdf but isn't one." | Re-pick the file |
| Too large | Browser, then `413` | "68 MB exceeds the 64 MB limit." | — |
| Parse produced nothing | Job → `failed` | "We read the file but found no text. Scanned PDFs need OCR, which this system doesn't do." | Remove · try another copy |
| Parser crashed | Job → `failed` with `error` | Show the real error, monospace, copyable | Retry · Remove |
| Embedding failed | Job → `failed`, BM25 badge still `ready` | "Text search is ready; semantic search failed." | Retry embedding only |

The last row matters and is easy to miss: BM25 and embeddings fail
independently, and a document with a lexical index and no vectors is **partially
usable**. The library already models this with two badges; the error states have
to respect it rather than marking the whole document dead.

**Scanned PDFs are the predictable support question.** There is no OCR in the
pipeline, so an image-only PDF parses to zero characters and fails. Say that in
the message; do not let it present as a generic parse error.

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

✅ = shipped. Everything else is outstanding.

| Endpoint                                | Change                                                                                                    | Why                                                                                                           |
| --------------------------------------- | --------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| *all except* `/health`, `/auth/*` | Require`Authorization: Bearer`                                                                          | Authentication                                                                                                |
| ✅ `GET /filings`                     | `indexed: bool` → `bm25: {…}` + `vector: {…}` objects                                            | Two badges need two states                                                                                    |
| `GET /filings/{doc}/status`           | Add`phase_started_at`, `queued_position`                                                              | Honest progress bar                                                                                           |
| `POST /chat`                          | Accept`conversation_id`; return `message_id`, `conversation_id`, `latency_ms`                     | Chat history                                                                                                  |
| ✅ `POST /chat`                       | `retrieved_pages: int[]` → `retrieval: [{page, rank, fused_score, bm25_score, vector_score, cited}]` | The "why this page" panel.`ScoredPage` already carries these; they are dropped at the schema boundary today |
| `POST /filings`                       | Record uploader + original filename in Postgres                                                           | Attribution in the library                                                                                    |
| ✅ `POST /filings`                    | Accepts every format in the parser registry, not just `.htm`/`.html`; the real suffix is preserved on disk so the registry can dispatch on it | Universal upload |
| ✅ `POST /chat`                       | `evidence` gains `label`, `segment_kind`, `location_match`, `model_cited_page`, `page_shift`             | Non-page citations, and disclosing an adjusted location (§5.0.1)                                              |
| ✅ `GET /filings/{doc}/pages/{n}`     | Adds `markdown`, `label`, `segment_kind`, `source_format`                                                 | The Markdown page viewer (§5A.3)                                                                              |
| `GET /filings`                        | Add `source_format` and `segment_kind` per document                                                       | The library's Type and Units columns. **Not yet shipped** — the UI cannot render §4.3 without it              |
| `GET /filings/{doc}/status`           | Add `source_format`, `segments_parsed`, `segments_total`                                                  | The parsing phase in §5A.2 has nothing to count without it                                                    |

### 7.2 New endpoints

All outstanding except the one marked shipped.

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
GET    /api/v1/filings/{doc}/pages/{n}   → text, char_count, embedded_chars, truncated   ✅ SHIPPED
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

| Service     | Image / build                       | Notes                                                                                                                   |
| ----------- | ----------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `db`      | `postgres:16-alpine`              | `pgdata` volume, `pg_isready` healthcheck                                                                           |
| `migrate` | api image,`alembic upgrade head`  | one-shot;`depends_on: db healthy`                                                                                     |
| `api`     | `./` → `docker/api.Dockerfile` | `depends_on: migrate completed_successfully`; healthcheck on `/api/v1/health`; mounts `filings/` and `storage/` |
| `ui`      | `./ui` → multi-stage node→nginx | serves the SPA, proxies`/api` to `api:8000`                                                                         |

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

| Phase | Deliverable | Status |
|---|---|---|
| **0** | Compose stack + Postgres + Alembic + auth | 🟨 **Partial** — stack, Postgres and Alembic done (R1–R2); real auth outstanding (R3) |
| **1** | Filing library, multi-file add, fetch-by-URL, per-document job status | ✅ **Done** — create a filing, add documents by drop or URL, watch each index |
| **2** | Chat + answer card + evidence panel | ✅ **Done** — filing-scoped questions, source-named citations, adjusted-location disclosure |
| **2b** | Markdown page viewer + richer document error states | ✅ **Done** |
| **3** | Conversations, history sidebar, decline card | ✅ **Done** — in Postgres (R4), surviving restarts, private per user |
| **4** | Settings: providers, connection test, reindex warning | 🟨 **Partial** — reads live config and warns; not writable (R5, R7) |
| **5** | Polish: dark mode, empty/error/loading states, keyboard paths, a11y pass | 🟨 **Partial** — themes, empty/loading/error states done; a11y audit outstanding (R10) |

**Phases 1 and 2 — the graded surfaces — are complete**, now in their filing form:
an analyst creates a filing, adds several documents of any supported format, and
asks the filing. Verified end to end against a live API on a filing holding two
10-Ks and two CSVs — the FY2018 question cited `3M_2018_10K` page 59 and the FY2022
question cited `3M_2022_10K` page 33, with pages from both filings in each retrieved
set, and a CSV question cited `table 'segments'` rather than inventing a page.

What remains is real auth and the two writable settings surfaces. The UI was
built first because it could be, against an API that already worked, and the
conversations adapter that used to hold history in localStorage has been
replaced by the `/conversations` API; `auth.store.ts` is the one adapter left.

---

## 11. Decisions and risks

**Decided**

- *One filing per conversation.* Citations are only checkable against a named document.
- *No token streaming.* Verification precedes display; see §1.
- *Two index badges, not one.* They are two artefacts that fail independently.
- *Index files stay on disk, Postgres holds product state.*
- *Same-origin `/api` via the nginx proxy.* No bundled API URL, no CORS in production.
- *Multi-user, conversations private per user.* (§12 Q1)
- *Provider settings are global*, not per-user — the firm configures its endpoints. (§12 Q2)
- *`storage/` is mounted into the container*, so the stack boots with all 78 filings
  searchable rather than showing an empty library. (§12 Q3)
- *Retrieval weights are not exposed in the UI.* Ship the measured configuration; a
  weights panel in front of a reviewer is a footgun, not a feature. (§12 Q4)

**Risks**

| Risk                                                                          | Mitigation                                                                                                                                 |
| ----------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| Changing the embedding model silently invalidates 78 indices                  | Explicit warning + impact review + bulk reindex before the setting is saved                                                                |
| Indexing a large 10-K may approach the 10-minute budget                       | Progress bar is drawn against`budget_seconds`; the API already flags `over_budget`                                                     |
| Demo auth mistaken for real auth                                              | Label it in the UI and the README; short token lifetime; single seeded account                                                             |
| Provider keys entered in the UI are secrets                                   | Encrypted at rest, masked in every response, never logged                                                                                  |
| First`docker compose up` embeds nothing — an empty library reads as broken | Ship an onboarding empty state that points at "Add filing"; optionally mount existing`storage/` so the 78 indices are there on first run |

---

## 12. Questions asked, and the answers given

1. **Multi-user or single-tenant?** Are conversations private per user, or does the whole
   team see one shared history? Changes the queries and the sidebar.
   Answer : Multiuser
2. **Should provider settings be global or per-user?** Global is simpler and matches "the
   firm configures its endpoints"; per-user allows a reviewer to try their own key.
   Answer: Global
3. **Mount the existing `storage/` into the container**, so the stack starts with all 78
   filings already searchable? Recommended for the live session.
   Answer : Yes Map It
4. **Retrieval settings in the UI** — worth exposing, given we know the current fusion
   config is costing recall, or keep the surface to providers only?
   Answer: Use recommended only

All four are settled and folded into §11. The recommended fusion configuration referred
to in Q4 has since been applied and measured — the rubric moved from **+1 to +7** across
the 136 practice questions when RRF was disabled. See
[docs/07-hybrid-retrieval.md](../docs/07-hybrid-retrieval.md).
