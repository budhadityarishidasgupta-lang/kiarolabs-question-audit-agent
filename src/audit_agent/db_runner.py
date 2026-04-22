import os
import psycopg2
from psycopg2.extras import RealDictCursor


class DBAuditRunner:
    MIGRATION_TARGETS = {
        "attempts": [
            "question_id",
            "session_id",
            "time_taken_ms",
            "contract_version",
        ],
        "spelling_attempts": [
            "lesson_id",
            "question_id",
            "session_id",
            "contract_version",
        ],
    }

    def __init__(self):
        self.db_url = os.getenv("AUDIT_DB_URL")
        if not self.db_url:
            raise ValueError("AUDIT_DB_URL is not set")

    def connect(self):
        return psycopg2.connect(self.db_url)

    def run_query(self, query):
        with self.connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query)
                try:
                    return cur.fetchall()
                except Exception:
                    return []

    def _get_columns(self, table_name):
        rows = self.run_query(f"""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = '{table_name}'
        """)
        return {row["column_name"] for row in rows}

    def _table_exists(self, table_name):
        rows = self.run_query(f"""
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name = '{table_name}'
            ) AS exists
        """)
        return bool(rows[0]["exists"]) if rows else False

    def check_columns(self, table_name, expected_columns):
        existing_columns = self._get_columns(table_name)
        return {
            column_name: "EXISTS" if column_name in existing_columns else "MISSING"
            for column_name in expected_columns
        }

    def run_audit(self):
        results = {}

        # 1. Table counts
        results["table_counts"] = {
            "attempts": self.run_query("SELECT COUNT(*) AS count FROM public.attempts;"),
            "words_attempts": self.run_query("SELECT COUNT(*) AS count FROM public.words_attempts;"),
            "spelling_attempts": self.run_query("SELECT COUNT(*) AS count FROM public.spelling_attempts;"),
        }

        # 2. Column existence checks
        results["attempts_columns"] = self.run_query("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'attempts'
        """)

        results["spelling_attempts_columns"] = self.run_query("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'spelling_attempts'
        """)

        # 3. Sample rows
        results["sample_attempts"] = self.run_query("""
            SELECT * FROM public.attempts LIMIT 5;
        """)

        results["sample_spelling_attempts"] = self.run_query("""
            SELECT * FROM public.spelling_attempts LIMIT 5;
        """)

        return results

    def run_migration_check(self):
        results = {}
        any_exists = False
        all_missing = True
        blocked = False

        for table_name, expected_columns in self.MIGRATION_TARGETS.items():
            if not self._table_exists(table_name):
                blocked = True
                results[table_name] = {
                    column_name: "MISSING"
                    for column_name in expected_columns
                }
                continue

            table_results = self.check_columns(table_name, expected_columns)
            results[table_name] = table_results

            if any(status == "EXISTS" for status in table_results.values()):
                any_exists = True
            if any(status != "MISSING" for status in table_results.values()):
                all_missing = False

        if blocked:
            results["decision"] = "BLOCK"
        elif all_missing:
            results["decision"] = "SAFE_TO_ADD"
        elif any_exists:
            results["decision"] = "PARTIAL"
        else:
            results["decision"] = "SAFE_TO_ADD"

        return results
