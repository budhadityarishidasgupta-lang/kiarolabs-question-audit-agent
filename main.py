from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from src.audit_agent.reporting import should_fail
from src.audit_agent.runner import AuditRunner


def parse_args() -> argparse.Namespace:
    if len(sys.argv) > 1 and sys.argv[1] == "parse-vr":
        parser = argparse.ArgumentParser(description="Parse one GL-style verbal reasoning PDF into draft CSV outputs.")
        parser.add_argument("command", choices=["parse-vr"])
        parser.add_argument("--pdf", required=True, help="Path to the input PDF file.")
        parser.add_argument("--paper-code", required=True, help="Paper code such as VR-P1.")
        parser.add_argument("--output-dir", default="exports", help="Directory to write draft CSV outputs.")
        return parser.parse_args()

    if len(sys.argv) > 1 and sys.argv[1] == "parse-vr-batch":
        parser = argparse.ArgumentParser(description="Parse all GL-style verbal reasoning PDFs in a directory.")
        parser.add_argument("command", choices=["parse-vr-batch"])
        parser.add_argument("--input-dir", required=True, help="Directory containing Verbal Reasoning_P*.pdf files.")
        parser.add_argument("--output-dir", default="exports", help="Directory to write draft CSV outputs.")
        return parser.parse_args()

    if len(sys.argv) > 1 and sys.argv[1] == "review-vr":
        parser = argparse.ArgumentParser(description="Review an existing VR draft CSV and regenerate summary reports.")
        parser.add_argument("command", choices=["review-vr"])
        parser.add_argument("--csv", required=True, help="Path to the draft CSV.")
        return parser.parse_args()

    if len(sys.argv) > 1 and sys.argv[1] == "extract-blocks":
        parser = argparse.ArgumentParser(description="Extract layout-aware blocks from a verbal reasoning PDF.")
        parser.add_argument("command", choices=["extract-blocks"])
        parser.add_argument("--pdf", required=True, help="Path to the input PDF file.")
        parser.add_argument("--output", default="blocks.json", help="Path to write blocks.json.")
        return parser.parse_args()

    if len(sys.argv) > 1 and sys.argv[1] == "parse-sections":
        parser = argparse.ArgumentParser(description="Parse section-specific draft rows from VR blocks.json.")
        parser.add_argument("command", choices=["parse-sections"])
        parser.add_argument("--blocks", required=True, help="Path to the input blocks.json file.")
        parser.add_argument("--output", default="draft.csv", help="Path to write the draft CSV.")
        return parser.parse_args()

    parser = argparse.ArgumentParser(description="Run the question accuracy audit agent.")
    parser.add_argument(
        "--mode",
        choices=["local", "github", "db", "db-migration-check", "db-math", "db-math-migration-check", "migrate", "vr-printable"],
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
    parser.add_argument(
        "--input-dir",
        default=".",
        help="Input directory for vr-printable mode.",
    )
    parser.add_argument(
        "--output-dir",
        default="reports/vr-printable",
        help="Output directory for vr-printable mode.",
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
    if getattr(args, "command", None) == "parse-vr":
        try:
            from src.audit_agent.vr_parser_v2 import run_parse_vr

            payload = run_parse_vr(
                pdf_path=Path(args.pdf).resolve(),
                paper_code=args.paper_code,
                output_dir=Path(args.output_dir).resolve(),
            )
            print(json.dumps(payload, indent=2))
            return 0
        except Exception as exc:
            print(f"Audit failed: {exc}")
            return 1

    if getattr(args, "command", None) == "parse-vr-batch":
        try:
            from src.audit_agent.vr_parser_v2 import run_parse_vr_batch

            payload = run_parse_vr_batch(
                input_dir=Path(args.input_dir).resolve(),
                output_dir=Path(args.output_dir).resolve(),
            )
            print(json.dumps(payload, indent=2))
            return 0
        except Exception as exc:
            print(f"Audit failed: {exc}")
            return 1

    if getattr(args, "command", None) == "review-vr":
        try:
            from src.audit_agent.vr_parser_v2 import run_review_vr

            payload = run_review_vr(csv_path=Path(args.csv).resolve())
            print(json.dumps(payload, indent=2))
            return 0
        except Exception as exc:
            print(f"Audit failed: {exc}")
            return 1

    if getattr(args, "command", None) == "extract-blocks":
        try:
            from src.audit_agent.vr_block_extractor import write_blocks_json

            payload = write_blocks_json(
                pdf_path=Path(args.pdf).resolve(),
                output_path=Path(args.output).resolve(),
            )
            print(json.dumps({"output": str(Path(args.output).resolve()), "blocks": len(payload["blocks"])}, indent=2))
            return 0
        except Exception as exc:
            print(f"Audit failed: {exc}")
            return 1

    if getattr(args, "command", None) == "parse-sections":
        try:
            from src.audit_agent.vr_section_parser import write_draft_csv

            payload = write_draft_csv(
                blocks_path=Path(args.blocks).resolve(),
                output_path=Path(args.output).resolve(),
            )
            print(json.dumps(payload, indent=2))
            return 0
        except Exception as exc:
            print(f"Audit failed: {exc}")
            return 1

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

    if args.mode == "vr-printable":
        try:
            from src.audit_agent.vr_printable_agent import write_vr_outputs

            manifest = write_vr_outputs(
                input_dir=Path(args.input_dir).resolve(),
                output_dir=Path(args.output_dir).resolve(),
            )
            print(json.dumps(manifest, indent=2))
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
