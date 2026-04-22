from __future__ import annotations

import json
from pathlib import Path

from .models import AuditResult


REPORTS_DIR = Path("reports")


def write_audit_report(result: AuditResult) -> tuple[Path, Path]:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = REPORTS_DIR / "latest-report.json"
    md_path = REPORTS_DIR / "latest-report.md"

    json_path.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")

    markdown = "\n".join(
        [
            "# Audit Report",
            "",
            f"- Audit: `{result.metadata.audit_name}`",
            f"- Mode: `{result.metadata.mode}`",
            f"- Findings: {len(result.findings)}",
            "",
            "## Findings",
            "",
            *(
                [f"- [{finding.severity}] {finding.title}: {finding.detail}" for finding in result.findings]
                or ["- None"]
            ),
            "",
            "## Notes",
            "",
            *([f"- {note}" for note in result.notes] or ["- None"]),
            "",
            "## Errors",
            "",
            *([f"- {error}" for error in result.errors] or ["- None"]),
            "",
        ]
    )
    md_path.write_text(markdown, encoding="utf-8")
    return json_path, md_path


def should_fail(result: AuditResult, fail_on: set[str]) -> bool:
    if not fail_on:
        return False
    return any((finding.severity or "").lower() in fail_on for finding in result.findings)
