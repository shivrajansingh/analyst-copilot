"""Chat clients, and which model each part of the pipeline talks to.

Two roles, deliberately separable:

`get_chat_client` is the model that *answers* -- the planner, the fast path,
the readers, the adjudicator.

`get_validator_client` is the model that *checks* an answer before it is
served. When `VALIDATOR_MODEL` names a different model, checking runs on it.
That separation is the point: measured on the practice key, a checker sharing
the writer's model re-derived the writer's own wrong formula, confirmed the
arithmetic, and passed 9 of 11 wrong answers. Two opinions from one model are
one opinion.

Unset, both return the same client and nothing changes.
"""

from analyst_copilot.config.settings import get_settings
from analyst_copilot.llm.base import ChatClient
from analyst_copilot.llm.openai import OpenAICompatibleChatClient

__all__ = [
    "ChatClient",
    "OpenAICompatibleChatClient",
    "get_chat_client",
    "get_validator_client",
]


def get_chat_client() -> ChatClient:
    """The model that answers questions."""
    return OpenAICompatibleChatClient()


def get_validator_client() -> ChatClient:
    """
    The model that checks an answer, which should not be the one that wrote it.

    Falls back to the answering model when nothing is configured, and also when
    the configured name *is* the answering model -- naming it there is not a
    second opinion, and honouring it silently would hide that.
    """
    settings = get_settings()
    if not settings.validator_is_separate:
        return get_chat_client()
    return OpenAICompatibleChatClient(
        base_url=settings.validator_base_url,
        api_key=settings.resolved_validator_api_key,
        model=settings.resolved_validator_model,
    )
