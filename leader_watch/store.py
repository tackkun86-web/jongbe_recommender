"""SQLite-backed alert history and candidate-state persistence."""
from __future__ import annotations

import datetime
import os
import sqlite3


_SCHEMA = """
CREATE TABLE IF NOT EXISTS candidates (
    code TEXT NOT NULL,
    date TEXT NOT NULL,
    name TEXT,
    phase TEXT,
    status TEXT,
    score REAL,
    updated_at TEXT,
    PRIMARY KEY (code, date)
);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    date TEXT NOT NULL,
    alert_type TEXT NOT NULL,
    score REAL,
    sent_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_alerts_dedup ON alerts(code, alert_type, date);
"""


class AlertStore:
    def __init__(self, db_path: str) -> None:
        directory = os.path.dirname(db_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def record_alert(self, code: str, date: str, alert_type: str, score: float, sent_at: datetime.datetime) -> None:
        self._conn.execute(
            "INSERT INTO alerts (code, date, alert_type, score, sent_at) VALUES (?, ?, ?, ?, ?)",
            (code, date, alert_type, score, sent_at.isoformat()),
        )
        self._conn.commit()

    def last_alert(self, code: str, date: str, alert_type: str) -> tuple[datetime.datetime, float] | None:
        row = self._conn.execute(
            "SELECT sent_at, score FROM alerts WHERE code=? AND date=? AND alert_type=? ORDER BY id DESC LIMIT 1",
            (code, date, alert_type),
        ).fetchone()
        if row is None:
            return None
        return datetime.datetime.fromisoformat(row[0]), row[1]

    def upsert_candidate(
        self, code: str, date: str, name: str, phase: str, status: str, score: float, updated_at: datetime.datetime
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO candidates (code, date, name, phase, status, score, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(code, date) DO UPDATE SET
                name=excluded.name, phase=excluded.phase, status=excluded.status,
                score=excluded.score, updated_at=excluded.updated_at
            """,
            (code, date, name, phase, status, score, updated_at.isoformat()),
        )
        self._conn.commit()

    def load_today_candidates(self, date: str) -> dict[str, dict]:
        rows = self._conn.execute(
            "SELECT code, name, phase, status, score, updated_at FROM candidates WHERE date=?",
            (date,),
        ).fetchall()
        return {
            row[0]: {
                "name": row[1],
                "phase": row[2],
                "status": row[3],
                "score": row[4],
                "updated_at": row[5],
            }
            for row in rows
        }

    def close(self) -> None:
        self._conn.close()
