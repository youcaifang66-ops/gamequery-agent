import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

FINAL_STATUSES = {"completed", "failed", "cancelled"}
EVENT_TYPES = {"progress", "sql", "result", "error", "done", "clarification"}


class TraceStoreError(RuntimeError):
    """稳定、可安全暴露错误码的追踪存储异常。"""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class AsyncSQLiteTraceStore:
    """单进程异步审计存储；写事务由锁串行化，SQLite 使用 WAL。"""

    def __init__(
        self,
        database: str | Path = ":memory:",
        *,
        busy_timeout_ms: int = 5_000,
    ):
        if busy_timeout_ms < 1:
            raise ValueError("busy_timeout_ms must be positive")
        self.database = str(database)
        self.busy_timeout_ms = busy_timeout_ms
        self._connection: aiosqlite.Connection | None = None
        self._write_lock = asyncio.Lock()

    async def open(self) -> None:
        if self._connection is not None:
            return
        if self.database != ":memory:":
            Path(self.database).parent.mkdir(parents=True, exist_ok=True)
        connection = await aiosqlite.connect(self.database, isolation_level=None)
        connection.row_factory = aiosqlite.Row
        await connection.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
        await connection.execute("PRAGMA journal_mode=WAL")
        await connection.execute("PRAGMA foreign_keys=ON")
        await connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS query_trace(
              trace_id TEXT PRIMARY KEY,
              query_digest TEXT NOT NULL,
              status TEXT NOT NULL CHECK(status IN ('running','completed','failed','cancelled')),
              started_at TEXT NOT NULL,
              finished_at TEXT,
              error_code TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_query_trace_started_at
              ON query_trace(started_at);
            CREATE TABLE IF NOT EXISTS trace_event(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              trace_id TEXT NOT NULL REFERENCES query_trace(trace_id) ON DELETE CASCADE,
              sequence INTEGER NOT NULL CHECK(sequence >= 1),
              event_type TEXT NOT NULL,
              payload TEXT NOT NULL,
              created_at TEXT NOT NULL,
              UNIQUE(trace_id, sequence)
            );
            """
        )
        self._connection = connection

    async def close(self) -> None:
        connection = self._connection
        self._connection = None
        if connection is not None:
            await connection.close()

    def _require_connection(self) -> aiosqlite.Connection:
        if self._connection is None:
            raise TraceStoreError("TRACE_STORE_CLOSED")
        return self._connection

    async def _fetchone(
        self, sql: str, parameters: tuple[Any, ...] = ()
    ) -> aiosqlite.Row | None:
        connection = self._require_connection()
        async with connection.execute(sql, parameters) as cursor:
            return await cursor.fetchone()

    async def _pragma(self, name: str) -> Any:
        if name not in {"journal_mode", "busy_timeout"}:
            raise ValueError("unsupported pragma")
        row = await self._fetchone(f"PRAGMA {name}")
        return row[0] if row else None

    async def start(self, trace_id: str, query_digest: str) -> None:
        connection = self._require_connection()
        async with self._write_lock:
            existing = await self._fetchone(
                "SELECT query_digest FROM query_trace WHERE trace_id=?", (trace_id,)
            )
            if existing:
                if existing["query_digest"] != query_digest:
                    raise TraceStoreError("TRACE_ID_CONFLICT")
                return
            await connection.execute(
                "INSERT INTO query_trace(trace_id,query_digest,status,started_at) "
                "VALUES (?,?,?,?)",
                (
                    trace_id,
                    query_digest,
                    "running",
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    async def append(
        self, trace_id: str, event_type: str, payload: dict[str, Any]
    ) -> int:
        if event_type not in EVENT_TYPES:
            raise TraceStoreError("INVALID_EVENT_TYPE")
        if event_type == "result" and set(payload) != {"row_count"}:
            raise TraceStoreError("UNSAFE_TRACE_PAYLOAD")
        connection = self._require_connection()
        async with self._write_lock:
            try:
                await connection.execute("BEGIN IMMEDIATE")
                trace = await self._fetchone(
                    "SELECT status FROM query_trace WHERE trace_id=?", (trace_id,)
                )
                if trace is None:
                    raise TraceStoreError("TRACE_NOT_FOUND")
                if trace["status"] != "running":
                    raise TraceStoreError("TRACE_ALREADY_FINISHED")
                row = await self._fetchone(
                    "SELECT COALESCE(MAX(sequence),0)+1 AS next_sequence "
                    "FROM trace_event WHERE trace_id=?",
                    (trace_id,),
                )
                sequence = int(row["next_sequence"])
                await connection.execute(
                    "INSERT INTO trace_event"
                    "(trace_id,sequence,event_type,payload,created_at) "
                    "VALUES (?,?,?,?,?)",
                    (
                        trace_id,
                        sequence,
                        event_type,
                        json.dumps(payload, ensure_ascii=False),
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
                await connection.execute("COMMIT")
                return sequence
            except BaseException:
                await connection.execute("ROLLBACK")
                raise

    async def finish(
        self, trace_id: str, status: str, error_code: str | None = None
    ) -> None:
        if status not in FINAL_STATUSES:
            raise ValueError("invalid final status")
        connection = self._require_connection()
        async with self._write_lock:
            trace = await self._fetchone(
                "SELECT status,error_code FROM query_trace WHERE trace_id=?", (trace_id,)
            )
            if trace is None:
                raise TraceStoreError("TRACE_NOT_FOUND")
            if trace["status"] != "running":
                if trace["status"] == status and trace["error_code"] == error_code:
                    return
                raise TraceStoreError("TRACE_ALREADY_FINISHED")
            await connection.execute(
                "UPDATE query_trace SET status=?,finished_at=?,error_code=? "
                "WHERE trace_id=?",
                (
                    status,
                    datetime.now(timezone.utc).isoformat(),
                    error_code,
                    trace_id,
                ),
            )

    async def replay(self, trace_id: str) -> dict[str, Any] | None:
        trace = await self._fetchone(
            "SELECT * FROM query_trace WHERE trace_id=?", (trace_id,)
        )
        if trace is None:
            return None
        connection = self._require_connection()
        async with connection.execute(
            "SELECT sequence,event_type,payload,created_at FROM trace_event "
            "WHERE trace_id=? ORDER BY sequence",
            (trace_id,),
        ) as cursor:
            events = await cursor.fetchall()
        return {
            **dict(trace),
            "events": [
                {**dict(event), "payload": json.loads(event["payload"])}
                for event in events
            ],
        }

    async def __aenter__(self):
        await self.open()
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        await self.close()


SQLiteTraceStore = AsyncSQLiteTraceStore
