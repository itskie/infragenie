"""
Module 1: Semantic Analyzer — Main Orchestrator.

Combines stack detection (detectors.py) and AST parsing (parsers.py)
into a single AnalysisReport that drives all downstream modules.
"""
from __future__ import annotations

from pathlib import Path

from infragenie.analyzer.detectors import detect_stack
from infragenie.analyzer.models import (
    AnalysisReport,
    ASTInsights,
    Framework,
    Language,
    RuntimeNeeds,
    StackDetectionResult,
)
from infragenie.analyzer.parsers import parse_project
from infragenie.utils.exceptions import NoStackDetectedError
from infragenie.utils.logger import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Runtime inference rules
# ---------------------------------------------------------------------------

# Default base images per language (security-hardened slim/alpine)
_BASE_IMAGES: dict[Language, str] = {
    Language.PYTHON: "python:3.12-slim",
    Language.JAVASCRIPT: "node:20-alpine",
    Language.TYPESCRIPT: "node:20-alpine",
    Language.GO: "golang:1.22-alpine",
    Language.RUST: "rust:1.78-slim",
    Language.JAVA: "eclipse-temurin:21-jre-alpine",
}

# Build commands per language
_BUILD_COMMANDS: dict[Language, str] = {
    Language.PYTHON: "pip install --no-cache-dir -r requirements.txt",
    Language.JAVASCRIPT: "npm ci --omit=dev",
    Language.TYPESCRIPT: "npm ci && npm run build",
    Language.GO: "go build -o /app/server ./...",
    Language.RUST: "cargo build --release",
}

# Start commands per framework (overrides language default)
_START_COMMANDS: dict[Framework, str] = {
    Framework.FASTAPI: "uvicorn main:app --host 0.0.0.0 --port 8080 --workers 2",
    Framework.FLASK: "gunicorn -w 2 -b 0.0.0.0:8080 app:app",
    Framework.DJANGO: "gunicorn -w 2 -b 0.0.0.0:8080 config.wsgi:application",
    Framework.EXPRESS: "node index.js",
    Framework.NEXTJS: "node .next/standalone/server.js",
    Framework.GIN: "./server",
    Framework.ECHO: "./server",
}

# Fallback start commands per language
_FALLBACK_START: dict[Language, str] = {
    Language.PYTHON: "python main.py",
    Language.JAVASCRIPT: "node index.js",
    Language.TYPESCRIPT: "node dist/index.js",
    Language.GO: "./server",
    Language.RUST: "./target/release/app",
}

# ECS resource recommendations per environment
_RESOURCE_PRESETS = {
    "dev": {"cpu": 256, "memory": 512},
    "prod": {"cpu": 512, "memory": 1024},
}


class SemanticAnalyzer:
    """
    Main orchestrator for semantic code analysis.

    Usage:
        analyzer = SemanticAnalyzer()
        report = analyzer.analyze(Path("./my-project"))
        print(report.to_json())
    """

    def __init__(self, env: str = "development") -> None:
        self.env = env
        self._resource_preset = (
            _RESOURCE_PRESETS["dev"] if env == "development" else _RESOURCE_PRESETS["prod"]
        )

    def analyze(self, project_path: Path) -> AnalysisReport:
        """
        Run full analysis on a project directory.

        Steps:
        1. Detect tech stack from manifest files.
        2. Parse source ASTs to extract runtime hints.
        3. Infer runtime requirements for Docker/ECS.
        4. Return structured AnalysisReport.

        Raises:
            NoStackDetectedError: If no recognizable tech stack is found.
        """
        project_path = project_path.resolve()
        if not project_path.is_dir():
            raise NotADirectoryError(f"Project path is not a directory: {project_path}")

        project_name = project_path.name
        log.info("Starting analysis", project=project_name, path=str(project_path))

        # Step 1: Detect stack
        stack = self._detect_stack(project_path)
        if stack.language == Language.UNKNOWN:
            raise NoStackDetectedError(
                f"Could not detect a supported tech stack in: {project_path}"
            )
        log.info("Stack detected", language=stack.language, framework=stack.framework)

        # Step 2: Parse ASTs
        ast_insights = self._parse_ast(project_path, stack)

        # Step 3: Infer runtime needs
        runtime_needs = self._infer_runtime(stack, ast_insights)

        report = AnalysisReport(
            project_path=str(project_path),
            project_name=project_name,
            stack=stack,
            ast_insights=ast_insights,
            runtime_needs=runtime_needs,
        )

        log.info(
            "Analysis complete",
            project=project_name,
            language=stack.language,
            framework=stack.framework,
            port=runtime_needs.exposed_port,
            files_parsed=ast_insights.files_parsed,
        )
        return report

    def _detect_stack(self, project_path: Path) -> StackDetectionResult:
        """Detect tech stack from manifest files."""
        return detect_stack(project_path)

    def _parse_ast(self, project_path: Path, stack: StackDetectionResult) -> ASTInsights:
        """Run Tree-sitter AST parsing for the detected language."""
        return parse_project(project_path, stack.language)

    def _infer_runtime(
        self,
        stack: StackDetectionResult,
        ast: ASTInsights,
    ) -> RuntimeNeeds:
        """
        Infer Docker/ECS runtime requirements from stack + AST data.

        Decision priority:
        - Base image: language → runtime_version override
        - Port: AST detected port → framework default → 8080 fallback
        - Start cmd: framework → language default
        """
        lang = stack.language

        # Base image
        base_image = _BASE_IMAGES.get(lang, "ubuntu:22.04")
        if stack.runtime_version:
            # Override version in base image tag if specified
            base_image = self._apply_runtime_version(base_image, stack.runtime_version)

        # Build command
        build_cmd = _BUILD_COMMANDS.get(lang, "")
        if stack.package_manager == "uv":
            build_cmd = "uv sync --no-dev"
        elif stack.package_manager == "yarn":
            build_cmd = "yarn install --frozen-lockfile --production"
        elif stack.package_manager == "pnpm":
            build_cmd = "pnpm install --frozen-lockfile --prod"

        # Start command
        start_cmd = _START_COMMANDS.get(stack.framework, "")
        if not start_cmd:
            start_cmd = _FALLBACK_START.get(lang, "")

        # Port detection
        exposed_port = 8080  # safe default
        if ast.detected_ports:
            # Prefer the first non-privileged port found
            for pb in ast.detected_ports:
                if pb.port >= 1024:
                    exposed_port = pb.port
                    break

        # Update start command port to match detected port
        if exposed_port != 8080:
            start_cmd = start_cmd.replace("8080", str(exposed_port))


        resources = self._resource_preset

        return RuntimeNeeds(
            base_image=base_image,
            build_command=build_cmd,
            start_command=start_cmd,
            exposed_port=exposed_port,
            needs_build_step=bool(build_cmd),
            recommended_cpu=resources["cpu"],
            recommended_memory=resources["memory"],
        )

    @staticmethod
    def _apply_runtime_version(base_image: str, runtime_version: str) -> str:
        """
        Replace the version tag in a base image string with the detected runtime version.
        e.g. python:3.12-slim + ">=3.10" → python:3.10-slim
        """
        # Extract a clean semver-like version
        clean_version = re.sub(r"[^0-9.]", "", runtime_version.split(",")[0])
        if not clean_version:
            return base_image

        # Replace only the version segment (e.g. 3.12 → 3.10)
        parts = base_image.split(":")
        if len(parts) == 2:
            tag = parts[1]
            # Replace leading version number e.g. "3.12-slim" → "3.10-slim"
            import re as _re
            new_tag = _re.sub(r"^\d+\.\d+", clean_version, tag)
            return f"{parts[0]}:{new_tag}"
        return base_image


# ---------------------------------------------------------------------------
# Re-import to fix circular (re module used in _apply_runtime_version)
# ---------------------------------------------------------------------------
import re  # noqa: E402
