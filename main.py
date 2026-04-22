from __future__ import annotations

import argparse
from pathlib import Path

from src.audit_agent.reporting import should_fail
from src.audit_agent.runner import AuditRunner


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the question accuracy audit agent.")
    parser.add_argument(
        "--mode",
        default="",
        choices=["", "local", "github", "db"],
        help="Audit mode override. Use db for read-only Postgres inspection.",
    )
    parser.add_argument(
        "--config",
        default="config/audit_targets.json",
        help="Path to the audit config JSON file.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what the agent would scan without fetching blobs or reading local file contents.",
    )
    parser.add_argument(
        "--fail-on",
        default="",
        help="Comma-separated severities that should cause a non-zero exit, for example: critical,high",
    )
    parser.add_argument(
        "--db-env-var",
        default="AUDIT_DB_URL",
        help="Environment variable that contains the Postgres connection string for DB audit mode.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_default = "config/db_audit_checks.json" if args.mode == "db" else args.config
    config_path = Path(config_default).resolve()
    runner = AuditRunner(
        config_path=config_path,
        dry_run=args.dry_run,
        mode=args.mode or None,
        db_env_var=args.db_env_var,
    )

    try:
        result = runner.run()
    except Exception as exc:
        print(f"Audit failed: {exc}")
        return 1

    if args.mode == "db":
        print("Database audit complete")
        print(f"Clearance: {result.overall_clearance.value}")
        print("Reports: reports/db-audit-latest.md, reports/db-audit-latest.json")
        return 0

    print(f"Audit complete: {result.metadata.audit_name}")
    print(f"Mode: {result.metadata.mode}")
    print(f"Findings: {len(result.findings)}")
    print("Report: reports/latest-report.md")

    fail_on = {item.strip().lower() for item in args.fail_on.split(",") if item.strip()}
    return 1 if should_fail(result, fail_on) else 0


if __name__ == "__main__":
    raise SystemExit(main())
