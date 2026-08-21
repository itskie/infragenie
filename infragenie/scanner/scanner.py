"""
Module 3: Security Scanner — Trivy integration.
Scans filesystem and Docker images for CVEs.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from infragenie.config import settings
from infragenie.utils.exceptions import ScanFailedError, TrivyNotFoundError, ScannerError
from infragenie.utils.logger import get_logger

log = get_logger(__name__)


@dataclass
class Vulnerability:
    """A single CVE finding from Trivy."""
    vuln_id: str
    pkg_name: str
    installed_version: str
    fixed_version: str
    severity: str
    title: str
    description: str = ""
    references: list[str] = field(default_factory=list)


@dataclass
class ScanReport:
    """Aggregated result from a Trivy scan."""
    target: str
    scan_type: str  # "filesystem" | "image"
    vulnerabilities: list[Vulnerability] = field(default_factory=list)
    passed: bool = True
    summary: dict[str, int] = field(default_factory=dict)

    @property
    def critical_count(self) -> int:
        return self.summary.get("CRITICAL", 0)

    @property
    def high_count(self) -> int:
        return self.summary.get("HIGH", 0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "scan_type": self.scan_type,
            "passed": self.passed,
            "summary": self.summary,
            "vulnerabilities": [
                {
                    "id": v.vuln_id,
                    "package": v.pkg_name,
                    "installed": v.installed_version,
                    "fixed": v.fixed_version,
                    "severity": v.severity,
                    "title": v.title,
                }
                for v in self.vulnerabilities
            ],
        }


class SecurityScanner:
    """
    Trivy-powered security scanner.

    Usage:
        scanner = SecurityScanner()
        report = scanner.scan_filesystem(Path("./my-project"))
        report = scanner.scan_image("my-image:latest")
    """

    def __init__(self) -> None:
        self._trivy_path = self._find_trivy()

    def _find_trivy(self) -> str:
        """Locate Trivy binary or raise TrivyNotFoundError."""
        path = shutil.which("trivy")
        if not path:
            raise TrivyNotFoundError()
        log.info("Trivy found", path=path)
        return path

    def scan_filesystem(self, path: Path) -> ScanReport:
        """
        Scan a filesystem directory for vulnerabilities before building.
        """
        log.info("Scanning filesystem", path=str(path))
        return self._run_scan(target=str(path), scan_type="filesystem")

    def scan_image(self, image_tag: str) -> ScanReport:
        """
        Scan a built Docker image for vulnerabilities.
        """
        log.info("Scanning image", image=image_tag)
        return self._run_scan(target=image_tag, scan_type="image")

    def _run_scan(self, target: str, scan_type: str) -> ScanReport:
        """Execute Trivy and parse JSON output."""
        cmd = [
            self._trivy_path,
            scan_type,
            "--format", "json",
            "--severity", settings.trivy_severity,
            "--quiet",
            target,
        ]

        log.debug("Running Trivy", cmd=" ".join(cmd))

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
            )
        except subprocess.TimeoutExpired:
            raise ScannerError(f"Trivy scan timed out for: {target}")  # type: ignore

        if result.returncode not in (0, 1):  # 1 = vulns found (expected)
            log.error("Trivy error", stderr=result.stderr[:500])
            raise ScannerError(f"Trivy exited with code {result.returncode}: {result.stderr[:200]}")

        return self._parse_output(result.stdout, target, scan_type)

    def _parse_output(self, stdout: str, target: str, scan_type: str) -> ScanReport:
        """Parse Trivy JSON output into a ScanReport."""
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            log.warning("Could not parse Trivy JSON output")
            return ScanReport(target=target, scan_type=scan_type, passed=True)

        vulns: list[Vulnerability] = []
        summary: dict[str, int] = {}

        for result in data.get("Results", []):
            for v in result.get("Vulnerabilities", []):
                severity = v.get("Severity", "UNKNOWN")
                summary[severity] = summary.get(severity, 0) + 1
                vulns.append(Vulnerability(
                    vuln_id=v.get("VulnerabilityID", ""),
                    pkg_name=v.get("PkgName", ""),
                    installed_version=v.get("InstalledVersion", ""),
                    fixed_version=v.get("FixedVersion", ""),
                    severity=severity,
                    title=v.get("Title", ""),
                    description=v.get("Description", "")[:300],
                    references=v.get("References", [])[:3],
                ))

        # Determine pass/fail
        target_severities = settings.trivy_severity_list
        failed = any(summary.get(s, 0) > 0 for s in target_severities)

        report = ScanReport(
            target=target,
            scan_type=scan_type,
            vulnerabilities=vulns,
            passed=not failed,
            summary=summary,
        )

        log.info(
            "Scan complete",
            target=target,
            total=len(vulns),
            summary=summary,
            passed=report.passed,
        )

        if not report.passed:
            raise ScanFailedError(
                critical=summary.get("CRITICAL", 0),
                high=summary.get("HIGH", 0),
            )

        return report
