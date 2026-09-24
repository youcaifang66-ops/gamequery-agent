import asyncio
import json
from unittest.mock import MagicMock

import pytest

from app.observability.trace_store import AsyncSQLiteTraceStore
from app.retrieval.online import RetrievalUnavailableError
from app.security.sql_guard import SQLGuard
from app.services import query_service as query_service_module
from app.services.query_service import QueryService


def parse_sse(message: str) -> dict:
    return json.loads(message.split("data: ", 1)[1])


def make_service(store: AsyncSQLiteTraceStore) -> QueryService:
    return QueryService(
        meta_mysql_repository=MagicMock(),
        embedding_client=MagicMock(),
        dw_mysql_repository=MagicMock(),
        column_qdrant_repository=MagicMock(),
        metric_qdrant_repository=MagicMock(),
        value_es_repository=MagicMock(),
        sql_guard=SQLGuard({"fact_payment": ["amount"]}),
        trace_store=store,
    )


def test_success_stream_has_one_done_and_sanitized_trace(monkeypatch, tmp_path):
    class SuccessGraph:
        async def astream(self, **kwargs):
            yield {"type": "progress", "step": "执行SQL", "status": "running"}
            yield {"type": "result", "data": [{"amount": 42}, {"amount": 7}]}

    async def scenario():
        monkeypatch.setattr(query_service_module, "graph", SuccessGraph())
        store = AsyncSQLiteTraceStore(tmp_path / "success.sqlite3")
        await store.open()
        messages = [
            parse_sse(message)
            async for message in make_service(store).query(
                "查询收入", request_id="request-success"
            )
        ]
        replay = await store.replay("request-success")
        await store.close()
        return messages, replay

    messages, replay = asyncio.run(scenario())
    assert [event["sequence"] for event in messages] == [1, 2, 3]
    assert [event["type"] for event in messages] == ["progress", "result", "done"]
    assert all(event["request_id"] == "request-success" for event in messages)
    assert sum(event["type"] == "done" for event in messages) == 1
    assert replay["status"] == "completed"
    assert replay["events"][1]["payload"] == {"row_count": 2}
    assert "data" not in replay["events"][1]["payload"]


def test_graph_exception_is_sanitized_and_has_one_error(monkeypatch, tmp_path):
    class FailingGraph:
        async def astream(self, **kwargs):
            yield {"type": "progress", "step": "召回", "status": "running"}
            raise RuntimeError("mysql://root:secret@localhost/dw")

    async def scenario():
        monkeypatch.setattr(query_service_module, "graph", FailingGraph())
        store = AsyncSQLiteTraceStore(tmp_path / "failure.sqlite3")
        await store.open()
        messages = [
            parse_sse(message)
            async for message in make_service(store).query(
                "查询收入", request_id="request-failure"
            )
        ]
        replay = await store.replay("request-failure")
        await store.close()
        return messages, replay

    messages, replay = asyncio.run(scenario())
    assert [event["sequence"] for event in messages] == [1, 2]
    assert [event["type"] for event in messages] == ["progress", "error"]
    assert messages[-1]["code"] == "INTERNAL_ERROR"
    assert "secret" not in json.dumps(messages, ensure_ascii=False)
    assert replay["status"] == "failed"
    assert replay["error_code"] == "INTERNAL_ERROR"


def test_timeout_has_stable_error_and_no_done(monkeypatch, tmp_path):
    class SlowGraph:
        async def astream(self, **kwargs):
            await asyncio.sleep(0.1)
            yield {"type": "result", "data": []}

    async def scenario():
        monkeypatch.setattr(query_service_module, "graph", SlowGraph())
        monkeypatch.setattr(
            query_service_module.app_config.query, "request_timeout_seconds", 0.01
        )
        store = AsyncSQLiteTraceStore(tmp_path / "timeout.sqlite3")
        await store.open()
        messages = [
            parse_sse(message)
            async for message in make_service(store).query(
                "查询收入", request_id="request-timeout"
            )
        ]
        replay = await store.replay("request-timeout")
        await store.close()
        return messages, replay

    messages, replay = asyncio.run(scenario())
    assert [event["type"] for event in messages] == ["error"]
    assert messages[0]["code"] == "QUERY_TIMEOUT"
    assert replay["status"] == "failed"
    assert replay["error_code"] == "QUERY_TIMEOUT"


def test_cancellation_marks_trace_cancelled_and_reraises(monkeypatch, tmp_path):
    entered = asyncio.Event()

    class BlockingGraph:
        async def astream(self, **kwargs):
            entered.set()
            await asyncio.sleep(60)
            yield {"type": "result", "data": []}

    async def scenario():
        monkeypatch.setattr(query_service_module, "graph", BlockingGraph())
        store = AsyncSQLiteTraceStore(tmp_path / "cancelled.sqlite3")
        await store.open()
        stream = make_service(store).query(
            "查询收入", request_id="request-cancelled"
        )
        task = asyncio.create_task(anext(stream))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        replay = await store.replay("request-cancelled")

        class ReusableGraph:
            async def astream(self, **kwargs):
                yield {"type": "result", "data": [{"value": 1}]}

        monkeypatch.setattr(query_service_module, "graph", ReusableGraph())
        next_messages = [
            parse_sse(message)
            async for message in make_service(store).query(
                "查询收入", request_id="request-after-cancel"
            )
        ]
        next_replay = await store.replay("request-after-cancel")
        await store.close()
        return replay, next_messages, next_replay

    replay, next_messages, next_replay = asyncio.run(scenario())
    assert replay["status"] == "cancelled"
    assert [event["type"] for event in next_messages] == ["result", "done"]
    assert next_replay["status"] == "completed"


def test_closing_stream_after_partial_delivery_marks_cancelled(monkeypatch, tmp_path):
    class PartialGraph:
        async def astream(self, **kwargs):
            yield {"type": "progress", "step": "召回", "status": "running"}
            await asyncio.sleep(60)

    async def scenario():
        monkeypatch.setattr(query_service_module, "graph", PartialGraph())
        store = AsyncSQLiteTraceStore(tmp_path / "closed.sqlite3")
        await store.open()
        stream = make_service(store).query("查询收入", request_id="request-closed")
        first = parse_sse(await anext(stream))
        await stream.aclose()
        replay = await store.replay("request-closed")
        await store.close()
        return first, replay

    first, replay = asyncio.run(scenario())
    assert first["sequence"] == 1
    assert replay["status"] == "cancelled"


def test_trace_append_failure_stops_graph_and_returns_sanitized_error(
    monkeypatch, tmp_path
):
    yielded_second = False

    class TwoEventGraph:
        async def astream(self, **kwargs):
            nonlocal yielded_second
            yield {"type": "progress", "step": "召回", "status": "running"}
            yielded_second = True
            yield {"type": "result", "data": [{"secret": "row"}]}

    async def scenario():
        monkeypatch.setattr(query_service_module, "graph", TwoEventGraph())
        store = AsyncSQLiteTraceStore(tmp_path / "store-failure.sqlite3")
        await store.open()
        original_append = store.append

        async def fail_progress(trace_id, event_type, payload):
            if event_type == "progress":
                raise RuntimeError("disk path and credentials")
            return await original_append(trace_id, event_type, payload)

        monkeypatch.setattr(store, "append", fail_progress)
        messages = [
            parse_sse(message)
            async for message in make_service(store).query(
                "查询收入", request_id="request-store-failure"
            )
        ]
        replay = await store.replay("request-store-failure")
        await store.close()
        return messages, replay

    messages, replay = asyncio.run(scenario())
    assert not yielded_second
    assert [event["type"] for event in messages] == ["error"]
    assert messages[0]["code"] == "INTERNAL_ERROR"
    assert "credentials" not in json.dumps(messages)
    assert replay["status"] == "failed"


def test_validation_exhaustion_returns_error_without_done(monkeypatch, tmp_path):
    class NoResultGraph:
        async def astream(self, **kwargs):
            yield {"type": "progress", "step": "校验SQL", "status": "error"}

    async def scenario():
        monkeypatch.setattr(query_service_module, "graph", NoResultGraph())
        store = AsyncSQLiteTraceStore(tmp_path / "exhausted.sqlite3")
        await store.open()
        messages = [
            parse_sse(message)
            async for message in make_service(store).query(
                "查询收入", request_id="request-exhausted"
            )
        ]
        replay = await store.replay("request-exhausted")
        await store.close()
        return messages, replay

    messages, replay = asyncio.run(scenario())
    assert [event["type"] for event in messages] == ["progress", "error"]
    assert messages[-1]["code"] == "CORRECTION_EXHAUSTED"
    assert replay["error_code"] == "CORRECTION_EXHAUSTED"


def test_retrieval_unavailable_uses_stable_public_code(monkeypatch, tmp_path):
    class MissingIndexGraph:
        async def astream(self, **kwargs):
            raise RetrievalUnavailableError()
            yield

    async def scenario():
        monkeypatch.setattr(query_service_module, "graph", MissingIndexGraph())
        store = AsyncSQLiteTraceStore(tmp_path / "retrieval-unavailable.sqlite3")
        await store.open()
        messages = [
            parse_sse(message)
            async for message in make_service(store).query(
                "查询收入", request_id="request-retrieval"
            )
        ]
        replay = await store.replay("request-retrieval")
        await store.close()
        return messages, replay

    messages, replay = asyncio.run(scenario())
    assert [event["type"] for event in messages] == ["error"]
    assert messages[0]["code"] == "RETRIEVAL_UNAVAILABLE"
    assert replay["error_code"] == "RETRIEVAL_UNAVAILABLE"
