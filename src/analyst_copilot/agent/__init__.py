"""The agent harness: planning, validation, and whole-document deep search.

`AnalystAgent` is the entry point. A planner decides what a message needs, and
the answer is produced at the cheapest tier that can prove itself. Nothing is
served that the document does not support.

See `planner.py` for the decision and its escape hatches, and `pipeline.py` for
the tier boundaries and why they sit where they do.
"""

from analyst_copilot.agent.cancellation import NEVER, CancelToken, Cancelled
from analyst_copilot.agent.cards import DocumentCard, card_for, cards_for
from analyst_copilot.agent.conversation import ConversationReply, ConversationResponder
from analyst_copilot.agent.facts import corpus_facts
from analyst_copilot.agent.corpus import DocumentCorpus, PageMeta, PageRef, Shard
from analyst_copilot.agent.decompose import QuestionDecomposer
from analyst_copilot.agent.models import (
    AgentAnswer,
    AnswerMode,
    AnswerPart,
    Citation,
    EvidenceInput,
    Finding,
    Intent,
    Stage,
    StageEvent,
)
from analyst_copilot.agent.orchestrator import DeepSearchOrchestrator
from analyst_copilot.agent.pipeline import AnalystAgent, Scope
from analyst_copilot.agent.reader import ShardReader
from analyst_copilot.agent.planner import Plan, PlanKind, Planner
from analyst_copilot.agent.runtime import AgentRuntime
from analyst_copilot.agent.validator import AnswerValidator, Validation, Verdict
from analyst_copilot.agent.verification import (
    DeepVerification,
    Support,
    check_derivation,
    verify_agent_answer,
)

__all__ = [
    "AgentAnswer",
    "AgentRuntime",
    "AnalystAgent",
    "AnswerMode",
    "AnswerPart",
    "AnswerValidator",
    "CancelToken",
    "Cancelled",
    "Citation",
    "ConversationReply",
    "ConversationResponder",
    "DocumentCard",
    "DeepSearchOrchestrator",
    "DeepVerification",
    "DocumentCorpus",
    "EvidenceInput",
    "Finding",
    "Intent",
    "NEVER",
    "PageMeta",
    "PageRef",
    "Plan",
    "PlanKind",
    "Planner",
    "QuestionDecomposer",
    "Scope",
    "Shard",
    "ShardReader",
    "Stage",
    "StageEvent",
    "Support",
    "Validation",
    "Verdict",
    "card_for",
    "cards_for",
    "check_derivation",
    "corpus_facts",
    "verify_agent_answer",
]
