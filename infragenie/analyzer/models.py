"""
Pydantic models for Semantic Analyzer output.
These are the structured data contracts between modules.
"""
from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field


class Language(str, Enum):
    """Supported programming languages."""
    PYTHON = "python"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    GO = "go"
    RUST = "rust"
    JAVA = "java"
    UNKNOWN = "unknown"


class Framework(str, Enum):
    """Detected web/backend frameworks."""
    FASTAPI = "fastapi"
    FLASK = "flask"
    DJANGO = "django"
    EXPRESS = "express"
    NEXTJS = "nextjs"
    GIN = "gin"
    ECHO = "echo"
    SPRING = "spring"
    UNKNOWN = "unknown"


class DependencyInfo(BaseModel):
    """A single dependency extracted from a manifest file."""
    name: str
    version: str = "*"
    is_dev: bool = False


class PortBinding(BaseModel):
    """A port detected from source code analysis."""
    port: int
    protocol: str = "tcp"
    description: str = ""


class EnvVarUsage(BaseModel):
    """An environment variable referenced in source code."""
    name: str
    has_default: bool = False
    default_value: Optional[str ] = None
    file_path: str = ""
    line_number: int = 0


class HealthCheckInfo(BaseModel):
    """Detected health check endpoint."""
    path: str
    method: str = "GET"


class VolumeHint(BaseModel):
    """Detected file I/O that may need a Docker volume."""
    path: str
    description: str = ""


class StackDetectionResult(BaseModel):
    """Result of tech stack detection from dependency files."""
    language: Language = Language.UNKNOWN
    framework: Framework = Framework.UNKNOWN
    runtime_version: str = ""
    package_manager: str = ""
    entry_point: str = ""
    dependencies: list[DependencyInfo] = Field(default_factory=list)
    dev_dependencies: list[DependencyInfo] = Field(default_factory=list)
    raw_manifest: dict[str, Any] = Field(default_factory=dict)


class ASTInsights(BaseModel):
    """Insights extracted from Tree-sitter AST parsing."""
    detected_ports: list[PortBinding] = Field(default_factory=list)
    env_var_usages: list[EnvVarUsage] = Field(default_factory=list)
    health_check_endpoints: list[HealthCheckInfo] = Field(default_factory=list)
    volume_hints: list[VolumeHint] = Field(default_factory=list)
    has_async_code: bool = False
    files_parsed: int = 0
    parse_errors: list[str] = Field(default_factory=list)


class RuntimeNeeds(BaseModel):
    """Runtime requirements inferred for Docker/ECS."""
    base_image: str = ""                   # e.g. python:3.12-slim
    build_command: str = ""                # e.g. pip install -r requirements.txt
    start_command: str = ""                # e.g. uvicorn app.main:app --host 0.0.0.0
    exposed_port: int = 8080
    needs_build_step: bool = True
    recommended_cpu: int = 256             # ECS CPU units
    recommended_memory: int = 512          # ECS memory MB


class AnalysisReport(BaseModel):
    """
    Complete output of the Semantic Analyzer.
    This is the primary input to all downstream modules.
    """
    project_path: str
    project_name: str
    stack: StackDetectionResult
    ast_insights: ASTInsights
    runtime_needs: RuntimeNeeds
    analysis_version: str = "1.0.0"

    def to_json(self, indent: int = 2) -> str:
        """Serialize to pretty-printed JSON."""
        return self.model_dump_json(indent=indent)

    @classmethod
    def from_json(cls, data: str) -> AnalysisReport:
        """Deserialize from JSON string."""
        return cls.model_validate_json(data)
