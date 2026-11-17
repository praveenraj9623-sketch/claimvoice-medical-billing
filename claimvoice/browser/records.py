"""Persist browser voice reports through the repository's existing database adapter."""

import json

from claimvoice.phone.storage import Store


class BrowserRecords(Store):
    def initialize(self):
        with self.connect() as db:
            if self.postgres:
                db.execute("SELECT pg_advisory_xact_lock(672881905)")
            db.execute("""
                CREATE TABLE IF NOT EXISTS claimvoice_browser_runs (
                    id TEXT PRIMARY KEY,
                    report TEXT NOT NULL
                )
            """)

    def ready(self):
        self.execute("SELECT id FROM claimvoice_browser_runs LIMIT 1", fetch=True)
        return True

    def save(self, report):
        self.execute("""
            INSERT INTO claimvoice_browser_runs (id, report) VALUES (?, ?)
            ON CONFLICT (id) DO NOTHING
        """, (report["call_id"], json.dumps(report)))
