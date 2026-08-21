"""Unit test stubs for Module 2: Dockerfile Generator."""
from __future__ import annotations
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path


@pytest.fixture
def sample_report(tmp_path):
    from infragenie.analyzer import SemanticAnalyzer
    (tmp_path / "requirements.txt").write_text("fastapi==0.111.0\nuvicorn==0.30.0\n")
    (tmp_path / "main.py").write_text('import os\nPORT=int(os.getenv("PORT","8080"))\n')
    return SemanticAnalyzer().analyze(tmp_path)


class TestDockerfileGenerator:
    def test_generate_returns_artifacts(self, sample_report):
        """Generator returns GeneratedArtifacts with non-empty Dockerfile."""
        from infragenie.generator import DockerfileGenerator, GeneratedArtifacts

        mock_rag = MagicMock()
        mock_rag.retrieve_context.return_value = "Use non-root user. Multi-stage builds."
        mock_rag.generate.return_value = (
            "```dockerfile\n"
            "FROM python:3.12-slim AS builder\n"
            "WORKDIR /app\n"
            "COPY requirements.txt .\n"
            "RUN pip install --no-cache-dir -r requirements.txt\n\n"
            "FROM python:3.12-slim AS runtime\n"
            "WORKDIR /app\n"
            "COPY --from=builder /app /app\n"
            "RUN addgroup --system appuser && adduser --system --ingroup appuser --uid 1001 appuser\n"
            "USER appuser\n"
            "HEALTHCHECK --interval=30s CMD wget -qO- http://localhost:8080/health || exit 1\n"
            "EXPOSE 8080\n"
            "CMD [\"uvicorn\", \"main:app\", \"--host\", \"0.0.0.0\", \"--port\", \"8080\"]\n"
            "```"
        )

        gen = DockerfileGenerator(rag=mock_rag)
        artifacts = gen.generate(sample_report)

        assert isinstance(artifacts, GeneratedArtifacts)
        assert "FROM" in artifacts.dockerfile
        assert len(artifacts.dockerignore) > 0

    def test_security_guardrails_inject_user(self, sample_report):
        """If LLM omits USER, guardrail should inject it."""
        from infragenie.generator import DockerfileGenerator

        mock_rag = MagicMock()
        mock_rag.retrieve_context.return_value = ""
        # LLM response without USER instruction
        mock_rag.generate.return_value = (
            "```dockerfile\nFROM python:3.12-slim\nWORKDIR /app\nCMD [\"python\", \"main.py\"]\n```"
        )

        gen = DockerfileGenerator(rag=mock_rag)
        artifacts = gen.generate(sample_report)

        assert "USER" in artifacts.dockerfile or "appuser" in artifacts.dockerfile

    def test_security_guardrails_inject_healthcheck(self, sample_report):
        """If LLM omits HEALTHCHECK, guardrail should inject it."""
        from infragenie.generator import DockerfileGenerator

        mock_rag = MagicMock()
        mock_rag.retrieve_context.return_value = ""
        mock_rag.generate.return_value = (
            "```dockerfile\nFROM python:3.12-slim\nWORKDIR /app\nUSER appuser\nCMD [\"python\", \"main.py\"]\n```"
        )

        gen = DockerfileGenerator(rag=mock_rag)
        artifacts = gen.generate(sample_report)

        assert "HEALTHCHECK" in artifacts.dockerfile

    def test_dockerignore_excludes_secrets(self, sample_report):
        """Generated .dockerignore must exclude .env files."""
        from infragenie.generator import DockerfileGenerator

        mock_rag = MagicMock()
        mock_rag.retrieve_context.return_value = ""
        mock_rag.generate.return_value = "FROM python:3.12-slim\n"

        gen = DockerfileGenerator(rag=mock_rag)
        artifacts = gen.generate(sample_report)

        assert ".env" in artifacts.dockerignore
        assert ".git/" in artifacts.dockerignore
