from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .db_client import run_query
from .models import ClearanceLevel, DbAuditSummary, DbCheckResult


ROOT_DIR = Path(__file__).resolve().parents[2]
DB_CHECKS_PATH = ROOT_DIR / "config" / "db_audit_checks.json"


def _load_db_checks_config() -> dict[str, Any]:
    return json.loads(DB_CHECKS_PATH.read_text(encoding="utf-8"))


def check_table_exists(schema: str, table: str, db_env_var: str = "AUDIT_DB_URL") -> bool:
    rows = run_query(
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = %s
              AND table_name = %s
              AND table_type = 'BASE TABLE'
        ) AS exists
        """,
        (schema, table),
        db_env_var=db_env_var,
    )
    return bool(rows[0]["exists"]) if rows else False


def check_view_exists(schema: str, view: str, db_env_var: str = "AUDIT_DB_URL") -> bool:
    rows = run_query(
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.views
            WHERE table_schema = %s
              AND table_name = %s
        ) AS exists
        """,
        (schema, view),
        db_env_var=db_env_var,
    )
    return bool(rows[0]["exists"]) if rows else False


def get_columns(schema: str, table: str, db_env_var: str = "AUDIT_DB_URL") -> list[str]:
    rows = run_query(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = %s
          AND table_name = %s
        ORDER BY ordinal_position
        """,
        (schema, table),
        db_env_var=db_env_var,
    )
    return [str(row["column_name"]) for row in rows]


def get_row_count(schema: str, table: str, db_env_var: str = "AUDIT_DB_URL") -> int:
    rows = run_query(
        f'SELECT COUNT(*) AS row_count FROM "{schema}"."{table}"',
        db_env_var=db_env_var,
    )
    return int(rows[0]["row_count"]) if rows else 0


def get_sample_rows(schema: str, table: str, limit: int = 5, db_env_var: str = "AUDIT_DB_URL") -> list[dict]:
    safe_limit = max(1, min(limit, 20))
    return run_query(
        f'SELECT * FROM "{schema}"."{table}" LIMIT {safe_limit}',
        db_env_var=db_env_var,
    )


def run_db_audit_checks(db_env_var: str = "AUDIT_DB_URL") -> dict[str, Any]:
    config = _load_db_checks_config()
    warnings: list[str] = []
    table_status: dict[str, bool] = {}

    required_tables = [
        ("public", "attempts"),
        ("public", "words_attempts"),
        ("public", "spelling_attempts"),
        ("public", "spelling_words"),
        ("public", "spelling_lessons"),
    ]
    missing_required_tables: list[str] = []

    for schema, table in required_tables:
        exists = check_table_exists(schema, table, db_env_var=db_env_var)
        table_key = f"{schema}.{table}"
        table_status[table_key] = exists
        if not exists:
            missing_required_tables.append(table_key)

    attempts_columns = get_columns("public", "attempts", db_env_var=db_env_var) if table_status["public.attempts"] else []
    spelling_attempts_columns = (
        get_columns("public", "spelling_attempts", db_env_var=db_env_var)
        if table_status["public.spelling_attempts"]
        else []
    )

    expected_attempts_columns = config["checks"]["attempts_columns"]
    expected_spelling_attempts_columns = config["checks"]["spelling_attempts_columns"]

    missing_attempt_columns = [column for column in expected_attempts_columns if column not in attempts_columns]
    missing_spelling_attempt_columns = [
        column for column in expected_spelling_attempts_columns if column not in spelling_attempts_columns
    ]

    view_exists = check_view_exists("public", "spelling_words_contract", db_env_var=db_env_var)

    row_counts: dict[str, int] = {}
    for schema, table in config["checks"]["row_count_tables"]:
        table_key = f"{schema}.{table}"
        if table_status.get(table_key) is True:
            row_counts[f"{schema}.{table}"] = get_row_count(schema, table, db_env_var=db_env_var)
        else:
            row_counts[f"{schema}.{table}"] = 0

    spelling_words_exists = table_status["public.spelling_words"]
    spelling_lessons_exists = table_status["public.spelling_lessons"]

    if row_counts.get("public.words_attempts", 0) > 0:
        warnings.append("words_attempts has rows")

    spelling_words_columns = get_columns("public", "spelling_words", db_env_var=db_env_var) if spelling_words_exists else []
    spelling_lessons_columns = get_columns("public", "spelling_lessons", db_env_var=db_env_var) if spelling_lessons_exists else []
    expected_spelling_words = set(config["checks"]["expected_spelling_words_columns"])
    expected_spelling_lessons = set(config["checks"]["expected_spelling_lessons_columns"])
    if spelling_words_exists and not expected_spelling_words.issubset(set(spelling_words_columns)):
        warnings.append("spelling schema mismatch")
    if spelling_lessons_exists and not expected_spelling_lessons.issubset(set(spelling_lessons_columns)):
        warnings.append("spelling schema mismatch")

    if missing_attempt_columns or missing_spelling_attempt_columns:
        warnings.append("question/session metadata currently absent")

    if missing_required_tables:
        safety_decision = ClearanceLevel.RED.value
    elif warnings:
        safety_decision = ClearanceLevel.AMBER.value
    else:
        safety_decision = ClearanceLevel.GREEN.value

    return {
        "tables": table_status,
        "columns": {
            "public.attempts": {
                "present": attempts_columns,
                "missing": missing_attempt_columns,
            },
            "public.spelling_attempts": {
                "present": spelling_attempts_columns,
                "missing": missing_spelling_attempt_columns,
            },
        },
        "row_counts": row_counts,
        "view_exists": view_exists,
        "sample_rows": {
            "public.spelling_words": get_sample_rows("public", "spelling_words", limit=5, db_env_var=db_env_var)
            if spelling_words_exists
            else [],
            "public.spelling_lessons": get_sample_rows("public", "spelling_lessons", limit=5, db_env_var=db_env_var)
            if spelling_lessons_exists
            else [],
        },
        "warnings": warnings,
        "safety_decision": safety_decision,
    }


def run_membership_service_migration_readiness_checks(
    db_env_var: str = "AUDIT_DB_URL",
) -> DbAuditSummary:
    audit_result = run_db_audit_checks(db_env_var=db_env_var)
    check_results = [
        DbCheckResult(
            name=table_name,
            status="pass" if exists else "fail",
            detail=f"Table {'found' if exists else 'missing'}: {table_name}",
            evidence={"exists": exists},
        )
        for table_name, exists in audit_result["tables"].items()
    ]
    check_results.append(
        DbCheckResult(
            name="public.spelling_words_contract view",
            status="pass" if audit_result["view_exists"] else "pass",
            detail="Compatibility view may be created safely if missing.",
            evidence={"exists": audit_result["view_exists"]},
        )
    )
    check_results.append(
        DbCheckResult(
            name="public.attempts columns",
            status="pass",
            detail="Additive columns missing or present are both acceptable.",
            evidence=audit_result["columns"]["public.attempts"],
        )
    )
    check_results.append(
        DbCheckResult(
            name="public.spelling_attempts columns",
            status="pass",
            detail="Additive columns missing or present are both acceptable.",
            evidence=audit_result["columns"]["public.spelling_attempts"],
        )
    )

    clearance = ClearanceLevel(audit_result["safety_decision"])
    recommended_next_step = {
        ClearanceLevel.GREEN: "Additive migration prep looks safe to review and apply separately.",
        ClearanceLevel.AMBER: "Proceed carefully with additive-only prep and rerun the audit after changes.",
        ClearanceLevel.RED: "Stop and validate DB connectivity or missing base tables before planning migrations.",
    }[clearance]

    return DbAuditSummary(
        overall_clearance=clearance,
        connection_status="connected",
        safe_actions=[
            "Add nullable columns to public.attempts",
            "Add nullable columns to public.spelling_attempts",
            "Create public.spelling_words_contract view",
        ],
        blocked_actions=[
            "Archive public.words_attempts",
            "Rename live shared tables",
            "Drop or destructively clean existing tables",
        ],
        warnings=audit_result["warnings"],
        evidence={
            "attempts_columns": audit_result["columns"]["public.attempts"]["present"],
            "spelling_attempts_columns": audit_result["columns"]["public.spelling_attempts"]["present"],
            "row_counts": audit_result["row_counts"],
            "view_exists": audit_result["view_exists"],
            "sample_rows": audit_result["sample_rows"],
            "tables": audit_result["tables"],
        },
        check_results=check_results,
        recommended_next_step=recommended_next_step,
    )
