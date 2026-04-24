from __future__ import annotations

import argparse
import os
from pathlib import Path

from src.audit_agent.reporting import should_fail
from src.audit_agent.runner import AuditRunner


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the question accuracy audit agent.")
    parser.add_argument(
        "--mode",
        choices=["local", "github", "db", "db-migration-check", "db-math", "db-math-migration-check", "migrate"],
        required=True,
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


def run_safe_migration(cursor):
    queries = [
        """
        ALTER TABLE public.attempts
        ADD COLUMN IF NOT EXISTS question_id UUID,
        ADD COLUMN IF NOT EXISTS session_id UUID,
        ADD COLUMN IF NOT EXISTS time_taken_ms INTEGER,
        ADD COLUMN IF NOT EXISTS submitted_at TIMESTAMPTZ DEFAULT NOW(),
        ADD COLUMN IF NOT EXISTS contract_version VARCHAR(10);
        """,
        """
        ALTER TABLE public.spelling_attempts
        ADD COLUMN IF NOT EXISTS lesson_id INTEGER,
        ADD COLUMN IF NOT EXISTS question_id UUID,
        ADD COLUMN IF NOT EXISTS session_id UUID,
        ADD COLUMN IF NOT EXISTS submitted_at TIMESTAMPTZ DEFAULT NOW(),
        ADD COLUMN IF NOT EXISTS contract_version VARCHAR(10);
        """,
        """
        CREATE OR REPLACE VIEW public.spelling_words_contract AS
        SELECT
            sw.word_id AS id,
            sw.word,
            sw.level AS difficulty,
            sw.hint AS pattern_hint,
            sw.pattern,
            sw.example_sentence AS sample_sentence,
            sw.course_id,
            sw.lesson_name,
            NULL::TEXT AS missing_letter_mask
        FROM public.spelling_words sw;
        """
    ]

    results = []

    for query in queries:
        try:
            cursor.execute(query)
            results.append("SUCCESS")
        except Exception as exc:
            results.append(str(exc))

    return results


def main() -> int:
    args = parse_args()
    if args.mode == "migrate":
        try:
            import psycopg2

            db_url = os.getenv("AUDIT_DB_URL") or os.getenv("DATABASE_URL")
            if not db_url:
                raise ValueError("AUDIT_DB_URL is not set")

            conn = psycopg2.connect(db_url)
            try:
                with conn.cursor() as cursor:
                    migration_result = run_safe_migration(cursor)
                conn.commit()
            finally:
                conn.close()

            print({"migration_result": migration_result})
            return 0
        except Exception as exc:
            print(f"Audit failed: {exc}")
            return 1

    if args.mode in {"db", "db-migration-check", "db-math", "db-math-migration-check"}:
        try:
            from src.audit_agent.db_runner import DBAuditRunner

            runner = DBAuditRunner()
            if args.mode == "db":
                results = runner.run_audit()
            elif args.mode == "db-migration-check":
                results = runner.run_migration_check()
            elif args.mode == "db-math":
                results = runner.run_math_audit()
            else:
                results = runner.run_math_migration_check()
            print(results)
            return 0
        except Exception as exc:
            print(f"Audit failed: {exc}")
            return 1

    config_default = "config/db_audit_checks.json" if args.mode == "db" else args.config
    config_path = Path(config_default).resolve()
    runner = AuditRunner(
        config_path=config_path,
        dry_run=args.dry_run,
        mode=args.mode,
        db_env_var=args.db_env_var,
    )

    try:
        result = runner.run()
    except Exception as exc:
        print(f"Audit failed: {exc}")
        return 1

    print(f"Audit complete: {result.metadata.audit_name}")
    print(f"Mode: {result.metadata.mode}")
    print(f"Findings: {len(result.findings)}")
    print("Report: reports/latest-report.md")

    fail_on = {item.strip().lower() for item in args.fail_on.split(",") if item.strip()}
    return 1 if should_fail(result, fail_on) else 0


if __name__ == "__main__":
    raise SystemExit(main())
