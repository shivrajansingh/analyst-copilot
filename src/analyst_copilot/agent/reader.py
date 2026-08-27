"""One reader agent, responsible for one slice of one document.

A reader is deliberately narrow. It sees ten pages, it may read only those ten,
and it reports on nothing else. That narrowness is what makes the fan-out sound:
because every page belongs to exactly one reader, the union of the readers has
read the whole filing — and because no two readers can see the same page, two
agents cannot report the same figure from the same place and inflate a
consensus that was never independent.

The reader's report is corrected in one respect before it leaves here. A model
that quotes a table row correctly but attributes it to the neighbouring page is
common, and the quote is the more reliable of the two signals — so when the
quote is verbatim on a different page of the reader's own slice, the finding is
re-anchored there. This never changes an answer, only where it is said to live.
"""

from __future__ import annotations

import logging
import re
from typing import List, Optional

from analyst_copilot.agent.corpus import DocumentCorpus, DocumentUnavailable, Shard
from analyst_copilot.agent.models import EvidenceInput, Finding
from analyst_copilot.agent.prompts import READER_SYSTEM, build_reader_prompt
from analyst_copilot.agent.runtime import AgentRun, AgentRuntime
from analyst_copilot.agent.tools import (
    REPORT_FINDING,
    CalculateTool,
    DocumentToolset,
    ReportFindingTool,
    ToolRegistry,
    document_tools,
)
from analyst_copilot.llm.base import ChatClient

logger = logging.getLogger(__name__)

# Long enough that a table row with its header can be matched, short enough that
# a model's paraphrase of a heading cannot pass as a quotation.
MIN_QUOTE_CHARS = 24


class ShardReader:
    """Runs one reader agent over one shard and returns its finding."""

    def __init__(
        self,
        chat_client: ChatClient,
        corpus: DocumentCorpus,
        max_iterations: int = 8,
        max_tool_calls: int = 24,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> None:
        self._chat = chat_client
        self._corpus = corpus
        self._max_iterations = max_iterations
        self._max_tool_calls = max_tool_calls
        self._max_tokens = max_tokens
        self._temperature = temperature

    def read(self, question: str, shard: Shard, context: str = "") -> Finding:
        """Read one shard. Never raises: a failed reader is a not-found reader."""
        if not shard.pages:
            return Finding(found=False, shard=shard.index)

        doc_name = shard.pages[0].doc_name
        toolset = DocumentToolset(
            self._corpus,
            allowed=[page.ref for page in shard.pages],
            scope_label=shard.describe(),
        )
        registry = ToolRegistry(
            document_tools(toolset) + [CalculateTool(), ReportFindingTool()]
        )
        runtime = AgentRuntime(
            self._chat,
            max_iterations=self._max_iterations,
            max_tool_calls=self._max_tool_calls,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
        )

        run = runtime.run(
            system=READER_SYSTEM,
            user=build_reader_prompt(
                question=question,
                doc_name=doc_name,
                pages=shard.pages,
                shard_index=shard.index,
                shard_total=shard.total,
                context=context,
            ),
            registry=registry,
            terminal_tools=(REPORT_FINDING,),
        )

        finding = self._to_finding(run, shard, doc_name)
        finding.shard = shard.index
        return finding

    # -- conversion --------------------------------------------------------- #
    def _to_finding(self, run: AgentRun, shard: Shard, doc_name: str) -> Finding:
        if run.error:
            logger.warning("reader %d failed: %s", shard.index, run.error)
            return Finding(found=False, reasoning=f"reader failed: {run.error}")
        if not run.reported:
            # Ran out of iterations without reporting, or answered in prose.
            # Neither is a finding: an unstructured claim is exactly what the
            # terminal tool exists to prevent being treated as evidence.
            return Finding(
                found=False,
                reasoning=(
                    "reader did not report a finding"
                    + (" (iteration budget exhausted)" if run.exhausted else "")
                ),
            )

        report = run.report or {}
        found = bool(report.get("found"))
        partial = bool(report.get("partial"))
        if not found and not partial:
            return Finding(found=False, reasoning=str(report.get("why_authoritative") or ""))

        answer = str(report.get("answer") or "").strip()
        quote = str(report.get("quote") or "").strip()
        inputs = self._inputs(report.get("inputs"), doc_name)

        if found and not answer:
            return Finding(found=False, reasoning="reported found with no answer")
        if not found and not (inputs or answer or quote):
            # A partial has to carry something the adjudicator can use. Saying
            # "I have part of it" without the figures is not a contribution.
            return Finding(
                found=False, reasoning="reported partial with nothing to contribute"
            )

        page_index = self._resolve_page(shard, report.get("page"), quote)
        if page_index is None and found:
            return Finding(
                found=False,
                reasoning=(
                    f"reported page {report.get('page')!r} is not in this reader's slice "
                    "and the quote could not be located in it"
                ),
            )

        return Finding(
            found=found,
            answer=answer,
            doc_name=doc_name,
            # A partial may have no single page of its own: its figures carry
            # their own pages in `inputs`.
            page=page_index,
            quote=quote,
            why_authoritative=str(report.get("why_authoritative") or "").strip(),
            inputs=inputs,
            computation=str(report.get("computation") or "").strip(),
            confidence=_as_float(report.get("confidence"), default=0.5),
            partial=partial,
        )

    def _resolve_page(
        self,
        shard: Shard,
        reported: object,
        quote: str,
    ) -> Optional[int]:
        """
        The 0-based page index this finding belongs to.

        Tools speak the 1-based page numbers a reader was shown; citations are
        0-based. This is the single place the two meet, and it prefers the quote
        over the number whenever they disagree.
        """
        by_quote = self._page_bearing(shard, quote)
        reported_index = _as_page_index(reported)

        if reported_index is not None and shard.contains(
            shard.pages[0].doc_name, reported_index
        ):
            if by_quote is not None and by_quote != reported_index:
                logger.debug(
                    "reader %d quoted page %d but cited %d; using the quote",
                    shard.index,
                    by_quote + 1,
                    reported_index + 1,
                )
                return by_quote
            return reported_index

        # Reported page is missing or outside the slice: the quote decides, and
        # if there is no usable quote there is nothing to anchor.
        return by_quote

    def _page_bearing(self, shard: Shard, quote: str) -> Optional[int]:
        """Which page of the shard carries this quote verbatim, if any."""
        compact = _compact(quote)
        if len(compact) < MIN_QUOTE_CHARS:
            return None
        needle = compact[:200]
        for page in shard.pages:
            try:
                text = self._corpus.page(page.doc_name, page.page_index).text
            except DocumentUnavailable:
                continue
            if needle in _compact(text):
                return page.page_index
        return None

    @staticmethod
    def _inputs(raw: object, doc_name: str) -> List[EvidenceInput]:
        if not isinstance(raw, list):
            return []
        inputs: List[EvidenceInput] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or "").strip()
            value = str(item.get("value") or "").strip()
            if not label or not value:
                continue
            inputs.append(
                EvidenceInput(
                    label=label,
                    value=value,
                    doc_name=str(item.get("doc_name") or doc_name),
                    page=_as_page_index(item.get("page")),
                )
            )
        return inputs


def _as_page_index(value: object) -> Optional[int]:
    """A 1-based page number from a model becomes a 0-based page index."""
    if value is None or isinstance(value, bool):
        return None
    try:
        display = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return display - 1 if display >= 1 else None


def _as_float(value: object, default: float = 0.0) -> float:
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return min(1.0, max(0.0, parsed))


def _compact(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())
