"""
Ollama provider — llama3.2, mistral, codellama (fully local, no API key needed).
Install Ollama: https://ollama.ai
Run model: ollama pull llama3.2
"""
from __future__ import annotations
from typing import Any
from infragenie.llm.base import LLMProvider
from infragenie.utils.exceptions import LLMError
from infragenie.utils.logger import get_logger

log = get_logger(__name__)


class OllamaProvider(LLMProvider):
    """
    Local LLM via Ollama — zero cost, zero API key, works offline.

    Requirements:
        1. Install Ollama: brew install ollama
        2. Start server: ollama serve
        3. Pull model: ollama pull llama3.2
    """

    def __init__(self) -> None:
        from infragenie.config import settings
        self._settings = settings
        self._llm = None
        self._embeddings = None
        self._verify_ollama_running()
        log.info(
            "Ollama provider initialized",
            model=settings.ollama_model,
            url=settings.ollama_base_url,
        )

    def _verify_ollama_running(self) -> None:
        """Check if Ollama server is reachable."""
        import httpx
        try:
            resp = httpx.get(f"{self._settings.ollama_base_url}/api/tags", timeout=5)
            if resp.status_code != 200:
                raise LLMError(f"Ollama server returned {resp.status_code}")
        except httpx.ConnectError:
            raise LLMError(
                f"Cannot connect to Ollama at {self._settings.ollama_base_url}. "
                "Make sure Ollama is running: `ollama serve`"
            )

    @property
    def provider_name(self) -> str:
        return "ollama"

    @property
    def model_name(self) -> str:
        return self._settings.ollama_model

    def get_langchain_llm(self) -> Any:
        if self._llm is None:
            try:
                from langchain_ollama import ChatOllama
            except ImportError:
                raise LLMError(
                    "langchain-ollama not installed. Run: pip install langchain-ollama"
                )
            self._llm = ChatOllama(
                model=self._settings.ollama_model,
                base_url=self._settings.ollama_base_url,
                temperature=self._settings.openai_temperature,
            )
        return self._llm

    def get_embeddings(self) -> Any:
        """Use Ollama's local embeddings (nomic-embed-text model)."""
        if self._embeddings is None:
            try:
                from langchain_ollama import OllamaEmbeddings
                self._embeddings = OllamaEmbeddings(
                    model="nomic-embed-text",
                    base_url=self._settings.ollama_base_url,
                )
            except ImportError:
                # Fallback to sentence-transformers
                log.warning("langchain-ollama not found, using HuggingFace embeddings fallback")
                from langchain_community.embeddings import HuggingFaceEmbeddings
                self._embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
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
            raise LLMError(f"Ollama chat failed: {e}") from e
