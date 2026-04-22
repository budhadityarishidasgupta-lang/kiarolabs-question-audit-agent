import os
import psycopg2
from psycopg2.extras import RealDictCursor


class DBAuditRunner:
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
