# Running the stack in Docker

Four services, one command.

```mermaid
flowchart LR
    B([browser]) -->|":4006"| UI[ui · nginx]
    UI -->|"/api/*"| API[api · uvicorn]
    API --> ST[("filings/ storage/<br/>mounted from your machine")]
    API --> DB[(db · postgres)]
    MG[migrate] -.->|"runs once,<br/>then exits"| DB
    MG -.->|api waits for it| API
```

```bash
cp .env.example .env      # then fill in your provider keys
docker compose -f docker-compose.yml up --build
```

The app is at **<http://localhost:4006>**.

The API is **not** published to your machine. The browser reaches it through
nginx, same-origin, so nothing needs CORS and no API host is baked into the
JavaScript bundle.

`docker compose up` **without** `-f` also loads `docker-compose.override.yml`,
which swaps both app services for hot-reloading development servers.

> ⚠️ **A `restart` is not enough after changing code.** It reuses the existing
> images. Use `up --build -d` — and `up --build -d api` if only Python changed.

## The database

`db` is `postgres:16-alpine` with a `pgdata` volume, reachable only inside the
compose network. It holds **product state** — chat history today, auth
tomorrow — never index artefacts: the BM25 pickles and vector `.npz` files stay
under `storage/` on a bind mount, because Postgres storing hundreds of
megabytes of float arrays would slow every search and buy nothing.

`migrate` runs Alembic's `upgrade head` against a healthy `db` and exits; the
API starts only after it completes (`service_completed_successfully`), so a
fresh clone boots with a migrated schema. Add a migration by editing the models
in `src/analyst_copilot/api/db/` and generating one:

```bash
DATABASE_URL=postgresql+psycopg://analyst:analyst@localhost:5432/analyst \
  alembic revision --autogenerate -m "describe the change"
```

Outside the compose stack the database is optional: with `DATABASE_URL` unset
the API answers questions normally but records no history, and
`/conversations` responds 503 `database_unavailable`.

---

## The images

| | Base | Size | Notes |
|---|---|---|---|
| `api` | `python:3.12-slim-bookworm` | 523 MB | Two-stage; the toolchain stays in the builder |
| `ui` | `nginx:1.27-alpine` | 78 MB | Two-stage; node only exists at build time |

**The api build is two-stage for a specific reason.** The parsers pull in
`pdfplumber → pdfminer.six → cryptography`, and `lxml`. All have wheels for
amd64 and arm64, but if one is ever missing for a platform, pip falls back to
compiling — which needs a toolchain. The builder has `build-essential` so that
fallback works; the runtime does not, so ~250 MB of compilers never ship.

**The ui build runs `tsc -b` before `vite build`**, because that is what
`npm run build` does. A type error fails the image rather than producing a
bundle nobody typechecked.

**The build context is 3.2 MB, not 830 MB.** `.dockerignore` excludes the four
directories that dominate this repo — `filings/` (344 MB), `.venv/` (266 MB),
`ui/node_modules/` (168 MB), `.git/` (40 MB). The corpus is excluded on purpose:
it is data, it is mounted at runtime, and baking it into a layer would make
every image rebuild carry a third of a gigabyte of 10-Ks.

---

## Configuration

Everything comes from `.env` at run time via `env_file`. **`.env` is excluded
from the build context**, so provider keys are never written into an image
layer where anyone with the image can read them.

Two settings the container overrides:

| Setting | Why |
|---|---|
| `API_HOST=0.0.0.0` | The application default is `127.0.0.1`, which is right on a laptop and unreachable inside a container |
| `API_CORS_ORIGINS=[]` | nginx makes the browser's requests same-origin, so the wildcard default is unnecessary |

**A provider on the host** — Ollama, typically — is not on the container's
`localhost`. `docker-compose.yml` maps `host.docker.internal`, so:

```env
EMBEDDING_BASE_URL=http://host.docker.internal:11434/v1
```

---

## nginx

Two directives are not defaults and both matter.

**`client_max_body_size 64m`.** A filer's own PDF of a 10-K runs well past
nginx's 1 MB default. Without this, an upload the API would have accepted dies
at the proxy with a 413 the analyst cannot act on. Keep it in step with
`API_MAX_UPLOAD_BYTES`.

**`proxy_read_timeout 300s`.** A question is answered synchronously — retrieval,
then a chat completion whose own client timeout is 120 s, then verification.
The 60 s default would cut correct answers off mid-flight.

`proxy_request_buffering off` streams uploads through rather than spooling
64 MB to disk before the API sees a byte; the API enforces its own cap as the
bytes arrive, and cannot do that if nginx buffers first.

Client-side routes (`/filings`, `/chat`) fall through to `index.html`. Hashed
assets under `/assets/` are immutable-cached for a year; `index.html` is never
cached, because it is the one filename that does not change.

---

## Volumes

```yaml
- ./filings:/app/filings     # uploaded documents
- ./storage:/app/storage     # Markdown, BM25 and vector indices
```

Bind mounts rather than named volumes, on purpose: `storage/` represents hours
of embedding and `filings/` holds documents an analyst added, and both should
survive `docker compose down -v` and be readable without a container.

**On Linux**, the image runs as uid 10001 and a bind mount keeps the host's
ownership, so the container may not be able to write. `docker-compose.yml` has
a commented `user:` line for that:

```yaml
user: "${UID:-1000}:${GID:-1000}"
```

macOS and Windows do not need it — Docker Desktop's file sharing is
uid-agnostic.

---

## Development

`docker compose up` (without `-f`) also loads `docker-compose.override.yml`,
which replaces both services with hot-reloading dev servers:

- **api** — `uvicorn --reload` over a read-only bind mount of `src/`
- **ui** — the Vite dev server with HMR on <http://localhost:5173>, with
  `VITE_API_TARGET=http://api:8000` so its proxy finds the API on the compose
  network

```bash
docker compose up                          # development, hot reload
docker compose -f docker-compose.yml up    # the built production images
```

The ui dev service mounts `./ui` but keeps `/app/node_modules` as an anonymous
volume, so the container's Linux-built modules are not shadowed by the host's
darwin ones.

---

## Health

Both services have healthchecks, and `ui` waits for `api` to be **healthy**, not
merely started. That ordering is load-bearing: nginx resolves the name `api`
once at startup, and if it starts before the API exists it serves 502s until
something restarts it.

```bash
docker compose ps                          # STATUS shows (healthy)
docker compose logs -f api
curl http://localhost:3000/api/v1/health
```

The api healthcheck calls the endpoint with `urllib` from the interpreter that
is already in the image, rather than adding ~10 MB of `curl` to fetch one URL.

---

## Verified

Against the built images, on this stack:

```
/            -> 200        /filings -> 200 (SPA fallback)   /chat -> 200
/api/v1/health      -> {"status":"ok", ...}
/api/v1/collections -> both filings visible from the mounted storage/
chat through nginx  -> cited BOEING_2022_10K page_index 112 (gold: 112)
3 MB upload         -> 202, rejected in the body by type — not a 413 at the proxy
migrate             -> alembic upgrade head -> 0001_initial, exits 0
conversations       -> create + chat with conversation_id persisted; history
                       survives `docker compose restart api`; rendered by the
                       UI after a full page reload
```
