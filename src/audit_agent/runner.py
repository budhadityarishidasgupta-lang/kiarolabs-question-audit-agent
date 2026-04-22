from __future__ import annotations

import json
from pathlib import Path

from .db_checks import run_membership_service_migration_readiness_checks
from .db_reporting import write_db_audit_reports
from .models import AuditMetadata, AuditResult, DbAuditSummary
from .reporting import write_audit_report


class AuditRunner:
    def __init__(
        self,
        config_path: Path,
        dry_run: bool = False,
        mode: str | None = None,
        db_env_var: str = "AUDIT_DB_URL",
    ) -> None:
        self.config_path = config_path
        self.dry_run = dry_run
        self.mode = mode
        self.db_env_var = db_env_var

    def _load_config(self) -> dict:
        if not self.config_path.exists():
            return {}
        return json.loads(self.config_path.read_text(encoding="utf-8"))

    def run_db_audit(self) -> DbAuditSummary:
        summary = run_membership_service_migration_readiness_checks(db_env_var=self.db_env_var)
        write_db_audit_reports(summary)
        return summary

    def run(self):
        if self.mode == "db":
            return self.run_db_audit()

        config = self._load_config()
        mode = self.mode or config.get("mode", "local")
        audit_name = config.get("audit_name", "question-audit")

        result = AuditResult(
            metadata=AuditMetadata(audit_name=audit_name, mode=mode),
            findings=[],
            notes=[
                "Non-DB audit mode remains scaffolded in this repository.",
                "Use --mode db for live Postgres readiness inspection.",
            ],
            errors=[],
        )

        if self.dry_run:
            result.notes.append("Dry run enabled.")

        write_audit_report(result)
        return result
