"""
Ask a practice question against a filing using hybrid retrieval + LLM + verifier.

Usage:
  PYTHONPATH=src python scripts/examples/qa_example.py
"""

from __future__ import annotations

import json
from pathlib import Path

from analyst_copilot.config.settings import get_settings
from analyst_copilot.services.qa import QuestionAnsweringService


def first_practice_question(questions_path: Path, doc_name: str):
    with questions_path.open(encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            if record["doc_name"] == doc_name:
                return record
    raise ValueError(f"No practice question for {doc_name}")


def main() -> None:
    settings = get_settings()
    doc_name = "3M_2018_10K"
    record = first_practice_question(settings.data_dir / "practice-questions.jsonl", doc_name)

    print("=== Analyst Copilot — QA example ===\n")
    print(f"Filing:   {doc_name}")
    print(f"Expected: {record['answer']}")
    print(f"Gold page:{record['evidence'][0]['evidence_page_num']}")
    print(f"Question: {record['question']}\n")

    service = QuestionAnsweringService()
    result = service.answer(
        question=record["question"],
        doc_name=doc_name,
        filing_path=settings.filings_dir / f"{doc_name}.htm",
    )

    print(result.display_text)
    print(f"\nfound={result.found} page={result.page} reason={result.abstention_reason}")
    if result.evidence_snippet:
        snippet = result.evidence_snippet[:220].replace("\n", " ")
        print(f"evidence: {snippet}...")
    if result.retrieval and result.retrieval.hits:
        print("\nRetrieved pages:")
        for hit in result.retrieval.hits:
            print(
                f"  rank={hit.rank} printed_page={hit.page.printed_page} "
                f"fused={hit.score:.4f}"
            )


if __name__ == "__main__":
    main()
