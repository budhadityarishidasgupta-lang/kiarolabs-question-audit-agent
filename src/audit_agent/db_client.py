from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any


class DbAuditError(RuntimeError):
    """Raised when the DB audit client cannot operate safely."""


def _load_driver():
    try:
        import psycopg  # type: ignore

        return "psycopg", psycopg
    except ImportError:
        try:
            import psycopg2  # type: ignore

            return "psycopg2", psycopg2
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise DbAuditError(
                "No PostgreSQL driver available. Install psycopg or psycopg2 to use DB audit mode."
            ) from exc


def get_connection(db_env_var: str = "AUDIT_DB_URL"):
    db_url = os.getenv(db_env_var)
    if not db_url:
        raise DbAuditError(
            f"Missing required database connection string in environment variable: {db_env_var}"
        )

    driver_name, driver = _load_driver()

    if driver_name == "psycopg":
        connection = driver.connect(db_url)
        connection.autocommit = True
        try:
            connection.read_only = True
        except Exception:
            pass
        return connection

    connection = driver.connect(db_url)
    connection.set_session(readonly=True, autocommit=True)
    return connection


def get_db_connection(db_env_var: str = "AUDIT_DB_URL"):
    return get_connection(db_env_var=db_env_var)


@contextmanager
def _cursor(connection):
    cursor = connection.cursor()
    try:
        yield cursor
    finally:
        cursor.close()


def run_query(sql: str, params: tuple[Any, ...] | None = None, db_env_var: str = "AUDIT_DB_URL") -> list[dict]:
    connection = get_connection(db_env_var=db_env_var)
    try:
        with _cursor(connection) as cursor:
            cursor.execute(sql, params or ())
            rows = cursor.fetchall()
            columns = [column[0] for column in cursor.description or []]
            return [dict(zip(columns, row)) for row in rows]
    finally:
        connection.close()
