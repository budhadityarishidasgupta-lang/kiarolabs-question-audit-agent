from __future__ import annotations

import json
from pathlib import Path

from .models import DbAuditSummary


REPORTS_DIR = Path("reports")


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_db_audit_reports(summary: DbAuditSummary) -> tuple[Path, Path]:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    json_path = REPORTS_DIR / "db-audit-latest.json"
    md_path = REPORTS_DIR / "db-audit-latest.md"

    json_payload = {
        "overall_clearance": summary.overall_clearance.value,
        "connection_status": summary.connection_status,
        "safe_actions": summary.safe_actions,
        "blocked_actions": summary.blocked_actions,
        "warnings": summary.warnings,
        "recommended_next_step": summary.recommended_next_step,
        "evidence": summary.evidence,
        "checks": [
            {
                "name": check.name,
                "status": check.status,
                "detail": check.detail,
                "evidence": check.evidence,
            }
            for check in summary.check_results
        ],
    }

    markdown = "\n".join(
        [
            "# Database Audit Report",
            "",
            f"## Database connection status",
            "",
            f"- Status: `{summary.connection_status}`",
            f"- Overall clearance: `{summary.overall_clearance.value}`",
            "",
            "## Table and view existence",
            "",
            *[
                f"- {check.name}: `{check.status}` - {check.detail}"
                for check in summary.check_results
                if "exists" in check.name or "view" in check.name
            ],
            "",
            "## Columns present/missing",
            "",
            f"- `public.attempts` present: {', '.join(summary.evidence.get('attempts_columns', [])) or 'none found'}",
            f"- `public.spelling_attempts` present: {', '.join(summary.evidence.get('spelling_attempts_columns', [])) or 'none found'}",
            "",
            "## Row counts",
            "",
            *[
                f"- `{table_name}`: {row_count}"
                for table_name, row_count in summary.evidence.get("row_counts", {}).items()
            ],
            "",
            "## View status",
            "",
            f"- `public.spelling_words_contract`: `{'present' if summary.evidence.get('view_exists') else 'missing'}`",
            "",
            "## Safety decision",
            "",
            f"- Clearance: `{summary.overall_clearance.value}`",
            f"- Decision: {summary.recommended_next_step}",
            "",
            "## Warnings",
            "",
            *([f"- {item}" for item in summary.warnings] or ["- None"]),
            "",
        ]
    )

    _write_json(json_path, json_payload)
    md_path.write_text(markdown, encoding="utf-8")
    return json_path, md_path
