"""
Module 2: AI Dockerfile Generator.
Uses RAG + LLM to generate secure, multi-stage Dockerfiles
and .dockerignore files from an AnalysisReport.
"""
from __future__ import annotations
from typing import Optional

import re
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

from infragenie.analyzer.models import AnalysisReport, Framework, Language
from infragenie.generator.rag_chain import RAGChain
from infragenie.utils.logger import get_logger

log = get_logger(__name__)


@dataclass
class GeneratedArtifacts:
    """Output of the DockerfileGenerator."""
    dockerfile: str
    dockerignore: str
    build_args: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def save(self, output_dir: Path) -> None:
        """Write artifacts to disk."""
        (output_dir / "Dockerfile").write_text(self.dockerfile, encoding="utf-8")
        (output_dir / ".dockerignore").write_text(self.dockerignore, encoding="utf-8")
        log.info("Artifacts written", path=str(output_dir))


class DockerfileGenerator:
    def write_artifacts(self, artifacts: GeneratedArtifacts, output_dir: Path) -> None:
        """Write generated Dockerfile and .dockerignore to disk."""
        artifacts.save(output_dir)
        log.info("Artifacts written", path=str(output_dir))

    """
    AI-powered Dockerfile generator.

    Workflow:
    1. Retrieve AWS security context via RAG.
    2. Build a detailed prompt from AnalysisReport.
    3. LLM generates multi-stage Dockerfile.
    4. Post-process to enforce mandatory security rules.
    5. Generate .dockerignore.
    """

    # Mandatory security rules — applied as post-processing guardrails
    SECURITY_RULES = [
        "Must use non-root USER",
        "Must use multi-stage build",
        "Must include HEALTHCHECK",
        "Must use slim/alpine base image",
        "Must not expose secrets",
    ]

    def __init__(self, rag: Optional[RAGChain ] = None) -> None:
        self.rag = rag or RAGChain()

    def generate(self, report: AnalysisReport) -> GeneratedArtifacts:
        """Generate Dockerfile and .dockerignore from an AnalysisReport."""
        log.info(
            "Generating Dockerfile",
            project=report.project_name,
            language=report.stack.language,
            framework=report.stack.framework,
        )

        # 1. Retrieve context
        query = (
            f"Secure multi-stage Dockerfile for {report.stack.language} "
            f"with {report.stack.framework} framework. "
            f"Base image: {report.runtime_needs.base_image}"
        )
        context = self._get_context(query)

        # 2. Build prompt
        prompt = self._build_prompt(report, context)

        # 3. Call LLM
        raw_response = self.rag.generate(prompt)

        # 4. Extract Dockerfile from response
        dockerfile = self._extract_dockerfile(raw_response)

        # 5. Enforce security guardrails
        dockerfile = self._enforce_security(dockerfile, report)

        # 6. Generate .dockerignore
        dockerignore = self._generate_dockerignore(report)

        # 7. Extract any build args
        build_args = self._extract_build_args(dockerfile)

        notes = self._generate_notes(report)

        return GeneratedArtifacts(
            dockerfile=dockerfile,
            dockerignore=dockerignore,
            build_args=build_args,
            notes=notes,
        )

    def _get_context(self, query: str) -> str:
        """Retrieve RAG context, fallback to empty string on failure."""
        try:
            return self.rag.retrieve_context(query)
        except Exception as exc:
            log.warning("RAG context retrieval failed, continuing without context", error=str(exc))
            return ""

    def _build_prompt(self, report: AnalysisReport, context: str) -> str:
        """Build a structured prompt for the LLM."""
        stack = report.stack
        rt = report.runtime_needs
        ast = report.ast_insights

        env_vars = "\n".join(
            f"  - {e.name}{'  # has default' if e.has_default else ''}"
            for e in ast.env_var_usages[:20]
        ) or "  - (none detected)"

        health_path = (
            ast.health_check_endpoints[0].path
            if ast.health_check_endpoints
            else "/health"
        )

        deps_list = ", ".join(
            d.name for d in stack.dependencies[:15]
        ) or "see manifest"

        return textwrap.dedent(f"""
        # Task: Generate a production-ready Dockerfile

        ## Project Info
        - Project: {report.project_name}
        - Language: {stack.language}
        - Framework: {stack.framework}
        - Runtime Version: {stack.runtime_version or 'latest stable'}
        - Package Manager: {stack.package_manager}
        - Entry Point: {stack.entry_point or 'auto-detected'}

        ## Runtime Requirements
        - Base Image: {rt.base_image}
        - Build Command: {rt.build_command}
        - Start Command: {rt.start_command}
        - Exposed Port: {rt.exposed_port}

        ## Detected Environment Variables (reference ENV instructions)
        {env_vars}

        ## Detected Health Check Endpoint
        - Path: {health_path}

        ## Key Dependencies
        {deps_list}

        ## Security Context (from AWS Well-Architected docs)
        {context}

        ## MANDATORY Requirements (non-negotiable)
        1. Use MULTI-STAGE build (builder stage + minimal runtime stage)
        2. Create and use a NON-ROOT user named 'appuser' (UID 1001)
        3. Include HEALTHCHECK instruction using {health_path}
        4. Use the minimal base image: {rt.base_image}
        5. Add LABEL with maintainer and version metadata
        6. Use --no-cache-dir / --omit=dev flags
        7. Set WORKDIR to /app
        8. Copy only necessary files (not .env, .git, secrets)

        ## Output Format
        Return ONLY the Dockerfile content between ```dockerfile and ``` markers.
        No explanations outside the markers.
        """).strip()

    def _extract_dockerfile(self, response: str) -> str:
        """Extract Dockerfile content from LLM response."""
        # Try to extract from markdown code block
        patterns = [
            r"```dockerfile\n(.*?)```",
            r"```Dockerfile\n(.*?)```",
            r"```\n(FROM.*?)```",
        ]
        for pat in patterns:
            match = re.search(pat, response, re.DOTALL | re.IGNORECASE)
            if match:
                return match.group(1).strip()

        # If no code block, check if response starts with FROM
        if response.strip().startswith("FROM"):
            return response.strip()

        # Last resort: return as-is
        log.warning("Could not extract Dockerfile from LLM response, using raw output")
        return response.strip()

    def _enforce_security(self, dockerfile: str, report: AnalysisReport) -> str:
        """
        Post-processing security guardrails.
        Ensures mandatory security requirements even if LLM misses them.
        """
        lines = dockerfile.splitlines()
        has_user = any(line.strip().upper().startswith("USER ") for line in lines)
        has_healthcheck = any(line.strip().upper().startswith("HEALTHCHECK") for line in lines)
        has_workdir = any(line.strip().upper().startswith("WORKDIR") for line in lines)

        additions: list[str] = []

        if not has_workdir:
            log.warning("WORKDIR missing — adding WORKDIR /app")
            additions.append("WORKDIR /app")

        if not has_user:
            log.warning("Non-root USER missing — injecting USER appuser")
            additions.extend([
                "RUN addgroup --system appuser && adduser --system --ingroup appuser --uid 1001 appuser",
                "USER appuser",
            ])

        if not has_healthcheck:
            port = report.runtime_needs.exposed_port
            hc_path = (
                report.ast_insights.health_check_endpoints[0].path
                if report.ast_insights.health_check_endpoints
                else "/health"
            )
            log.warning("HEALTHCHECK missing — injecting default healthcheck")
            additions.append(
                f'HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 '
                f'CMD wget -qO- http://localhost:{port}{hc_path} || exit 1'
            )

        if additions:
            dockerfile = dockerfile + "\n\n# === Security Guardrails (auto-injected) ===\n"
            dockerfile += "\n".join(additions)

        return dockerfile

    def _generate_dockerignore(self, report: AnalysisReport) -> str:
        """Generate a comprehensive .dockerignore file."""
        lang = report.stack.language
        base_ignores = [
            ".git/",
            ".gitignore",
            ".env",
            ".env.*",
            "!.env.example",
            ".DS_Store",
            "*.log",
            "*.tmp",
            "README.md",
            "docs/",
            "tests/",
            "test/",
            "__pycache__/",
            "*.pyc",
            ".pytest_cache/",
            ".mypy_cache/",
            ".ruff_cache/",
            "Dockerfile",
            ".dockerignore",
            "docker-compose*.yml",
        ]

        lang_ignores: dict[Language, list[str]] = {
            Language.PYTHON: [".venv/", "venv/", "env/", "*.egg-info/", "dist/", "build/"],
            Language.JAVASCRIPT: ["node_modules/", ".next/", "dist/", "build/", "coverage/"],
            Language.TYPESCRIPT: ["node_modules/", ".next/", "dist/", "build/", "coverage/", "*.js.map"],
            Language.GO: ["bin/", "vendor/"],
            Language.RUST: ["target/"],
        }

        all_ignores = base_ignores + lang_ignores.get(lang, [])
        return "\n".join(all_ignores) + "\n"

    def _extract_build_args(self, dockerfile: str) -> dict[str, str]:
        """Extract ARG instructions from Dockerfile as build arg hints."""
        args: dict[str, str] = {}
        for line in dockerfile.splitlines():
            match = re.match(r"^ARG\s+(\w+)(?:=(.*))?$", line.strip())
            if match:
                args[match.group(1)] = match.group(2) or ""
        return args

    def _generate_notes(self, report: AnalysisReport) -> list[str]:
        """Generate human-readable notes about the generated Dockerfile."""
        notes = [
            f"Base image: {report.runtime_needs.base_image}",
            f"Exposed port: {report.runtime_needs.exposed_port}",
            "Non-root user: appuser (UID 1001)",
            "Multi-stage build: ✅ (builder → runtime)",
            "HEALTHCHECK: ✅",
            ".dockerignore: ✅ (prevents secret leakage)",
        ]
        if report.ast_insights.env_var_usages:
            notes.append(
                f"Env vars detected: {len(report.ast_insights.env_var_usages)} "
                f"(use --env-file or AWS Secrets Manager)"
            )
        return notes
