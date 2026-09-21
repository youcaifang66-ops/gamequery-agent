import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class SQLiteTraceStore:
    def __init__(self, database: str | Path = ":memory:"):
        self.connection = sqlite3.connect(str(database), check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS query_trace(
              trace_id TEXT PRIMARY KEY, query TEXT NOT NULL, status TEXT NOT NULL,
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS trace_event(
              id INTEGER PRIMARY KEY AUTOINCREMENT, trace_id TEXT NOT NULL,
              sequence INTEGER NOT NULL, event_type TEXT NOT NULL, payload TEXT NOT NULL,
              created_at TEXT NOT NULL, UNIQUE(trace_id, sequence));
            """
        )

    def start(self, trace_id: str, query: str):
        now = datetime.now(timezone.utc).isoformat()
        self.connection.execute(
            "INSERT INTO query_trace VALUES (?,?,?,?,?)",
            (trace_id, query, "running", now, now),
        )
        self.connection.commit()

    def append(self, trace_id: str, event_type: str, payload: dict):
        sequence = self.connection.execute(
            "SELECT COALESCE(MAX(sequence),0)+1 FROM trace_event WHERE trace_id=?", (trace_id,)
        ).fetchone()[0]
        now = datetime.now(timezone.utc).isoformat()
        self.connection.execute(
            "INSERT INTO trace_event(trace_id,sequence,event_type,payload,created_at) VALUES (?,?,?,?,?)",
            (trace_id, sequence, event_type, json.dumps(payload, ensure_ascii=False), now),
        )
        self.connection.execute(
            "UPDATE query_trace SET updated_at=? WHERE trace_id=?", (now, trace_id)
        )
        self.connection.commit()

    def finish(self, trace_id: str, status: str):
        if status not in {"completed", "failed", "cancelled"}:
            raise ValueError("invalid final status")
        self.connection.execute(
            "UPDATE query_trace SET status=?,updated_at=? WHERE trace_id=?",
            (status, datetime.now(timezone.utc).isoformat(), trace_id),
        )
        self.connection.commit()

    def replay(self, trace_id: str) -> dict | None:
        trace = self.connection.execute(
            "SELECT * FROM query_trace WHERE trace_id=?", (trace_id,)
        ).fetchone()
        if not trace:
            return None
        events = self.connection.execute(
            "SELECT sequence,event_type,payload,created_at FROM trace_event WHERE trace_id=? ORDER BY sequence",
            (trace_id,),
        ).fetchall()
        return {
            **dict(trace),
            "events": [
                {**dict(event), "payload": json.loads(event["payload"])} for event in events
            ],
        }
