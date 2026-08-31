#!/usr/bin/env python3
"""
Run the planner on its own, before anything is retrieved or embedded.

The planner is the first decision in the pipeline and the cheapest place to get
it wrong: a greeting routed to `document` searches 189 pages to decline, and a
real question routed to `smalltalk` is answered from nothing. This runs that one
decision in isolation, prints what the model actually returned, and says whether
the pydantic validator accepted it -- the two things you need to tune
`planner.SYSTEM` and `planner.PlanPayload`.

Nothing here touches the embedding model or the index. Document cards are built
from filenames, which is what the planner sees in production.

Usage (from the project root):

  # one message
  python scripts/examples/plan.py "what was capex in FY2018?"

  # against a specific document set, so scoping is exercised
  python scripts/examples/plan.py "how did margin move from 2018 to 2022?" \
      --docs 3M_2018_10K 3M_2022_10K 3M_2023Q2_10Q

  # with a prior turn, so follow-up resolution is exercised
  python scripts/examples/plan.py "and the year before?" \
      --history "analyst: What was FY2018 capex?\nassistant: $1,577 million."

  # the whole labelled set, scored
  python scripts/examples/plan.py --suite data/planner-cases.jsonl

  # see exactly what the model was sent
  python scripts/examples/plan.py "hi" --show-prompt
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from analyst_copilot.agent.cards import cards_for
from analyst_copilot.agent.planner import PlanAttempt, PlanKind, Planner
from analyst_copilot.agent.recall import HistoryAnswerer, Recollection
from analyst_copilot.config.settings import get_settings
from analyst_copilot.llm import get_chat_client

# Used when --docs is not given. Three documents with overlapping coverage, so
# the scoping rules have something to be wrong about.
DEFAULT_DOCS = ["3M_2018_10K", "3M_2022_10K", "3M_2023Q2_10Q"]

RULE = "=" * 78


def history_text(turns: Sequence[dict]) -> str:
    """Stored turns as the planner sees them: role and text, nothing else."""
    return "\n".join(
        f"{'analyst' if turn.get('role') == 'user' else 'assistant'}: {turn.get('content', '')}"
        for turn in turns
        if turn.get("content")
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Classify a message with the planner and show its output.",
    )
    parser.add_argument("message", nargs="?", help="Analyst message to classify")
    parser.add_argument(
        "--suite",
        type=Path,
        help="JSONL file of labelled cases to run and score instead of one message",
    )
    parser.add_argument(
        "--docs",
        nargs="*",
        default=None,
        help=f"Document names to build cards from (default: {' '.join(DEFAULT_DOCS)})",
    )
    parser.add_argument("--history", default="", help="Earlier turns, as plain text")
    parser.add_argument(
        "--recall",
        action="store_true",
        help="When the plan is `history`, run the recall step too and show what it "
        "found. Needs --turns, or a suite whose cases carry them.",
    )
    parser.add_argument(
        "--turns",
        type=Path,
        help="JSON file of stored turns [{role, content, found, page, doc_name}], "
        "so recall has proved answers to restate",
    )
    parser.add_argument(
        "--show-prompt", action="store_true", help="Print the prompt sent to the model"
    )
    parser.add_argument(
        "--show-raw", action="store_true", help="Print the raw model reply for every case"
    )
    parser.add_argument(
        "--json", action="store_true", help="Print machine-readable output only"
    )
    parser.add_argument(
        "--no-scope",
        action="store_true",
        help="Disable document scoping, to see the model's unreconciled choice",
    )
    args = parser.parse_args()
    if not args.message and not args.suite:
        parser.error("give a message, or --suite with a case file")
    return args


def build_planner(scope: bool) -> Planner:
    settings = get_settings()
    return Planner(
        get_chat_client(),
        scope_documents=scope and settings.planner_scope_documents,
        require_named_year=settings.planner_scope_requires_year,
        min_confidence=settings.planner_min_confidence,
    )


# -- one message ---------------------------------------------------------- #
def attempt_as_dict(attempt: PlanAttempt) -> dict:
    plan = attempt.plan
    return {
        "kind": plan.kind.value,
        "question": plan.question,
        "documents": plan.documents,
        "confidence": plan.confidence,
        "reason": plan.reason,
        "assumed": plan.assumed,
        "validated": attempt.validated,
        "error": attempt.error,
        "proposed_documents": list(attempt.payload.documents) if attempt.payload else None,
        "raw": attempt.raw,
    }


def print_attempt(message: str, attempt: PlanAttempt, args: argparse.Namespace) -> None:
    plan = attempt.plan
    print(RULE)
    print(f"Message:  {message}")
    if args.history:
        print(f"History:  {args.history.strip()[:200]}")
    print("-" * 78)

    if args.show_prompt and attempt.prompt:
        print("Prompt sent")
        print("-" * 78)
        print(attempt.prompt)
        print("-" * 78)

    print("Raw model reply")
    print("-" * 78)
    print(attempt.raw.strip() if attempt.raw else "(no reply — the model was never asked)")
    print("-" * 78)

    if attempt.validated:
        print("Validator: accepted")
    else:
        print(f"Validator: REJECTED — {attempt.error}")
        print("           falling back to a document search over everything")
    print("-" * 78)

    print(f"kind:       {plan.kind.value}{'  (assumed, not decided)' if plan.assumed else ''}")
    print(f"question:   {plan.question}")
    print(f"confidence: {plan.confidence:.2f}")
    print(f"reason:     {plan.reason or '(none given)'}")

    proposed = list(attempt.payload.documents) if attempt.payload else []
    scope = plan.documents or ["(all documents)"]
    print(f"documents:  {', '.join(scope)}")
    if proposed and proposed != plan.documents:
        print(f"            model proposed {', '.join(proposed)} — reconciled against the cards")
    print(RULE)


def recall_as_dict(recollection: Recollection) -> dict:
    source = recollection.source
    return {
        "found": recollection.found,
        "answer": recollection.answer,
        "reason": recollection.reason,
        "error": recollection.error,
        "source_page": source.page if source else None,
        "source_doc": source.doc_name if source else None,
        "source_text": source.content if source else None,
        "raw": recollection.raw,
    }


def print_recall(recollection: Recollection) -> None:
    print("Recall step")
    print("-" * 78)
    if not recollection.found:
        print(f"declined — {recollection.reason or 'nothing to restate'}")
        print("the message falls through to the ordinary search")
        print(RULE)
        return
    source = recollection.source
    print(f"answer:     {recollection.answer}")
    print(f"restated:   {(source.content if source else '')[:200]}")
    print(f"citation:   {source.doc_name if source else '(none)'} page {(source.page or 0) + 1}")
    print(f"reason:     {recollection.reason or '(none given)'}")
    print(RULE)


# -- the labelled set ------------------------------------------------------ #
@dataclass
class Case:
    message: str
    kind: str
    history: str = ""
    documents: Optional[List[str]] = None
    note: str = ""
    #: Stored turns with their outcomes, for the recall step. The planner only
    #: ever sees these rendered as text; recall needs the pages.
    turns: List[dict] = field(default_factory=list)
    #: What recall should conclude, when the case is exercised with --recall.
    recalls: Optional[bool] = None


def load_suite(path: Path) -> List[Case]:
    cases: List[Case] = []
    for number, line in enumerate(path.read_text().splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{path}:{number}: {exc}") from exc
        cases.append(
            Case(
                message=row["message"],
                kind=row["kind"],
                history=row.get("history", ""),
                documents=row.get("documents"),
                note=row.get("note", ""),
                turns=row.get("turns", []),
                recalls=row.get("recalls"),
            )
        )
    return cases


def run_suite(
    planner: Planner, cases: Sequence[Case], docs: Sequence[str], args: argparse.Namespace
) -> int:
    """Run every case, print a table, return the number that failed."""
    cards = cards_for(list(docs))
    recaller = HistoryAnswerer(get_chat_client()) if args.recall else None
    rows = []
    for case in cases:
        history = case.history or history_text(case.turns)
        attempt = planner.explain(case.message, cards, history)
        got = attempt.plan.kind.value
        kind_ok = got == case.kind

        # Recall runs only where the planner sent it, so the table shows the two
        # decisions as they actually compose: a wrong `history` shows up here as
        # a decline, not as a wrong answer.
        recollection = None
        if recaller is not None and attempt.plan.kind is PlanKind.HISTORY:
            recollection = recaller.recall(case.message, case.turns)
        if case.recalls is not None and recaller is not None:
            kind_ok = kind_ok and bool(recollection and recollection.found) == case.recalls
        # Scope is only checked when the case states one, and only as a subset
        # test: searching one document too many is a cost, not a wrong answer.
        scope_ok = True
        if case.documents is not None:
            scope_ok = not set(case.documents) - set(attempt.plan.documents or docs)
        rows.append((case, attempt, kind_ok, scope_ok, recollection))

    if args.json:
        print(
            json.dumps(
                [
                    {
                        "message": case.message,
                        "expected_kind": case.kind,
                        "kind_ok": kind_ok,
                        "scope_ok": scope_ok,
                        **attempt_as_dict(attempt),
                    }
                    for case, attempt, kind_ok, scope_ok, _ in rows
                ],
                indent=2,
            )
        )
        return sum(1 for _, _, kind_ok, scope_ok, _ in rows if not (kind_ok and scope_ok))

    width = min(52, max(len(case.message) for case in cases))
    print(RULE)
    print(f"{'':4}{'message'.ljust(width)}  {'expected':<12} {'got':<12} result")
    print("-" * 78)
    for case, attempt, kind_ok, scope_ok, recollection in rows:
        mark = "ok  " if kind_ok and scope_ok else "FAIL"
        message = case.message if len(case.message) <= width else case.message[: width - 1] + "…"
        print(f"{mark}  {message.ljust(width)}  {case.kind:<12} {attempt.plan.kind.value:<12}", end="")
        print("" if attempt.validated else "  [invalid output]")
        if not scope_ok:
            want = ", ".join(case.documents or [])
            got_scope = ", ".join(attempt.plan.documents) or "(all)"
            print(f"      scope lost a document — wanted {want}, searched {got_scope}")
        if not attempt.validated and attempt.error:
            print(f"      {attempt.error}")
        if recollection is not None:
            if recollection.found:
                page = (recollection.source.page or 0) + 1 if recollection.source else 0
                print(f"      recalled from page {page}: {recollection.answer[:100]}")
            else:
                print(f"      recall declined — {recollection.reason[:100]}")
        if args.show_raw and attempt.raw:
            print(f"      raw: {attempt.raw.strip()[:160]}")

    passed = sum(1 for _, _, kind_ok, scope_ok, _ in rows if kind_ok and scope_ok)
    invalid = sum(1 for _, attempt, _, _, _ in rows if not attempt.validated)
    print("-" * 78)
    print(f"{passed}/{len(rows)} correct    {invalid} rejected by the validator")

    by_kind: dict = {}
    for case, attempt, kind_ok, _, _ in rows:
        hit, total = by_kind.get(case.kind, (0, 0))
        by_kind[case.kind] = (hit + int(kind_ok), total + 1)
    for kind, (hit, total) in sorted(by_kind.items()):
        print(f"  {kind:<14} {hit}/{total}")
    print(RULE)
    return len(rows) - passed


def main() -> None:
    args = parse_args()
    docs = args.docs if args.docs is not None else DEFAULT_DOCS
    planner = build_planner(scope=not args.no_scope)

    if args.suite:
        cases = load_suite(args.suite)
        if not args.json:
            print(f"Planner: {get_chat_client().model_name}")
            print(f"Corpus:  {', '.join(docs) or '(none)'}")
        failed = run_suite(planner, cases, docs, args)
        raise SystemExit(1 if failed else 0)

    turns = json.loads(args.turns.read_text()) if args.turns else []
    history = args.history or history_text(turns)

    cards = cards_for(list(docs))
    attempt = planner.explain(args.message, cards, history)

    recollection = None
    if args.recall and attempt.plan.kind is PlanKind.HISTORY:
        recollection = HistoryAnswerer(get_chat_client()).recall(args.message, turns)

    if args.json:
        payload = attempt_as_dict(attempt)
        if recollection is not None:
            payload["recall"] = recall_as_dict(recollection)
        print(json.dumps(payload, indent=2))
    else:
        args.history = history
        print_attempt(args.message, attempt, args)
        if recollection is not None:
            print_recall(recollection)


if __name__ == "__main__":
    main()
