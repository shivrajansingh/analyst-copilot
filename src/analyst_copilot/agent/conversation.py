"""Replying to a message that is not a question about a document.

Short module, load-bearing product decision. An assistant that can only answer
from a filing and says "not found in this filing" to everything else is not an
assistant, and the first thing anyone types is "hi".

What this must not become is a general chatbot with a filing attached. It is
told what it is, told which documents are loaded, and told explicitly not to
state a figure from a filing here — because anything said on this path has not
been through retrieval or verification, and an unproven number is the one thing
the product exists to prevent.
"""

from __future__ import annotations

import logging
from typing import Optional, Sequence

from analyst_copilot.agent.prompts import (
    CONVERSATION_SYSTEM,
    build_conversation_prompt,
)
from analyst_copilot.llm.base import ChatClient

logger = logging.getLogger(__name__)

# Used when the model cannot be reached. Still useful, still honest, and still
# tells the user what to do next.
FALLBACK_REPLY = (
    "I answer questions about the filings loaded here, and I show the document "
    "and page every answer came from — or I tell you plainly when the filing "
    "does not contain it. Ask me about a figure, a policy or a trend in the "
    "selected filing and I will go and look."
)


class ConversationResponder:
    """Answers greetings and questions about the assistant itself."""

    def __init__(self, chat_client: Optional[ChatClient] = None, max_tokens: int = 700) -> None:
        self._chat = chat_client
        self._max_tokens = max_tokens

    def reply(
        self,
        message: str,
        collection: Optional[str] = None,
        documents: Sequence[str] = (),
        history: str = "",
    ) -> str:
        if self._chat is None:
            return FALLBACK_REPLY
        try:
            text = self._chat.complete(
                messages=[
                    {"role": "system", "content": CONVERSATION_SYSTEM},
                    {
                        "role": "user",
                        "content": build_conversation_prompt(
                            message=message,
                            collection=collection,
                            documents=list(documents),
                            history=history,
                        ),
                    },
                ],
                # A little warmth here, unlike everywhere else in the pipeline:
                # this is the one path where the output is prose rather than a
                # figure, and a greeting read off at temperature 0 sounds like a
                # form letter.
                temperature=0.3,
                max_tokens=self._max_tokens,
            )
        except Exception as exc:  # noqa: BLE001 - never fail a hello
            logger.warning("conversational reply failed: %s", exc)
            return FALLBACK_REPLY
        return text.strip() or FALLBACK_REPLY
