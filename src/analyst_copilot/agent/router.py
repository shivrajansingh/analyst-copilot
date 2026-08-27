"""What kind of message is this?

The complaint this module answers is precise: typing "Hi" into a filing
assistant should not retrieve five pages of a 10-K and reply "not found in this
filing". That answer is technically true and makes the product feel like a
search box with a chat skin.

So every message is classified before anything is retrieved. Two properties
matter more than accuracy in the abstract:

- **Greetings are free.** The common cases are matched literally, with no model
  call, because a round trip to classify "thanks" is a round trip wasted.
- **Ambiguity resolves toward the document.** Misrouting a greeting into
  retrieval wastes a few seconds; misrouting a real question into small talk
  answers it from nothing, which is the error that loses a mark and misleads an
  analyst. The prompt says so, and so does the fallback when the model fails.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

from analyst_copilot.agent.models import Intent
from analyst_copilot.agent.prompts import ROUTER_SYSTEM, build_router_prompt
from analyst_copilot.llm.base import ChatClient
from analyst_copilot.services.qa.parser import load_json_object

logger = logging.getLogger(__name__)

# Matched on the whole message, after punctuation is stripped. Deliberately
# exact rather than "contains": "hi, what was capex?" is a question, and a
# substring rule would route it to small talk and answer it from nothing.
_EXACT_SMALLTALK = frozenset(
    {
        "hi", "hello", "hey", "heya", "hiya", "yo", "sup", "greetings",
        "thanks", "thank you", "thankyou", "ty", "cheers", "ta",
        "ok", "okay", "k", "cool", "nice", "great", "perfect", "awesome",
        "bye", "goodbye", "see you", "later", "cya",
        "good morning", "good afternoon", "good evening", "good day",
        "how are you", "how are you doing", "hows it going", "how is it going",
        "thanks a lot", "thanks so much", "that helps", "thats helpful",
        "no worries", "nevermind", "never mind", "sorry", "my bad",
        "hi there", "hello there", "hey there", "morning", "afternoon",
    }
)

_EXACT_CAPABILITY = frozenset(
    {
        "who are you", "what are you", "what can you do", "what do you do",
        "help", "how do you work", "how does this work", "what is this",
        "what formats do you support", "what can i ask", "what can i ask you",
        "which filings do you have", "what filings do you have",
        "what documents do you have", "capabilities",
    }
)

_PUNCTUATION = re.compile(r"[^a-z0-9\s]")
_SPACES = re.compile(r"\s+")


@dataclass
class Routing:
    intent: Intent
    reason: str = ""
    #: True when the classification cost no model call.
    matched_literally: bool = False


def normalize_message(message: str) -> str:
    lowered = _PUNCTUATION.sub(" ", (message or "").lower())
    return _SPACES.sub(" ", lowered).strip()


class IntentRouter:
    """Classifies a message as small talk, a capability question, or a real one."""

    def __init__(self, chat_client: Optional[ChatClient] = None) -> None:
        self._chat = chat_client

    def route(self, message: str, history: str = "") -> Routing:
        text = normalize_message(message)
        if not text:
            return Routing(
                intent=Intent.SMALLTALK, reason="empty message", matched_literally=True
            )

        if text in _EXACT_SMALLTALK:
            return Routing(Intent.SMALLTALK, "matched a known greeting", True)
        if text in _EXACT_CAPABILITY:
            return Routing(Intent.CAPABILITY, "matched a known capability question", True)

        # A very short message with no question in it and no figures is almost
        # never a filing question, but "capex 2022" is, so the model decides.
        if self._chat is None:
            return Routing(Intent.DOCUMENT_QUESTION, "no classifier available")

        try:
            raw = self._chat.complete(
                messages=[
                    {"role": "system", "content": ROUTER_SYSTEM},
                    {"role": "user", "content": build_router_prompt(message, history)},
                ],
                temperature=0.0,
                max_tokens=512,
            )
        except Exception as exc:  # noqa: BLE001 - a dead classifier must not lose the question
            logger.warning("intent routing failed, treating as a document question: %s", exc)
            return Routing(Intent.DOCUMENT_QUESTION, f"classifier unavailable: {exc}")

        payload = load_json_object(raw) or {}
        value = str(payload.get("intent") or "").strip().lower()
        reason = str(payload.get("reason") or "").strip()
        try:
            intent = Intent(value)
        except ValueError:
            return Routing(
                Intent.DOCUMENT_QUESTION,
                f"unrecognised classification {value!r}; treated as a question",
            )
        return Routing(intent, reason)
