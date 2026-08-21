"""
Tech stack detectors — parse dependency manifests to identify language,
framework, runtime version, and dependencies without AST parsing.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import toml

from infragenie.analyzer.models import (
    DependencyInfo,
    Framework,
    Language,
    StackDetectionResult,
)
from infragenie.utils.logger import get_logger

log = get_logger(__name__)

# Maps common packages to frameworks
_PY_FRAMEWORK_MAP: dict[str, Framework] = {
    "fastapi": Framework.FASTAPI,
    "flask": Framework.FLASK,
    "django": Framework.DJANGO,
}

_JS_FRAMEWORK_MAP: dict[str, Framework] = {
    "express": Framework.EXPRESS,
    "next": Framework.NEXTJS,
    "nextjs": Framework.NEXTJS,
}

_GO_FRAMEWORK_MAP: dict[str, Framework] = {
    "github.com/gin-gonic/gin": Framework.GIN,
    "github.com/labstack/echo": Framework.ECHO,
}


def _parse_version(raw: Any) -> str:
    """Normalize a version specifier to a plain string."""
    if isinstance(raw, dict):
        return raw.get("version", "*")
    return str(raw).lstrip("^~>=<! ")


# ---------------------------------------------------------------------------
# Python
# ---------------------------------------------------------------------------

def detect_from_requirements_txt(path: Path) -> StackDetectionResult:
    """Parse requirements.txt or requirements/*.txt files."""
    deps: list[DependencyInfo] = []
    framework = Framework.UNKNOWN
    text = path.read_text(encoding="utf-8", errors="ignore")

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        match = re.match(r"^([A-Za-z0-9_\-\.]+)\s*([><=!~^]*.*)?$", line)
        if match:
            name = match.group(1).lower()
            version = (match.group(2) or "*").strip() or "*"
            deps.append(DependencyInfo(name=name, version=version))
            if name in _PY_FRAMEWORK_MAP and framework == Framework.UNKNOWN:
                framework = _PY_FRAMEWORK_MAP[name]

    log.info("requirements.txt parsed", deps=len(deps), framework=framework)
    return StackDetectionResult(
        language=Language.PYTHON,
        framework=framework,
        package_manager="pip",
        dependencies=deps,
    )


def detect_from_pyproject_toml(path: Path) -> StackDetectionResult:
    """Parse pyproject.toml (PEP 518/621) for Python projects."""
    data = toml.loads(path.read_text(encoding="utf-8"))
    project = data.get("project", {})
    raw_deps: list[str] = project.get("dependencies", [])

    deps: list[DependencyInfo] = []
    framework = Framework.UNKNOWN
    runtime_version = ""

    # Extract Python version from requires-python
    if req_py := project.get("requires-python", ""):
        runtime_version = req_py.lstrip(">=<!")

    for raw in raw_deps:
        match = re.match(r"^([A-Za-z0-9_\-\.]+)\s*([><=!~^].*)?$", raw.strip())
        if match:
            name = match.group(1).lower()
            version = (match.group(2) or "*").strip() or "*"
            deps.append(DependencyInfo(name=name, version=version))
            if name in _PY_FRAMEWORK_MAP and framework == Framework.UNKNOWN:
                framework = _PY_FRAMEWORK_MAP[name]

    pm = "uv" if (path.parent / "uv.lock").exists() else "pip"
    log.info("pyproject.toml parsed", deps=len(deps), framework=framework)
    return StackDetectionResult(
        language=Language.PYTHON,
        framework=framework,
        runtime_version=runtime_version,
        package_manager=pm,
        dependencies=deps,
        raw_manifest=data,
    )


# ---------------------------------------------------------------------------
# Node.js / JavaScript / TypeScript
# ---------------------------------------------------------------------------

def detect_from_package_json(path: Path) -> StackDetectionResult:
    """Parse package.json for Node.js/JS/TS projects."""
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    framework = Framework.UNKNOWN
    language = Language.JAVASCRIPT

    # Check for TypeScript
    all_deps = {
        **data.get("dependencies", {}),
        **data.get("devDependencies", {}),
    }
    if "typescript" in all_deps:
        language = Language.TYPESCRIPT

    # Detect framework
    for pkg, fw in _JS_FRAMEWORK_MAP.items():
        if pkg in all_deps and framework == Framework.UNKNOWN:
            framework = fw

    # Runtime version from engines field
    engines = data.get("engines", {})
    runtime_version = engines.get("node", "")

    # Entry point from main / module field
    entry_point = data.get("main", data.get("module", "index.js"))

    deps = [
        DependencyInfo(name=k, version=_parse_version(v))
        for k, v in data.get("dependencies", {}).items()
    ]
    dev_deps = [
        DependencyInfo(name=k, version=_parse_version(v), is_dev=True)
        for k, v in data.get("devDependencies", {}).items()
    ]

    pm = "yarn" if (path.parent / "yarn.lock").exists() else "npm"
    if (path.parent / "pnpm-lock.yaml").exists():
        pm = "pnpm"

    log.info("package.json parsed", deps=len(deps), framework=framework)
    return StackDetectionResult(
        language=language,
        framework=framework,
        runtime_version=runtime_version,
        package_manager=pm,
        entry_point=entry_point,
        dependencies=deps,
        dev_dependencies=dev_deps,
        raw_manifest=data,
    )


# ---------------------------------------------------------------------------
# Go
# ---------------------------------------------------------------------------

def detect_from_go_mod(path: Path) -> StackDetectionResult:
    """Parse go.mod for Go projects."""
    text = path.read_text(encoding="utf-8", errors="ignore")
    framework = Framework.UNKNOWN
    runtime_version = ""
    deps: list[DependencyInfo] = []

    for line in text.splitlines():
        line = line.strip()
        if line.startswith("go "):
            runtime_version = line.split()[1]
        elif line.startswith("require"):
            continue
        elif line and not line.startswith("module") and not line.startswith(")"):
            parts = line.split()
            if len(parts) >= 2:
                name, version = parts[0], parts[1]
                deps.append(DependencyInfo(name=name, version=version))
                for pkg, fw in _GO_FRAMEWORK_MAP.items():
                    if pkg in name and framework == Framework.UNKNOWN:
                        framework = fw

    log.info("go.mod parsed", deps=len(deps), framework=framework)
    return StackDetectionResult(
        language=Language.GO,
        framework=framework,
        runtime_version=runtime_version,
        package_manager="go modules",
        dependencies=deps,
    )


# ---------------------------------------------------------------------------
# Rust
# ---------------------------------------------------------------------------

def detect_from_cargo_toml(path: Path) -> StackDetectionResult:
    """Parse Cargo.toml for Rust projects."""
    data = toml.loads(path.read_text(encoding="utf-8"))
    package = data.get("package", {})
    raw_deps = data.get("dependencies", {})

    deps = [
        DependencyInfo(name=k, version=_parse_version(v))
        for k, v in raw_deps.items()
    ]

    log.info("Cargo.toml parsed", deps=len(deps))
    return StackDetectionResult(
        language=Language.RUST,
        package_manager="cargo",
        runtime_version=package.get("edition", ""),
        dependencies=deps,
        raw_manifest=data,
    )


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

# Maps manifest filename → detector function
MANIFEST_DETECTORS: dict[str, Any] = {
    "requirements.txt": detect_from_requirements_txt,
    "pyproject.toml": detect_from_pyproject_toml,
    "package.json": detect_from_package_json,
    "go.mod": detect_from_go_mod,
    "Cargo.toml": detect_from_cargo_toml,
}

MANIFEST_PRIORITY = [
    "pyproject.toml",
    "requirements.txt",
    "package.json",
    "go.mod",
    "Cargo.toml",
]


def detect_stack(project_path: Path) -> StackDetectionResult:
    """
    Auto-detect tech stack by scanning for known manifest files.
    Uses priority order — first match wins.
    """
    for manifest_name in MANIFEST_PRIORITY:
        manifest_path = project_path / manifest_name
        if manifest_path.exists():
            detector = MANIFEST_DETECTORS[manifest_name]
            log.info("Stack manifest found", manifest=manifest_name)
            try:
                return detector(manifest_path)
            except Exception as exc:
                log.warning("Detector failed", manifest=manifest_name, error=str(exc))

    log.warning("No manifest found", path=str(project_path))
    return StackDetectionResult()
