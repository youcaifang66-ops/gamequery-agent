from app.observability.trace_store import SQLiteTraceStore


def test_trace_is_ordered_and_replayable():
    store = SQLiteTraceStore()
    store.start("trace-1", "统计各游戏DAU")
    store.append("trace-1", "progress", {"step": "recall", "status": "success"})
    store.append("trace-1", "sql", {"version": 1, "sql": "SELECT 1"})
    store.finish("trace-1", "completed")

    replay = store.replay("trace-1")
    assert replay["status"] == "completed"
    assert [event["sequence"] for event in replay["events"]] == [1, 2]
    assert replay["events"][1]["payload"]["sql"] == "SELECT 1"
