"""SQLite-backed event store for detection audit trail.

Each detection event is logged with camera_id, person count, and timestamp.
The store is designed for append-heavy workloads with time-range queries.
"""

import logging
import os
import sqlite3
import threading
import time

logger = logging.getLogger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    camera_id   TEXT    NOT NULL,
    is_detected INTEGER NOT NULL DEFAULT 0,
    obj_count   INTEGER NOT NULL DEFAULT 0,
    timestamp   REAL    NOT NULL
);
"""
_CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_events_camera_ts
    ON events (camera_id, timestamp);
"""


class EventStore:
    """Thread-safe SQLite event logger."""

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self._init_db()

    def _init_db(self) -> None:
        os.makedirs(os.path.dirname(self._db_path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._conn.execute(_CREATE_TABLE)
        self._conn.execute(_CREATE_INDEX)
        self._conn.commit()
        logger.info("Event store ready: %s", self._db_path)

    def log(self, camera_id: str, is_detected: bool, obj_count: int,
            timestamp: float | None = None) -> None:
        ts = timestamp or time.time()
        with self._lock:
            # Try to insert into new schema, fallback if table exists with old schema
            try:
                self._conn.execute(
                    "INSERT INTO events (camera_id, is_detected, obj_count, timestamp) "
                    "VALUES (?, ?, ?, ?)",
                    (camera_id, int(is_detected), obj_count, ts),
                )
            except sqlite3.OperationalError:
                # Handle legacy schema
                self._conn.execute(
                    "INSERT INTO events (camera_id, person_detected, person_count, timestamp) "
                    "VALUES (?, ?, ?, ?)",
                    (camera_id, int(is_detected), obj_count, ts),
                )
            self._conn.commit()

    def query(
        self,
        camera_id: str | None = None,
        from_ts: float | None = None,
        to_ts: float | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        clauses: list[str] = []
        params: list = []

        if camera_id:
            clauses.append("camera_id = ?")
            params.append(camera_id)
        if from_ts is not None:
            clauses.append("timestamp >= ?")
            params.append(from_ts)
        if to_ts is not None:
            clauses.append("timestamp <= ?")
            params.append(to_ts)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        
        # Try new schema first
        try:
            sql = (
                f"SELECT id, camera_id, is_detected, obj_count, timestamp "
                f"FROM events {where} ORDER BY timestamp DESC LIMIT ? OFFSET ?"
            )
            with self._lock:
                cursor = self._conn.execute(sql, params + [limit, offset])
                rows = cursor.fetchall()
        except sqlite3.OperationalError:
            # Fallback for legacy schema
            sql = (
                f"SELECT id, camera_id, person_detected, person_count, timestamp "
                f"FROM events {where} ORDER BY timestamp DESC LIMIT ? OFFSET ?"
            )
            with self._lock:
                cursor = self._conn.execute(sql, params + [limit, offset])
                rows = cursor.fetchall()

        return [
            {
                "id": r[0],
                "camera_id": r[1],
                "is_detected": bool(r[2]),
                "obj_count": r[3],
                "timestamp": r[4],
            }
            for r in rows
        ]

    def count(
        self,
        camera_id: str | None = None,
        from_ts: float | None = None,
        to_ts: float | None = None,
    ) -> int:
        clauses: list[str] = []
        params: list = []

        if camera_id:
            clauses.append("camera_id = ?")
            params.append(camera_id)
        if from_ts is not None:
            clauses.append("timestamp >= ?")
            params.append(from_ts)
        if to_ts is not None:
            clauses.append("timestamp <= ?")
            params.append(to_ts)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT COUNT(*) FROM events {where}"

        with self._lock:
            cursor = self._conn.execute(sql, params)
            return cursor.fetchone()[0]

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
