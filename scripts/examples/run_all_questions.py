#!/usr/bin/env python3
"""
Run every question in data/questions-by-doc.json.

For each filing: embed if needed, answer its questions, then update the
results JSON after every question.

Usage (from the project root):

  python scripts/examples/run_all_questions.py
  python scripts/examples/run_all_questions.py --limit 5
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from analyst_copilot.config.settings import get_settings
from analyst_copilot.data import load_questions_by_doc, resolve_user_filing_path
from analyst_copilot.services.indexing import HybridFilingIndexer
from analyst_copilot.services.qa import QuestionAnsweringService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Embed each filing if needed, then answer all grouped questions.",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="Grouped questions JSON (default: data/questions-by-doc.json).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Results JSON to create/update (default: data/questions-by-doc-results.json).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max unanswered questions to run (0 = all remaining).",
    )
    return parser.parse_args()


def question_text(item: Any) -> str:
    if isinstance(item, str):
        return item
    return str(item["question"])


def existing_answer(item: Any) -> Optional[Dict[str, Any]]:
    if isinstance(item, dict) and isinstance(item.get("answer"), dict):
        return item["answer"]
    return None


def build_results_skeleton(grouped: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for block in grouped:
        rows = []
        for item in block["questions"]:
            rows.append(
                {
                    "question": question_text(item),
                    "answer": existing_answer(item),
                }
            )
        results.append({"doc_path": block["doc_path"], "questions": rows})
    return results


def merge_saved_results(
    skeleton: List[Dict[str, Any]],
    saved: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    saved_by_doc = {block["doc_path"]: block for block in saved}
    for block in skeleton:
        previous = saved_by_doc.get(block["doc_path"])
        if previous is None:
            continue
        previous_answers = {
            question_text(item): existing_answer(item) for item in previous.get("questions", [])
        }
        for row in block["questions"]:
            if row["answer"] is None:
                row["answer"] = previous_answers.get(row["question"])
    return skeleton


def write_json(path: Path, payload: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def ensure_index(indexer: HybridFilingIndexer, filing_path: Path, doc_name: str) -> None:
    if indexer.indices_exist(doc_name):
        print(f"  Index: already embedded ({doc_name})")
        return
    print(f"  Index: not found. Embedding {doc_name} (can take several minutes)...")
    indexer.index_filing(filing_path, doc_name=doc_name, save=True)
    print("  Index: ready.")


def answer_payload(result) -> Dict[str, Any]:
    return {
        "text": result.answer,
        "evidence": result.evidence_snippet,
        "found": result.found,
        "page": result.page,
        # Diagnostics: distinguishes "never retrieved" from "retrieved but
        # rejected", which are very different problems to fix.
        "abstention_reason": result.abstention_reason,
        "retrieved_pages": (
            [hit.page.citation_page for hit in result.retrieval.hits]
            if result.retrieval is not None
            else []
        ),
    }


def main() -> None:
    args = parse_args()
    settings = get_settings()
    input_path = args.input or (settings.data_dir / "questions-by-doc.json")
    output_path = args.output or (settings.data_dir / "questions-by-doc-results.json")

    grouped = load_questions_by_doc(input_path)
    results = build_results_skeleton(grouped)
    if output_path.exists():
        saved = json.loads(output_path.read_text(encoding="utf-8"))
        results = merge_saved_results(results, saved)
        print(f"Resuming from existing results: {output_path}\n")

    pending = sum(1 for block in results for row in block["questions"] if row["answer"] is None)
    print(f"Documents: {len(results)}")
    print(f"Unanswered questions: {pending}")
    if args.limit:
        print(f"This run limit: {args.limit}")
    print()

    indexer = HybridFilingIndexer()
    service = QuestionAnsweringService(indexer=indexer)
    answered_this_run = 0

    for block in results:
        remaining_in_doc = [row for row in block["questions"] if row["answer"] is None]
        if not remaining_in_doc:
            continue
        if args.limit and answered_this_run >= args.limit:
            break

        doc_path = block["doc_path"]
        filing_path = resolve_user_filing_path(doc_path)
        doc_name = filing_path.stem
        print(f"Document: {doc_path}")
        ensure_index(indexer, filing_path, doc_name)

        for row in remaining_in_doc:
            if args.limit and answered_this_run >= args.limit:
                break
            question = row["question"]
            print(f"  Q: {question[:90]}...")
            try:
                qa = service.answer(
                    question=question,
                    doc_name=doc_name,
                    filing_path=filing_path,
                )
                row["answer"] = answer_payload(qa)
                found = "yes" if qa.found else "no"
                print(f"     found={found} page={qa.page}")
            except Exception as exc:
                traceback.print_exc()
                row["answer"] = {
                    "text": str(exc),
                    "evidence": "",
                    "found": False,
                    "page": None,
                    "abstention_reason": f"runner_error:{type(exc).__name__}",
                    "retrieved_pages": [],
                }
                print(f"     ERROR: {exc}")

            answered_this_run += 1
            write_json(output_path, results)

        print()

    print(f"Updated {output_path}")
    print(f"Questions answered this run: {answered_this_run}")


if __name__ == "__main__":
    main()
