import asyncio
from pathlib import Path
from unittest.mock import MagicMock

from app.api.dependencies import get_sql_guard
from app.conf.app_config import app_config
from app.observability.trace_store import AsyncSQLiteTraceStore
from app.security.sql_guard import SQLGuard
from app.services import query_service as query_service_module
from app.services.query_service import QueryService


def test_sql_guard_dependency_uses_project_schema_and_runtime_policy():
    guard = get_sql_guard()

    assert isinstance(guard, SQLGuard)
    assert "fact_payment" in guard.schema
    assert guard.max_rows == app_config.sql_policy.max_rows
    assert guard.statement_timeout_ms == app_config.sql_policy.statement_timeout_ms
    assert get_sql_guard() is guard


def test_query_service_injects_guard_into_graph_context(monkeypatch, tmp_path):
    captured = {}

    class FakeGraph:
        async def astream(self, *, input, context, stream_mode):
            captured.update(input=input, context=context, stream_mode=stream_mode)
            yield {"type": "progress", "message": "ok"}

    monkeypatch.setattr(query_service_module, "graph", FakeGraph())
    guard = SQLGuard({"fact_payment": ["amount"]})
    store = AsyncSQLiteTraceStore(tmp_path / "wiring.sqlite3")
    dependencies = {
        "meta_mysql_repository": MagicMock(),
        "embedding_client": MagicMock(),
        "dw_mysql_repository": MagicMock(),
        "column_qdrant_repository": MagicMock(),
        "metric_qdrant_repository": MagicMock(),
        "value_es_repository": MagicMock(),
        "sql_guard": guard,
        "trace_store": store,
    }
    service = QueryService(**dependencies)

    async def collect_messages():
        await store.open()
        messages = [message async for message in service.query("收入是多少")]
        await store.close()
        return messages

    messages = asyncio.run(collect_messages())

    assert messages
    assert captured["context"]["sql_guard"] is guard
    assert captured["input"]["query"] == "收入是多少"
    assert captured["stream_mode"] == "custom"


def test_meta_config_path_exists_at_project_root():
    path = Path(__file__).parents[1] / "conf" / "meta_config.yaml"

    assert path.is_file()
