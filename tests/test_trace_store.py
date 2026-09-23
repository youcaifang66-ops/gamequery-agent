import asyncio

import pytest

from app.observability.trace_store import AsyncSQLiteTraceStore, TraceStoreError


def run(coroutine):
    return asyncio.run(coroutine)


def test_trace_is_ordered_and_replayable(tmp_path):
    async def scenario():
        store = AsyncSQLiteTraceStore(tmp_path / "traces.sqlite3")
        await store.open()
        await store.start("trace-1", "sha256:digest")
        first = await store.append(
            "trace-1", "progress", {"step": "recall", "status": "success"}
        )
        second = await store.append("trace-1", "sql", {"version": 1})
        await store.finish("trace-1", "completed")
        replay = await store.replay("trace-1")
        await store.close()
        return first, second, replay

    first, second, replay = run(scenario())
    assert (first, second) == (1, 2)
    assert replay["status"] == "completed"
    assert [event["sequence"] for event in replay["events"]] == [1, 2]
    assert replay["events"][1]["payload"] == {"version": 1}


def test_twenty_concurrent_traces_and_same_trace_appends_are_lossless(tmp_path):
    async def scenario():
        store = AsyncSQLiteTraceStore(tmp_path / "concurrent.sqlite3")
        await store.open()

        async def write_trace(index: int):
            trace_id = f"trace-{index}"
            await store.start(trace_id, f"digest-{index}")
            await asyncio.gather(
                *(
                    store.append(trace_id, "progress", {"worker": worker})
                    for worker in range(10)
                )
            )
            await store.finish(trace_id, "completed")

        await asyncio.gather(*(write_trace(index) for index in range(20)))
        traces = [await store.replay(f"trace-{index}") for index in range(20)]
        await store.close()
        return traces

    traces = run(scenario())
    for trace in traces:
        assert trace["status"] == "completed"
        assert [event["sequence"] for event in trace["events"]] == list(range(1, 11))


def test_open_enables_wal_and_busy_timeout(tmp_path):
    async def scenario():
        store = AsyncSQLiteTraceStore(tmp_path / "settings.sqlite3", busy_timeout_ms=4321)
        await store.open()
        journal_mode = await store._pragma("journal_mode")
        busy_timeout = await store._pragma("busy_timeout")
        await store.close()
        return journal_mode, busy_timeout

    journal_mode, busy_timeout = run(scenario())
    assert journal_mode.lower() == "wal"
    assert int(busy_timeout) == 4321


def test_start_is_idempotent_only_for_same_digest(tmp_path):
    async def scenario():
        store = AsyncSQLiteTraceStore(tmp_path / "idempotent.sqlite3")
        await store.open()
        await store.start("trace-1", "same")
        await store.start("trace-1", "same")
        with pytest.raises(TraceStoreError, match="TRACE_ID_CONFLICT"):
            await store.start("trace-1", "different")
        await store.close()

    run(scenario())


def test_terminal_status_cannot_change(tmp_path):
    async def scenario():
        store = AsyncSQLiteTraceStore(tmp_path / "terminal.sqlite3")
        await store.open()
        await store.start("trace-1", "digest")
        await store.finish("trace-1", "failed", error_code="QUERY_FAILED")
        await store.finish("trace-1", "failed", error_code="QUERY_FAILED")
        with pytest.raises(TraceStoreError, match="TRACE_ALREADY_FINISHED"):
            await store.finish("trace-1", "completed")
        replay = await store.replay("trace-1")
        await store.close()
        return replay

    replay = run(scenario())
    assert replay["status"] == "failed"
    assert replay["error_code"] == "QUERY_FAILED"
    assert replay["finished_at"] is not None


def test_result_events_reject_row_values(tmp_path):
    async def scenario():
        store = AsyncSQLiteTraceStore(tmp_path / "sanitized.sqlite3")
        await store.open()
        await store.start("trace-1", "digest")
        with pytest.raises(TraceStoreError, match="UNSAFE_TRACE_PAYLOAD"):
            await store.append("trace-1", "result", {"row_count": 1, "rows": [[42]]})
        await store.close()

    run(scenario())


def test_store_must_be_open_and_cannot_be_used_after_close(tmp_path):
    async def scenario():
        store = AsyncSQLiteTraceStore(tmp_path / "lifecycle.sqlite3")
        with pytest.raises(TraceStoreError, match="TRACE_STORE_CLOSED"):
            await store.replay("missing")
        await store.open()
        await store.close()
        with pytest.raises(TraceStoreError, match="TRACE_STORE_CLOSED"):
            await store.start("trace", "digest")

    run(scenario())
