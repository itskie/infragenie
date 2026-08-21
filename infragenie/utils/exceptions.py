"""Custom exception hierarchy for InfraGenie."""
from __future__ import annotations


class InfraGenieError(Exception):
    """Base exception for all InfraGenie errors."""


# --- Analyzer ---
class AnalyzerError(InfraGenieError):
    """Raised when semantic analysis fails."""


class UnsupportedLanguageError(AnalyzerError):
    """Raised when the detected language has no parser."""

    def __init__(self, language: str) -> None:
        super().__init__(f"No parser available for language: {language!r}")
        self.language = language


class NoStackDetectedError(AnalyzerError):
    """Raised when no tech stack could be detected."""


# --- Generator ---
class GeneratorError(InfraGenieError):
    """Raised when Dockerfile generation fails."""


class RAGIndexError(GeneratorError):
    """Raised when the RAG knowledge index is unavailable."""


class LLMError(GeneratorError):
    """Raised when the LLM call fails."""


# --- Scanner ---
class ScannerError(InfraGenieError):
    """Raised when security scanning fails."""


class TrivyNotFoundError(ScannerError):
    """Raised when Trivy binary is not installed."""

    def __init__(self) -> None:
        super().__init__(
            "Trivy is not installed. Install via: brew install trivy"
        )


class ScanFailedError(ScannerError):
    """Raised when a scan finds critical vulnerabilities."""

    def __init__(self, critical: int, high: int) -> None:
        super().__init__(
            f"Scan failed: {critical} CRITICAL, {high} HIGH vulnerabilities found."
        )
        self.critical = critical
        self.high = high


# --- Deployer ---
class DeployerError(InfraGenieError):
    """Raised when AWS deployment fails."""


class ECRError(DeployerError):
    """Raised when ECR push/auth fails."""


class ECSError(DeployerError):
    """Raised when ECS task definition or service deployment fails."""


class AWSAuthError(DeployerError):
    """Raised when AWS credentials/role is not configured."""

    def __init__(self) -> None:
        super().__init__(
            "AWS credentials not found. Configure IAM role or set AWS_PROFILE."
        )

# Alias for DeployerError
DeploymentError = DeployerError

class DockerNotFoundError(DeployerError):
    """Raised when Docker is missing or Docker daemon is not running."""
