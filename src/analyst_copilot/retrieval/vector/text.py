"""Prepare page text before embedding."""

from __future__ import annotations

from typing import Optional

from analyst_copilot.config.settings import get_settings


def truncate_page_text(text: str, max_chars: Optional[int] = None) -> str:
    """Truncate long page text to stay within embedding context limits."""
    limit = max_chars or get_settings().retrieval_max_chars_per_page
    if len(text) <= limit:
        return text
    return text[:limit]
