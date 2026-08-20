"""
Embedding example: parse a filing by page, embed via OpenAI-compatible /v1/embeddings.

Works with Ollama ({OLLAMA_URL}/v1) and other OpenAI-compatible embedding APIs.
Configure via .env — see README.
"""

from __future__ import annotations

import math
import sys
from typing import List, Tuple

from analyst_copilot.config.settings import get_settings
from analyst_copilot.embeddings import get_embedding_client
from analyst_copilot.parsing import parse_filing_html
from analyst_copilot.parsing.models import Page

MAX_CHARS_PER_PAGE = 2500


def cosine_similarity(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def truncate(text: str, limit: int = MAX_CHARS_PER_PAGE) -> str:
    if len(text) <= limit:
        return text
    return text[:limit]


def select_demo_pages(pages: List[Page], limit: int = 12) -> List[Page]:
    selected: List[Page] = []
    for page in pages:
        if page.printed_page is not None and 55 <= page.printed_page <= 65:
            selected.append(page)
    if len(selected) < limit:
        for page in pages[:6]:
            if page not in selected:
                selected.append(page)
    return selected[:limit]


def main() -> None:
    settings = get_settings()
    filing_path = settings.filings_dir / "3M_2018_10K.htm"

    print("=== Analyst Copilot — embedding example ===\n")
    print(f"Filing: {filing_path.name}\n")

    document = parse_filing_html(filing_path)
    demo_pages = select_demo_pages(document.pages)
    page_texts = [truncate(page.text) for page in demo_pages]

    print(f"Parsed {document.page_count} pages; embedding {len(demo_pages)} for demo.\n")

    client = get_embedding_client()
    print(f"Base URL: {client.base_url}")
    print(f"Model:    {client.model_name}")

    try:
        vectors = client.embed_texts(page_texts)
    except Exception as exc:
        print(f"\nEmbedding request failed: {exc}")
        sys.exit(1)

    print(f"Dimensions: {client.dimensions}\n")

    query = (
        "What is the FY2018 capital expenditure amount from the cash flow statement? "
        "Purchases of property, plant and equipment."
    )
    print(f"Query: {query}\n")

    query_vector = client.embed_query(query)
    scored: List[Tuple[float, Page]] = []
    for page, vector in zip(demo_pages, vectors):
        scored.append((cosine_similarity(query_vector, vector), page))

    scored.sort(key=lambda item: item[0], reverse=True)

    print("Top matches (cosine similarity):")
    for rank, (score, page) in enumerate(scored[:5], start=1):
        snippet = page.text[:160].replace("\n", " ")
        print(
            f"  {rank}. score={score:.4f} | "
            f"printed_page={page.printed_page} | page_index={page.page_index} | "
            f"{snippet}..."
        )


if __name__ == "__main__":
    main()
