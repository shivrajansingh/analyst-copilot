"""Prompts for document QA."""

from __future__ import annotations

from typing import List

from analyst_copilot.retrieval.models import ScoredPage

SYSTEM_PROMPT = """You are a financial analyst assistant answering questions from a single document.

Rules:
- Use only the provided excerpts. Do not use outside knowledge.
- If the excerpts do not contain enough evidence, set not_found to true.
- Never invent a number, year, or company fact.
- Cite the `page` value of the excerpt that supports the answer, exactly as given.
- Quote the supporting sentence or table row in `evidence_snippet`, copied
  verbatim from the excerpt. It is checked against the excerpt text.
- Return JSON only, no markdown fences.

Choosing which excerpt to cite. Several excerpts often carry the same figure --
a statement, the discussion of it, and a footnote. Cite the authoritative source
for the kind of question asked:
- The question names a statement ("according to the cash flow statement", "on
  the balance sheet") -> cite that statement.
- A figure with no source named -> cite the primary financial statement it is
  reported in, not a narrative page that repeats it.
- "What drove / why did / explain a change" -> cite the management discussion
  that explains it, not the statement showing the total.
- What the company does, where it operates, what it sells -> cite the business
  description, not a footnote that mentions it in passing.

Excerpts may be Markdown, including tables. In a table, a figure belongs to the
column header above it and the row label beside it; do not read a figure from
the wrong year's column.

JSON schema:
{
  "not_found": boolean,
  "answer": string,
  "document": string or null,
  "page": number or null,
  "evidence_snippet": string,
  "confidence": number between 0 and 1
}

When not_found is true, answer must be empty and page must be null.
"""

MULTI_DOCUMENT_RULES = """
The excerpts come from several documents in one folder. Two extra rules:

- Set `document` to the `document` value of the excerpt you cite, copied
  exactly. Page numbers repeat across documents -- page 59 exists in all of
  them -- so a page without a document names nothing.
- Documents in a folder are usually the same company across years, or related
  filings from one period. Read the fiscal year and entity in each excerpt and
  answer from the one the question asks about. Do not blend figures from two
  documents into one number unless the question asks for a comparison, and when
  it does, say which figure came from which document.
"""


def build_system_prompt(multi_document: bool = False) -> str:
    """The system prompt, with the folder-specific rules only when they apply."""
    if not multi_document:
        return SYSTEM_PROMPT
    return SYSTEM_PROMPT + MULTI_DOCUMENT_RULES


def build_user_prompt(
    question: str,
    hits: List[ScoredPage],
    max_chars: int,
    multi_document: bool = False,
) -> str:
    blocks: List[str] = [f"Question:\n{question}\n", "Excerpts:"]
    for hit in hits:
        page_no = hit.page.citation_page
        text = hit.page.text[:max_chars]
        # The label names the segment the way its source does, so an excerpt
        # from a worksheet is not presented to the model as a page of prose.
        # The document is named only when there is more than one, so a
        # single-document question is not invited to cite anything else.
        document = f'document="{hit.page.doc_name}" ' if multi_document else ""
        blocks.append(
            f"\n--- excerpt rank={hit.rank} {document}page={page_no} "
            f"location=\"{hit.page.citation_label}\" "
            f"fused_score={hit.score:.4f} ---\n{text}"
        )
    blocks.append(
        "\nReturn JSON only. If the answer is not clearly supported by an excerpt, "
        'set "not_found": true.'
    )
    return "\n".join(blocks)
