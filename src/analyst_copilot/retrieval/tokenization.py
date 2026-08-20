"""Text tokenization utilities for lexical retrieval."""

from __future__ import annotations

import re
from typing import List

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
_COMMA_IN_NUMBER = re.compile(r"(?<=\d),(?=\d)")


class TextTokenizer:
    """Tokenizer tuned for SEC filing text and financial line items."""

    VERSION = "v1"

    def tokenize(self, text: str) -> List[str]:
        """Lowercase, normalize numbers, and extract alphanumeric tokens."""
        normalized = text.lower()
        normalized = _COMMA_IN_NUMBER.sub("", normalized)
        return _TOKEN_PATTERN.findall(normalized)

    def tokenize_many(self, texts: List[str]) -> List[List[str]]:
        return [self.tokenize(text) for text in texts]
