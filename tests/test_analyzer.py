"""
Unit tests for Module 1: Semantic Analyzer.
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from infragenie.analyzer.models import Framework, Language, StackDetectionResult
from infragenie.analyzer.detectors import (
    detect_from_requirements_txt,
    detect_from_package_json,
    detect_from_go_mod,
    detect_stack,
)
from infragenie.analyzer.parsers import parse_project
from infragenie.analyzer.analyzer import SemanticAnalyzer


# -----------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------

@pytest.fixture
def tmp_python_project(tmp_path: Path) -> Path:
    """Create a minimal FastAPI project fixture."""
    (tmp_path / "requirements.txt").write_text(
        "fastapi==0.111.0\nuvicorn==0.30.0\npydantic>=2.7.0\n"
    )
    (tmp_path / "main.py").write_text(
        'import os\nfrom fastapi import FastAPI\n\napp = FastAPI()\nPORT = int(os.getenv("PORT", "8080"))\nport = 8080\n\n@app.get("/health")\ndef health(): return {"status": "ok"}\n\nif __name__ == "__main__":\n    import uvicorn\n    uvicorn.run(app, host="0.0.0.0", port=8080)\n'
    )
    return tmp_path


@pytest.fixture
def tmp_node_project(tmp_path: Path) -> Path:
    """Create a minimal Express project fixture."""
    pkg = {
        "name": "my-api",
        "version": "1.0.0",
        "main": "index.js",
        "engines": {"node": ">=20"},
        "dependencies": {"express": "^4.19.0"},
        "devDependencies": {"nodemon": "^3.0.0"},
    }
    (tmp_path / "package.json").write_text(json.dumps(pkg))
    (tmp_path / "index.js").write_text(
        "const express = require('express');\nconst app = express();\nconst PORT = process.env.PORT || 3000;\napp.get('/health', (req, res) => res.json({status: 'ok'}));\napp.listen(PORT);\n"
    )
    return tmp_path


@pytest.fixture
def tmp_go_project(tmp_path: Path) -> Path:
    """Create a minimal Go project fixture."""
    (tmp_path / "go.mod").write_text(
        "module github.com/user/myapp\n\ngo 1.22\n\nrequire (\n\tgithub.com/gin-gonic/gin v1.10.0\n)\n"
    )
    (tmp_path / "main.go").write_text(
        'package main\n\nimport (\n\t"os"\n\t"github.com/gin-gonic/gin"\n)\n\nfunc main() {\n\tr := gin.Default()\n\tr.GET("/health", func(c *gin.Context) { c.JSON(200, gin.H{"status": "ok"}) })\n\tport := os.Getenv("PORT")\n\tif port == "" { port = "8080" }\n\tr.Run(":" + port)\n}\n'
    )
    return tmp_path


# -----------------------------------------------------------------------
# Detector Tests
# -----------------------------------------------------------------------

class TestRequirementsTxtDetector:
    def test_detects_fastapi(self, tmp_python_project: Path) -> None:
        result = detect_from_requirements_txt(tmp_python_project / "requirements.txt")
        assert result.language == Language.PYTHON
        assert result.framework == Framework.FASTAPI

    def test_parses_all_deps(self, tmp_python_project: Path) -> None:
        result = detect_from_requirements_txt(tmp_python_project / "requirements.txt")
        dep_names = [d.name for d in result.dependencies]
        assert "fastapi" in dep_names
        assert "uvicorn" in dep_names

    def test_empty_requirements(self, tmp_path: Path) -> None:
        (tmp_path / "requirements.txt").write_text("# just a comment\n")
        result = detect_from_requirements_txt(tmp_path / "requirements.txt")
        assert result.language == Language.PYTHON
        assert len(result.dependencies) == 0


class TestPackageJsonDetector:
    def test_detects_express(self, tmp_node_project: Path) -> None:
        result = detect_from_package_json(tmp_node_project / "package.json")
        assert result.language == Language.JAVASCRIPT
        assert result.framework == Framework.EXPRESS

    def test_detects_entry_point(self, tmp_node_project: Path) -> None:
        result = detect_from_package_json(tmp_node_project / "package.json")
        assert result.entry_point == "index.js"

    def test_separates_dev_deps(self, tmp_node_project: Path) -> None:
        result = detect_from_package_json(tmp_node_project / "package.json")
        dev_names = [d.name for d in result.dev_dependencies]
        assert "nodemon" in dev_names


class TestGoModDetector:
    def test_detects_gin(self, tmp_go_project: Path) -> None:
        result = detect_from_go_mod(tmp_go_project / "go.mod")
        assert result.language == Language.GO
        assert result.framework == Framework.GIN

    def test_parses_go_version(self, tmp_go_project: Path) -> None:
        result = detect_from_go_mod(tmp_go_project / "go.mod")
        assert result.runtime_version == "1.22"


class TestStackDispatcher:
    def test_python_project(self, tmp_python_project: Path) -> None:
        result = detect_stack(tmp_python_project)
        assert result.language == Language.PYTHON

    def test_node_project(self, tmp_node_project: Path) -> None:
        result = detect_stack(tmp_node_project)
        assert result.language == Language.JAVASCRIPT

    def test_empty_project_returns_unknown(self, tmp_path: Path) -> None:
        result = detect_stack(tmp_path)
        assert result.language == Language.UNKNOWN


# -----------------------------------------------------------------------
# Parser Tests
# -----------------------------------------------------------------------

class TestASTParser:
    def test_detects_port_from_python(self, tmp_python_project: Path) -> None:
        insights = parse_project(tmp_python_project, Language.PYTHON)
        ports = [p.port for p in insights.detected_ports]
        assert 8080 in ports

    def test_detects_env_vars(self, tmp_python_project: Path) -> None:
        insights = parse_project(tmp_python_project, Language.PYTHON)
        env_names = [e.name for e in insights.env_var_usages]
        assert "PORT" in env_names

    def test_detects_health_endpoint(self, tmp_python_project: Path) -> None:
        insights = parse_project(tmp_python_project, Language.PYTHON)
        paths = [h.path for h in insights.health_check_endpoints]
        assert "/health" in paths

    def test_node_env_detection(self, tmp_node_project: Path) -> None:
        insights = parse_project(tmp_node_project, Language.JAVASCRIPT)
        env_names = [e.name for e in insights.env_var_usages]
        assert "PORT" in env_names


# -----------------------------------------------------------------------
# SemanticAnalyzer Integration Tests
# -----------------------------------------------------------------------

class TestSemanticAnalyzer:
    def test_full_analysis_python(self, tmp_python_project: Path) -> None:
        analyzer = SemanticAnalyzer()
        report = analyzer.analyze(tmp_python_project)

        assert report.stack.language == Language.PYTHON
        assert report.stack.framework == Framework.FASTAPI
        assert report.runtime_needs.exposed_port == 8080
        assert "python" in report.runtime_needs.base_image.lower()
        assert report.runtime_needs.start_command != ""

    def test_report_serialization(self, tmp_python_project: Path) -> None:
        analyzer = SemanticAnalyzer()
        report = analyzer.analyze(tmp_python_project)
        json_str = report.to_json()
        reconstructed = type(report).from_json(json_str)
        assert reconstructed.project_name == report.project_name

    def test_invalid_path_raises(self) -> None:
        analyzer = SemanticAnalyzer()
        with pytest.raises(NotADirectoryError):
            analyzer.analyze(Path("/nonexistent/path"))

    def test_no_stack_raises(self, tmp_path: Path) -> None:
        from infragenie.utils.exceptions import NoStackDetectedError
        analyzer = SemanticAnalyzer()
        with pytest.raises(NoStackDetectedError):
            analyzer.analyze(tmp_path)
