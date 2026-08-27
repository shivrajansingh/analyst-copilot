"""The agent harness: routing, validation, and whole-document deep search.

`AnalystAgent` is the entry point. It answers a message at the cheapest tier
that can prove itself, and never serves a figure the document does not support.
See `pipeline.py` for the tier boundaries and why they sit where they do.
"""

from analyst_copilot.agent.conversation import ConversationResponder
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
from analyst_copilot.agent.router import IntentRouter
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
    "Citation",
    "ConversationResponder",
    "DeepSearchOrchestrator",
    "DeepVerification",
    "DocumentCorpus",
    "EvidenceInput",
    "Finding",
    "Intent",
    "IntentRouter",
    "PageMeta",
    "PageRef",
    "QuestionDecomposer",
    "Scope",
    "Shard",
    "ShardReader",
    "Stage",
    "StageEvent",
    "Support",
    "Validation",
    "Verdict",
    "check_derivation",
    "verify_agent_answer",
]
