import asyncio

import pytest

from app.agent.graph import build_graph


def node_set(*, validation_results):
    calls = []
    pending_results = list(validation_results)

    async def extract_keywords(state):
        calls.append("extract_keywords")
        return {"keywords": ["DAU"]}

    async def recall_column(state):
        await asyncio.sleep(0.003)
        calls.append("recall_column")
        return {"retrieved_column_infos": ["column"]}

    async def recall_value(state):
        await asyncio.sleep(0.001)
        calls.append("recall_value")
        return {"retrieved_value_infos": ["value"]}

    async def recall_metric(state):
        await asyncio.sleep(0.002)
        calls.append("recall_metric")
        return {"retrieved_metric_infos": ["metric"]}

    async def merge_retrieved_info(state):
        assert state["retrieved_column_infos"] == ["column"]
        assert state["retrieved_value_infos"] == ["value"]
        assert state["retrieved_metric_infos"] == ["metric"]
        calls.append("merge_retrieved_info")
        return {"table_infos": ["raw-table"], "metric_infos": ["raw-metric"]}

    async def filter_table(state):
        await asyncio.sleep(0.002)
        calls.append("filter_table")
        return {"table_infos": ["filtered-table"]}

    async def filter_metric(state):
        await asyncio.sleep(0.001)
        calls.append("filter_metric")
        return {"metric_infos": ["filtered-metric"]}

    async def add_extra_context(state):
        assert state["table_infos"] == ["filtered-table"]
        assert state["metric_infos"] == ["filtered-metric"]
        calls.append("add_extra_context")
        return {
            "date_info": {"date": "2026-09-23", "weekday": "3", "quarter": "Q3"},
            "db_info": {"dialect": "mysql", "version": "8.0"},
        }

    async def check_query_context(state):
        calls.append("check_query_context")
        return {"clarification": None}

    async def generate_sql(state):
        calls.append("generate_sql")
        return {"sql": "candidate", "correction_attempts": 0}

    async def validate_sql(state):
        calls.append("validate_sql")
        outcome = pending_results.pop(0) if pending_results else validation_results[-1]
        if outcome == "success":
            return {
                "sql": "guarded",
                "validated_sql": "guarded",
                "sql_policy": {
                    "tables": [],
                    "max_rows": 500,
                    "limit_action": "added",
                    "timeout_ms": 5_000,
                },
                "error": None,
                "error_code": None,
                "error_correctable": False,
            }
        return {
            "validated_sql": None,
            "sql_policy": None,
            "error": "failed",
            "error_code": outcome,
            "error_correctable": outcome == "SQL_EXPLAIN_FAILED",
        }

    async def correct_sql(state):
        calls.append("correct_sql")
        return {
            "sql": f"corrected-{state.get('correction_attempts', 0) + 1}",
            "correction_attempts": state.get("correction_attempts", 0) + 1,
        }

    async def run_sql(state):
        calls.append("run_sql")
        return {}

    return calls, {
        "extract_keywords": extract_keywords,
        "recall_column": recall_column,
        "recall_value": recall_value,
        "recall_metric": recall_metric,
        "merge_retrieved_info": merge_retrieved_info,
        "filter_table": filter_table,
        "filter_metric": filter_metric,
        "add_extra_context": add_extra_context,
        "check_query_context": check_query_context,
        "generate_sql": generate_sql,
        "validate_sql": validate_sql,
        "correct_sql": correct_sql,
        "run_sql": run_sql,
    }


def test_explicit_barriers_wait_for_all_branches_and_run_successors_once():
    calls, nodes = node_set(validation_results=["success"])
    graph = build_graph(nodes)

    asyncio.run(graph.ainvoke({"query": "统计DAU"}))

    assert calls.count("merge_retrieved_info") == 1
    assert calls.count("add_extra_context") == 1
    assert calls.count("run_sql") == 1
    assert calls.index("merge_retrieved_info") > max(
        calls.index("recall_column"),
        calls.index("recall_value"),
        calls.index("recall_metric"),
    )


def test_non_correctable_policy_error_never_calls_corrector_or_runner():
    calls, nodes = node_set(validation_results=["WRITE_OPERATION_DENIED"])
    graph = build_graph(nodes)

    asyncio.run(graph.ainvoke({"query": "删除数据"}))

    assert calls.count("validate_sql") == 1
    assert "correct_sql" not in calls
    assert "run_sql" not in calls


def test_correctable_error_is_revalidated_and_stops_after_two_repairs():
    calls, nodes = node_set(
        validation_results=[
            "SQL_EXPLAIN_FAILED",
            "SQL_EXPLAIN_FAILED",
            "SQL_EXPLAIN_FAILED",
        ]
    )
    graph = build_graph(nodes)

    result = asyncio.run(graph.ainvoke({"query": "统计DAU"}))

    assert calls.count("validate_sql") == 3
    assert calls.count("correct_sql") == 2
    assert "run_sql" not in calls
    assert result["correction_attempts"] == 2


def test_one_repair_then_success_reaches_runner_once():
    calls, nodes = node_set(
        validation_results=["SQL_EXPLAIN_FAILED", "success"]
    )
    graph = build_graph(nodes)

    asyncio.run(graph.ainvoke({"query": "统计DAU"}))

    assert calls.count("correct_sql") == 1
    assert calls.count("validate_sql") == 2
    assert calls.count("run_sql") == 1


def test_unknown_node_override_is_rejected_at_construction():
    with pytest.raises(ValueError, match="unknown node overrides"):
        build_graph({"not_a_node": lambda state: {}})


def test_clarification_ends_before_sql_generation():
    calls, nodes = node_set(validation_results=["success"])

    async def clarify(state, runtime):
        calls.append("check_query_context")
        clarification = {
            "code": "MISSING_DATE",
            "missing_slots": ["date"],
            "message": "请提供日期。",
        }
        runtime.stream_writer({"type": "clarification", **clarification})
        return {"clarification": clarification}

    nodes["check_query_context"] = clarify
    graph = build_graph(nodes)

    async def collect():
        return [
            chunk
            async for chunk in graph.astream(
                {"query": "查询各游戏DAU"}, stream_mode="custom"
            )
        ]

    events = asyncio.run(collect())

    assert any(event["type"] == "clarification" for event in events)
    assert "generate_sql" not in calls
    assert "validate_sql" not in calls
    assert "run_sql" not in calls
