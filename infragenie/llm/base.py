"""
Abstract base class for all LLM providers.
Every provider must implement chat() and get_langchain_llm().
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class LLMProvider(ABC):
    """
    Unified interface for all supported LLM backends.

    Implementations:
        - OpenAIProvider   → GPT-4o, GPT-4-turbo
        - AnthropicProvider→ Claude 3.5 Sonnet, Claude 3 Opus
        - GoogleProvider   → Gemini 1.5 Pro, Gemini 1.5 Flash
        - OllamaProvider   → llama3.2, mistral, codellama (local)
    """

    @abstractmethod
    def chat(self, system_prompt: str, user_prompt: str) -> str:
        """
        Send a chat message and return the response text.

        Args:
            system_prompt: Instructions for the AI (role, rules, constraints).
            user_prompt: The actual user request / task.

        Returns:
            The LLM's response as a plain string.
        """
        ...

    @abstractmethod
    def get_langchain_llm(self) -> Any:
        """
        Return the underlying LangChain chat model object.
        Used by RAGChain for retrieval-augmented generation.
        """
        ...

    @abstractmethod
    def get_embeddings(self) -> Any:
        """
        Return a LangChain embeddings model for vectorstore indexing.
        Used by ChromaDB to embed knowledge documents.
        """
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Human-readable provider name (e.g. 'openai', 'anthropic')."""
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        """The specific model being used (e.g. 'gpt-4o')."""
        ...
