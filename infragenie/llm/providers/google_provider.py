"""Google provider — Gemini 1.5 Pro, Gemini 1.5 Flash (free tier available)."""
from __future__ import annotations
from typing import Any
from infragenie.llm.base import LLMProvider
from infragenie.utils.exceptions import LLMError
from infragenie.utils.logger import get_logger

log = get_logger(__name__)


class GoogleProvider(LLMProvider):
    """Gemini 1.5 Pro / Flash via LangChain Google GenerativeAI."""

    def __init__(self) -> None:
        from infragenie.config import settings
        if not settings.google_api_key:
            raise LLMError(
                "GOOGLE_API_KEY is not set. "
                "Get a free key at: https://aistudio.google.com/app/apikey"
            )
        self._settings = settings
        self._llm = None
        self._embeddings = None
        log.info("Google provider initialized", model=settings.google_model)

    @property
    def provider_name(self) -> str:
        return "google"

    @property
    def model_name(self) -> str:
        return self._settings.google_model

    def get_langchain_llm(self) -> Any:
        if self._llm is None:
            try:
                from langchain_google_genai import ChatGoogleGenerativeAI
            except ImportError:
                raise LLMError("langchain-google-genai not installed. Run: pip install langchain-google-genai")
            self._llm = ChatGoogleGenerativeAI(
                model=self._settings.google_model,
                temperature=self._settings.openai_temperature,
                google_api_key=self._settings.google_api_key,
            )
        return self._llm

    def get_embeddings(self) -> Any:
        if self._embeddings is None:
            try:
                from langchain_google_genai import GoogleGenerativeAIEmbeddings
            except ImportError:
                raise LLMError("langchain-google-genai not installed.")
            self._embeddings = GoogleGenerativeAIEmbeddings(
                model="models/text-embedding-004",
                google_api_key=self._settings.google_api_key,
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
            raise LLMError(f"Google Gemini chat failed: {e}") from e
