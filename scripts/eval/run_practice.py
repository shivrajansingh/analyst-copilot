"""
Run QA over grouped practice questions and write eval results JSON.

Two brains, so a change can be attributed:

  --harness   the full agent harness (default): retrieve, validate, and read the
              whole filing when the cheap tier cannot prove an answer
  --fast-only the retrieval pipeline alone, which is what produced the +7
              baseline and is the number any harness gain must be measured
              against

Usage:
  PYTHONPATH=src python scripts/eval/run_practice.py
  PYTHONPATH=src python scripts/eval/run_practice.py --limit 5 --fast-only
  PYTHONPATH=src python scripts/eval/run_practice.py --limit 10 --offset 0
"""

from __future__ import annotations

import argparse
import json
import traceback
from pathlib import Path
from typing import Any, Dict, List

from analyst_copilot.agent import AnalystAgent
from analyst_copilot.config.settings import get_settings
from analyst_copilot.data import load_questions_by_doc, questions_by_doc_path, write_questions_by_doc
from analyst_copilot.services.qa import QuestionAnsweringService


def question_text(item: Any) -> str:
    """Grouped questions are plain strings in the old layout, dicts in the new one."""
    if isinstance(item, str):
        return item
    return str(item["question"])


def flatten_items(grouped: List[Dict[str, Any]], limit: int, offset: int) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    for block in grouped:
        doc_path = block["doc_path"]
        for question in block["questions"]:
            items.append({"doc_path": doc_path, "question": question_text(question)})
    start = max(offset, 0)
    end = start + limit if limit > 0 else len(items)
    return items[start:end]


def _fast_row(service: QuestionAnsweringService, question: str, doc_name: str, filing_path: Path):
    """One row from the retrieval pipeline alone."""
    answer = service.answer(question=question, doc_name=doc_name, filing_path=filing_path)
    return {
        "text": answer.answer,
        "evidence": answer.evidence_snippet,
        "found": answer.found,
        "page": answer.page,
        "abstention_reason": answer.abstention_reason,
        "mode": "fast",
        "retrieved_pages": (
            [hit.page.citation_page for hit in answer.retrieval.hits]
            if answer.retrieval is not None
            else []
        ),
    }


def _harness_row(agent: AnalystAgent, question: str, doc_name: str, filing_path: Path):
    """
    One row from the full harness.

    The scorer reads a single `page`, so a multi-part answer reports its primary
    citation there and the rest under `citations` -- scoring a compound question
    against one gold page is a limitation of the key, not of the answer.
    """
    answer = agent.answer(question, doc_name=doc_name)
    citation = answer.citation
    return {
        "text": answer.answer,
        "evidence": citation.snippet if citation else "",
        "found": answer.found,
        "page": citation.page if citation else None,
        "abstention_reason": answer.abstention_reason,
        "mode": answer.mode.value,
        "intent": answer.intent.value,
        "validation": answer.validation,
        "computation": answer.computation,
        "inputs": [item.to_dict() for item in answer.inputs],
        "citations": [
            {"doc_name": c.doc_name, "page": c.page, "label": c.label}
            for c in answer.citations
        ],
        "pages_read": answer.pages_read,
        "shards_run": answer.shards_run,
        "retrieved_pages": (
            [hit.page.citation_page for hit in answer.retrieval.hits]
            if answer.retrieval is not None
            else []
        ),
    }


def run_eval(limit: int, offset: int, output: Path, harness: bool = True) -> Path:
    settings = get_settings()
    if not questions_by_doc_path().exists():
        write_questions_by_doc()

    grouped = load_questions_by_doc()
    items = flatten_items(grouped, limit=limit, offset=offset)
    service = QuestionAnsweringService()
    agent = AnalystAgent(qa_service=service) if harness else None
    results: List[Dict[str, Any]] = []
    modes: Dict[str, int] = {}

    brain = "agent harness" if harness else "fast path only"
    print(
        f"Evaluating {len(items)} question(s) with the {brain} "
        f"(offset={offset}, limit={limit or 'all'})\n"
    )

    for index, item in enumerate(items, start=1):
        doc_path = item["doc_path"]
        question = item["question"]
        filing_path = settings.project_root / doc_path
        doc_name = filing_path.stem
        print(f"[{index}/{len(items)}] {doc_name}: {question[:80]}...")

        try:
            row = (
                _harness_row(agent, question, doc_name, filing_path)
                if agent is not None
                else _fast_row(service, question, doc_name, filing_path)
            )
            modes[row.get("mode", "?")] = modes.get(row.get("mode", "?"), 0) + 1
            print(
                f"      -> {row['mode']}: "
                + (
                    f"page {row['page']}  {str(row['text'])[:60]}"
                    if row["found"]
                    else f"abstained ({row['abstention_reason']})"
                )
            )
            results.append({"doc": doc_path, "question": question, "answer": row})
        except Exception as exc:
            print(f"  ERROR: {exc}")
            traceback.print_exc()
            results.append(
                {
                    "doc": doc_path,
                    "question": question,
                    "answer": {
                        "text": str(exc),
                        "evidence": "",
                        "found": False,
                        "page": None,
                        "abstention_reason": f"runner_error:{type(exc).__name__}",
                        "retrieved_pages": [],
                    },
                }
            )

        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if modes:
        print("\nAnswered by tier: " + ", ".join(f"{k}={v}" for k, v in sorted(modes.items())))
    print(f"Wrote {output}")
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate QA on practice questions.")
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max number of questions to run (0 = all).",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Skip this many questions from the start of the flattened list.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output JSON path (default: data/eval-results.json).",
    )
    parser.add_argument(
        "--fast-only",
        action="store_true",
        help="Use the retrieval pipeline alone, skipping validation and deep search.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()
    output = args.output or (settings.data_dir / "eval-results.json")
    run_eval(
        limit=args.limit,
        offset=args.offset,
        output=output,
        harness=not args.fast_only,
    )


if __name__ == "__main__":
    main()
