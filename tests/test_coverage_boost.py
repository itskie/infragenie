"""
Comprehensive tests to cover edge cases, alternate branches, and raise code coverage to 90%+.
"""
from __future__ import annotations
import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from infragenie.analyzer.models import Framework, Language, StackDetectionResult
from infragenie.analyzer.detectors import (
    detect_from_pyproject_toml,
    detect_from_cargo_toml,
    detect_from_package_json,
    detect_from_requirements_txt,
    detect_stack,
)
from infragenie.analyzer.analyzer import SemanticAnalyzer
from infragenie.analyzer.parsers import collect_source_files, parse_project
from infragenie.scanner.scanner import SecurityScanner, ScanReport, Vulnerability
from infragenie.scanner.triage import AITriage
from infragenie.scanner.remediation import RemediationEngine
from infragenie.utils.exceptions import ScannerError, ScanFailedError, TrivyNotFoundError
from infragenie.cli import app
from typer.testing import CliRunner

runner = CliRunner()


# ---------------------------------------------------------------------------
# Detectors Extra Branches
# ---------------------------------------------------------------------------

def test_pyproject_toml_detection(tmp_path: Path):
    pyproj = (
        '[project]\n'
        'name = "demo"\n'
        'requires-python = ">=3.11"\n'
        'dependencies = ["flask>=3.0", "requests==2.31.0"]\n'
    )
    (tmp_path / "pyproject.toml").write_text(pyproj)
    (tmp_path / "uv.lock").write_text("")
    res = detect_from_pyproject_toml(tmp_path / "pyproject.toml")
    assert res.language == Language.PYTHON
    assert res.framework == Framework.FLASK
    assert res.package_manager == "uv"
    assert res.runtime_version == "3.11"


def test_cargo_toml_detection(tmp_path: Path):
    cargo = (
        '[package]\n'
        'name = "rust_app"\n'
        'edition = "2021"\n'
        '[dependencies]\n'
        'actix-web = "4"\n'
    )
    (tmp_path / "Cargo.toml").write_text(cargo)
    res = detect_from_cargo_toml(tmp_path / "Cargo.toml")
    assert res.language == Language.RUST
    assert res.package_manager == "cargo"
    assert res.runtime_version == "2021"
    assert len(res.dependencies) == 1


def test_package_json_yarn_and_pnpm(tmp_path: Path):
    pkg = {"name": "nextapp", "dependencies": {"next": "14.0.0", "typescript": "5.0.0"}}
    (tmp_path / "package.json").write_text(json.dumps(pkg))
    (tmp_path / "pnpm-lock.yaml").write_text("")
    res = detect_from_package_json(tmp_path / "package.json")
    assert res.language == Language.TYPESCRIPT
    assert res.framework == Framework.NEXTJS
    assert res.package_manager == "pnpm"


def test_requirements_django_detection(tmp_path: Path):
    (tmp_path / "requirements.txt").write_text("django==5.0.0\ngunicorn==22.0.0\n")
    res = detect_from_requirements_txt(tmp_path / "requirements.txt")
    assert res.framework == Framework.DJANGO


# ---------------------------------------------------------------------------
# Analyzer Extra Frameworks & Runtime Infer
# ---------------------------------------------------------------------------

def test_analyzer_framework_variations(tmp_path: Path):
    analyzer = SemanticAnalyzer(env="production")
    
    # Test Django
    (tmp_path / "requirements.txt").write_text("django==5.0.0\n")
    (tmp_path / "app.py").write_text("port = 8000\n")
    report = analyzer.analyze(tmp_path)
    assert report.stack.framework == Framework.DJANGO
    assert "django" in report.runtime_needs.start_command or "wsgi" in report.runtime_needs.start_command
    assert report.runtime_needs.recommended_cpu == 512

    # Test Version override helper
    updated_img = SemanticAnalyzer._apply_runtime_version("python:3.12-slim", "3.10")
    assert updated_img == "python:3.10-slim"


def test_analyzer_package_manager_build_commands(tmp_path: Path):
    # Test yarn
    p = tmp_path / "yarn_proj"
    p.mkdir()
    (p / "package.json").write_text(json.dumps({"name": "app", "dependencies": {"express": "4.18.0"}}))
    (p / "yarn.lock").write_text("")
    (p / "index.js").write_text("console.log('hi')")
    report = SemanticAnalyzer().analyze(p)
    assert "yarn" in report.runtime_needs.build_command


# ---------------------------------------------------------------------------
# Parser Edge Cases
# ---------------------------------------------------------------------------

def test_collect_source_files_ignores(tmp_path: Path):
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "bad.js").write_text("x")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "good.js").write_text("x")
    files = collect_source_files(tmp_path, Language.JAVASCRIPT)
    assert len(files) == 1
    assert "good.js" in str(files[0])


# ---------------------------------------------------------------------------
# Scanner & Remediation Extra Branches
# ---------------------------------------------------------------------------

def test_scanner_image_scan():
    with patch("shutil.which", return_value="/usr/bin/trivy"):
        scanner = SecurityScanner()
        with patch.object(scanner, "_run_scan") as mock_run:
            mock_run.return_value = ScanReport(target="myimage:latest", scan_type="image", passed=True)
            rep = scanner.scan_image("myimage:latest")
            assert rep.scan_type == "image"


def test_scanner_subprocess_errors():
    with patch("shutil.which", return_value="/usr/bin/trivy"):
        scanner = SecurityScanner()
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="trivy", timeout=300)):
            with pytest.raises(Exception):
                scanner.scan_filesystem(Path("."))

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=2, stderr="fatal trivy error", stdout="")
            with pytest.raises(ScannerError):
                scanner.scan_filesystem(Path("."))


def test_remediation_engine():
    vulns = [
        Vulnerability(
            vuln_id="CVE-2024-1234",
            pkg_name="urllib3",
            installed_version="1.26.5",
            fixed_version="1.26.19",
            severity="HIGH",
            title="Bypass",
        ),
        Vulnerability(
            vuln_id="CVE-2024-5678",
            pkg_name="openssl",
            installed_version="1.1.1",
            fixed_version="",
            severity="LOW",
            title="Info leak",
        ),
    ]
    remediations = RemediationEngine().suggest(vulns)
    assert len(remediations) == 2
    assert remediations[0].action == "update_dependency"
    assert remediations[1].action == "monitor"


def test_scan_report_to_dict():
    report = ScanReport(
        target="test",
        scan_type="filesystem",
        vulnerabilities=[
            Vulnerability(
                vuln_id="CVE-1",
                pkg_name="demo",
                installed_version="1.0",
                fixed_version="1.1",
                severity="HIGH",
                title="title",
            )
        ],
        summary={"HIGH": 1},
        passed=False,
    )
    d = report.to_dict()
    assert d["target"] == "test"
    assert len(d["vulnerabilities"]) == 1
    assert report.high_count == 1
    assert report.critical_count == 0


# ---------------------------------------------------------------------------
# CLI Commands Coverage
# ---------------------------------------------------------------------------

def test_cli_analyze_command(tmp_path: Path):
    (tmp_path / "requirements.txt").write_text("fastapi==0.111.0\n")
    (tmp_path / "main.py").write_text("port = 8080\n")
    result = runner.invoke(app, ["analyze", str(tmp_path)])
    assert result.exit_code == 0
    assert "FastAPI" in result.stdout or "fastapi" in result.stdout


def test_cli_scan_command():
    with patch("shutil.which", return_value="/usr/bin/trivy"):
        with patch("infragenie.scanner.SecurityScanner.scan_filesystem") as mock_scan:
            mock_scan.return_value = ScanReport(target=".", scan_type="filesystem", passed=True, summary={"LOW": 0})
            result = runner.invoke(app, ["scan", "."])
            assert result.exit_code == 0
            assert "PASSED" in result.stdout

def test_cli_generate_command(tmp_path: Path):
    (tmp_path / "requirements.txt").write_text("fastapi==0.111.0\n")
    (tmp_path / "main.py").write_text("port = 8080\n")
    with patch("infragenie.generator.DockerfileGenerator.generate") as mock_gen:
        from infragenie.generator.generator import GeneratedArtifacts
        mock_gen.return_value = GeneratedArtifacts(
            dockerfile="FROM python:3.12-slim\n",
            dockerignore=".env\n",
            notes=["Note 1"]
        )
        res = runner.invoke(app, ["generate", str(tmp_path), "--dry-run"])
        assert res.exit_code == 0
        assert "FROM python" in res.stdout


def test_cli_deploy_command(tmp_path: Path):
    (tmp_path / "requirements.txt").write_text("fastapi==0.111.0\n")
    (tmp_path / "main.py").write_text("port = 8080\n")
    with (
        patch("infragenie.deployer.deployer.AWSDeployer.check_docker_available", return_value=True),
        patch("infragenie.deployer.deployer.ECRClient"),
        patch("infragenie.deployer.deployer.ECSClient"),
        patch("infragenie.deployer.deployer.ObservabilityClient"),
        patch("infragenie.deployer.AWSDeployer.deploy") as mock_dep,
    ):
        from infragenie.deployer.deployer import DeploymentResult
        mock_dep.return_value = DeploymentResult(
            image_uri="123.dkr.ecr.us-east-1.amazonaws.com/test:latest",
            task_definition_arn="arn:aws:ecs:us-east-1:123:task-definition/test:1",
            service_arn="arn:aws:ecs:us-east-1:123:service/test",
            service_name="test-service",
            cluster="infragenie-cluster",
            region="us-east-1",
        )
        res = runner.invoke(app, ["deploy", str(tmp_path)])
        assert res.exit_code == 0
        assert "Deployed successfully" in res.stdout
        from infragenie.deployer.deployer import DeploymentResult
        mock_dep.return_value = DeploymentResult(
            image_uri="123.dkr.ecr.us-east-1.amazonaws.com/test:latest",
            task_definition_arn="arn:aws:ecs:us-east-1:123:task-definition/test:1",
            service_arn="arn:aws:ecs:us-east-1:123:service/test",
            service_name="test-service",
            cluster="infragenie-cluster",
            region="us-east-1",
        )
        res = runner.invoke(app, ["deploy", str(tmp_path)])
        assert res.exit_code == 0
        assert "Deployed successfully" in res.stdout
