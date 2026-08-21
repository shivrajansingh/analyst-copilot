#!/usr/bin/env python3
"""
Ask a question about one SEC filing.

Usage (from the project root):

  python scripts/examples/ask.py filings/3M_2018_10K.htm "What is FY2018 capex?"
  python scripts/examples/ask.py 3M_2018_10K "What is FY2018 capex?"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from analyst_copilot.config.settings import get_settings
from analyst_copilot.data import resolve_user_filing_path
from analyst_copilot.services.indexing import HybridFilingIndexer
from analyst_copilot.services.qa import QuestionAnsweringService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Index a filing if needed, then answer a question with evidence.",
    )
    parser.add_argument("doc_path", help="Filing path, filename, or document stem")
    parser.add_argument("question", help="Analyst question in plain English")
    return parser.parse_args()


def ensure_index(indexer: HybridFilingIndexer, filing_path: Path, doc_name: str) -> None:
    if indexer.indices_exist(doc_name):
        print("Index: already embedded. Using saved BM25 + vector indices.")
        return
    print("Index: not found. Embedding this filing (can take several minutes)...")
    indexer.index_filing(filing_path, doc_name=doc_name, save=True)
    print("Index: ready.\n")


def print_answer(doc_path: Path, question: str, result) -> None:
    settings = get_settings()
    try:
        relative = doc_path.relative_to(settings.project_root)
    except ValueError:
        relative = doc_path

    print("=" * 72)
    print(f"Document: {relative}")
    print(f"Question: {question}")
    print("-" * 72)
    print("Answer")
    print("-" * 72)
    print(result.answer.strip())
    print()
    print(f"Found:    {'yes' if result.found else 'no'}")
    if result.page is not None:
        print(f"Page:     {result.page}")
    else:
        print("Page:     (none)")
    print("Evidence:")
    if result.evidence_snippet:
        print(result.evidence_snippet.strip())
    elif not result.found:
        reason = result.abstention_reason or "not enough support in this filing"
        print(f"(not found in this filing — {reason})")
    else:
        print("(no snippet returned)")
    print("=" * 72)


def main() -> None:
    args = parse_args()
    filing_path = resolve_user_filing_path(args.doc_path)
    doc_name = filing_path.stem
    question = args.question.strip()
    if not question:
        raise SystemExit("Question must not be empty.")

    indexer = HybridFilingIndexer()
    ensure_index(indexer, filing_path, doc_name)

    print("Searching and generating an answer...\n")
    result = QuestionAnsweringService(indexer=indexer).answer(
        question=question,
        doc_name=doc_name,
        filing_path=filing_path,
    )
    print_answer(filing_path, question, result)


if __name__ == "__main__":
    main()
