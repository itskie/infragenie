"""OpenAI provider — GPT-4o, GPT-4-turbo."""
from __future__ import annotations
from typing import Any
from infragenie.llm.base import LLMProvider
from infragenie.utils.exceptions import LLMError
from infragenie.utils.logger import get_logger

log = get_logger(__name__)


class OpenAIProvider(LLMProvider):
    """GPT-4o / GPT-4-turbo via LangChain + OpenAI SDK."""

    def __init__(self) -> None:
        from infragenie.config import settings
        if not settings.openai_api_key:
            raise LLMError("OPENAI_API_KEY is not set in environment.")
        self._settings = settings
        self._llm = None
        self._embeddings = None
        log.info("OpenAI provider initialized", model=settings.openai_model)

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def model_name(self) -> str:
        return self._settings.openai_model

    def get_langchain_llm(self) -> Any:
        if self._llm is None:
            from langchain_openai import ChatOpenAI
            self._llm = ChatOpenAI(
                model=self._settings.openai_model,
                temperature=self._settings.openai_temperature,
                api_key=self._settings.openai_api_key,
            )
        return self._llm

    def get_embeddings(self) -> Any:
        if self._embeddings is None:
            from langchain_openai import OpenAIEmbeddings
            self._embeddings = OpenAIEmbeddings(
                model="text-embedding-3-small",
                api_key=self._settings.openai_api_key,
            )
        return self._embeddings

    def chat(self, system_prompt: str, user_prompt: str) -> str:
        from langchain_core.messages import HumanMessage, SystemMessage
        try:
            llm = self.get_langchain_llm()
            response = llm.invoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
            ])
            return str(response.content)
        except Exception as e:
            raise LLMError(f"OpenAI chat failed: {e}") from e
