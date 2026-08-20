from analyst_copilot.llm.base import ChatClient
from analyst_copilot.llm.openai import OpenAICompatibleChatClient

__all__ = ["ChatClient", "OpenAICompatibleChatClient", "get_chat_client"]


def get_chat_client() -> ChatClient:
    return OpenAICompatibleChatClient()
