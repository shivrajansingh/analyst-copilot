"""Parse JSON from a chat completion."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

from analyst_copilot.services.qa.models import LLMExtraction

_FENCE_PATTERN = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


def parse_llm_extraction(raw_text: str) -> LLMExtraction:
    payload = load_json_object(raw_text)
    if payload is None:
        return LLMExtraction(not_found=True, raw_text=raw_text)

    not_found = bool(payload.get("not_found", False))
    answer = str(payload.get("answer") or "").strip()
    snippet = str(payload.get("evidence_snippet") or "").strip()
    page = _optional_int(payload.get("page"))
    confidence = _optional_float(payload.get("confidence"))
    document = str(payload.get("document") or "").strip() or None

    if not_found or not answer:
        return LLMExtraction(
            not_found=True,
            raw_text=raw_text,
            confidence=confidence,
        )

    return LLMExtraction(
        not_found=False,
        answer=answer,
        page=page,
        evidence_snippet=snippet,
        confidence=confidence,
        raw_text=raw_text,
        document=document,
    )


def load_json_object(raw_text: str) -> Optional[Dict[str, Any]]:
    text = raw_text.strip()
    fenced = _FENCE_PATTERN.search(text)
    if fenced:
        text = fenced.group(1).strip()

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(text[start : end + 1])
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return None
    return None


def _optional_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# The harness's classifiers ask for JSON from the same models, and they hit the
# same fenced-and-prefaced replies this parser already tolerates.
_load_json_object = load_json_object
