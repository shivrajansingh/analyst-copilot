"""The harness: one message in, one proven answer or an honest refusal out.

Three tiers, and the interesting design decision is where the boundaries sit.

    message
      |
      +-- not a question about a document? answer it conversationally
      |
      +-- several questions in one? split, research each separately
      |
      +-- TIER 1  hybrid retrieval -> model -> deterministic verifier   ~3s
      |
      +-- TIER 2  a second reader checks the answer against the whole
      |           cited page                                            ~4s
      |
      +-- TIER 3  every page of the document read by parallel agents,
                  adjudicated, then deterministically verified         ~60s

Tier 1 answers most questions it can answer at all, and it is cheap. Its
weakness is structural rather than qualitative: it only ever sees the five pages
retrieval selected, and measured against the practice key that set contains the
gold page 58% of the time. No prompt improves on a page that was never
retrieved.

Tier 2 exists because tier 1's verifier checks digits, not meaning. It catches
the right figure attached to the wrong question -- the wrong fiscal year, a
segment instead of the consolidated total, half of a compound question -- which
digit-tracing passes cleanly and the rubric scores as zero.

Tier 3 has no recall ceiling because it has no shortlist. It costs roughly
fifty times tier 1, which is exactly why it runs only when the cheaper tiers
could not produce an answer that survived checking.

What never moves: the deterministic verifier is the last word on both answering
tiers. Agents propose, it disposes, and nothing reaches an analyst that the
page's own text does not support.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Sequence

from analyst_copilot.agent.conversation import ConversationResponder
from analyst_copilot.agent.corpus import DocumentCorpus, DocumentUnavailable
from analyst_copilot.agent.decompose import QuestionDecomposer
from analyst_copilot.agent.models import (
    AgentAnswer,
    AnswerMode,
    AnswerPart,
    Citation,
    EvidenceInput,
    Intent,
    Stage,
    StageEvent,
)
from analyst_copilot.agent.orchestrator import DeepSearchOrchestrator
from analyst_copilot.agent.prompts import format_history
from analyst_copilot.agent.router import IntentRouter
from analyst_copilot.agent.validator import AnswerValidator, Validation, Verdict
from analyst_copilot.agent.verification import verify_agent_answer
from analyst_copilot.config.settings import Settings, get_settings
from analyst_copilot.llm import ChatClient, get_chat_client
from analyst_copilot.parsing.models import SegmentKind
from analyst_copilot.services.qa.models import NOT_FOUND_MESSAGE, QAAnswer
from analyst_copilot.services.qa.service import QuestionAnsweringService

logger = logging.getLogger(__name__)

StageCallback = Callable[[StageEvent], None]


@dataclass
class Scope:
    """
    What one message is allowed to search.

    The corpus is resolved lazily, and that is not an optimisation. Tier 1
    indexes a document the first time it is asked about, and indexing is what
    writes the Markdown the agents read. Resolving the corpus up front would
    therefore find nothing for a document being asked about for the first time,
    and silently disable the deep path for exactly the question most likely to
    need it.
    """

    collection: Optional[str] = None
    doc_name: Optional[str] = None
    documents: List[str] = field(default_factory=list)
    build_corpus: Optional[Callable[[], Optional[DocumentCorpus]]] = None
    _corpus: Optional[DocumentCorpus] = None
    _resolved: bool = False

    @property
    def corpus(self) -> Optional[DocumentCorpus]:
        """The readable documents in scope, or None if none are readable yet."""
        if not self._resolved:
            self._resolved = True
            self._corpus = self.build_corpus() if self.build_corpus else None
        return self._corpus

    @property
    def name(self) -> str:
        return self.collection or self.doc_name or ""

    @property
    def searchable(self) -> bool:
        return bool(self.documents)


class AnalystAgent:
    """Routes a message, answers it at the cheapest tier that can prove itself."""

    def __init__(
        self,
        qa_service: Optional[QuestionAnsweringService] = None,
        chat_client: Optional[ChatClient] = None,
        collection_indexer=None,
        settings: Optional[Settings] = None,
        router: Optional[IntentRouter] = None,
        decomposer: Optional[QuestionDecomposer] = None,
        validator: Optional[AnswerValidator] = None,
        orchestrator: Optional[DeepSearchOrchestrator] = None,
        responder: Optional[ConversationResponder] = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._qa = qa_service or QuestionAnsweringService()
        self._chat_client = chat_client
        self._collection_indexer = collection_indexer
        self._router = router
        self._decomposer = decomposer
        self._validator = validator
        self._orchestrator = orchestrator
        self._responder = responder

    # -- lazily built collaborators ----------------------------------------- #
    def _chat(self) -> ChatClient:
        """
        The chat client, created on first use.

        Deferred so the harness can be constructed at process start without a
        provider being reachable, which is what lets the API boot and report
        health while a provider is briefly down.
        """
        if self._chat_client is None:
            self._chat_client = get_chat_client()
        return self._chat_client

    def _intents(self) -> IntentRouter:
        if self._router is None:
            self._router = IntentRouter(self._chat())
        return self._router

    def _splitter(self) -> QuestionDecomposer:
        if self._decomposer is None:
            self._decomposer = QuestionDecomposer(
                self._chat(), max_parts=self._settings.agent_max_parts
            )
        return self._decomposer

    def _checker(self) -> AnswerValidator:
        if self._validator is None:
            self._validator = AnswerValidator(self._chat())
        return self._validator

    def _deep(self) -> DeepSearchOrchestrator:
        if self._orchestrator is None:
            self._orchestrator = DeepSearchOrchestrator(
                self._chat(),
                pages_per_shard=self._settings.agent_pages_per_shard,
                max_concurrency=self._settings.agent_max_concurrency,
                max_shards=self._settings.agent_max_shards,
                reader_max_iterations=self._settings.agent_reader_max_iterations,
                synthesis_max_iterations=self._settings.agent_synthesis_max_iterations,
                max_tokens=self._settings.agent_max_tokens,
            )
        return self._orchestrator

    def _conversation(self) -> ConversationResponder:
        if self._responder is None:
            self._responder = ConversationResponder(self._chat())
        return self._responder

    # -- entry point -------------------------------------------------------- #
    def answer(
        self,
        message: str,
        collection: Optional[str] = None,
        doc_name: Optional[str] = None,
        history: Optional[Sequence[dict]] = None,
        on_stage: Optional[StageCallback] = None,
        scope_ready: Optional[bool] = None,
    ) -> AgentAnswer:
        """
        Answer one message.

        `scope_ready` lets a caller that already knows whether the filing is
        indexed say so, rather than having this decide from the Markdown store.
        It is checked only for a document question, which is the point: a
        greeting is answered whether or not anything has finished indexing, and
        that is exactly the case where a user is most likely to type one.
        """
        context = format_history(history or [], limit=self._settings.agent_history_turns)
        scope = self._resolve_scope(collection, doc_name)

        _emit(on_stage, StageEvent(Stage.ROUTING, "reading the message"))
        routing = self._intents().route(message, context)

        if routing.intent in (Intent.SMALLTALK, Intent.CAPABILITY):
            reply = self._conversation().reply(
                message,
                collection=scope.collection,
                documents=scope.documents,
                history=context,
            )
            _emit(on_stage, StageEvent(Stage.DONE, "replied"))
            return AgentAnswer(
                question=message,
                answer=reply,
                # A greeting was answered, so this is not a refusal -- but there
                # is nothing to cite, and callers branch on `mode` before
                # `found` for exactly this case.
                found=True,
                mode=AnswerMode.CONVERSATIONAL,
                intent=routing.intent,
                doc_name=scope.doc_name or "",
                collection=scope.collection,
                searched_documents=0,
            )

        if scope_ready is False or not scope.searchable:
            _emit(on_stage, StageEvent(Stage.DONE, "nothing to search"))
            return AgentAnswer(
                question=message,
                answer=NOT_FOUND_MESSAGE,
                found=False,
                mode=AnswerMode.FAST,
                intent=routing.intent,
                doc_name=scope.doc_name or "",
                collection=scope.collection,
                searched_documents=0,
                abstention_reason="no_indexed_documents",
            )

        parts = self._plan(message, context, on_stage)
        answered: List[AnswerPart] = []
        for number, part_question in enumerate(parts, start=1):
            answered.append(
                self._answer_part(
                    question=part_question,
                    scope=scope,
                    context=context,
                    on_stage=on_stage,
                    part=number,
                    part_total=len(parts),
                )
            )

        _emit(on_stage, StageEvent(Stage.DONE, "answered"))
        return self._compose(message, scope, routing.intent, answered)

    # -- planning ----------------------------------------------------------- #
    def _plan(
        self,
        message: str,
        context: str,
        on_stage: Optional[StageCallback],
    ) -> List[str]:
        if not self._settings.agent_decompose:
            return [message]
        _emit(on_stage, StageEvent(Stage.DECOMPOSING, "checking for multiple questions"))
        decomposition = self._splitter().split(message, context)
        if decomposition.split:
            _emit(
                on_stage,
                StageEvent(
                    Stage.DECOMPOSING,
                    f"answering {len(decomposition.parts)} questions separately",
                    total=len(decomposition.parts),
                ),
            )
        return decomposition.parts

    # -- one question ------------------------------------------------------- #
    def _answer_part(
        self,
        question: str,
        scope: Scope,
        context: str,
        on_stage: Optional[StageCallback],
        part: int,
        part_total: int,
    ) -> AnswerPart:
        located = _locator(part, part_total)

        _emit(on_stage, StageEvent(Stage.RETRIEVING, "searching the filing", **located))
        fast = self._fast_path(question, scope)
        escalation = ""

        if fast is not None and fast.found:
            validation = self._validate(question, fast, scope, on_stage, located)
            if validation.serves:
                return AnswerPart(
                    question=question,
                    answer=fast.answer,
                    found=True,
                    mode=AnswerMode.FAST,
                    citation=_citation_from_qa(fast),
                    validation=f"{validation.verdict.value}: {validation.reason}".strip(": "),
                    retrieval=fast.retrieval,
                )
            escalation = f"validation said {validation.verdict.value}: {validation.reason}"
        elif fast is not None:
            escalation = f"fast path abstained ({fast.abstention_reason or 'no answer'})"
        else:
            escalation = "fast path unavailable"

        if not (self._settings.agent_deep_search and scope.corpus is not None):
            return _abstained(question, fast, escalation)

        _emit(
            on_stage,
            StageEvent(Stage.ESCALATING, "reading the whole filing", **located),
        )
        return self._deep_path(question, scope, context, on_stage, escalation, fast, located)

    def _fast_path(self, question: str, scope: Scope) -> Optional[QAAnswer]:
        """Tier 1: the existing retrieve-and-verify pipeline, unchanged."""
        try:
            if scope.collection:
                return self._qa.answer_collection(question, scope.collection)
            if scope.doc_name:
                return self._qa.answer(question, scope.doc_name)
        except Exception as exc:  # noqa: BLE001 - tier 1 failing is a reason to escalate
            logger.warning("fast path failed for %r: %s", question[:60], exc)
            return None
        return None

    def _validate(
        self,
        question: str,
        fast: QAAnswer,
        scope: Scope,
        on_stage: Optional[StageCallback],
        located: dict,
    ):
        if not self._settings.agent_validate_answers or scope.corpus is None:
            return _served("validation disabled")

        _emit(on_stage, StageEvent(Stage.VALIDATING, "checking the answer", **located))
        return self._checker().check(
            question=question,
            answer=fast.answer,
            doc_name=fast.doc_name,
            page=fast.page,
            corpus=scope.corpus,
            page_label=fast.location_label or "",
            evidence_snippet=fast.evidence_snippet,
        )

    def _deep_path(
        self,
        question: str,
        scope: Scope,
        context: str,
        on_stage: Optional[StageCallback],
        escalation: str,
        fast: Optional[QAAnswer],
        located: dict,
    ) -> AnswerPart:
        """Tier 3: every page read, adjudicated, then deterministically verified."""
        corpus = scope.corpus
        assert corpus is not None  # guarded by the caller

        try:
            result = self._deep().search(
                question=question,
                corpus=corpus,
                context=context,
                on_stage=(
                    (lambda event: _emit(on_stage, _relocate_event(event, located)))
                    if on_stage
                    else None
                ),
            )
        except Exception as exc:  # noqa: BLE001 - a failed deep search is an abstention
            logger.exception("deep search failed for %r", question[:60])
            return _abstained(question, fast, f"{escalation}; deep search failed: {exc}")

        base = AnswerPart(
            question=question,
            answer=NOT_FOUND_MESSAGE,
            found=False,
            mode=AnswerMode.DEEP,
            escalation_reason=escalation,
            retrieval=fast.retrieval if fast else None,
            pages_read=result.pages_read,
            shards_run=result.shards_run,
        )

        if not result.found:
            base.abstention_reason = "deep_search_found_nothing"
            base.validation = result.reason
            return base

        _emit(on_stage, StageEvent(Stage.VERIFYING, "checking the evidence", **located))
        verdict = verify_agent_answer(
            answer=result.answer,
            doc_name=result.doc_name,
            page=result.page,
            quote=result.quote,
            inputs=result.inputs,
            computation=result.computation,
            page_text=_page_text_lookup(corpus),
            locate_quote=_quote_locator(corpus),
        )

        if not verdict.ok:
            # The readers found something the document does not support. That is
            # exactly what this check exists for, and abstaining is the correct
            # outcome -- a -1 costs twice what this 0 does.
            logger.info("deep answer rejected for %r: %s", question[:60], verdict.reason)
            base.abstention_reason = f"deep_unverified:{verdict.reason}"
            base.validation = verdict.reason
            return base

        base.answer = result.answer
        base.found = True
        base.citation = _citation_from_deep(verdict, corpus)
        base.inputs = list(result.inputs)
        base.computation = result.computation
        base.validation = (
            verdict.derivation.reason
            if verdict.derivation and verdict.derivation.ok
            else verdict.reason
        )
        return base

    # -- scope -------------------------------------------------------------- #
    def _resolve_scope(self, collection: Optional[str], doc_name: Optional[str]) -> Scope:
        if collection:
            documents = self._ready_documents(collection)

            def build_collection() -> Optional[DocumentCorpus]:
                ready = self._ready_documents(collection) or documents
                if not ready:
                    return None
                corpus = DocumentCorpus.for_collection(collection, ready)
                return corpus if corpus.available_documents() else None

            return Scope(
                collection=collection,
                documents=documents,
                build_corpus=build_collection,
            )

        if doc_name:

            def build_document() -> Optional[DocumentCorpus]:
                corpus = DocumentCorpus.for_document(doc_name)
                return corpus if corpus.available_documents() else None

            # `documents` is the scope's name, not proof of readiness: whether
            # anything is indexed is the caller's `scope_ready` to state.
            return Scope(
                doc_name=doc_name,
                documents=[doc_name],
                build_corpus=build_document,
            )
        return Scope()

    def _ready_documents(self, collection: str) -> List[str]:
        indexer = self._collection_indexer
        if indexer is None:
            from analyst_copilot.collections.indexer import CollectionIndexer

            indexer = self._collection_indexer = CollectionIndexer()
        try:
            return list(indexer.ready_documents(collection))
        except Exception as exc:  # noqa: BLE001 - an unreadable folder is an empty one
            logger.warning("could not list documents in %r: %s", collection, exc)
            return []

    # -- composition -------------------------------------------------------- #
    def _compose(
        self,
        message: str,
        scope: Scope,
        intent: Intent,
        parts: Sequence[AnswerPart],
    ) -> AgentAnswer:
        found_parts = [part for part in parts if part.found]
        citations = [part.citation for part in found_parts if part.citation]
        primary = citations[0] if citations else None
        deep_used = any(part.mode is AnswerMode.DEEP for part in parts)

        answer = _compose_text(parts)
        first = parts[0] if parts else None

        return AgentAnswer(
            question=message,
            answer=answer,
            found=bool(found_parts),
            mode=AnswerMode.DEEP if deep_used else AnswerMode.FAST,
            intent=intent,
            doc_name=(primary.doc_name if primary else (scope.doc_name or scope.name)),
            collection=scope.collection,
            searched_documents=len(scope.documents),
            citation=primary,
            citations=citations,
            parts=list(parts) if len(parts) > 1 else [],
            abstention_reason=(
                None if found_parts else _first_reason(parts)
            ),
            retrieval=first.retrieval if first else None,
            validation=first.validation if first else None,
            pages_read=max((part.pages_read for part in parts), default=0),
            shards_run=max((part.shards_run for part in parts), default=0),
            inputs=list(found_parts[0].inputs) if found_parts else [],
            computation=found_parts[0].computation if found_parts else "",
        )


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _compose_text(parts: Sequence[AnswerPart]) -> str:
    """
    One answer text from however many parts were researched.

    Composed here rather than by a model on purpose: a language model asked to
    merge four answers rewrites their figures, and a figure that changes after
    verification is unverified again.
    """
    if not parts:
        return NOT_FOUND_MESSAGE
    if len(parts) == 1:
        return parts[0].answer
    blocks = [f"{part.question}\n{part.answer}" for part in parts]
    return "\n\n".join(blocks)


def _first_reason(parts: Sequence[AnswerPart]) -> Optional[str]:
    for part in parts:
        if part.abstention_reason:
            return part.abstention_reason
    return "no_answer"


def _abstained(
    question: str,
    fast: Optional[QAAnswer],
    escalation: str,
) -> AnswerPart:
    return AnswerPart(
        question=question,
        answer=NOT_FOUND_MESSAGE,
        found=False,
        mode=AnswerMode.FAST,
        abstention_reason=(fast.abstention_reason if fast else "fast_path_unavailable"),
        escalation_reason=escalation,
        retrieval=fast.retrieval if fast else None,
    )


def _citation_from_qa(answer: QAAnswer) -> Optional[Citation]:
    if answer.page is None:
        return None
    return Citation(
        doc_name=answer.doc_name,
        page=answer.page,
        label=answer.location_label or f"page {answer.page + 1}",
        snippet=answer.evidence_snippet,
        segment_kind=answer.segment_kind or SegmentKind.PAGE,
        location_match=answer.location_match or "exact",
        model_cited_page=answer.cited_page,
        page_shift=answer.page_shift,
    )


def _citation_from_deep(verdict, corpus: DocumentCorpus) -> Optional[Citation]:
    if verdict.page is None:
        return None
    label = f"page {verdict.page + 1}"
    kind = SegmentKind.PAGE
    try:
        view = corpus.page(verdict.doc_name, verdict.page)
        label, kind = view.label, view.segment_kind
    except DocumentUnavailable:
        pass
    return Citation(
        doc_name=verdict.doc_name,
        page=verdict.page,
        label=label,
        snippet=verdict.snippet,
        segment_kind=kind,
        location_match=verdict.location_match,
        page_shift=verdict.page_shift,
    )


def _page_text_lookup(corpus: DocumentCorpus):
    def lookup(doc_name: str, page_index: int) -> Optional[str]:
        try:
            return corpus.page(doc_name, page_index).text
        except DocumentUnavailable:
            return None

    return lookup


def _quote_locator(corpus: DocumentCorpus):
    def locate(quote: str):
        ref = corpus.find_quote(quote)
        return (ref.doc_name, ref.page_index) if ref else None

    return locate


def _locator(part: int, part_total: int) -> dict:
    """Stage-event fields that say which sub-question is in flight."""
    if part_total <= 1:
        return {}
    return {"part": part, "part_total": part_total}


def _relocate_event(event: StageEvent, located: dict) -> StageEvent:
    if not located:
        return event
    event.part = located.get("part")
    event.part_total = located.get("part_total")
    return event


def _served(reason: str) -> Validation:
    """A non-verdict that lets the fast answer through. See `Verdict.serves`."""
    return Validation(Verdict.UNCHECKED, reason)


def _emit(callback: Optional[StageCallback], event: StageEvent, **fields) -> None:
    if callback is None:
        return
    for key, value in fields.items():
        setattr(event, key, value)
    try:
        callback(event)
    except Exception:  # noqa: BLE001 - progress must never break an answer
        logger.debug("stage callback raised", exc_info=True)
