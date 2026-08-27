"""Splitting a question that is really several questions.

Measured problem: a practice question like "What was the FY2022 capital
expenditure and how did it change from FY2021, and what drove the change?" is
three questions sharing one question mark. Retrieval embeds the whole thing, so
the query vector lands between a cash-flow statement, a year-on-year table and a
paragraph of management commentary, and ranks none of them well. The answer then
addresses whichever part the model found first, which under the rubric scores
the same as answering none of them.

Splitting is done before retrieval so each part is retrieved, answered and cited
on its own. Two rules keep it from doing harm:

- **Each part must stand alone.** Parts are researched independently and in
  parallel, with no knowledge of each other, so the company, the fiscal year and
  the units have to be carried into every one of them. "And the year before?" is
  not a researchable question.
- **Splitting is the exception.** Most questions are single, and a split that
  invents a part the analyst did not ask for spends a full research pass on it
  and clutters the answer. On any doubt the question is returned unchanged.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional

from analyst_copilot.agent.prompts import DECOMPOSE_SYSTEM, build_decompose_prompt
from analyst_copilot.llm.base import ChatClient
from analyst_copilot.services.qa.parser import load_json_object

logger = logging.getLogger(__name__)

# Below this a question is too short to be two questions, whatever it contains.
MIN_CHARS_TO_SPLIT = 60

# A part shorter than this is a fragment rather than a standalone question, and
# researching it wastes a pass.
MIN_PART_CHARS = 12


@dataclass
class Decomposition:
    parts: List[str] = field(default_factory=list)
    reason: str = ""
    split: bool = False


def _looks_compound(question: str) -> bool:
    """
    A cheap pre-filter, so single questions never pay for a model call.

    Deliberately loose: a false positive costs one classification call that
    returns the question unchanged, while a false negative silently keeps the
    two-question failure this module exists to fix.
    """
    if len(question) < MIN_CHARS_TO_SPLIT:
        return False
    lowered = question.lower()
    if question.count("?") > 1 or ";" in question:
        return True
    return any(
        marker in lowered
        for marker in (
            " and ", " also ", " as well as ", " plus ", " along with ",
            " what drove", " why did", " explain", " compare", " versus ", " vs ",
            " respectively", " both ", " each of ", " breakdown",
        )
    )


class QuestionDecomposer:
    """Splits a compound question into standalone parts, or returns it unchanged."""

    def __init__(
        self,
        chat_client: Optional[ChatClient] = None,
        max_parts: int = 4,
    ) -> None:
        self._chat = chat_client
        self._max_parts = max(1, max_parts)

    def split(self, question: str, context: str = "") -> Decomposition:
        single = Decomposition(parts=[question], reason="single question", split=False)
        if self._chat is None or not _looks_compound(question):
            return single

        try:
            raw = self._chat.complete(
                messages=[
                    {"role": "system", "content": DECOMPOSE_SYSTEM},
                    {"role": "user", "content": build_decompose_prompt(question, context)},
                ],
                temperature=0.0,
                max_tokens=1024,
            )
        except Exception as exc:  # noqa: BLE001 - never lose a question to a splitter
            logger.warning("decomposition failed, answering as one question: %s", exc)
            return single

        payload = load_json_object(raw) or {}
        raw_parts = payload.get("parts")
        if not isinstance(raw_parts, list):
            return single

        parts = [
            str(part).strip()
            for part in raw_parts
            if isinstance(part, (str, int, float)) and len(str(part).strip()) >= MIN_PART_CHARS
        ]
        # Identical parts would each run a full research pass over the same
        # question and then be reported twice.
        deduped: List[str] = []
        for part in parts:
            if part.lower() not in {existing.lower() for existing in deduped}:
                deduped.append(part)

        if len(deduped) < 2:
            return single
        if len(deduped) > self._max_parts:
            logger.info(
                "decomposition returned %d parts; keeping the first %d",
                len(deduped),
                self._max_parts,
            )
            deduped = deduped[: self._max_parts]

        return Decomposition(
            parts=deduped,
            reason=str(payload.get("reason") or "").strip() or "compound question",
            split=True,
        )
