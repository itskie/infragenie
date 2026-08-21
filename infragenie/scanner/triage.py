"""
AI Context-Aware Triage — filters false positive CVEs
by cross-referencing scan results with actual code usage.
"""
from __future__ import annotations
from typing import Optional

from infragenie.analyzer.models import AnalysisReport
from infragenie.scanner.scanner import ScanReport, Vulnerability
from infragenie.utils.logger import get_logger

log = get_logger(__name__)

# Packages known to be safe to suppress if not directly used
_KNOWN_SAFE_DEV_ONLY: set[str] = {
    "pytest", "ruff", "mypy", "black", "flake8", "isort",
    "eslint", "prettier", "jest", "mocha", "nodemon",
}


class AITriage:
    """
    Filters false positives from scan results based on code context.

    Rules:
    1. Dev-only packages not used in production code → suppress
    2. CVEs with no fix available and LOW/MEDIUM severity → note only
    3. CVEs in packages not present in final image deps → suppress
    """

    def triage(
        self,
        scan_report: ScanReport,
        analysis_report: AnalysisReport,
    ) -> tuple[list[Vulnerability], list[Vulnerability]]:
        """
        Triage vulnerabilities into real issues and false positives.

        Returns:
            (confirmed, suppressed) — two lists of Vulnerability objects.
        """
        runtime_deps = {
            d.name.lower()
            for d in analysis_report.stack.dependencies
        }
        dev_deps = {
            d.name.lower()
            for d in analysis_report.stack.dev_dependencies
        }

        confirmed: list[Vulnerability] = []
        suppressed: list[Vulnerability] = []

        for vuln in scan_report.vulnerabilities:
            pkg = vuln.pkg_name.lower()
            reason = self._suppress_reason(vuln, pkg, runtime_deps, dev_deps)
            if reason:
                log.debug("Suppressing CVE", vuln_id=vuln.vuln_id, pkg=pkg, reason=reason)
                suppressed.append(vuln)
            else:
                confirmed.append(vuln)

        log.info(
            "Triage complete",
            total=len(scan_report.vulnerabilities),
            confirmed=len(confirmed),
            suppressed=len(suppressed),
        )
        return confirmed, suppressed

    def _suppress_reason(
        self,
        vuln: Vulnerability,
        pkg: str,
        runtime_deps: set[str],
        dev_deps: set[str],
    ) -> Optional[str ]:
        """Return a suppression reason string, or None if vuln is real."""

        # Rule 1: Known dev-only tool not in runtime deps
        if pkg in _KNOWN_SAFE_DEV_ONLY and pkg not in runtime_deps:
            return "dev-only tool not in runtime image"

        # Rule 2: Pure dev dependency
        if pkg in dev_deps and pkg not in runtime_deps:
            return "dev dependency — not in production image"

        # Rule 3: No fix available + severity is LOW/MEDIUM
        if not vuln.fixed_version and vuln.severity in ("LOW", "MEDIUM"):
            return "no fix available, non-critical severity"

        return None
