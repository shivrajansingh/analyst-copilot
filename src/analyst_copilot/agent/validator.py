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
- **The right figures, the wrong conclusion.** "Is this business
  capital-intensive?" answered *yes* from figures that argue *no*. Every figure
  traces. The answer is the opposite of the truth.
- **The right figures, the wrong period.** A quick ratio for "Q2 FY2023"
  computed from the March balance sheet. Every digit is on the page.

Neither is detectable by tracing digits, because both are about *meaning*. So a
reader that did not write the answer is shown the question, the answer and the
whole cited page — not the 2,200-character excerpt the writer saw — and asked
whether the answer is right.

Its verdict is a gate, not a judgement. On a fast answer, `correct` serves it
and anything else escalates to the deep path. **On a deep answer there is no
further tier, so anything but `correct` abstains** — which is the right trade:
measured on the practice key, every deep answer this check rejects is a -1 that
becomes a 0, and the rubric charges twice as much for the former.

The asymmetry on the fast path is deliberate too. A false `incorrect` costs a
slow second search; a false `correct` puts a wrong figure in front of an
analyst.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Sequence

from analyst_copilot.agent.cancellation import CancelToken, token_or_never
from analyst_copilot.agent.corpus import DocumentCorpus
from analyst_copilot.agent.prompts import (
    BLIND_READER_SYSTEM,
    COMPARISON_SYSTEM,
    VALIDATOR_SYSTEM,
    build_blind_prompt,
    build_comparison_prompt,
    build_validator_prompt,
)
from analyst_copilot.agent.runtime import AgentRuntime
from analyst_copilot.agent import trace as tracing
from analyst_copilot.agent.tools import (
    REPORT_READING,
    REPORT_VALIDATION,
    CalculateTool,
    DocumentToolset,
    ReportReadingTool,
    ReportValidationTool,
    ToolRegistry,
    document_tools,
)
from analyst_copilot.agent.verification import figures_agree, figures_in
from analyst_copilot.config.settings import get_settings
from analyst_copilot.llm.base import ChatClient
from analyst_copilot.services.qa.parser import load_json_object

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


# Words that dress a figure rather than assert anything of their own. An answer
# built only from these plus a number is a figure; anything else is an argument,
# and arguments are not compared by their digits.
_UNIT_WORDS = frozenset(
    """usd dollar dollars million millions billion billions thousand thousands
    percent percentage percentage-point points bps times ratio approximately approx
    about roughly around circa fy cy quarter year years the a an of in on at to
    is was were are and or per share shares net total yes no""".split()
)
_MAX_CONTENT_WORDS = 2
_WORD = re.compile(r"[A-Za-z]+")


def _headline(text: str) -> Optional[float]:
    """
    The figure an answer asserts, or None when it is asserting prose.

    None is the important half. It routes an explanation to a judgement instead
    of to a digit comparison, and it is what stops "some number in common" from
    reading as "the same answer".
    """
    content = [
        word
        for word in (match.group(0).lower() for match in _WORD.finditer(text))
        if len(word) > 1 and word not in _UNIT_WORDS
    ]
    if len(content) > _MAX_CONTENT_WORDS:
        return None

    values = figures_in(text)
    if not values:
        return None
    # A leading fiscal year is not the claim. "FY2022 capex was 1,577" asserts
    # 1,577, and comparing 2022 instead would pass any answer about FY2022.
    real = [v for v in values if not (float(v).is_integer() and 1900 <= v <= 2100)]
    return (real or values)[0]


class AnswerValidator:
    """Re-checks a proposed answer against the full text of its cited page."""

    def __init__(
        self,
        chat_client: ChatClient,
        max_iterations: int = 6,
        max_tokens: int = 2048,
        max_page_chars: int = 24000,
        blind: Optional[bool] = None,
        retries: Optional[int] = None,
    ) -> None:
        settings = get_settings()
        self._chat = chat_client
        self._max_iterations = max_iterations
        self._max_tokens = max_tokens
        self._max_page_chars = max_page_chars
        self._blind = settings.validator_blind if blind is None else blind
        self._retries = max(
            0, settings.validator_retries if retries is None else retries
        )

    def check(
        self,
        question: str,
        answer: str,
        doc_name: str,
        page: Optional[int],
        corpus: DocumentCorpus,
        page_label: str = "",
        evidence_snippet: str = "",
        computation: str = "",
        inputs: Sequence[object] = (),
        on_trace: Optional[tracing.TraceCallback] = None,
        cancel: Optional[CancelToken] = None,
    ) -> Validation:
        stop = token_or_never(cancel)
        stop.raise_if_cancelled()
        if page is None:
            return Validation(Verdict.UNCHECKED, "no page was cited")

        try:
            view = corpus.page(doc_name, page)
        except Exception as exc:  # noqa: BLE001 - a missing page is not a wrong answer
            logger.warning("validation skipped, page unreadable: %s", exc)
            return Validation(Verdict.UNCHECKED, f"cited page could not be read: {exc}")

        if self._blind:
            blind = self._check_blind(
                question, answer, doc_name, corpus, view, inputs, on_trace, stop
            )
            if blind is not None:
                return blind
            # The blind reader could not run. Falling through to the anchored
            # check is worth more than no check at all -- it is the weaker of
            # the two, not nothing.
            logger.info("blind check unavailable, falling back to review")

        return self._check_anchored(
            question, answer, doc_name, corpus, view, page_label,
            evidence_snippet, computation, inputs, on_trace, stop,
        )

    # -- checking by re-answering ------------------------------------------- #
    def _check_blind(
        self,
        question: str,
        answer: str,
        doc_name: str,
        corpus: DocumentCorpus,
        view,
        inputs: Sequence[object],
        on_trace: Optional[tracing.TraceCallback],
        stop: CancelToken,
    ) -> Optional[Validation]:
        """
        Answer the question independently, then compare. None if it could not run.

        The proposed answer is never shown to this reader. That is what makes it
        a check rather than a review: it has nothing to agree with, so its
        answer is arrived at rather than confirmed.
        """
        registry = ToolRegistry(
            document_tools(DocumentToolset(corpus, scope_label="the whole filing"))
            + [CalculateTool(), ReportReadingTool()]
        )
        run = self._run(
            system=BLIND_READER_SYSTEM,
            user=build_blind_prompt(
                question=question,
                doc_name=doc_name,
                page_label=view.label,
                page_text=view.text,
                extra_pages=self._input_pages(corpus, inputs, view),
                max_chars=self._max_page_chars,
            ),
            registry=registry,
            terminal=REPORT_READING,
            on_trace=on_trace,
            stop=stop,
        )
        if run is None:
            return None

        report = run.report or {}
        if not bool(report.get("answered")):
            # The page does not answer the question. That is not a verdict on
            # the figures -- it is a statement that this citation cannot prove
            # them, which is exactly what `insufficient` means.
            return Validation(
                Verdict.INSUFFICIENT,
                str(report.get("reason") or "the cited page does not answer the question"),
            )

        independent = str(report.get("answer") or "").strip()
        if not independent:
            return None
        return self._compare(question, answer, independent, str(report.get("reason") or ""))

    def _compare(
        self,
        question: str,
        proposed: str,
        independent: str,
        reason: str,
    ) -> Validation:
        """
        Do the two answers say the same thing?

        Figures are compared in code. That is the half worth having: no model
        judgement, no room to be agreeable, and `figures_agree` already allows
        the rounding and rescaling that make `8.7 billion` and `8,738` the same
        reading. Prose falls back to a model, which is the best available and is
        marked as such in the reason.
        """
        mine, theirs = _headline(independent), _headline(proposed)

        # Numerically only when both answers *are* figures. Comparing the
        # numbers inside two paragraphs is worse than not comparing at all:
        # "any figure in common" is nearly always true of two explanations of
        # the same page, so three wrong answers were re-confirmed by a digit
        # they happened to share. Prose is a question about meaning; it goes to
        # the judgement below, where at least a different model is deciding.
        if mine is not None and theirs is not None:
            if figures_agree(theirs, mine):
                return Validation(
                    Verdict.CORRECT, f"read independently and agreed: {reason}".strip()
                )
            return Validation(
                Verdict.INCORRECT,
                f"read independently and got {independent!r}, not {proposed[:120]!r}. {reason}".strip(),
                corrected_answer=independent,
            )

        same, why = self._compare_prose(question, proposed, independent)
        if same is None:
            # No numbers to compare and no judgement available. Not a verdict.
            return Validation(
                Verdict.UNCHECKED,
                f"could not compare prose answers: {why}",
            )
        if same:
            return Validation(Verdict.CORRECT, f"read independently and agreed: {why}".strip())
        return Validation(
            Verdict.INCORRECT,
            f"read independently and disagreed: {why}".strip(),
            corrected_answer=independent,
        )

    def _compare_prose(self, question: str, proposed: str, independent: str):
        """Whether two prose answers agree. (None, reason) when it cannot be decided."""
        try:
            raw = self._chat.complete(
                messages=[
                    {"role": "system", "content": COMPARISON_SYSTEM},
                    {
                        "role": "user",
                        "content": build_comparison_prompt(question, proposed, independent),
                    },
                ],
                temperature=0.0,
                max_tokens=600,
            )
        except Exception as exc:  # noqa: BLE001 - a failed comparison is not a wrong answer
            return None, f"{type(exc).__name__}: {exc}"

        payload = load_json_object(raw)
        if not payload or "same" not in payload:
            return None, "the comparison did not return a verdict"
        return bool(payload.get("same")), str(payload.get("reason") or "")[:300]

    @staticmethod
    def _input_pages(corpus: DocumentCorpus, inputs: Sequence[object], view) -> list:
        """
        The pages a derived answer's inputs were read from, cited page excluded.

        A ratio is computed across two statements, so a reader given only the
        cited page cannot re-derive it and would report `answered: false` on an
        answer that is perfectly sound.
        """
        pages, seen = [], {(view.doc_name, view.page_index)}
        for item in inputs:
            name = getattr(item, "doc_name", "") or view.doc_name
            index = getattr(item, "page", None)
            if index is None or (name, index) in seen:
                continue
            seen.add((name, index))
            try:
                pages.append(corpus.page(name, index))
            except Exception:  # noqa: BLE001 - an unreadable input page is just absent
                continue
        return pages

    # -- checking by review (the earlier behaviour) -------------------------- #
    def _check_anchored(
        self,
        question: str,
        answer: str,
        doc_name: str,
        corpus: DocumentCorpus,
        view,
        page_label: str,
        evidence_snippet: str,
        computation: str,
        inputs: Sequence[object],
        on_trace: Optional[tracing.TraceCallback],
        stop: CancelToken,
    ) -> Validation:
        registry = ToolRegistry(
            document_tools(DocumentToolset(corpus, scope_label="the whole filing"))
            + [CalculateTool(), ReportValidationTool()]
        )
        run = self._run(
            system=VALIDATOR_SYSTEM,
            user=build_validator_prompt(
                question=question,
                answer=answer,
                doc_name=doc_name,
                page_label=page_label or view.label,
                page_text=view.text,
                evidence_snippet=evidence_snippet,
                max_chars=self._max_page_chars,
                computation=computation,
                inputs=inputs,
            ),
            registry=registry,
            terminal=REPORT_VALIDATION,
            on_trace=on_trace,
            stop=stop,
        )
        if run is None:
            return Validation(Verdict.UNCHECKED, "validator returned no verdict")

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

    # -- running one agent, with retries ------------------------------------- #
    def _run(
        self,
        system: str,
        user: str,
        registry: ToolRegistry,
        terminal: str,
        on_trace: Optional[tracing.TraceCallback],
        stop: CancelToken,
    ):
        """
        Run one checking agent. None when it never reported.

        Retried because a checker that returns nothing currently *serves the
        answer* -- `UNCHECKED` passes. That happened on 9 of 62 measured
        questions, two of which were wrong. One more attempt is far cheaper than
        an unchecked figure in front of an analyst.
        """
        runtime = AgentRuntime(
            self._chat,
            max_iterations=self._max_iterations,
            temperature=0.0,
            max_tokens=self._max_tokens,
        )
        for attempt in range(self._retries + 1):
            stop.raise_if_cancelled()
            run = runtime.run(
                system=system,
                user=user,
                registry=registry,
                terminal_tools=(terminal,),
                on_trace=tracing.scoped(on_trace, "checker"),
                cancel=stop,
            )
            if run.reported and not run.error:
                return run
            logger.warning(
                "checker attempt %d/%d produced no verdict: %s",
                attempt + 1,
                self._retries + 1,
                run.error or ("iteration budget exhausted" if run.exhausted else "no report"),
            )
        return None
