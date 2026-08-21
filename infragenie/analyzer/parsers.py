"""
Tree-sitter powered AST parsers.
Extracts runtime insights from source code — ports, env vars,
health check endpoints, file I/O hints, and async patterns.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Sequence

from infragenie.analyzer.models import (
    ASTInsights,
    EnvVarUsage,
    HealthCheckInfo,
    Language,
    PortBinding,
    VolumeHint,
)
from infragenie.utils.logger import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Tree-sitter language loader (lazy)
# ---------------------------------------------------------------------------

def _load_language(lang: Language):  # type: ignore[return]
    """Lazily load tree-sitter Language object for a given language."""
    try:
        if lang == Language.PYTHON:
            import tree_sitter_python as tspython
            from tree_sitter import Language as TSLanguage
            return TSLanguage(tspython.language())
        elif lang in (Language.JAVASCRIPT, Language.TYPESCRIPT):
            import tree_sitter_javascript as tsjs
            from tree_sitter import Language as TSLanguage
            return TSLanguage(tsjs.language())
        elif lang == Language.GO:
            import tree_sitter_go as tsgo
            from tree_sitter import Language as TSLanguage
            return TSLanguage(tsgo.language())
    except ImportError as e:
        log.warning("Tree-sitter grammar not installed", language=lang, error=str(e))
    return None


# ---------------------------------------------------------------------------
# Source code analysis helpers
# ---------------------------------------------------------------------------

# Regex patterns for fast pre-filter before AST (fallback friendly)
_PORT_PATTERNS = [
    re.compile(r'(?:port|PORT)\s*[=:]\s*(\d{2,5})'),
    re.compile(r'listen\s*\(\s*["\']?(\d{2,5})["\']?'),
    re.compile(r'uvicorn\.run\([^)]*port\s*=\s*(\d{2,5})'),
    re.compile(r'app\.run\([^)]*port\s*=\s*(\d{2,5})'),
    re.compile(r':(\d{4,5})["\'\s]'),
]

_ENV_PATTERNS = [
    re.compile(r'os\.environ\.get\s*\(\s*["\']([A-Z_][A-Z0-9_]*)["\'](?:\s*,\s*["\']([^"\']*)["\'])?\s*\)'),
    re.compile(r'os\.getenv\s*\(\s*["\']([A-Z_][A-Z0-9_]*)["\'](?:\s*,\s*["\']([^"\']*)["\'])?\s*\)'),
    re.compile(r'process\.env\.([A-Z_][A-Z0-9_]*)'),
    re.compile(r'os\.Getenv\s*\(\s*"([A-Z_][A-Z0-9_]*)"\s*\)'),
]

_HEALTH_PATTERNS = [
    re.compile(r'["\'](/health(?:z|check)?)["\']'),
    re.compile(r'["\'](/ping)["\']'),
    re.compile(r'["\'](/ready(?:ness)?)["\']'),
    re.compile(r'["\'](/live(?:ness)?)["\']'),
    re.compile(r'["\'](/status)["\']'),
]

_FILE_IO_PATTERNS = [
    re.compile(r'open\s*\(["\']([^"\']+)["\']'),
    re.compile(r'os\.path\.(join|exists|isfile)\s*\(["\']([^"\']+)'),
    re.compile(r'Path\s*\(["\']([^"\']+)'),
    re.compile(r'fs\.(readFile|writeFile|createReadStream)\s*\(["\']([^"\']+)'),
]

_ASYNC_PATTERNS = [
    re.compile(r'\basync\s+def\b'),
    re.compile(r'\bawait\b'),
    re.compile(r'\basync\s+function\b'),
    re.compile(r'\bgo\s+func\b'),
]


def _extract_from_text(
    text: str,
    file_path: str,
) -> tuple[
    list[PortBinding],
    list[EnvVarUsage],
    list[HealthCheckInfo],
    list[VolumeHint],
    bool,
]:
    """Extract all insights from raw source text using regex patterns."""
    ports: list[PortBinding] = []
    env_vars: list[EnvVarUsage] = []
    health_checks: list[HealthCheckInfo] = []
    volumes: list[VolumeHint] = []
    has_async = False

    seen_ports: set[int] = set()
    seen_envs: set[str] = set()
    seen_health: set[str] = set()

    lines = text.splitlines()

    for line_no, line in enumerate(lines, start=1):
        # --- Ports ---
        for pat in _PORT_PATTERNS:
            for m in pat.finditer(line):
                port = int(m.group(1))
                if 1024 <= port <= 65535 and port not in seen_ports:
                    ports.append(PortBinding(port=port))
                    seen_ports.add(port)

        # --- Env vars ---
        for pat in _ENV_PATTERNS:
            for m in pat.finditer(line):
                name = m.group(1)
                if name not in seen_envs:
                    default = m.group(2) if m.lastindex and m.lastindex >= 2 else None
                    env_vars.append(EnvVarUsage(
                        name=name,
                        has_default=default is not None,
                        default_value=default,
                        file_path=file_path,
                        line_number=line_no,
                    ))
                    seen_envs.add(name)

        # --- Health checks ---
        for pat in _HEALTH_PATTERNS:
            for m in pat.finditer(line):
                path = m.group(1)
                if path not in seen_health:
                    health_checks.append(HealthCheckInfo(path=path))
                    seen_health.add(path)

        # --- File I/O ---
        for pat in _FILE_IO_PATTERNS:
            for m in pat.finditer(line):
                fp = m.group(m.lastindex or 1)
                if fp.startswith("/") and len(fp) > 1:
                    volumes.append(VolumeHint(path=fp, description=f"File I/O at line {line_no}"))

        # --- Async ---
        if not has_async:
            for pat in _ASYNC_PATTERNS:
                if pat.search(line):
                    has_async = True
                    break

    return ports, env_vars, health_checks, volumes, has_async


def _try_ast_parse(text: str, lang_obj: object, file_path: str) -> dict:
    """
    Attempt Tree-sitter AST parse and return lightweight summary.
    Falls back to empty dict on failure — regex analysis still runs.
    """
    try:
        from tree_sitter import Parser
        parser = Parser(lang_obj)  # type: ignore[arg-type]
        tree = parser.parse(bytes(text, "utf-8"))
        return {
            "root_type": tree.root_node.type,
            "child_count": tree.root_node.child_count,
            "has_errors": tree.root_node.has_error,
        }
    except Exception as exc:
        log.debug("AST parse failed (using regex fallback)", error=str(exc), file=file_path)
        return {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_SOURCE_EXTENSIONS: dict[Language, list[str]] = {
    Language.PYTHON: [".py"],
    Language.JAVASCRIPT: [".js", ".mjs", ".cjs"],
    Language.TYPESCRIPT: [".ts", ".tsx"],
    Language.GO: [".go"],
    Language.RUST: [".rs"],
}

_IGNORE_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "env",
    "dist", "build", "target", ".mypy_cache", ".ruff_cache",
}


def collect_source_files(project_path: Path, language: Language) -> list[Path]:
    """Collect all source files for a given language, ignoring common non-source dirs."""
    extensions = _SOURCE_EXTENSIONS.get(language, [])
    if not extensions:
        return []

    files: list[Path] = []
    for f in project_path.rglob("*"):
        if any(part in _IGNORE_DIRS for part in f.parts):
            continue
        if f.suffix in extensions and f.is_file():
            files.append(f)
    return files


def parse_project(project_path: Path, language: Language) -> ASTInsights:
    """
    Parse all source files in a project and return aggregated AST insights.

    Strategy:
    1. Try Tree-sitter AST parse for structured analysis.
    2. Always run regex analysis (handles parse errors gracefully).
    3. Merge and deduplicate results.
    """
    lang_obj = _load_language(language)
    files = collect_source_files(project_path, language)

    all_ports: list[PortBinding] = []
    all_envs: list[EnvVarUsage] = []
    all_health: list[HealthCheckInfo] = []
    all_volumes: list[VolumeHint] = []
    has_async = False
    parse_errors: list[str] = []

    seen_ports: set[int] = set()
    seen_envs: set[str] = set()
    seen_health: set[str] = set()

    log.info("Parsing source files", count=len(files), language=language)

    for file_path in files:
        try:
            text = file_path.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            parse_errors.append(f"{file_path}: {exc}")
            continue

        rel_path = str(file_path.relative_to(project_path))

        # Tree-sitter parse (metadata only for now)
        if lang_obj:
            ast_meta = _try_ast_parse(text, lang_obj, rel_path)
            if ast_meta.get("has_errors"):
                parse_errors.append(f"{rel_path}: AST has syntax errors")

        # Regex-based extraction
        ports, envs, health, volumes, is_async = _extract_from_text(text, rel_path)

        for p in ports:
            if p.port not in seen_ports:
                all_ports.append(p)
                seen_ports.add(p.port)

        for e in envs:
            if e.name not in seen_envs:
                all_envs.append(e)
                seen_envs.add(e.name)

        for h in health:
            if h.path not in seen_health:
                all_health.append(h)
                seen_health.add(h.path)

        all_volumes.extend(volumes)
        if is_async:
            has_async = True

    log.info(
        "Parsing complete",
        ports=len(all_ports),
        envs=len(all_envs),
        health_checks=len(all_health),
        async_code=has_async,
    )

    return ASTInsights(
        detected_ports=all_ports,
        env_var_usages=all_envs,
        health_check_endpoints=all_health,
        volume_hints=all_volumes,
        has_async_code=has_async,
        files_parsed=len(files),
        parse_errors=parse_errors,
    )
