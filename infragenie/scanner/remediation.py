"""
Auto-fix suggestion engine.
Maps CVEs to specific Dockerfile or dependency changes.
"""
from __future__ import annotations
from typing import Optional

from dataclasses import dataclass
from infragenie.scanner.scanner import Vulnerability
from infragenie.utils.logger import get_logger

log = get_logger(__name__)


@dataclass
class RemediationSuggestion:
    """A suggested fix for a vulnerability."""
    vuln_id: str
    package: str
    action: str           # "update_dependency" | "update_base_image" | "remove_package"
    suggestion: str       # Human-readable instruction
    dockerfile_change: Optional[str ] = None  # Specific Dockerfile line to change


class RemediationEngine:
    """
    Generates specific fix suggestions for confirmed vulnerabilities.
    """

    def suggest(self, vulns: list[Vulnerability]) -> list[RemediationSuggestion]:
        """Generate remediation suggestions for a list of vulnerabilities."""
        suggestions = []
        for v in vulns:
            s = self._remediate(v)
            if s:
                suggestions.append(s)
                log.debug("Suggestion generated", vuln_id=v.vuln_id, action=s.action)
        return suggestions

    def _remediate(self, v: Vulnerability) -> Optional[RemediationSuggestion ]:
        """Generate a single remediation suggestion."""
        if v.fixed_version:
            return RemediationSuggestion(
                vuln_id=v.vuln_id,
                package=v.pkg_name,
                action="update_dependency",
                suggestion=(
                    f"Update '{v.pkg_name}' from {v.installed_version} "
                    f"to {v.fixed_version} to fix {v.vuln_id} ({v.severity})."
                ),
                dockerfile_change=(
                    f"# Update: change {v.pkg_name}=={v.installed_version} "
                    f"→ {v.pkg_name}=={v.fixed_version} in requirements/package.json"
                ),
            )
        else:
            return RemediationSuggestion(
                vuln_id=v.vuln_id,
                package=v.pkg_name,
                action="monitor",
                suggestion=(
                    f"No fix available for {v.vuln_id} in '{v.pkg_name}' ({v.severity}). "
                    f"Monitor upstream for a patch. Consider removing if not required."
                ),
            )
