"""Prompts for filing QA."""

from __future__ import annotations

from typing import List

from analyst_copilot.retrieval.models import ScoredPage

SYSTEM_PROMPT = """You are a financial analyst assistant answering questions from a single SEC filing.

Rules:
- Use only the provided excerpts. Do not use outside knowledge.
- If the excerpts do not contain enough evidence, set not_found to true.
- Never invent a number, year, or company fact.
- Cite the `page` value of the excerpt that supports the answer, exactly as given.
- Return JSON only, no markdown fences.

JSON schema:
{
  "not_found": boolean,
  "answer": string,
  "page": number or null,
  "evidence_snippet": string,
  "confidence": number between 0 and 1
}

When not_found is true, answer must be empty and page must be null.
"""


def build_user_prompt(question: str, hits: List[ScoredPage], max_chars: int) -> str:
    blocks: List[str] = [f"Question:\n{question}\n", "Excerpts:"]
    for hit in hits:
        page_no = hit.page.citation_page
        text = hit.page.text[:max_chars]
        blocks.append(
            f"\n--- excerpt rank={hit.rank} page={page_no} "
            f"fused_score={hit.score:.4f} ---\n{text}"
        )
    blocks.append(
        "\nReturn JSON only. If the answer is not clearly supported by an excerpt, "
        'set "not_found": true.'
    )
    return "\n".join(blocks)
