#!/usr/bin/env python3
"""
Build BM25 + vector indices for every filing in `filings/`.

By default this SKIPS filings that already have a current index, so it is safe
to re-run and safe to interrupt. Use --overwrite to re-embed everything.

Usage (from the project root):

  python scripts/index_all.py                       # index whatever is missing
  python scripts/index_all.py --overwrite           # re-embed every filing
  python scripts/index_all.py --dry-run             # show the plan, embed nothing
  python scripts/index_all.py --only '3M*'          # restrict by filename pattern
  python scripts/index_all.py --limit 5             # first 5 filings needing work
  python scripts/index_all.py --workers 4           # embed 4 filings concurrently
  python scripts/index_all.py --fail-fast           # stop at the first failure

An index is "current" only when it was built by this PARSER_VERSION, with this
EMBEDDING_MODEL, at this retrieval_max_chars_per_page. Change any of those and
the affected indices are treated as stale and rebuilt even without --overwrite.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from analyst_copilot.config.settings import get_settings  # noqa: E402
from analyst_copilot.parsing.html_filing_parser import PARSER_VERSION  # noqa: E402
from analyst_copilot.retrieval.bm25.storage import BM25IndexStore  # noqa: E402
from analyst_copilot.retrieval.vector.storage import VectorIndexStore  # noqa: E402
from analyst_copilot.services.indexing import HybridFilingIndexer  # noqa: E402

# The spec requires adding one filing to complete within 10 minutes.
PER_FILING_BUDGET_SECONDS = 600


@dataclass
class Outcome:
    doc_name: str
    state: str  # current | stale | missing
    action: str  # skipped | indexed | failed
    pages: Optional[int] = None
    seconds: Optional[float] = None
    attempts: int = 0
    error: str = ""


def classify(doc_name: str) -> str:
    """Distinguish a usable index from one that exists but is out of date."""
    indexer = HybridFilingIndexer()
    if indexer.indices_exist(doc_name):
        return "current"
    for store in (BM25IndexStore(), VectorIndexStore()):
        directory = store.index_dir(doc_name)
        if directory.exists() and any(directory.iterdir()):
            return "stale"
    return "missing"


def index_one(filing_path: Path, state: str, retries: int) -> Outcome:
    doc_name = filing_path.stem
    started = time.monotonic()
    last_error = ""

    for attempt in range(1, retries + 1):
        try:
            # A fresh indexer per task keeps worker threads independent.
            indices = HybridFilingIndexer().index_filing(
                filing_path, doc_name=doc_name, save=True
            )
            return Outcome(
                doc_name=doc_name,
                state=state,
                action="indexed",
                pages=len(indices.bm25_index.pages),
                seconds=round(time.monotonic() - started, 1),
                attempts=attempt,
            )
        except Exception as exc:  # transient provider errors are common at this scale
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < retries:
                backoff = 5 * attempt
                print(f"    {doc_name}: attempt {attempt} failed ({last_error}); "
                      f"retrying in {backoff}s")
                time.sleep(backoff)

    return Outcome(
        doc_name=doc_name,
        state=state,
        action="failed",
        seconds=round(time.monotonic() - started, 1),
        attempts=retries,
        error=last_error,
    )


def select_filings(only: Optional[str], overwrite: bool, limit: int) -> Tuple[List[Tuple[Path, str]], List[Outcome]]:
    """Return (work to do, already-current filings skipped)."""
    settings = get_settings()
    paths = sorted(settings.filings_dir.glob("*.htm"))
    if only:
        paths = [p for p in paths if fnmatch.fnmatch(p.stem, only) or fnmatch.fnmatch(p.name, only)]

    work: List[Tuple[Path, str]] = []
    skipped: List[Outcome] = []
    for path in paths:
        state = classify(path.stem)
        if state == "current" and not overwrite:
            skipped.append(Outcome(doc_name=path.stem, state=state, action="skipped"))
            continue
        work.append((path, state))

    if limit > 0:
        work = work[:limit]
    return work, skipped


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build BM25 + vector indices for every filing.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--overwrite",
        action="store_true",
        help="Re-embed every filing, replacing indices that are already current.",
    )
    mode.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip filings with a current index (the default).",
    )
    parser.add_argument("--only", help="Only filings whose name matches this glob, e.g. '3M*'.")
    parser.add_argument("--limit", type=int, default=0, help="Index at most N filings (0 = all).")
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Filings to embed concurrently. Raise to speed up a full run, but "
             "watch for provider rate limits (default 1).",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="Attempts per filing before giving up (default 3).",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop on the first filing that fails instead of continuing.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print the plan and exit.")
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Where to write the run report (default: storage/index-report.json).",
    )
    return parser.parse_args()


def print_plan(work, skipped, args) -> None:
    settings = get_settings()
    print(f"Filings dir      : {settings.filings_dir}")
    print(f"Embedding model  : {settings.resolved_embedding_model}")
    print(f"Chars per page   : {settings.retrieval_max_chars_per_page}")
    print(f"Parser version   : {PARSER_VERSION}")
    print(f"Mode             : {'overwrite' if args.overwrite else 'skip existing'}")
    print()

    by_state = {"missing": 0, "stale": 0, "current": 0}
    for _, state in work:
        by_state[state] = by_state.get(state, 0) + 1

    print(f"To index         : {len(work)}")
    if by_state["missing"]:
        print(f"   missing       : {by_state['missing']}")
    if by_state["stale"]:
        print(f"   stale         : {by_state['stale']}  (built by an older parser/model/cap)")
    if by_state["current"]:
        print(f"   current       : {by_state['current']}  (re-embedding because --overwrite)")
    print(f"Skipped (current): {len(skipped)}")
    print()


def summarize(outcomes: List[Outcome], skipped: List[Outcome], elapsed: float, report_path: Path) -> int:
    indexed = [o for o in outcomes if o.action == "indexed"]
    failed = [o for o in outcomes if o.action == "failed"]
    pages = sum(o.pages or 0 for o in indexed)
    over_budget = [o for o in indexed if (o.seconds or 0) > PER_FILING_BUDGET_SECONDS]

    print("\n" + "=" * 66)
    print(f"Indexed {len(indexed)} filing(s), {pages} page(s) in {elapsed/60:.1f} min")
    print("=" * 66)
    print(f"  skipped (already current) : {len(skipped)}")
    print(f"  failed                    : {len(failed)}")
    if indexed:
        times = sorted(o.seconds or 0 for o in indexed)
        print(f"  per filing: median {times[len(times)//2]:.0f}s, slowest {times[-1]:.0f}s")
    if over_budget:
        print(f"\n  !! {len(over_budget)} filing(s) exceeded the {PER_FILING_BUDGET_SECONDS}s "
              "per-filing budget from the spec:")
        for outcome in over_budget:
            print(f"     {outcome.doc_name}: {outcome.seconds:.0f}s ({outcome.pages} pages)")
    if failed:
        print(f"\n  --- {len(failed)} failure(s), re-run to retry ---")
        for outcome in failed:
            print(f"     {outcome.doc_name}: {outcome.error[:110]}")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(
            {
                "parser_version": PARSER_VERSION,
                "embedding_model": get_settings().resolved_embedding_model,
                "max_chars_per_page": get_settings().retrieval_max_chars_per_page,
                "elapsed_seconds": round(elapsed, 1),
                "indexed": len(indexed),
                "skipped": len(skipped),
                "failed": len(failed),
                "pages": pages,
                "outcomes": [asdict(o) for o in outcomes + skipped],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"\nWrote {report_path}")
    return 1 if failed else 0


def main() -> None:
    args = parse_args()
    report_path = args.report or (get_settings().storage_dir / "index-report.json")

    work, skipped = select_filings(args.only, args.overwrite, args.limit)
    print_plan(work, skipped, args)

    if args.dry_run:
        for path, state in work:
            print(f"   would index [{state}] {path.name}")
        raise SystemExit(0)
    if not work:
        print("Nothing to do. Use --overwrite to rebuild current indices.")
        raise SystemExit(0)

    outcomes: List[Outcome] = []
    started = time.monotonic()
    total = len(work)
    done = 0

    def record(outcome: Outcome) -> None:
        nonlocal done
        done += 1
        outcomes.append(outcome)
        if outcome.action == "indexed":
            print(f"[{done}/{total}] {outcome.doc_name}: {outcome.pages} pages "
                  f"in {outcome.seconds:.0f}s")
        else:
            print(f"[{done}/{total}] {outcome.doc_name}: FAILED — {outcome.error[:90]}")

    try:
        if args.workers > 1:
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                futures = {
                    pool.submit(index_one, path, state, args.retries): path
                    for path, state in work
                }
                for future in as_completed(futures):
                    outcome = future.result()
                    record(outcome)
                    if outcome.action == "failed" and args.fail_fast:
                        for pending in futures:
                            pending.cancel()
                        break
        else:
            for path, state in work:
                print(f"[{done + 1}/{total}] {path.stem} ({state})...")
                outcome = index_one(path, state, args.retries)
                record(outcome)
                if outcome.action == "failed" and args.fail_fast:
                    break
    except KeyboardInterrupt:
        print("\nInterrupted. Indices already written are kept; re-run to continue.")

    raise SystemExit(summarize(outcomes, skipped, time.monotonic() - started, report_path))


if __name__ == "__main__":
    main()
