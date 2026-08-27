"""Counting tokens ourselves, for when the provider will not.

A gateway is free to omit `usage` from a response, and several do. The choice
then is between reporting nothing and reporting an estimate -- and an estimate
is worth having, so long as it never passes for a measurement. Everything
counted here is stamped `estimated=True`, and that flag reaches the screen.

`tiktoken` is used when it is installed and falls back to a character ratio when
it is not. The fallback is deliberately crude and documented as such: four
characters to a token is roughly right for English prose and roughly wrong for
a page of figures, which is most of what this system reads.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

#: Characters per token when there is no tokenizer. English prose sits near
#: four; a dense financial table sits lower, so this over-counts tokens on
#: exactly the documents this product reads. It is a floor on the error, not a
#: measurement, which is why nothing counted this way is reported as one.
CHARS_PER_TOKEN = 4

#: Per-message overhead in the chat format: role, separators, priming.
PER_MESSAGE_OVERHEAD = 4

_encoder: Any = None
_encoder_tried = False


def _encoding() -> Any:
    """The tokenizer, loaded once, or None if tiktoken is not installed."""
    global _encoder, _encoder_tried
    if _encoder_tried:
        return _encoder
    _encoder_tried = True
    try:
        import tiktoken  # type: ignore

        _encoder = tiktoken.get_encoding("o200k_base")
    except Exception as exc:  # noqa: BLE001 - an absent tokenizer is not an error
        logger.debug("tiktoken unavailable, estimating tokens by length: %s", exc)
        _encoder = None
    return _encoder


def count_text(text: str) -> int:
    """Tokens in one string."""
    if not text:
        return 0
    encoding = _encoding()
    if encoding is not None:
        try:
            return len(encoding.encode(text))
        except Exception:  # noqa: BLE001 - never let counting break a call
            pass
    return max(1, (len(text) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN)


def count_messages(messages: Iterable[Dict[str, Any]]) -> int:
    """
    Tokens in a chat transcript, including tool calls.

    Tool call arguments are part of what was sent and are counted. Skipping them
    would under-report exactly the agent turns that spend the most.
    """
    total = 0
    for message in messages or []:
        total += PER_MESSAGE_OVERHEAD
        content = message.get("content")
        if isinstance(content, str):
            total += count_text(content)
        elif isinstance(content, list):
            # Multi-part content: count the text parts, ignore the rest.
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    total += count_text(part["text"])
        for call in message.get("tool_calls") or []:
            function = (call or {}).get("function") or {}
            total += count_text(str(function.get("name") or ""))
            total += count_text(str(function.get("arguments") or ""))
    return total


def count_tools(tools: Optional[List[Dict[str, Any]]]) -> int:
    """
    Tokens in the tool schemas sent with a request.

    Not a rounding error: the reader agent carries four tool definitions on
    every one of its turns, and leaving them out under-reports a deep run's
    input by more than the question itself costs.
    """
    if not tools:
        return 0
    import json

    return count_text(json.dumps(tools, separators=(",", ":")))
