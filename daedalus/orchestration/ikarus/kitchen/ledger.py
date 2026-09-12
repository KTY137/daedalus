"""Order ledger: what the kitchen accepted, what happened, what came out.

SQLite, append-only events, one row per order. A projection for the Waiter
and the cockpit -- the canonical evidence lives in each order's directory.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

_DDL = """
CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY, kind TEXT NOT NULL, project TEXT, text TEXT NOT NULL, status TEXT NOT NULL,
    created_at REAL NOT NULL, updated_at REAL NOT NULL, result TEXT);
CREATE TABLE IF NOT EXISTS events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT, order_id TEXT NOT NULL, at REAL NOT NULL, level TEXT NOT NULL, text TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS events_order ON events(order_id);
"""

STATUS_ACCEPTED = "accepted"
STATUS_COOKING = "cooking"
STATUS_NOMINATED = "nominated"
STATUS_FAILED = "failed"
STATUS_BLOCKED = "blocked"
STATUS_DONE = "done"
TERMINAL = frozenset({STATUS_NOMINATED, STATUS_FAILED, STATUS_BLOCKED, STATUS_DONE})


class OrderLedger:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.db = sqlite3.connect(str(self.path), timeout=30, check_same_thread=False)
        self.db.executescript(_DDL)

    def close(self) -> None:
        self.db.close()

    def open_order(self, order_id: str, kind: str, project: str | None, text: str) -> bool:
        with self._lock, self.db:
            existing = self.db.execute("SELECT status FROM orders WHERE order_id=?", (order_id,)).fetchone()
            if existing and existing[0] not in TERMINAL:
                return False
            now = time.time()
            self.db.execute("INSERT OR REPLACE INTO orders VALUES (?,?,?,?,?,?,?,NULL)",
                            (order_id, kind, project, text, STATUS_ACCEPTED, now, now))
            self.db.execute("INSERT INTO events (order_id, at, level, text) VALUES (?,?,?,?)",
                            (order_id, now, "info", "order accepted"))
        return True

    def event(self, order_id: str, text: str, level: str = "info") -> None:
        with self._lock, self.db:
            self.db.execute("INSERT INTO events (order_id, at, level, text) VALUES (?,?,?,?)",
                            (order_id, time.time(), level, text[:4000]))
            self.db.execute("UPDATE orders SET updated_at=? WHERE order_id=?", (time.time(), order_id))

    def set_status(self, order_id: str, status: str, result: dict[str, Any] | None = None) -> None:
        with self._lock, self.db:
            self.db.execute("UPDATE orders SET status=?, updated_at=?, result=COALESCE(?, result) WHERE order_id=?",
                            (status, time.time(), json.dumps(result, sort_keys=True) if result is not None else None, order_id))

    def order(self, order_id: str) -> dict[str, Any] | None:
        row = self.db.execute("SELECT order_id, kind, project, text, status, created_at, updated_at, result FROM orders WHERE order_id=?",
                              (order_id,)).fetchone()
        if not row:
            return None
        events = [{"at": at, "level": level, "text": text} for at, level, text in
                  self.db.execute("SELECT at, level, text FROM events WHERE order_id=? ORDER BY seq", (order_id,))]
        return {"order_id": row[0], "kind": row[1], "project": row[2], "text": row[3], "status": row[4],
                "created_at": row[5], "updated_at": row[6], "result": json.loads(row[7]) if row[7] else None,
                "events": events}

    def recent(self, limit: int = 12) -> list[dict[str, Any]]:
        rows = self.db.execute("SELECT order_id, kind, project, text, status, created_at, updated_at FROM orders "
                               "ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
        return [{"order_id": r[0], "kind": r[1], "project": r[2], "text": r[3][:160], "status": r[4],
                 "created_at": r[5], "updated_at": r[6]} for r in rows]


__all__ = ["OrderLedger", "STATUS_ACCEPTED", "STATUS_COOKING", "STATUS_NOMINATED", "STATUS_FAILED",
           "STATUS_BLOCKED", "STATUS_DONE", "TERMINAL"]
