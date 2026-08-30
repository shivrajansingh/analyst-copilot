#!/usr/bin/env python3
"""
Batch: index filings one-by-one via Folder API, then ask questions per-doc in one thread.

Flow per document (in sorted order from data/filings):
  1. Create folder `POST /api/v1/collections` (idempotent)
  2. Upload file `POST /api/v1/collections/{folder}/documents` (multipart)
  3. Poll `GET /api/v1/collections/{folder}/jobs` until ready (budget 600s)
  4. Create conversation `POST /api/v1/conversations` pinned to folder
  5. For each question of that doc in data/questions-by-doc.json, call
     `POST /api/v1/chat` with same conversation_id (one thread per doc)
  6. Save each Q/A to answer/{doc_name}/{financebench_id}.md decorated

Usage:
  python scripts/run_batch_by_doc.py
  python scripts/run_batch_by_doc.py --limit 5
  python scripts/run_batch_by_doc.py --base-url https://analyst-copilot-stage.technicalheist.com --limit 10
  python scripts/run_batch_by_doc.py --answer-dir temp/answer-blind-checker
  python scripts/run_batch_by_doc.py --answer-dir temp/answer --filings-dir data/filings --questions data/questions-by-doc.json

Requires: Python 3.9+, no extra deps (uses urllib). Set base URL via --base-url or env ANALYST_BASE_URL.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FILINGS_DIR = PROJECT_ROOT / "data" / "filings"
DEFAULT_QUESTIONS = PROJECT_ROOT / "data" / "questions-by-doc.json"
DEFAULT_ANSWER_DIR = PROJECT_ROOT / "temp" / "answer"
DEFAULT_BASE_URL = os.environ.get("ANALYST_BASE_URL", "http://127.0.0.1:8000")

BUDGET_SECONDS = 600
POLL_INTERVAL = 10
TIMEOUT = 180


def http_json(method: str, url: str, body: Optional[dict] = None, headers: Optional[dict] = None, retries: int = 3) -> Tuple[int, dict]:
    data = None
    hdrs = {"Accept": "application/json", "User-Agent": "AnalystCopilot/1.0 (curl; +https://analyst-copilot-stage.technicalheist.com)"}
    if headers:
        hdrs.update(headers)
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    last_exc = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                raw = resp.read()
                status = resp.status
                text = raw.decode("utf-8") if raw else "{}"
                try:
                    js = json.loads(text) if text.strip() else {}
                except json.JSONDecodeError:
                    js = {"raw": text}
                if status in (403, 429, 500, 502, 503) and attempt < retries:
                    time.sleep(2 ** attempt + 1)
                    continue
                return status, js
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", errors="ignore")
            try:
                js = json.loads(raw) if raw.strip() else {}
            except json.JSONDecodeError:
                js = {"raw": raw, "error": str(e)}
            if e.code in (403, 429, 500, 502, 503) and attempt < retries:
                time.sleep(2 ** attempt + 1)
                last_exc = (e.code, js)
                continue
            return e.code, js
        except Exception as e:
            last_exc = (0, {"error": str(e)})
            if attempt < retries:
                time.sleep(2 ** attempt + 1)
                continue
            return 0, {"error": str(e)}
    if last_exc:
        return last_exc
    return 0, {"error": "retries exhausted"}


def http_multipart(url: str, file_path: Path, field_name: str = "files") -> Tuple[int, dict]:
    boundary = "----AnalystBoundary7MA4YWxkTrZu0gW"
    filename = file_path.name
    ctype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    body = bytearray()
    body.extend(f"--{boundary}\r\n".encode())
    body.extend(f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'.encode())
    body.extend(f"Content-Type: {ctype}\r\n\r\n".encode())
    body.extend(file_path.read_bytes())
    body.extend(f"\r\n--{boundary}--\r\n".encode())
    headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Accept": "application/json",
        "User-Agent": "AnalystCopilot/1.0 (curl; +https://analyst-copilot-stage.technicalheist.com)",
    }
    req = urllib.request.Request(url, data=bytes(body), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read().decode("utf-8")
            js = json.loads(raw) if raw.strip() else {}
            return resp.status, js
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="ignore")
        try:
            js = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            js = {"raw": raw}
        return e.code, js
    except Exception as e:
        return 0, {"error": str(e)}


def ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)


def sanitize_filename(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in s)[:120]


def load_questions_map(questions_path: Path) -> Dict[str, dict]:
    data = json.loads(questions_path.read_text(encoding="utf-8"))
    m = {}
    for entry in data:
        m[entry["doc_name"]] = entry
    return m


def create_folder(base_url: str, name: str, description: str = "") -> dict:
    url = f"{base_url.rstrip('/')}/api/v1/collections"
    status, js = http_json("POST", url, {"name": name, "description": description})
    if status not in (200, 201):
        # idempotent: 200 if exists, 201 if created; other codes are errors but folder may still exist
        # try get
        status2, js2 = http_json("GET", f"{url}/{urllib.parse.quote(name)}")
        if status2 == 200:
            return js2
        raise RuntimeError(f"create_folder {name} failed {status}: {js}")
    return js


def upload_to_folder(base_url: str, folder: str, file_path: Path) -> Tuple[str, dict]:
    url = f"{base_url.rstrip('/')}/api/v1/collections/{urllib.parse.quote(folder)}/documents"
    status, js = http_multipart(url, file_path, field_name="files")
    if status not in (200, 202):
        raise RuntimeError(f"upload {file_path.name} to {folder} failed {status}: {js}")
    # accepted[0]
    accepted = js.get("accepted") or []
    if not accepted:
        rejected = js.get("rejected") or []
        raise RuntimeError(f"upload rejected for {file_path.name}: {rejected or js}")
    job = accepted[0]
    return job.get("job_id", ""), js


def poll_jobs_until_ready(base_url: str, folder: str, job_id: str, timeout_s: int = BUDGET_SECONDS) -> dict:
    url_jobs = f"{base_url.rstrip('/')}/api/v1/collections/{urllib.parse.quote(folder)}/jobs"
    url_job = f"{base_url.rstrip('/')}/api/v1/jobs/{job_id}" if job_id else ""
    start = time.time()
    last_status = ""
    while time.time() - start < timeout_s + 30:
        # prefer per-job
        js = None
        if url_job:
            _, js = http_json("GET", url_job)
            last_status = js.get("status", "")
        else:
            _, arr = http_json("GET", url_jobs)
            if isinstance(arr, list) and arr:
                js = arr[0]
                last_status = js.get("status", "")
        if last_status == "ready":
            return js or {}
        if last_status == "failed":
            raise RuntimeError(f"indexing failed for {folder}: {js}")
        # also check collection summary searchable
        _, col = http_json("GET", f"{base_url.rstrip('/')}/api/v1/collections/{urllib.parse.quote(folder)}")
        if isinstance(col, dict) and col.get("searchable") and col.get("ready_count", 0) > 0:
            # still wait for job ready, but searchable is good sign
            pass
        time.sleep(POLL_INTERVAL)
    raise TimeoutError(f"poll timeout for {folder} last_status={last_status}")


def create_conversation(base_url: str, collection: str, title: str) -> str:
    url = f"{base_url.rstrip('/')}/api/v1/conversations"
    status, js = http_json("POST", url, {"collection": collection, "title": title})
    if status not in (200, 201):
        raise RuntimeError(f"create_conversation {collection} failed {status}: {js}")
    return js.get("id", "")


def chat_streaming(base_url: str, collection: str, question: str, conversation_id: Optional[str]) -> dict:
    url = f"{base_url.rstrip('/')}/api/v1/chat/stream"
    payload = {"collection": collection, "question": question}
    if conversation_id:
        payload["conversation_id"] = conversation_id
    data = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "User-Agent": "AnalystCopilot/1.0 (curl; +https://analyst-copilot-stage.technicalheist.com)",
    }
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            answer_data = None
            error_data = None
            last_event = None
            for raw_line in resp:
                line = raw_line.decode("utf-8", errors="ignore").rstrip("\r\n")
                if not line:
                    continue
                if line.startswith(":"):
                    continue  # keepalive
                if line.startswith("event:"):
                    last_event = line[6:].strip()
                    continue
                if line.startswith("data:"):
                    data_str = line[5:].strip()
                    if not data_str:
                        continue
                    try:
                        payload_json = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    if last_event == "answer" and isinstance(payload_json, dict) and "found" in payload_json:
                        answer_data = payload_json
                        # answer is final, can return after stream ends but we can break early
                        # continue to drain a bit then break
                        break
                    elif last_event == "error":
                        error_data = payload_json
                    elif last_event == "cancelled":
                        error_data = payload_json
                    # stage/trace/run events are ignored
                    last_event = None
            if answer_data is not None:
                return answer_data
            if error_data is not None:
                raise RuntimeError(f"chat stream error: {error_data}")
            raise RuntimeError("chat stream: no answer event received")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"chat stream failed {e.code}: {raw}") from e
    except Exception as e:
        raise RuntimeError(f"chat stream exception: {e}") from e


def chat_blocking(base_url: str, collection: str, question: str, conversation_id: Optional[str]) -> dict:
    url = f"{base_url.rstrip('/')}/api/v1/chat"
    payload = {"collection": collection, "question": question}
    if conversation_id:
        payload["conversation_id"] = conversation_id
    status, js = http_json("POST", url, payload)
    if status == 409:
        # no indexed documents yet
        raise RuntimeError(f"chat 409 FilingNotIndexed for {collection}: {js}")
    if status == 524:
        # Cloudflare 120s proxy timeout — deep questions exceed blocking limit, use streaming
        print(f"    524 timeout, retrying via streaming for {collection}...", file=sys.stderr)
        time.sleep(5)
        return chat_streaming(base_url, collection, question, conversation_id)
    if status not in (200,):
        # also retry via streaming for 5xx if deep
        if status in (500, 502, 503) and js.get("cloudflare_error"):
            time.sleep(2)
            try:
                return chat_streaming(base_url, collection, question, conversation_id)
            except Exception:
                pass
        raise RuntimeError(f"chat failed {status}: {js}")
    return js


def health_model(base_url: str) -> Tuple[str, str]:
    _, js = http_json("GET", f"{base_url.rstrip('/')}/api/v1/health")
    return js.get("chat_model", ""), js.get("embedding_model", "")


def format_answer_md(
    doc_name: str,
    company: str,
    question: dict,
    chat_resp: dict,
    folder: str,
    conversation_id: str,
    health_chat: str,
    health_embed: str,
) -> str:
    q_text = question.get("question", "")
    fid = question.get("financebench_id", "")
    q_type = question.get("question_type", "")
    found = chat_resp.get("found")
    answer = chat_resp.get("answer", "")
    evidence = chat_resp.get("evidence")
    citations = chat_resp.get("citations") or []
    retrieval = chat_resp.get("retrieval") or []
    usage = chat_resp.get("usage") or {}
    validation = chat_resp.get("validation") or ""
    mode = chat_resp.get("mode", "")
    latency = chat_resp.get("latency_ms", "")
    models = usage.get("models") or []
    model_used = ", ".join(models) if models else f"{health_chat} + {health_embed}".strip(" +")
    if not model_used:
        model_used = health_chat or "(unknown)"

    # evidence block
    if evidence:
        ev_lines = [
            f"- **Document:** `{evidence.get('doc_name','')}`",
            f"- **Page:** `{evidence.get('page','')}` (0-based) → **display_page:** `{evidence.get('display_page','')}` (`{evidence.get('label','')}`)",
            f"- **Kind:** `{evidence.get('segment_kind','')}` | **match:** `{evidence.get('location_match','')}` (shift {evidence.get('page_shift',0)})",
            f"- **Snippet:**",
            f"  > {evidence.get('snippet','').replace(chr(10), ' ')}",
        ]
        ev_md = "\n".join(ev_lines)
    else:
        ev_md = "_No evidence — model returned `not found in this filing`._"

    # citations table
    cit_md = ""
    if citations:
        cit_md = "| # | doc | page | label | snippet |\n|---|---|---|---|---|\n"
        for i, c in enumerate(citations, 1):
            sn = (c.get("snippet","") or "")[:120].replace("|","\\|").replace("\n"," ")
            cit_md += f"| {i} | {c.get('doc_name','')} | {c.get('display_page','')} | {c.get('label','')} | {sn} |\n"
    else:
        cit_md = "_No citations._"

    ret_md = ""
    if retrieval:
        ret_md = "| rank | doc | page | fused | bm25 | vector | cited |\n|---|---|---|---|---|---|---|\n"
        for r in retrieval[:5]:
            ret_md += f"| {r.get('rank','')} | {r.get('doc_name','')} | {r.get('display_page','')} | {r.get('fused_score','')} | {r.get('bm25_score','')} | {r.get('vector_score','')} | {r.get('cited', False)} |\n"
    else:
        ret_md = "_No retrieval trace (deep abstention)._"

    usage_md = ""
    if usage:
        usage_md = f"- **Tokens:** in {usage.get('input_tokens','')} / out {usage.get('output_tokens','')} / total {usage.get('total_tokens','')} (cached {usage.get('cached_input_tokens',0)})\n"
        usage_md += f"- **Calls:** {usage.get('calls','')} | **Cost USD:** {usage.get('cost_usd','')} | **Priced:** {usage.get('priced','')}\n"
        stages = usage.get("stages") or []
        if stages:
            usage_md += "- **Stages:**\n"
            for s in stages:
                usage_md += f"  - `{s.get('stage','')}`: {s.get('label','')} — {s.get('input_tokens',0)}/{s.get('output_tokens',0)} tokens, models {s.get('models',[])}\n"
        by_model = usage.get("by_model") or []
        if by_model:
            usage_md += "- **By model:**\n"
            for m in by_model:
                usage_md += f"  - `{m.get('model','')}`: {m.get('input_tokens',0)}/{m.get('output_tokens',0)} tokens, cost {m.get('cost_usd','')}\n"
    else:
        usage_md = "_No usage._"

    md = f"""# {doc_name} — {fid}

**Company:** {company} | **Folder:** `{folder}` | **Type:** {q_type} | **Mode:** `{mode}` | **Latency:** {latency} ms
**Conversation:** `{conversation_id}` | **Found:** `{found}`

---

## QUESTION

> {q_text}

**ID:** `{fid}`

---

## ANSWER

{answer if answer else "_No answer_"}

---

## EVIDENCE

{ev_md}

**Validation:** {validation or "_none_"}

**Citations:**
{cit_md}

**Retrieval (top-5 hybrid):**
{ret_md}

---

## MODEL USED

**{model_used}**

- Health (GET /api/v1/health): chat `{health_chat}` + embedding `{health_embed}`
- This answer `usage.models`: `{models}`
- `mode` indicates tier: `fast` = hybrid retrieval + LLM + verifier; `deep` = read every page (shards) + synthesis; `conversational` = no doc read.

**Usage:**
{usage_md}

---

## RAW

<details><summary>Full ChatResponse JSON</summary>

```json
{json.dumps(chat_resp, indent=2, ensure_ascii=False)}
```

</details>

---

*Generated: {time.strftime("%Y-%m-%d %H:%M:%S %Z", time.gmtime())} | Folder `{folder}` | Doc `{doc_name}`*
"""
    return md


def main():
    parser = argparse.ArgumentParser(description="Index filings one-by-one via Folder API then ask questions per-doc in one thread.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="API base, e.g. https://analyst-copilot-stage.technicalheist.com")
    parser.add_argument("--filings-dir", default=str(DEFAULT_FILINGS_DIR), help="Dir with .htm/.pdf filings")
    parser.add_argument("--questions", default=str(DEFAULT_QUESTIONS), help="Path to questions-by-doc.json")
    parser.add_argument("--answer-dir", default=str(DEFAULT_ANSWER_DIR), help="Dir to write answer files")
    parser.add_argument("--limit", type=int, default=None, help="Stop after N questions total (default all)")
    parser.add_argument("--folder-prefix", default="", help="Optional prefix for folder names")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    filings_dir = Path(args.filings_dir)
    questions_path = Path(args.questions)
    answer_dir = Path(args.answer_dir)
    limit = args.limit

    if not filings_dir.exists():
        print(f"filings dir not found: {filings_dir}", file=sys.stderr)
        sys.exit(1)
    if not questions_path.exists():
        print(f"questions not found: {questions_path}", file=sys.stderr)
        sys.exit(1)

    ensure_dir(answer_dir)
    qmap = load_questions_map(questions_path)
    health_chat, health_embed = health_model(base_url)
    print(f"Health: chat={health_chat} embed={health_embed} base={base_url}")

    filings = sorted([p for p in filings_dir.iterdir() if p.is_file() and p.suffix.lower() in {".htm",".html",".pdf",".docx",".xlsx",".xlsm",".csv",".tsv",".md",".txt"}])
    print(f"Filings on disk: {len(filings)}  Q docs: {len(qmap)}  limit={limit or 'all'}")

    total_questions = 0
    total_docs = 0

    for fpath in filings:
        doc_name = fpath.stem  # e.g. 3M_2018_10K
        entry = qmap.get(doc_name)
        if not entry:
            print(f"Skip {doc_name}: no questions in {questions_path.name}")
            continue

        # respect global limit before starting new doc
        if limit is not None and total_questions >= limit:
            print(f"Limit {limit} reached, stopping.")
            break

        questions: List[dict] = entry.get("questions", []) or []
        if not questions:
            print(f"Skip {doc_name}: 0 questions")
            continue

        # remaining budget for this doc
        remaining = None if limit is None else max(0, limit - total_questions)
        if remaining is not None and remaining == 0:
            break
        # if this doc would exceed limit, slice
        ask_questions = questions[:remaining] if remaining is not None else questions

        company = entry.get("company", "")
        folder = f"{args.folder_prefix}{doc_name}" if args.folder_prefix else doc_name

        print(f"\n=== Doc {doc_name} ({company}) → folder {folder} : {len(ask_questions)}/{len(questions)} Qs ===")

        # 1. create folder
        try:
            col = create_folder(base_url, folder, description=f"Batch {doc_name} {company}")
            print(f"Folder {folder}: document_count={col.get('document_count')} ready={col.get('ready_count')} searchable={col.get('searchable')}")
        except Exception as e:
            print(f"  create_folder failed for {folder}: {e}", file=sys.stderr)
            continue

        # 2. upload (skip if already indexed)
        already_ready = False
        try:
            _, col_check = http_json("GET", f"{base_url.rstrip('/')}/api/v1/collections/{urllib.parse.quote(folder)}")
            if isinstance(col_check, dict) and col_check.get("searchable"):
                for d in col_check.get("documents", []) or []:
                    if d.get("doc_name") == doc_name and d.get("state") == "ready":
                        already_ready = True
                        print(f"  Skip upload — {doc_name} already indexed in {folder} (state ready, {d.get('segment_count')} pages)")
                        break
        except Exception:
            pass

        if already_ready:
            job = {"status": "ready", "page_count": None, "elapsed_seconds": 0}
        else:
            try:
                job_id, up_resp = upload_to_folder(base_url, folder, fpath)
                print(f"  Upload accepted job {job_id} status {up_resp.get('accepted',[{}])[0].get('status')}")
            except Exception as e:
                print(f"  upload failed for {doc_name}: {e}", file=sys.stderr)
                continue

            # 3. poll until ready
            try:
                job = poll_jobs_until_ready(base_url, folder, job_id, timeout_s=BUDGET_SECONDS)
                print(f"  Indexed {doc_name} → {job.get('status')} page_count={job.get('page_count')} elapsed={job.get('elapsed_seconds')}s")
            except Exception as e:
                print(f"  indexing failed/timeout for {doc_name}: {e}", file=sys.stderr)
                continue

        # 4. create conversation (one thread per doc)
        try:
            conv_id = create_conversation(base_url, folder, title=f"{doc_name} batch")
            print(f"  Conversation {conv_id} pinned to {folder}")
        except Exception as e:
            print(f"  create_conversation failed for {folder}: {e}", file=sys.stderr)
            conv_id = None  # still try chat without thread? but spec wants one thread
            # fallback: ask without conversation_id
            print("  proceeding without conversation_id")

        # 5. ask each question in same thread
        doc_answer_dir = answer_dir / sanitize_filename(doc_name)
        ensure_dir(doc_answer_dir)

        for idx, q in enumerate(ask_questions, 1):
            if limit is not None and total_questions >= limit:
                print(f"  limit {limit} reached inside doc {doc_name}")
                break
            q_text = q.get("question","")
            fid = q.get("financebench_id") or f"q{idx}"
            out_path = doc_answer_dir / f"{sanitize_filename(fid)}.md"
            if out_path.exists():
                try:
                    existing = out_path.read_text(encoding="utf-8", errors="ignore")
                    if "ERROR:" not in existing and "mode: `error`" not in existing:
                        print(f"  Q{total_questions+1} [{fid}] skip — already exists {out_path.name}")
                        total_questions += 1
                        continue
                    else:
                        print(f"  Q{total_questions+1} [{fid}] retry — previous error {out_path.name}")
                except Exception:
                    pass
            print(f"  Q{total_questions+1} [{fid}] {q_text[:80]}...")
            try:
                resp = chat_blocking(base_url, folder, q_text, conv_id)
            except Exception as e:
                print(f"    chat failed for {fid}: {e}", file=sys.stderr)
                # save failure stub
                resp = {"found": False, "answer": f"ERROR: {e}", "evidence": None, "usage": {}, "mode": "error", "question": q_text, "doc_name": doc_name, "collection": folder}

            # 6. save one file per question
            md = format_answer_md(doc_name, company, q, resp, folder, conv_id or "", health_chat, health_embed)
            out_path.write_text(md, encoding="utf-8")
            print(f"    → {out_path}  found={resp.get('found')} model={','.join((resp.get('usage') or {}).get('models') or []) or health_chat}")

            total_questions += 1
            # gentle throttle to avoid Cloudflare burst block
            time.sleep(1)

        total_docs += 1
        print(f"  Doc {doc_name} done. Total Q so far: {total_questions}")

    print(f"\nBatch done. Docs processed: {total_docs}  Questions answered: {total_questions}  limit={limit}")
    print(f"Answers in: {answer_dir.resolve()}")
    print(f"Each question → answer/{{doc_name}}/{{financebench_id}}.md  (one file per question)")
    print(f"Format per file: QUESTION / ANSWER / EVIDENCE / MODEL USED (decorated)")


if __name__ == "__main__":
    main()
