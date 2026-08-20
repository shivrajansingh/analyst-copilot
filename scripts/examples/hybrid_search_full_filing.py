"""
Hybrid search over an entire filing (all pages).

Indexes every page of the first filing in filings/, then runs hybrid
retrieval using the matching practice question from practice-questions.jsonl.

Usage:
  PYTHONPATH=src python scripts/examples/hybrid_search_full_filing.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Tuple

from analyst_copilot.config.settings import get_settings
from analyst_copilot.retrieval.hybrid.searcher import HybridSearcher
from analyst_copilot.services.indexing import HybridFilingIndexer


def first_filing_path(filings_dir: Path) -> Path:
    return sorted(filings_dir.glob("*.htm"))[0]


def practice_question_for_doc(
    questions_path: Path,
    doc_name: str,
) -> Tuple[str, str, int]:
    with questions_path.open(encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            if record["doc_name"] == doc_name:
                evidence_page = record["evidence"][0]["evidence_page_num"]
                return record["question"], record["answer"], evidence_page
    raise ValueError(f"No practice question found for document: {doc_name}")


def main() -> None:
    settings = get_settings()
    filing_path = first_filing_path(settings.filings_dir)
    doc_name = filing_path.stem
    questions_path = settings.project_root / "practice-questions.jsonl"

    question, expected_answer, evidence_page = practice_question_for_doc(
        questions_path,
        doc_name,
    )

    print("=== Hybrid search — full filing test ===\n")
    print(f"Filing:          {filing_path.name}")
    print(f"Practice answer: {expected_answer}")
    print(f"Evidence page:   {evidence_page}")
    print(
        f"Fusion:          RRF k={settings.hybrid_rrf_k} "
        f"(w={settings.hybrid_rrf_weight}) + "
        f"weighted bm25={settings.hybrid_bm25_weight}/"
        f"vector={settings.hybrid_vector_weight} "
        f"(w={settings.hybrid_weighted_weight})"
    )
    print(f"Candidate pool:  {settings.hybrid_candidate_pool}")
    print(f"Statement boost: {settings.hybrid_statement_boost}x\n")

    indexer = HybridFilingIndexer()
    if indexer.indices_exist(doc_name):
        print("Using saved BM25 + vector indices (skip re-embedding).\n")
        indices = indexer.load_indices(doc_name)
    else:
        print("Building BM25 + vector indices for the full filing...\n")
        indices = indexer.index_filing(filing_path, doc_name=doc_name, save=True)

    print(f"Indexed pages:   {indices.bm25_index.metadata.page_count} (entire filing)")
    print(f"Embedding model: {indices.vector_index.metadata.embedding_model}")
    print(f"Vector dims:     {indices.vector_index.metadata.dimensions}\n")

    print(f"Question:\n{question}\n")

    result = HybridSearcher().search(
        indices.bm25_index,
        indices.vector_index,
        question,
        top_k=5,
    )

    print("Top hybrid matches:")
    for hit in result.hits:
        snippet = hit.page.text[:140].replace("\n", " ")
        bm25 = f"{hit.bm25_score:.4f}" if hit.bm25_score is not None else "n/a"
        vector = f"{hit.vector_score:.4f}" if hit.vector_score is not None else "n/a"
        print(
            f"  {hit.rank}. fused={hit.score:.4f} | bm25={bm25} | vector={vector} | "
            f"printed_page={hit.page.printed_page} | page_index={hit.page.page_index} | "
            f"{snippet}..."
        )

    top = result.top_hit
    if top is None:
        print("\nResult: NO MATCHES")
        return

    printed = top.page.printed_page
    page_ok = printed in (evidence_page, evidence_page + 1)
    text_ok = expected_answer.replace("$", "").replace(".00", "") in top.page.text.replace(",", "")

    print("\n--- Evaluation ---")
    print(f"Top printed_page: {printed} (benchmark evidence_page={evidence_page})")
    print(f"Page match:       {'YES' if page_ok else 'NO'}")
    print(f"Answer in text:   {'YES' if text_ok else 'NO'} (value {expected_answer})")


if __name__ == "__main__":
    main()
