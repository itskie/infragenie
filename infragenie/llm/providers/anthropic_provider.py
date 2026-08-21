"""Anthropic provider — Claude 3.5 Sonnet, Claude 3 Opus."""
from __future__ import annotations
from typing import Any
from infragenie.llm.base import LLMProvider
from infragenie.utils.exceptions import LLMError
from infragenie.utils.logger import get_logger

log = get_logger(__name__)


class AnthropicProvider(LLMProvider):
    """Claude 3.5 Sonnet / Claude 3 Opus via LangChain Anthropic."""

    def __init__(self) -> None:
        from infragenie.config import settings
        if not settings.anthropic_api_key:
            raise LLMError("ANTHROPIC_API_KEY is not set in environment.")
        self._settings = settings
        self._llm = None
        self._embeddings = None
        log.info("Anthropic provider initialized", model=settings.anthropic_model)

    @property
    def provider_name(self) -> str:
        return "anthropic"

    @property
    def model_name(self) -> str:
        return self._settings.anthropic_model

    def get_langchain_llm(self) -> Any:
        if self._llm is None:
            try:
                from langchain_anthropic import ChatAnthropic
            except ImportError:
                raise LLMError("langchain-anthropic not installed. Run: pip install langchain-anthropic")
            self._llm = ChatAnthropic(
                model=self._settings.anthropic_model,
                temperature=self._settings.openai_temperature,
                api_key=self._settings.anthropic_api_key,
            )
        return self._llm

    def get_embeddings(self) -> Any:
        # Anthropic doesn't have its own embeddings API
        # Fall back to a local sentence-transformer model
        log.info("Anthropic: using local HuggingFace embeddings for RAG")
        try:
            from langchain_community.embeddings import HuggingFaceEmbeddings
            return HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
        except ImportError:
            raise LLMError(
                "HuggingFace embeddings not available. "
                "Run: pip install sentence-transformers"
            )

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
            raise LLMError(f"Anthropic chat failed: {e}") from e
