"""A second opinion on the fast path's answer, before it is served.

The fast path already verifies that the answer's figures trace to the cited
page. That catches a fabricated number; it does not catch the two failures that
cost the most marks in the measured run:

- **Right figure, wrong question.** 23 of 136 answers were correct and cited the
  wrong page, and a further group answered about the wrong fiscal year or a
  segment rather than the consolidated total. Every figure traced. The answer was
  still not the answer.
- **Half an answer.** A compound question answered in one part reads as
  complete, verifies cleanly, and is wrong by omission.

Neither is detectable by tracing digits, because both are about *meaning*. So a
reader that did not write the answer is shown the question, the answer and the
whole cited page — not the 2,200-character excerpt the writer saw — and asked
whether the answer is right.

Its verdict is a gate, not a judgement: `correct` serves the answer, anything
else escalates to the deep path. That asymmetry is deliberate. A false
`incorrect` costs a slow second search; a false `correct` puts a wrong figure in
front of an analyst.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from analyst_copilot.agent.corpus import DocumentCorpus
from analyst_copilot.agent.prompts import VALIDATOR_SYSTEM, build_validator_prompt
from analyst_copilot.agent.runtime import AgentRuntime
from analyst_copilot.agent.tools import (
    REPORT_VALIDATION,
    CalculateTool,
    DocumentToolset,
    ReportValidationTool,
    ToolRegistry,
    document_tools,
)
from analyst_copilot.llm.base import ChatClient

logger = logging.getLogger(__name__)


class Verdict(str, Enum):
    CORRECT = "correct"
    INCORRECT = "incorrect"
    INSUFFICIENT = "insufficient"
    #: The check could not be run — no page text, or the model was unreachable.
    UNCHECKED = "unchecked"

    @property
    def serves(self) -> bool:
        """
        Whether this verdict lets the fast answer through.

        `UNCHECKED` serves. When validation itself is broken, falling back to
        the fast path's own verified answer is right: that answer already passed
        the deterministic evidence check, and escalating every question to a
        full document read because a validator call failed would turn a provider
        hiccup into a 60-second response for everyone.
        """
        return self in (Verdict.CORRECT, Verdict.UNCHECKED)


@dataclass
class Validation:
    verdict: Verdict
    reason: str = ""
    corrected_answer: str = ""

    @property
    def serves(self) -> bool:
        return self.verdict.serves


class AnswerValidator:
    """Re-checks a proposed answer against the full text of its cited page."""

    def __init__(
        self,
        chat_client: ChatClient,
        max_iterations: int = 6,
        max_tokens: int = 2048,
        max_page_chars: int = 24000,
    ) -> None:
        self._chat = chat_client
        self._max_iterations = max_iterations
        self._max_tokens = max_tokens
        self._max_page_chars = max_page_chars

    def check(
        self,
        question: str,
        answer: str,
        doc_name: str,
        page: Optional[int],
        corpus: DocumentCorpus,
        page_label: str = "",
        evidence_snippet: str = "",
    ) -> Validation:
        if page is None:
            return Validation(Verdict.UNCHECKED, "no page was cited")

        try:
            view = corpus.page(doc_name, page)
        except Exception as exc:  # noqa: BLE001 - a missing page is not a wrong answer
            logger.warning("validation skipped, page unreadable: %s", exc)
            return Validation(Verdict.UNCHECKED, f"cited page could not be read: {exc}")

        toolset = DocumentToolset(corpus, scope_label="the whole filing")
        registry = ToolRegistry(
            document_tools(toolset) + [CalculateTool(), ReportValidationTool()]
        )
        runtime = AgentRuntime(
            self._chat,
            max_iterations=self._max_iterations,
            temperature=0.0,
            max_tokens=self._max_tokens,
        )

        run = runtime.run(
            system=VALIDATOR_SYSTEM,
            user=build_validator_prompt(
                question=question,
                answer=answer,
                doc_name=doc_name,
                page_label=page_label or view.label,
                page_text=view.text,
                evidence_snippet=evidence_snippet,
                max_chars=self._max_page_chars,
            ),
            registry=registry,
            terminal_tools=(REPORT_VALIDATION,),
        )

        if run.error:
            logger.warning("validator unavailable: %s", run.error)
            return Validation(Verdict.UNCHECKED, f"validator unavailable: {run.error}")
        if not run.reported:
            return Validation(
                Verdict.UNCHECKED,
                "validator did not return a verdict"
                + (" (iteration budget exhausted)" if run.exhausted else ""),
            )

        report = run.report or {}
        raw = str(report.get("verdict") or "").strip().lower()
        try:
            verdict = Verdict(raw)
        except ValueError:
            return Validation(Verdict.UNCHECKED, f"unrecognised verdict {raw!r}")

        return Validation(
            verdict=verdict,
            reason=str(report.get("reason") or "").strip(),
            corrected_answer=str(report.get("corrected_answer") or "").strip(),
        )
