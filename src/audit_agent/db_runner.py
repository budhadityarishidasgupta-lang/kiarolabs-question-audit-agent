import os
import psycopg2
from psycopg2.extras import RealDictCursor


class DBAuditRunner:
    MIGRATION_TARGETS = {
        "attempts": {
            "question_id": "uuid",
            "session_id": "uuid",
            "time_taken_ms": "integer",
            "contract_version": "character varying",
        },
        "spelling_attempts": {
            "lesson_id": "integer",
            "question_id": "uuid",
            "session_id": "uuid",
            "contract_version": "character varying",
        },
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

    def _get_columns_with_types(self, table_name):
        rows = self.run_query(f"""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = '{table_name}'
        """)
        return {
            row["column_name"]: row["data_type"]
            for row in rows
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
        has_missing = False
        has_conflict = False
        all_skip = True

        for table_name, expected_columns in self.MIGRATION_TARGETS.items():
            existing_columns = self._get_columns_with_types(table_name)
            table_results = {}

            for column_name, expected_type in expected_columns.items():
                if column_name not in existing_columns:
                    table_results[column_name] = "MISSING"
                    has_missing = True
                    all_skip = False
                    continue

                actual_type = str(existing_columns[column_name]).lower()
                if actual_type == expected_type:
                    table_results[column_name] = "SKIP"
                else:
                    table_results[column_name] = "CONFLICT"
                    has_conflict = True
                    all_skip = False

            results[table_name] = table_results

        if has_conflict:
            results["decision"] = "CONFLICT"
        elif all_skip:
            results["decision"] = "SKIP"
        elif has_missing:
            results["decision"] = "SAFE_TO_ADD"
        else:
            results["decision"] = "SAFE_TO_ADD"

        return results
