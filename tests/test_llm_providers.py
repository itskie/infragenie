"""
Unit tests for Multi-LLM Provider system.
All external API calls are mocked — no real keys needed.
"""
from __future__ import annotations
import pytest
from unittest.mock import MagicMock, patch


class TestLLMFactory:
    def test_factory_returns_openai_by_default(self):
        """Default provider should be OpenAI."""
        from infragenie.llm.factory import LLMFactory
        LLMFactory.reset()

        with patch.dict("os.environ", {"LLM_PROVIDER": "openai", "OPENAI_API_KEY": "sk-test"}):
            with patch("langchain_openai.ChatOpenAI"):
                with patch("langchain_openai.OpenAIEmbeddings"):
                    from importlib import reload
                    import infragenie.config as cfg
                    reload(cfg)
                    provider = LLMFactory.create(force_provider="openai")
                    assert provider.provider_name == "openai"
        LLMFactory.reset()

    def test_factory_raises_on_unknown_provider(self):
        """Unknown provider name should raise LLMError."""
        from infragenie.llm.factory import LLMFactory
        from infragenie.utils.exceptions import LLMError
        LLMFactory.reset()

        with pytest.raises(LLMError, match="Unknown LLM provider"):
            LLMFactory.create(force_provider="grok")

    def test_available_providers_list(self):
        """All 4 providers should be listed."""
        from infragenie.llm.factory import LLMFactory
        providers = LLMFactory.available_providers()
        assert "openai" in providers
        assert "anthropic" in providers
        assert "google" in providers
        assert "ollama" in providers
        assert len(providers) == 4


class TestOpenAIProvider:
    def test_raises_without_api_key(self):
        """Should raise LLMError if OPENAI_API_KEY is empty."""
        from infragenie.utils.exceptions import LLMError
        with patch.dict("os.environ", {"OPENAI_API_KEY": ""}):
            import importlib
            import infragenie.config as cfg
            importlib.reload(cfg)
            with pytest.raises(LLMError, match="OPENAI_API_KEY"):
                from infragenie.llm.providers.openai_provider import OpenAIProvider
                OpenAIProvider()

    def test_provider_name(self):
        """Provider name must be 'openai'."""
        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test123"}):
            with patch("langchain_openai.ChatOpenAI"), patch("langchain_openai.OpenAIEmbeddings"):
                import importlib
                import infragenie.config as cfg
                importlib.reload(cfg)
                from infragenie.llm.providers.openai_provider import OpenAIProvider
                p = OpenAIProvider()
                assert p.provider_name == "openai"


class TestAnthropicProvider:
    def test_raises_without_api_key(self):
        """Should raise LLMError if ANTHROPIC_API_KEY is empty."""
        from infragenie.utils.exceptions import LLMError
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}):
            import importlib
            import infragenie.config as cfg
            importlib.reload(cfg)
            with pytest.raises(LLMError, match="ANTHROPIC_API_KEY"):
                from infragenie.llm.providers.anthropic_provider import AnthropicProvider
                AnthropicProvider()

    def test_provider_name(self):
        """Provider name must be 'anthropic'."""
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-ant-test"}):
            import importlib
            import infragenie.config as cfg
            importlib.reload(cfg)
            from infragenie.llm.providers.anthropic_provider import AnthropicProvider
            p = AnthropicProvider()
            assert p.provider_name == "anthropic"


class TestGoogleProvider:
    def test_raises_without_api_key(self):
        """Should raise LLMError if GOOGLE_API_KEY is empty."""
        from infragenie.utils.exceptions import LLMError
        with patch.dict("os.environ", {"GOOGLE_API_KEY": ""}):
            import importlib
            import infragenie.config as cfg
            importlib.reload(cfg)
            with pytest.raises(LLMError, match="GOOGLE_API_KEY"):
                from infragenie.llm.providers.google_provider import GoogleProvider
                GoogleProvider()

    def test_provider_name(self):
        """Provider name must be 'google'."""
        with patch.dict("os.environ", {"GOOGLE_API_KEY": "AIza-test"}):
            import importlib
            import infragenie.config as cfg
            importlib.reload(cfg)
            from infragenie.llm.providers.google_provider import GoogleProvider
            p = GoogleProvider()
            assert p.provider_name == "google"


class TestOllamaProvider:
    def test_raises_if_ollama_not_running(self):
        """Should raise LLMError if Ollama server is not reachable."""
        import httpx
        from infragenie.utils.exceptions import LLMError
        with patch("httpx.get", side_effect=httpx.ConnectError("refused")):
            with pytest.raises(LLMError, match="ollama serve"):
                from infragenie.llm.providers.ollama_provider import OllamaProvider
                OllamaProvider()

    def test_provider_name(self):
        """Provider name must be 'ollama'."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("httpx.get", return_value=mock_resp):
            from infragenie.llm.providers.ollama_provider import OllamaProvider
            p = OllamaProvider()
            assert p.provider_name == "ollama"
