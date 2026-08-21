"""Unit test stubs for Module 3: Security Scanner."""
from __future__ import annotations
import json
import pytest
from unittest.mock import MagicMock, patch


class TestSecurityScanner:
    def test_raises_if_trivy_missing(self):
        """TrivyNotFoundError raised when trivy is not in PATH."""
        from infragenie.utils.exceptions import TrivyNotFoundError
        with patch("shutil.which", return_value=None):
            with pytest.raises(TrivyNotFoundError):
                from infragenie.scanner import SecurityScanner
                # Force re-init without cache
                import importlib
                import infragenie.scanner.scanner as m
                importlib.reload(m)
                m.SecurityScanner()

    def test_scan_report_passed_on_no_vulns(self):
        """ScanReport.passed is True when no vulnerabilities found."""
        from infragenie.scanner.scanner import SecurityScanner, ScanReport
        with patch("shutil.which", return_value="/usr/bin/trivy"):
            scanner = SecurityScanner()
            report = scanner._parse_output(
                json.dumps({"Results": []}),
                target="./test",
                scan_type="filesystem",
            )
        assert report.passed is True
        assert len(report.vulnerabilities) == 0

    def test_scan_report_fails_on_critical(self):
        """ScanReport raises ScanFailedError on CRITICAL vulns."""
        from infragenie.scanner.scanner import SecurityScanner
        from infragenie.utils.exceptions import ScanFailedError

        trivy_output = json.dumps({"Results": [{"Vulnerabilities": [{
            "VulnerabilityID": "CVE-2024-0001",
            "PkgName": "requests",
            "InstalledVersion": "2.28.0",
            "FixedVersion": "2.32.0",
            "Severity": "CRITICAL",
            "Title": "Test CVE",
        }]}]})

        with patch("shutil.which", return_value="/usr/bin/trivy"):
            scanner = SecurityScanner()
            with pytest.raises(ScanFailedError):
                scanner._parse_output(trivy_output, target="./test", scan_type="filesystem")


class TestAITriage:
    def test_suppresses_dev_only_packages(self, tmp_path):
        from infragenie.analyzer import SemanticAnalyzer
        from infragenie.scanner.scanner import ScanReport, Vulnerability
        from infragenie.scanner.triage import AITriage

        (tmp_path / "requirements.txt").write_text("fastapi==0.111.0\n")
        (tmp_path / "main.py").write_text("PORT=8080\n")
        report = SemanticAnalyzer().analyze(tmp_path)

        scan = ScanReport(target="test", scan_type="filesystem")
        scan.vulnerabilities = [
            Vulnerability(
                vuln_id="CVE-2024-9999",
                pkg_name="pytest",
                installed_version="8.0.0",
                fixed_version="8.1.0",
                severity="HIGH",
                title="test",
            )
        ]

        confirmed, suppressed = AITriage().triage(scan, report)
        assert len(suppressed) == 1  # pytest is dev-only
        assert suppressed[0].vuln_id == "CVE-2024-9999"
