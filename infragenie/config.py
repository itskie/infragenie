"""
InfraGenie configuration — loaded from environment variables.
Never hardcode secrets. Use .env for local dev, IAM Roles for production.
"""
from __future__ import annotations
from pathlib import Path

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All InfraGenie configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=[
            ".env",
            str(Path(__file__).resolve().parent.parent / ".env"),
            str(Path.home() / ".infragenie.env")
        ],
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- App ---
    infragenie_env: Literal["development", "production"] = "development"

    # --- LLM ---
    # --- LLM Provider Selection ---
    llm_provider: str = Field(default="openai", description="openai | anthropic | google | ollama")

    # --- OpenAI ---
    openai_api_key: str = Field(default="", description="OpenAI API key")
    openai_model: str = Field(default="gpt-4o", description="LLM model name")
    openai_temperature: float = Field(default=0.2, ge=0.0, le=2.0)

    # --- Anthropic ---
    anthropic_api_key: str = Field(default="", description="Anthropic Claude API key")
    anthropic_model: str = Field(default="claude-3-5-sonnet-20241022")

    # --- Google ---
    google_api_key: str = Field(default="", description="Google AI Studio API key")
    google_model: str = Field(default="gemini-2.5-flash")

    # --- Ollama (local, no API key) ---
    ollama_base_url: str = Field(default="http://localhost:11434")
    ollama_model: str = Field(default="llama3.2")

    # --- AWS ---
    aws_region: str = Field(default="us-east-1")
    aws_profile: str = Field(default="default")

    # --- ECR ---
    ecr_registry_uri: str = Field(default="", description="ECR registry URI")

    # --- ECS ---
    ecs_cluster_name: str = Field(default="infragenie-cluster")
    ecs_task_execution_role_arn: str = Field(default="")
    ecs_vpc_id: str = Field(default="")
    ecs_private_subnet_ids: str = Field(default="")
    ecs_security_group_ids: str = Field(default="")

    # --- ChromaDB ---
    chroma_persist_dir: str = Field(default="./.chroma_db")

    # --- Trivy ---
    trivy_severity: str = Field(default="HIGH,CRITICAL")
    trivy_exit_code: int = Field(default=1)

    # --- Logging ---
    log_level: str = Field(default="INFO")
    log_format: Literal["json", "console"] = "console"

    @field_validator("openai_api_key")
    @classmethod
    def warn_missing_api_key(cls, v: str) -> str:
        # Only needed when llm_provider=openai
        return v

    @property
    def subnet_ids(self) -> list[str]:
        """Parse comma-separated subnet IDs."""
        return [s.strip() for s in self.ecs_private_subnet_ids.split(",") if s.strip()]

    @property
    def security_group_ids(self) -> list[str]:
        """Parse comma-separated security group IDs."""
        return [s.strip() for s in self.ecs_security_group_ids.split(",") if s.strip()]

    @property
    def trivy_severity_list(self) -> list[str]:
        """Parse comma-separated Trivy severity levels."""
        return [s.strip() for s in self.trivy_severity.split(",") if s.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached singleton Settings instance."""
    return Settings()


# Module-level alias for convenience
settings = get_settings()
