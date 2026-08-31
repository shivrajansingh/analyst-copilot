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
from typing import Callable, Dict, List, Optional, Sequence

from analyst_copilot import usage as metering
from analyst_copilot.agent.cancellation import CancelToken, Cancelled, token_or_never
from analyst_copilot.agent.cards import DocumentCard, cards_for
from analyst_copilot.agent.conversation import ConversationReply, ConversationResponder
from analyst_copilot.agent.facts import corpus_facts, thread_facts, thread_summary
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
from analyst_copilot.agent.planner import Plan, PlanKind, Planner
from analyst_copilot.agent.recall import HistoryAnswerer
from analyst_copilot.agent.validator import AnswerValidator, Validation, Verdict
from analyst_copilot.agent import trace as tracing
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

    @property
    def corpus(self) -> Optional[DocumentCorpus]:
        """
        The readable documents in scope, or None if none are readable yet.

        Only a *successful* resolution is cached. Tier 1 writes the Markdown the
        agents read, so anything that peeks before it -- the planner building
        document cards, for one -- would otherwise latch None in for the whole
        request and silently disable the deep path.
        """
        if self._corpus is None and self.build_corpus is not None:
            self._corpus = self.build_corpus()
        return self._corpus

    def page_counts(self) -> Dict[str, int]:
        """
        Pages per document, for the planner's cards. Empty is fine.

        Never forces anything: if the Markdown is not written yet the cards
        simply carry no page counts, which costs the planner nothing.
        """
        corpus = self.corpus
        return corpus.page_counts() if corpus is not None else {}

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
        planner: Optional[Planner] = None,
        decomposer: Optional[QuestionDecomposer] = None,
        validator: Optional[AnswerValidator] = None,
        orchestrator: Optional[DeepSearchOrchestrator] = None,
        responder: Optional[ConversationResponder] = None,
        recaller: Optional[HistoryAnswerer] = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._qa = qa_service or QuestionAnsweringService()
        self._chat_client = chat_client
        self._collection_indexer = collection_indexer
        self._planner_agent = planner
        self._decomposer = decomposer
        self._validator = validator
        self._orchestrator = orchestrator
        self._responder = responder
        self._recaller = recaller

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

    def _planner(self) -> Planner:
        if self._planner_agent is None:
            self._planner_agent = Planner(
                self._chat(),
                scope_documents=self._settings.planner_scope_documents,
                require_named_year=self._settings.planner_scope_requires_year,
                min_confidence=self._settings.planner_min_confidence,
            )
        return self._planner_agent

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

    def _recall(self) -> HistoryAnswerer:
        if self._recaller is None:
            self._recaller = HistoryAnswerer(self._chat())
        return self._recaller

    # -- entry point -------------------------------------------------------- #
    def answer(
        self,
        message: str,
        collection: Optional[str] = None,
        doc_name: Optional[str] = None,
        history: Optional[Sequence[dict]] = None,
        on_stage: Optional[StageCallback] = None,
        scope_ready: Optional[bool] = None,
        on_trace: Optional[tracing.TraceCallback] = None,
        cancel: Optional[CancelToken] = None,
        meter: Optional[metering.UsageMeter] = None,
    ) -> AgentAnswer:
        """
        Answer one message.

        `scope_ready` lets a caller that already knows whether the filing is
        indexed say so, rather than having this decide from the Markdown store.
        It is checked only for a document question, which is the point: a
        greeting is answered whether or not anything has finished indexing, and
        that is exactly the case where a user is most likely to type one.

        `cancel` stops the run. It raises `Cancelled` out of this method rather
        than returning an abstention, because "stopped" and "the filing does not
        say" are different facts and only one of them is about the document.

        `meter` counts what the answer costs. It is bound to the context here
        rather than threaded through the twenty calls below, and the binding
        happens *inside* this method on purpose: the pipeline runs in a worker
        thread, and a context set by the caller is not reliably the context this
        body runs in.
        """
        with metering.metering(meter):
            return self._answer(
                message, collection, doc_name, history, on_stage, scope_ready,
                on_trace, cancel,
            )

    def _answer(
        self,
        message: str,
        collection: Optional[str],
        doc_name: Optional[str],
        history: Optional[Sequence[dict]],
        on_stage: Optional[StageCallback],
        scope_ready: Optional[bool],
        on_trace: Optional[tracing.TraceCallback],
        cancel: Optional[CancelToken],
    ) -> AgentAnswer:
        stop = token_or_never(cancel)
        context = format_history(history or [], limit=self._settings.agent_history_turns)
        scope = self._resolve_scope(collection, doc_name)
        cards = cards_for(scope.documents, scope.page_counts())

        stop.raise_if_cancelled()
        _emit(on_stage, StageEvent(Stage.PLANNING, "deciding what this needs"))
        with metering.stage(Stage.PLANNING.value, "Understood the question"):
            plan = self._decide(message, cards, context, on_trace)

        if plan.kind is PlanKind.HISTORY and self._settings.planner_recall_history:
            recalled = self._answer_from_history(
                message, plan, scope, history or [], on_stage, on_trace
            )
            if recalled is not None:
                return recalled
            # Nothing in the thread answered it. This is the expected outcome
            # more often than not, and it costs one call before the ordinary
            # search runs -- which is why recall is only ever allowed to restate.
            plan = Plan(
                kind=PlanKind.DOCUMENT,
                question=plan.question,
                documents=plan.documents,
                confidence=plan.confidence,
                reason="not already answered in this thread; searching the filing",
            )
            tracing.emit(on_trace, tracing.thought("planner", plan.reason))

        if plan.kind is PlanKind.HISTORY:
            # Recall is switched off, so the thread is not consulted and the
            # message is searched like any other question.
            plan = Plan(
                kind=PlanKind.DOCUMENT,
                question=plan.question,
                documents=plan.documents,
                confidence=plan.confidence,
                reason="recall disabled; searching the filing",
            )

        if not plan.kind.needs_documents:
            answered = self._answer_without_documents(
                message, plan, scope, cards, context, history or [], on_stage, on_trace
            )
            if answered is not None:
                return answered
            # The reply handed it back: it needed the document after all. This is
            # the escape that stops a misclassification from being final.
            plan = Plan(
                kind=PlanKind.DOCUMENT,
                question=plan.question,
                documents=[],
                confidence=0.0,
                reason=f"{plan.kind.value} reply asked for the document",
            )
            tracing.emit(on_trace, tracing.thought("planner", plan.reason))

        if scope_ready is False or not scope.searchable:
            _emit(on_stage, StageEvent(Stage.DONE, "nothing to search"))
            return AgentAnswer(
                question=message,
                answer=NOT_FOUND_MESSAGE,
                found=False,
                mode=AnswerMode.FAST,
                intent=_intent_of(plan.kind),
                doc_name=scope.doc_name or "",
                collection=scope.collection,
                searched_documents=0,
                abstention_reason="no_indexed_documents",
            )

        # Researched in its resolved form -- "and the year before?" cannot be
        # retrieved for, and every stage below needs a question that stands alone.
        parts = self._plan(plan.question, context, on_stage, stop)
        answered: List[AnswerPart] = []
        for number, part_question in enumerate(parts, start=1):
            # Between sub-questions: a compound question is several runs' worth
            # of work, and stopping during the second should not pay for a third.
            stop.raise_if_cancelled()
            answered.append(
                self._answer_part(
                    question=part_question,
                    scope=scope,
                    context=context,
                    on_stage=on_stage,
                    part=number,
                    part_total=len(parts),
                    on_trace=on_trace,
                    cancel=stop,
                    plan=plan,
                )
            )

        _emit(on_stage, StageEvent(Stage.DONE, "answered"))
        return self._compose(message, scope, plan, answered)

    # -- deciding ----------------------------------------------------------- #
    def _decide(
        self,
        message: str,
        cards: Sequence[DocumentCard],
        context: str,
        on_trace: Optional[tracing.TraceCallback],
    ) -> Plan:
        """Ask the planner what this message needs, and report what it said."""
        if not self._settings.planner_enabled:
            return Plan(
                kind=PlanKind.DOCUMENT,
                question=message,
                reason="planner disabled",
                assumed=True,
            )

        tracing.emit(
            on_trace, tracing.agent_status("planner", tracing.AgentStatus.RUNNING)
        )
        plan = self._planner().plan(message, cards, context)

        told = f"{plan.kind.value}"
        if plan.question != message:
            told += f" · rewritten as: {plan.question}"
        if plan.scoped:
            told += f" · searching only {', '.join(plan.documents)}"
        if plan.reason:
            told += f" — {plan.reason}"
        tracing.emit(on_trace, tracing.thought("planner", told))
        tracing.emit(
            on_trace, tracing.agent_status("planner", tracing.AgentStatus.FOUND)
        )
        return plan

    def _answer_without_documents(
        self,
        message: str,
        plan: Plan,
        scope: Scope,
        cards: Sequence[DocumentCard],
        context: str,
        history: Sequence[dict],
        on_stage: Optional[StageCallback],
        on_trace: Optional[tracing.TraceCallback],
    ) -> Optional[AgentAnswer]:
        """
        Answer a message that needs no document read, or hand it back.

        Returns None when the reply decided it needed the document after all --
        the escape that keeps a misclassification from being final. A question
        about the document *set* gets pre-computed facts and is forbidden from
        calculating from them, because there is no verifier on this path.
        """
        # Pre-computed answers for the two kinds that ask *about* something
        # rather than *from* it. Both are counted in Python; the prompt forbids
        # the model from working either out, because nothing verifies this path.
        facts = ""
        if plan.kind is PlanKind.CORPUS_META:
            facts = corpus_facts(cards, scope.collection or scope.doc_name or "")
        elif plan.kind is PlanKind.THREAD_META:
            facts = thread_facts(history)
        with metering.stage("conversational", "Answered directly"):
            reply = self._conversation().reply(
                message,
                collection=scope.collection,
                documents=scope.documents,
                history=context,
                facts=facts,
            )
        if reply.needs_document and plan.kind is not PlanKind.THREAD_META:
            _emit(on_stage, StageEvent(Stage.PLANNING, "this needs the filing after all"))
            return None
        if reply.needs_document:
            # A question about the transcript asked for the document. No filing
            # holds what the analyst typed, so honouring the escape here would
            # read every page to fail. Answer from the facts instead.
            logger.warning("thread_meta reply asked for the document; answering from the thread")
            reply = ConversationReply(text=thread_summary(history))

        _emit(on_stage, StageEvent(Stage.DONE, "replied"))
        return AgentAnswer(
            question=message,
            answer=reply.text,
            # The message was answered, so this is not a refusal -- but there is
            # nothing to cite, and callers branch on `mode` before `found` for
            # exactly this case.
            found=True,
            mode=AnswerMode.CONVERSATIONAL,
            intent=_intent_of(plan.kind),
            doc_name=scope.doc_name or "",
            collection=scope.collection,
            searched_documents=0,
            validation=plan.reason or None,
        )

    # -- recall -------------------------------------------------------------- #
    def _answer_from_history(
        self,
        message: str,
        plan: Plan,
        scope: Scope,
        history: Sequence[dict],
        on_stage: Optional[StageCallback],
        on_trace: Optional[tracing.TraceCallback],
    ) -> Optional[AgentAnswer]:
        """
        Restate an answer this thread already proved, or hand the message back.

        Returns None whenever the thread cannot answer it, which is the common
        case and not a failure -- the caller then searches normally. The citation
        is the source turn's own, never a new one: the page shown is a page that
        was retrieved and verified when the figure was first produced.
        """
        _emit(on_stage, StageEvent(Stage.PLANNING, "checking what we already covered"))
        with metering.stage("recall", "Checked the conversation"):
            recollection = self._recall().recall(message, history)

        if not recollection.found or recollection.source is None:
            tracing.emit(
                on_trace,
                tracing.thought("recall", recollection.reason or "not answered in this thread"),
            )
            return None

        source = recollection.source
        tracing.emit(
            on_trace,
            tracing.thought("recall", recollection.reason or "restated an earlier answer"),
        )
        citation = Citation(
            doc_name=source.doc_name or scope.doc_name or "",
            page=source.page or 0,
            label=f"page {(source.page or 0) + 1}",
            # The snippet is the earlier answer, not page text. Nothing was read
            # on this path, and inventing a quotation from a page we did not open
            # is exactly the dishonesty the citation exists to prevent.
            snippet=source.content,
        )
        _emit(on_stage, StageEvent(Stage.DONE, "answered from earlier in this conversation"))
        return AgentAnswer(
            question=message,
            answer=recollection.answer,
            found=True,
            mode=AnswerMode.FAST,
            intent=_intent_of(PlanKind.DOCUMENT),
            doc_name=citation.doc_name,
            collection=scope.collection,
            searched_documents=0,
            citation=citation,
            citations=[citation],
            recalled=True,
            validation=(
                "Restated from earlier in this conversation, with that answer's "
                "original citation. Nothing was re-read."
            ),
        )

    # -- planning ----------------------------------------------------------- #
    def _plan(
        self,
        message: str,
        context: str,
        on_stage: Optional[StageCallback],
        cancel: Optional[CancelToken] = None,
    ) -> List[str]:
        if not self._settings.agent_decompose:
            return [message]
        token_or_never(cancel).raise_if_cancelled()
        _emit(on_stage, StageEvent(Stage.DECOMPOSING, "checking for multiple questions"))
        with metering.stage(Stage.DECOMPOSING.value, "Checked for several questions"):
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
        on_trace: Optional[tracing.TraceCallback] = None,
        cancel: Optional[CancelToken] = None,
        plan: Optional[Plan] = None,
    ) -> AnswerPart:
        stop = token_or_never(cancel)
        located = _locator(part, part_total)

        stop.raise_if_cancelled()
        _emit(on_stage, StageEvent(Stage.RETRIEVING, "searching the filing", **located))
        fast = self._fast_path(question, scope)
        escalation = ""

        if fast is not None and fast.found:
            validation = self._validate(
                question, fast, scope, on_stage, located, on_trace, stop
            )
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

        # The tier boundary worth guarding hardest: everything after this line
        # is the sixty-second path, and none of it should begin for a run that
        # has already been stopped.
        stop.raise_if_cancelled()
        _emit(
            on_stage,
            StageEvent(Stage.ESCALATING, "reading the whole filing", **located),
        )
        return self._deep_path(
            question, scope, context, on_stage, escalation, fast, located, on_trace,
            stop, plan,
        )

    def _fast_path(self, question: str, scope: Scope) -> Optional[QAAnswer]:
        """
        Tier 1: the existing retrieve-and-verify pipeline, unchanged.

        Uninterruptible once entered, and left that way deliberately: it is a
        retrieval and a single model call, so the whole tier is shorter than the
        one in-flight call a checkpoint inside it could save.
        """
        try:
            with metering.stage(Stage.RETRIEVING.value, "Read the retrieved pages"):
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
        on_trace: Optional[tracing.TraceCallback] = None,
        cancel: Optional[CancelToken] = None,
    ):
        stop = token_or_never(cancel)
        if not self._settings.agent_validate_answers:
            return _served("validation disabled")
        if scope.corpus is None:
            # Nothing parsed to check against. The fast answer already passed the
            # deterministic evidence check, so it is served rather than lost.
            return _served("no parsed pages to check the answer against")

        _emit(on_stage, StageEvent(Stage.VALIDATING, "checking the answer", **located))
        tracing.emit(
            on_trace, tracing.agent_status("checker", tracing.AgentStatus.RUNNING)
        )
        with metering.stage(Stage.VALIDATING.value, "Checked the answer"):
            validation = self._checker().check(
                question=question,
                answer=fast.answer,
                doc_name=fast.doc_name,
                page=fast.page,
                corpus=scope.corpus,
                page_label=fast.location_label or "",
                evidence_snippet=fast.evidence_snippet,
                on_trace=on_trace,
                cancel=stop,
            )
        _report_verdict(on_trace, validation)
        return validation

    def _deep_path(
        self,
        question: str,
        scope: Scope,
        context: str,
        on_stage: Optional[StageCallback],
        escalation: str,
        fast: Optional[QAAnswer],
        located: dict,
        on_trace: Optional[tracing.TraceCallback] = None,
        cancel: Optional[CancelToken] = None,
        plan: Optional[Plan] = None,
    ) -> AnswerPart:
        """Tier 3: every page in scope read, adjudicated, then verified."""
        stop = token_or_never(cancel)
        corpus = scope.corpus
        assert corpus is not None  # guarded by the caller

        relay = (
            (lambda event: _emit(on_stage, _relocate_event(event, located)))
            if on_stage
            else None
        )
        scope_used = list(plan.documents) if (plan and plan.documents) else []

        try:
            result = self._deep().search(
                question=question,
                corpus=corpus,
                context=context,
                on_stage=relay,
                on_trace=on_trace,
                cancel=stop,
                only=scope_used or None,
            )

            # The scope was a hypothesis. If the documents the planner chose held
            # nothing, read the ones it skipped before giving up -- a wrong guess
            # should cost time, not the answer. Only worth doing when something
            # was actually skipped.
            if (
                not result.found
                and scope_used
                and self._settings.planner_widen_on_empty
                and corpus.scoped_documents(excluding=scope_used)
            ):
                logger.info(
                    "widening past the planner's scope for %r: %s held nothing",
                    question[:60],
                    ", ".join(scope_used),
                )
                _emit(
                    on_stage,
                    StageEvent(
                        Stage.ESCALATING,
                        "nothing in the chosen documents — widening the search",
                        **located,
                    ),
                )
                tracing.emit(
                    on_trace,
                    tracing.thought(
                        "planner",
                        "the documents I chose held nothing; reading the rest",
                    ),
                )
                widened = self._deep().search(
                    question=question,
                    corpus=corpus,
                    context=context,
                    on_stage=relay,
                    on_trace=on_trace,
                    cancel=stop,
                    excluding=scope_used,
                )
                # Carry the cost of both passes: the reader should see what the
                # question actually took, not what the second half of it took.
                widened.pages_read += result.pages_read
                widened.shards_run += result.shards_run
                result = widened
        except Cancelled:
            # Not a failed search. The clause below turns failures into
            # abstentions, and an abstention says the filing does not answer the
            # question -- which nobody established, because nobody finished
            # looking.
            raise
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

        # The same meaning check the fast path gets. The deterministic verifier
        # has proved the figures are on the page; it cannot tell whether they
        # are the right figures for the question -- the wrong period's column,
        # a conclusion that contradicts its own numbers, a list with an item too
        # many. Measured on the practice key, those are what the deep path gets
        # wrong, and there is no tier after this one, so a doubt abstains.
        _emit(on_stage, StageEvent(Stage.VALIDATING, "checking the answer", **located))
        validation = self._validate_deep(question, result, verdict, scope, on_trace, stop)
        if not validation.serves:
            logger.info(
                "deep answer withheld for %r: %s", question[:60], validation.reason
            )
            base.abstention_reason = f"deep_rejected:{validation.verdict.value}"
            base.validation = f"{validation.verdict.value}: {validation.reason}"
            return base

        base.answer = result.answer
        base.found = True
        base.citation = _citation_from_deep(verdict, corpus)
        base.inputs = list(result.inputs)
        base.computation = result.computation
        base.validation = (
            validation.reason
            or (
                verdict.derivation.reason
                if verdict.derivation and verdict.derivation.ok
                else verdict.reason
            )
        )
        return base

    def _validate_deep(
        self,
        question: str,
        result,
        verdict,
        scope: Scope,
        on_trace: Optional[tracing.TraceCallback] = None,
        cancel: Optional[CancelToken] = None,
    ):
        """
        Check a deep answer's meaning against the page it was cited to.

        The derivation is passed through when there is one, so the validator
        knows a computed figure is *expected* to be absent from the page and
        judges whether the inputs and the operation were the right ones instead
        of hunting for a number that was never printed.
        """
        if not self._settings.agent_validate_answers or scope.corpus is None:
            return _served("validation disabled")
        tracing.emit(
            on_trace, tracing.agent_status("checker", tracing.AgentStatus.RUNNING)
        )
        validation = self._checker().check(
            question=question,
            answer=result.answer,
            doc_name=verdict.doc_name,
            page=verdict.page,
            corpus=scope.corpus,
            evidence_snippet=verdict.snippet,
            computation=result.computation,
            inputs=result.inputs,
            on_trace=on_trace,
            cancel=token_or_never(cancel),
        )
        _report_verdict(on_trace, validation)
        return validation

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
        plan: Plan,
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
            intent=_intent_of(plan.kind),
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


def _intent_of(kind: PlanKind) -> Intent:
    """
    The plan's kind as the wire's `intent`.

    The API has reported three intents since before the planner existed, and
    `corpus_meta` and `thread_meta` are later additions. Both map onto
    `capability` because that is what they are from a caller's point of view -- a
    question about the assistant's holdings or about the session itself, answered
    without citing a document.
    """
    if kind is PlanKind.SMALLTALK:
        return Intent.SMALLTALK
    if kind in (PlanKind.CAPABILITY, PlanKind.CORPUS_META, PlanKind.THREAD_META):
        return Intent.CAPABILITY
    return Intent.DOCUMENT_QUESTION


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


def _report_verdict(on_trace, validation) -> None:
    """
    Report what the checker concluded, in its own words.

    Its reason is the single most informative line in the whole feed -- it says
    why an answer was believed or doubted -- and it is text the model actually
    wrote, so showing it invents nothing.
    """
    if validation.reason:
        tracing.emit(
            on_trace,
            tracing.thought("checker", f"{validation.verdict.value}: {validation.reason}"),
        )
    tracing.emit(
        on_trace,
        tracing.agent_status(
            "checker",
            tracing.AgentStatus.FOUND if validation.serves else tracing.AgentStatus.EMPTY,
        ),
    )


def _served(reason: str) -> Validation:
    """A non-verdict that lets the fast answer through. See `Verdict.serves`."""
    return Validation(Verdict.UNCHECKED, reason)


def _emit(callback: Optional[StageCallback], event: StageEvent) -> None:
    if callback is None:
        return
    try:
        callback(event)
    except Exception:  # noqa: BLE001 - progress must never break an answer
        logger.debug("stage callback raised", exc_info=True)
