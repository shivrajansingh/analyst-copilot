"""Deep search: read the whole document, then adjudicate what was found.

This is the tier that has no recall ceiling. The fast path can only answer from
the five pages retrieval chose, and measured against the practice key that set
contains the gold page 58% of the time — so 42% of questions are unanswerable by
construction, however good the model is. Here every page is read by some agent,
so the ceiling is the readers' judgement rather than the retriever's.

The cost of removing that ceiling is a precision problem, and it is a real one.
A filing prints its important figures several times over, so reading 160 pages
does not surface one answer — it surfaces a dozen readers all reporting "found
it", each pointing somewhere different. Two things keep that in hand:

- **Readers cannot overlap.** Each page is assigned to exactly one reader, so
  duplicate reports are genuinely different pages, not the same page seen twice.
- **Synthesis adjudicates, and only synthesis.** It sees candidate findings
  rather than raw pages, so its input stays small however large the filing, and
  it can compare candidates on authority instead of guessing among excerpts.

After this module, the deterministic verifier still has the last word. Agents
propose; it disposes.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Sequence

from analyst_copilot.agent.corpus import DocumentCorpus
from analyst_copilot.agent.models import EvidenceInput, Finding, Stage, StageEvent
from analyst_copilot.agent.prompts import (
    NO_FINDINGS_REPORT,
    SYNTHESIS_SYSTEM,
    build_synthesis_prompt,
)
from analyst_copilot.agent.reader import ShardReader, _as_page_index
from analyst_copilot.agent.runtime import AgentRuntime
from analyst_copilot.agent.tools import (
    SUBMIT_ANSWER,
    CalculateTool,
    DocumentToolset,
    SubmitAnswerTool,
    ToolRegistry,
    document_tools,
)
from analyst_copilot.llm.base import ChatClient

logger = logging.getLogger(__name__)

StageCallback = Callable[[StageEvent], None]

# Candidates handed to synthesis. Beyond this the input stops being a shortlist
# and starts being the document again, which is what synthesis exists to avoid.
MAX_CANDIDATES = 24


@dataclass
class DeepResult:
    """What the deep path produced, before deterministic verification."""

    found: bool = False
    answer: str = ""
    doc_name: str = ""
    page: Optional[int] = None
    quote: str = ""
    reason: str = ""
    inputs: List[EvidenceInput] = field(default_factory=list)
    computation: str = ""
    findings: List[Finding] = field(default_factory=list)
    shards_run: int = 0
    pages_read: int = 0
    error: str = ""

    @property
    def candidates(self) -> List[Finding]:
        return [finding for finding in self.findings if finding.found]


class DeepSearchOrchestrator:
    """Shard the corpus, fan readers out over it, then synthesize."""

    def __init__(
        self,
        chat_client: ChatClient,
        pages_per_shard: int = 10,
        max_concurrency: int = 8,
        max_shards: int = 0,
        reader_max_iterations: int = 8,
        synthesis_max_iterations: int = 10,
        max_tokens: int = 4096,
    ) -> None:
        self._chat = chat_client
        self._pages_per_shard = pages_per_shard
        self._max_concurrency = max(1, max_concurrency)
        self._max_shards = max_shards
        self._reader_max_iterations = reader_max_iterations
        self._synthesis_max_iterations = synthesis_max_iterations
        self._max_tokens = max_tokens

    def search(
        self,
        question: str,
        corpus: DocumentCorpus,
        context: str = "",
        on_stage: Optional[StageCallback] = None,
    ) -> DeepResult:
        pages = corpus.prewarm()
        shards = corpus.shards(self._pages_per_shard)
        if self._max_shards and len(shards) > self._max_shards:
            # A bound exists so one enormous filing cannot run unbounded, but
            # dropping shards silently would report complete coverage of a
            # document that was only partly read.
            logger.warning(
                "capping deep search at %d of %d shards for %s",
                self._max_shards,
                len(shards),
                ", ".join(corpus.doc_names),
            )
            shards = shards[: self._max_shards]

        if not shards:
            return DeepResult(
                found=False,
                reason="no parsed pages are available to read",
                error="empty_corpus",
            )

        _emit(
            on_stage,
            StageEvent(
                stage=Stage.DEEP_SEARCH,
                detail=f"reading {pages} pages with {len(shards)} readers",
                done=0,
                total=len(shards),
            ),
        )

        findings = self._fan_out(question, corpus, shards, context, on_stage)
        result = DeepResult(
            findings=findings,
            shards_run=len(shards),
            pages_read=pages,
        )

        candidates = result.candidates
        _emit(
            on_stage,
            StageEvent(
                stage=Stage.SYNTHESIZING,
                detail=(
                    f"{len(candidates)} of {len(shards)} readers found something"
                    if candidates
                    else "no reader found the answer"
                ),
            ),
        )

        self._synthesize(question, corpus, result, context)
        return result

    # -- fan-out ------------------------------------------------------------ #
    def _fan_out(
        self,
        question: str,
        corpus: DocumentCorpus,
        shards: Sequence,
        context: str,
        on_stage: Optional[StageCallback],
    ) -> List[Finding]:
        reader = ShardReader(
            self._chat,
            corpus,
            max_iterations=self._reader_max_iterations,
            max_tokens=self._max_tokens,
        )
        findings: List[Finding] = []
        completed = 0

        with ThreadPoolExecutor(
            max_workers=min(self._max_concurrency, len(shards)),
            thread_name_prefix="reader",
        ) as pool:
            futures = {
                pool.submit(reader.read, question, shard, context): shard
                for shard in shards
            }
            for future in as_completed(futures):
                shard = futures[future]
                try:
                    finding = future.result()
                except Exception as exc:  # noqa: BLE001 - one reader must not end the search
                    logger.warning("reader %s raised: %s", shard.index, exc)
                    finding = Finding(
                        found=False, shard=shard.index, reasoning=f"reader crashed: {exc}"
                    )
                findings.append(finding)
                completed += 1
                _emit(
                    on_stage,
                    StageEvent(
                        stage=Stage.DEEP_SEARCH,
                        detail=(
                            f"reader {shard.index} found evidence"
                            if finding.found
                            else f"reader {shard.index}: nothing here"
                        ),
                        done=completed,
                        total=len(shards),
                    ),
                )

        findings.sort(key=lambda item: (item.shard or 0))
        return findings

    # -- synthesis ---------------------------------------------------------- #
    def _synthesize(
        self,
        question: str,
        corpus: DocumentCorpus,
        result: DeepResult,
        context: str,
    ) -> None:
        candidates = result.candidates
        if not candidates:
            result.found = False
            result.reason = (
                "Every page of the document was read and no page answered the question."
            )
            return

        # One candidate that is neither partial nor computed needs no
        # adjudication: there is nothing to compare it against, and a synthesis
        # call over a single finding only adds a chance to paraphrase it wrongly.
        if len(candidates) == 1 and not candidates[0].partial:
            only = candidates[0]
            result.found = True
            result.answer = only.answer
            result.doc_name = only.doc_name
            result.page = only.page
            result.quote = only.quote
            result.inputs = list(only.inputs)
            result.computation = only.computation
            result.reason = only.why_authoritative or "the only page that answered"
            return

        ranked = sorted(
            candidates,
            key=lambda item: (not item.partial, item.confidence),
            reverse=True,
        )[:MAX_CANDIDATES]

        toolset = DocumentToolset(corpus, scope_label="the whole filing")
        registry = ToolRegistry(
            document_tools(toolset) + [CalculateTool(), SubmitAnswerTool()]
        )
        runtime = AgentRuntime(
            self._chat,
            max_iterations=self._synthesis_max_iterations,
            temperature=0.0,
            max_tokens=self._max_tokens,
        )

        run = runtime.run(
            system=SYNTHESIS_SYSTEM,
            user=build_synthesis_prompt(
                question=question,
                findings_report=format_findings(ranked) or NO_FINDINGS_REPORT,
                documents=corpus.available_documents(),
                pages_read=result.pages_read,
                context=context,
            ),
            registry=registry,
            terminal_tools=(SUBMIT_ANSWER,),
        )

        if run.error or not run.reported:
            # Synthesis failed, but the readers' work is still good. Fall back to
            # the strongest candidate rather than discarding a whole fan-out
            # because the adjudicator timed out; the verifier still gates it.
            best = ranked[0]
            logger.warning(
                "synthesis unavailable (%s); falling back to reader %s",
                run.error or "no report",
                best.shard,
            )
            result.found = True
            result.answer = best.answer
            result.doc_name = best.doc_name
            result.page = best.page
            result.quote = best.quote
            result.inputs = list(best.inputs)
            result.computation = best.computation
            result.reason = "synthesis unavailable; strongest single finding used"
            return

        report = run.report or {}
        if not bool(report.get("found")):
            result.found = False
            result.reason = str(report.get("reason") or "the findings did not prove an answer")
            return

        doc_name = _resolve_doc(str(report.get("doc_name") or ""), corpus, ranked)
        result.found = True
        result.answer = str(report.get("answer") or "").strip()
        result.doc_name = doc_name
        result.page = _as_page_index(report.get("page"))
        result.quote = str(report.get("quote") or "").strip()
        result.reason = str(report.get("reason") or "").strip()
        result.computation = str(report.get("computation") or "").strip()
        result.inputs = _inputs_from(report.get("inputs"), doc_name)

        if not result.answer:
            result.found = False
            result.reason = "synthesis reported found with no answer"


# --------------------------------------------------------------------------- #
# formatting
# --------------------------------------------------------------------------- #
def format_findings(findings: Sequence[Finding]) -> str:
    """
    Render candidate findings for the synthesis prompt.

    Each candidate carries its page, its quote and its reasoning, because the
    decision synthesis has to make is which page is authoritative — and that is
    an argument about provenance, not about which figure looks nicest.
    """
    blocks: List[str] = []
    for number, finding in enumerate(findings, start=1):
        header = (
            f"[{number}] {finding.doc_name} page {(finding.page or 0) + 1}"
            f"  confidence {finding.confidence:.2f}"
            f"{'  PARTIAL' if finding.partial else ''}"
        )
        lines = [header, f"    answer: {finding.answer}"]
        if finding.quote:
            lines.append(f"    quote: {_one_line(finding.quote, 300)}")
        if finding.why_authoritative:
            lines.append(f"    why this page: {_one_line(finding.why_authoritative, 240)}")
        if finding.is_derived:
            sources = "; ".join(
                f"{item.label}={item.value}"
                + (f" (page {item.page + 1})" if item.page is not None else "")
                for item in finding.inputs
            )
            lines.append(f"    computed: {finding.computation}")
            lines.append(f"    from: {sources}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _one_line(text: str, limit: int) -> str:
    flattened = " ".join(text.split())
    return flattened[:limit] + ("..." if len(flattened) > limit else "")


def _resolve_doc(
    reported: str,
    corpus: DocumentCorpus,
    candidates: Sequence[Finding],
) -> str:
    """The document a synthesis citation names, matched loosely against reality."""
    available = corpus.available_documents()
    if reported:
        if reported in available:
            return reported
        slugs = {_slug(name): name for name in available}
        match = slugs.get(_slug(reported))
        if match:
            return match
    if candidates:
        return candidates[0].doc_name
    return available[0] if available else ""


def _slug(value: str) -> str:
    return "".join(character for character in value.lower() if character.isalnum())


def _inputs_from(raw: object, doc_name: str) -> List[EvidenceInput]:
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


def _emit(callback: Optional[StageCallback], event: StageEvent) -> None:
    if callback is None:
        return
    try:
        callback(event)
    except Exception:  # noqa: BLE001 - progress reporting must never break a search
        logger.debug("stage callback raised", exc_info=True)
