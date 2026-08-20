"""
Run QA over grouped practice questions and write eval results JSON.

Usage:
  PYTHONPATH=src python scripts/eval/run_practice.py
  PYTHONPATH=src python scripts/eval/run_practice.py --limit 5
  PYTHONPATH=src python scripts/eval/run_practice.py --limit 10 --offset 0
"""

from __future__ import annotations

import argparse
import json
import traceback
from pathlib import Path
from typing import Any, Dict, List

from analyst_copilot.config.settings import get_settings
from analyst_copilot.data import load_questions_by_doc, questions_by_doc_path, write_questions_by_doc
from analyst_copilot.services.qa import QuestionAnsweringService


def flatten_items(grouped: List[Dict[str, Any]], limit: int, offset: int) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    for block in grouped:
        doc_path = block["doc_path"]
        for question in block["questions"]:
            items.append({"doc_path": doc_path, "question": question})
    start = max(offset, 0)
    end = start + limit if limit > 0 else len(items)
    return items[start:end]


def run_eval(limit: int, offset: int, output: Path) -> Path:
    settings = get_settings()
    if not questions_by_doc_path().exists():
        write_questions_by_doc()

    grouped = load_questions_by_doc()
    items = flatten_items(grouped, limit=limit, offset=offset)
    service = QuestionAnsweringService()
    results: List[Dict[str, Any]] = []

    print(f"Evaluating {len(items)} question(s) (offset={offset}, limit={limit or 'all'})\n")

    for index, item in enumerate(items, start=1):
        doc_path = item["doc_path"]
        question = item["question"]
        filing_path = settings.project_root / doc_path
        doc_name = filing_path.stem
        print(f"[{index}/{len(items)}] {doc_name}: {question[:80]}...")

        try:
            answer = service.answer(
                question=question,
                doc_name=doc_name,
                filing_path=filing_path,
            )
            results.append(
                {
                    "doc": doc_path,
                    "question": question,
                    "answer": {
                        "text": answer.answer,
                        "evidence": answer.evidence_snippet,
                        "found": answer.found,
                        "page": answer.page,
                    },
                }
            )
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
                    },
                }
            )

        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"\nWrote {output}")
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
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()
    output = args.output or (settings.data_dir / "eval-results.json")
    run_eval(limit=args.limit, offset=args.offset, output=output)


if __name__ == "__main__":
    main()
