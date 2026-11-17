"""Store synthetic call reports in local SQLite or an explicit PostgreSQL DSN."""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from time import time
import sqlite3

from .engine import CLAIM_ID

_SCHEMA = """
CREATE TABLE IF NOT EXISTS claimvoice_phone_runs (
    id TEXT PRIMARY KEY,
    provider_status TEXT,
    provider_seconds INTEGER,
    relay_started INTEGER NOT NULL DEFAULT 0,
    report TEXT
)
"""

_DIAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS claimvoice_dials (
    id TEXT PRIMARY KEY REFERENCES claimvoice_phone_runs(id),
    request_id TEXT UNIQUE NOT NULL,
    utc_day TEXT NOT NULL,
    lease_until BIGINT NOT NULL,
    reserved_micros BIGINT NOT NULL,
    provider_sid TEXT UNIQUE
)
"""
_AI_REVIEW_SCHEMA = """
CREATE TABLE IF NOT EXISTS claimvoice_ai_reviews (
    id TEXT PRIMARY KEY REFERENCES claimvoice_phone_runs(id),
    findings TEXT
)
"""
_LOCK_SCHEMA = """
CREATE TABLE IF NOT EXISTS claimvoice_dial_lock (
    id INTEGER PRIMARY KEY CHECK (id = 1)
)
"""


class DialBlocked(RuntimeError):
    """A local call limit was reached before contacting the provider."""


class Store:
    def __init__(self, target):
        self.target = target
        self.postgres = target.startswith(("postgresql://", "postgres://"))
        self.initialize()

    @contextmanager
    def connect(self):
        if self.postgres:
            import psycopg

            db = psycopg.connect(self.target, connect_timeout=5)
        else:
            db = sqlite3.connect(self.target, timeout=5)
        try:
            with db:
                yield db
        finally:
            db.close()

    def query(self, db, sql, params=()):
        return db.execute(sql.replace("?", "%s") if self.postgres else sql, params)

    def initialize(self):
        with self.connect() as db:
            if self.postgres:
                db.execute("SELECT pg_advisory_xact_lock(672881904)")
            db.execute(_SCHEMA)
            db.execute(_DIAL_SCHEMA)
            db.execute(_LOCK_SCHEMA)
            db.execute(_AI_REVIEW_SCHEMA)
            db.execute("INSERT INTO claimvoice_dial_lock (id) VALUES (1) ON CONFLICT DO NOTHING")
            db.execute("CREATE INDEX IF NOT EXISTS claimvoice_dials_day_idx ON claimvoice_dials (utc_day)")

    def ready(self):
        return self.execute("SELECT id FROM claimvoice_dial_lock WHERE id = 1", fetch=True) == [(1,)]

    def execute(self, sql, params=(), fetch=False):
        with self.connect() as db:
            cursor = self.query(db, sql, params)
            return cursor.fetchall() if fetch else cursor.rowcount

    def reserve_dial(self, call_id, request_id, active_seconds, reserved_micros, budget_micros):
        with self.connect() as db:
            # Serialize reservations across processes. Query after locking so the clock
            # and budget window are current even when another process held the lock.
            self.query(db, "UPDATE claimvoice_dial_lock SET id = 1 WHERE id = 1")
            existing = self.query(db, "SELECT id FROM claimvoice_dials WHERE request_id = ?", (request_id,)).fetchone()
            if existing:
                return existing[0], False
            now = int(time())
            utc_day = datetime.fromtimestamp(now, timezone.utc).date().isoformat()
            active = self.query(db, """
                SELECT 1 FROM claimvoice_dials d JOIN claimvoice_phone_runs r ON d.id = r.id
                WHERE d.lease_until > ? AND (r.provider_status IS NULL OR r.provider_status = 'dial_unconfirmed')
                LIMIT 1
            """, (now,)).fetchone()
            if active:
                raise DialBlocked("Another test call is active or awaiting provider confirmation.")
            reserved, = self.query(db,
                "SELECT COALESCE(SUM(reserved_micros), 0) FROM claimvoice_dials WHERE utc_day = ?",
                (utc_day,),
            ).fetchone()
            if reserved + reserved_micros > budget_micros:
                raise DialBlocked("The daily estimated voice budget has been reached.")
            self.query(db, "INSERT INTO claimvoice_phone_runs (id) VALUES (?)", (call_id,))
            self.query(db, """
                INSERT INTO claimvoice_dials (id, request_id, utc_day, lease_until, reserved_micros)
                VALUES (?, ?, ?, ?, ?)
            """, (call_id, request_id, utc_day, now + active_seconds, reserved_micros))
        return call_id, True

    def bind_provider(self, call_id, sid):
        return self.execute("""
            UPDATE claimvoice_dials SET provider_sid = ?
            WHERE id = ? AND (provider_sid IS NULL OR provider_sid = ?)
              AND NOT EXISTS (SELECT 1 FROM claimvoice_dials WHERE provider_sid = ? AND id <> ?)
        """, (sid, call_id, sid, sid, call_id)) == 1

    def claim_relay(self, call_id, sid):
        return self.execute("""
            UPDATE claimvoice_phone_runs SET relay_started = 1
            WHERE id = ? AND relay_started = 0 AND (provider_status IS NULL OR provider_status = 'dial_unconfirmed')
              AND EXISTS (SELECT 1 FROM claimvoice_dials WHERE id = ? AND provider_sid = ? AND lease_until > ?)
        """, (call_id, call_id, sid, int(time()))) == 1

    def update_provider(self, call_id, sid, status, duration=None):
        if not self.bind_provider(call_id, sid):
            return False
        self.execute("""
            UPDATE claimvoice_phone_runs SET provider_status = ?, provider_seconds = ?
            WHERE id = ? AND (provider_status IS NULL OR provider_status = 'dial_unconfirmed'
                  OR (provider_status = ? AND provider_seconds IS NULL))
        """, (status, duration, call_id, status))
        return True

    def note_unconfirmed_dial(self, call_id):
        self.execute(
            "UPDATE claimvoice_phone_runs SET provider_status = ? WHERE id = ? AND provider_status IS NULL",
            ("dial_unconfirmed", call_id),
        )

    def finish(self, call_id, report):
        self.execute("UPDATE claimvoice_phone_runs SET report = ? WHERE id = ? AND report IS NULL",
                     (json.dumps(report), call_id))

    def begin_ai_review(self, call_id):
        return self.execute(
            "INSERT INTO claimvoice_ai_reviews (id) VALUES (?) ON CONFLICT DO NOTHING", (call_id,),
        ) == 1

    def finish_ai_review(self, call_id, findings):
        self.execute("UPDATE claimvoice_ai_reviews SET findings = ? WHERE id = ? AND findings IS NULL",
                     (json.dumps(findings), call_id))

    def reports(self, estimated_cost, *, limit=100, call_id=None):
        sql = """
            SELECT r.id, r.provider_status, r.provider_seconds, r.report, d.provider_sid, a.id, a.findings
            FROM claimvoice_phone_runs r LEFT JOIN claimvoice_dials d ON d.id = r.id
            LEFT JOIN claimvoice_ai_reviews a ON a.id = r.id
        """
        if call_id is not None:
            sql += "WHERE r.id = ? "
        sql += "ORDER BY d.lease_until DESC NULLS LAST, r.id DESC LIMIT ?"
        rows = self.execute(sql, (limit,) if call_id is None else (call_id, limit), fetch=True)
        found = []
        for call_id, status, seconds, payload, sid, ai_review_id, findings in rows:
            report = json.loads(payload) if payload else {
                "call_id": call_id, "claim_id": CLAIM_ID, "transport": "twilio",
                "outcome": status or "awaiting_provider", "ivr_passed": False, "fields": {},
                "evidence": {}, "transcript": [], "checks": [status or "awaiting_provider"],
                "review_status": "needs_review", "app_latency_ms": [],
            }
            report["ai_review_status"] = "not_run"
            report["ai_checks"] = []
            if ai_review_id is not None:
                report["ai_review_status"] = "finished" if findings is not None else "unconfirmed"
                report["ai_checks"] = json.loads(findings) if findings is not None else ["ai_checker_unconfirmed"]
                if report["ai_checks"]:
                    report["checks"] += report["ai_checks"]
                    report["review_status"] = "needs_review"
            report["provider_call_sid"] = sid
            report["provider_status"] = status
            report["provider_seconds"] = seconds
            report["estimated_cost_usd"] = estimated_cost(seconds) if seconds is not None else None
            found.append(report)
        return found
