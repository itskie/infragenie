"""
LLM Factory — auto-selects and instantiates the correct provider
based on the LLM_PROVIDER environment variable.
"""
from __future__ import annotations
from typing import Optional

from infragenie.llm.base import LLMProvider
from infragenie.utils.exceptions import LLMError
from infragenie.utils.logger import get_logger

log = get_logger(__name__)

# Registry of all supported providers
_PROVIDER_REGISTRY: dict[str, str] = {
    "openai":    "infragenie.llm.providers.openai_provider.OpenAIProvider",
    "anthropic": "infragenie.llm.providers.anthropic_provider.AnthropicProvider",
    "google":    "infragenie.llm.providers.google_provider.GoogleProvider",
    "ollama":    "infragenie.llm.providers.ollama_provider.OllamaProvider",
}


class LLMFactory:
    """
    Factory that creates the appropriate LLMProvider from config.

    Usage:
        provider = LLMFactory.create()
        response = provider.chat(system_prompt, user_prompt)

    Provider is selected via LLM_PROVIDER env var (default: openai).
    """

    _instance: Optional[LLMProvider ] = None  # Singleton cache

    @classmethod
    def create(cls, force_provider: Optional[str ] = None) -> LLMProvider:
        """
        Create or return cached LLMProvider instance.

        Args:
            force_provider: Override env var (useful for testing).

        Returns:
            LLMProvider instance ready to use.
        """
        if cls._instance is not None and force_provider is None:
            return cls._instance

        from infragenie.config import settings
        provider_name = (force_provider or settings.llm_provider).lower().strip()

        if provider_name not in _PROVIDER_REGISTRY:
            available = ", ".join(_PROVIDER_REGISTRY.keys())
            raise LLMError(
                f"Unknown LLM provider: '{provider_name}'. "
                f"Available: {available}"
            )

        log.info("Creating LLM provider", provider=provider_name)

        # Lazy import — only load the selected provider's dependencies
        module_path, class_name = _PROVIDER_REGISTRY[provider_name].rsplit(".", 1)
        import importlib
        module = importlib.import_module(module_path)
        provider_class = getattr(module, class_name)

        try:
            instance = provider_class()
        except LLMError:
            raise
        except Exception as e:
            raise LLMError(
                f"Failed to initialize {provider_name} provider: {e}\n"
                f"Check your API key and model settings in .env"
            ) from e

        if force_provider is None:
            cls._instance = instance  # Cache for reuse

        log.info(
            "LLM provider ready",
            provider=instance.provider_name,
            model=instance.model_name,
        )
        return instance

    @classmethod
    def reset(cls) -> None:
        """Reset cached provider (useful for testing or switching providers)."""
        cls._instance = None

    @classmethod
    def available_providers(cls) -> list[str]:
        """Return list of all supported provider names."""
        return list(_PROVIDER_REGISTRY.keys())
