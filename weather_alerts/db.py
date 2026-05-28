from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS alert_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    county TEXT NOT NULL,
    event TEXT NOT NULL,
    description TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_alert_log_timestamp ON alert_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_alert_log_county ON alert_log(county);
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def insert_log(db_path: str | Path, entry: dict[str, Any]) -> None:
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO alert_log (timestamp, county, event, description) VALUES (?, ?, ?, ?)",
            (
                str(entry.get("timestamp") or datetime.now(timezone.utc).isoformat()),
                str(entry.get("county") or "UNKNOWN")[:80],
                str(entry.get("event") or "")[:200],
                str(entry.get("description") or "")[:10000],
            ),
        )


def list_logs(db_path: str | Path, *, hours: int = 24) -> list[dict[str, Any]]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, timestamp, county, event, description
            FROM alert_log
            WHERE timestamp >= ?
            ORDER BY timestamp DESC, id DESC
            """,
            (cutoff.isoformat(),),
        ).fetchall()
    return [dict(row) for row in rows]


def prune_logs(db_path: str | Path, *, days: int = 7) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    with connect(db_path) as conn:
        conn.execute("DELETE FROM alert_log WHERE timestamp < ?", (cutoff.isoformat(),))
