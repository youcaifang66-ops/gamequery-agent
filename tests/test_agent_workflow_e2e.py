import asyncio
import json
from unittest.mock import MagicMock

import pytest

from app.agent.graph import build_graph
from app.agent.nodes.fail_sql import fail_sql as production_fail_sql
from app.observability.trace_store import AsyncSQLiteTraceStore
from app.retrieval.online import RetrievalUnavailableError
from app.security.sql_guard import SQLGuard
from app.services import query_service as query_service_module
from app.services.query_service import QueryService


def parse_sse(message):
    return json.loads(message.split("data: ", 1)[1])


class FakeDWRepository:
    def __init__(self):
        self.validate_calls = []
        self.run_calls = []

    async def validate(self, sql):
        self.validate_calls.append(sql)

    async def run(self, sql):
        self.run_calls.append(sql)
        return [{"value": 42}]


def workflow_nodes(*, outcomes, repository, retrieval_failure=False, slow=False):
    visited = []
    sql_versions = []
    pending = list(outcomes)

    async def extract_keywords(state):
        visited.append("extract_keywords")
        if slow:
            await asyncio.sleep(0.1)
        return {"keywords": ["收入"]}

    async def recall_column(state):
        visited.append("recall_column")
        if retrieval_failure:
            raise RetrievalUnavailableError()
        return {"retrieved_column_infos": [], "column_retrieval_evidence": []}

    async def recall_value(state):
        visited.append("recall_value")
        return {"retrieved_value_infos": []}

    async def recall_metric(state):
        visited.append("recall_metric")
        return {"retrieved_metric_infos": [], "metric_retrieval_evidence": []}

    async def merge_retrieved_info(state):
        visited.append("merge_retrieved_info")
        return {"table_infos": [], "metric_infos": []}

    async def filter_table(state):
        visited.append("filter_table")
        return {"table_infos": []}

    async def filter_metric(state):
        visited.append("filter_metric")
        return {"metric_infos": []}

    async def add_extra_context(state):
        visited.append("add_extra_context")
        return {
            "date_info": {"date": "2026-09-23", "weekday": "3", "quarter": "Q3"},
            "db_info": {"dialect": "mysql", "version": "8.0"},
        }

    async def generate_sql(state):
        visited.append("generate_sql")
        sql_versions.append("candidate-v1")
        return {"sql": "candidate-v1", "correction_attempts": 0}

    async def check_query_context(state):
        visited.append("check_query_context")
        return {"clarification": None}

    async def validate_sql(state):
        visited.append("validate_sql")
        outcome = pending.pop(0) if pending else outcomes[-1]
        if outcome == "success":
            await repository.validate(state["sql"])
            return {
                "validated_sql": state["sql"],
                "sql_policy": {
                    "tables": ["fact_payment"],
                    "max_rows": 500,
                    "limit_action": "added",
                    "timeout_ms": 5000,
                },
                "error": None,
                "error_code": None,
                "error_correctable": False,
            }
        correctable = outcome == "SQL_EXPLAIN_FAILED"
        if correctable:
            await repository.validate(state["sql"])
        return {
            "validated_sql": None,
            "sql_policy": None,
            "error": "安全的校验错误",
            "error_code": outcome,
            "error_correctable": correctable,
        }

    async def correct_sql(state):
        visited.append("correct_sql")
        attempt = state.get("correction_attempts", 0) + 1
        sql = f"candidate-v{attempt + 1}"
        sql_versions.append(sql)
        return {"sql": sql, "correction_attempts": attempt}

    async def run_sql(state, runtime):
        visited.append("run_sql")
        result = await repository.run(state["validated_sql"])
        runtime.stream_writer({"type": "result", "data": result})
        return {}

    async def fail_sql(state, runtime):
        visited.append("fail_sql")
        return await production_fail_sql(state, runtime)

    return visited, sql_versions, {
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
        "fail_sql": fail_sql,
    }


def make_service(store, repository):
    return QueryService(
        meta_mysql_repository=MagicMock(),
        embedding_client=MagicMock(),
        dw_mysql_repository=repository,
        column_qdrant_repository=MagicMock(),
        metric_qdrant_repository=MagicMock(),
        value_es_repository=MagicMock(),
        sql_guard=SQLGuard({"fact_payment": ["amount"]}),
        trace_store=store,
    )


def execute_scenario(monkeypatch, tmp_path, **node_options):
    async def scenario():
        repository = FakeDWRepository()
        visited, sql_versions, nodes = workflow_nodes(
            repository=repository, **node_options
        )
        monkeypatch.setattr(query_service_module, "graph", build_graph(nodes))
        store = AsyncSQLiteTraceStore(tmp_path / "workflow.sqlite3")
        await store.open()
        events = [
            parse_sse(message)
            async for message in make_service(store, repository).query(
                "查询收入", request_id="workflow-request"
            )
        ]
        replay = await store.replay("workflow-request")
        await store.close()
        return events, replay, visited, sql_versions, repository

    return asyncio.run(scenario())


@pytest.mark.parametrize(
    ("outcomes", "expected_versions", "validate_count"),
    [
        (["success"], ["candidate-v1"], 1),
        (
            ["SQL_EXPLAIN_FAILED", "success"],
            ["candidate-v1", "candidate-v2"],
            2,
        ),
    ],
)
def test_success_paths_have_one_done_and_one_repository_run(
    monkeypatch, tmp_path, outcomes, expected_versions, validate_count
):
    events, replay, visited, versions, repository = execute_scenario(
        monkeypatch, tmp_path, outcomes=outcomes
    )

    assert versions == expected_versions
    assert visited.count("validate_sql") == validate_count
    assert visited.count("run_sql") == 1
    assert len(repository.validate_calls) == validate_count
    assert repository.run_calls == [expected_versions[-1]]
    assert [event["type"] for event in events] == ["result", "done"]
    assert sum(event["type"] in {"done", "error"} for event in events) == 1
    assert replay["status"] == "completed"


def test_two_repairs_end_with_correction_exhausted(monkeypatch, tmp_path):
    events, replay, visited, versions, repository = execute_scenario(
        monkeypatch,
        tmp_path,
        outcomes=["SQL_EXPLAIN_FAILED"] * 3,
    )

    assert versions == ["candidate-v1", "candidate-v2", "candidate-v3"]
    assert visited.count("correct_sql") == 2
    assert visited.count("validate_sql") == 3
    assert visited[-1] == "fail_sql"
    assert repository.run_calls == []
    assert [event["type"] for event in events] == ["error"]
    assert events[0]["code"] == "CORRECTION_EXHAUSTED"
    assert replay["error_code"] == "CORRECTION_EXHAUSTED"


def test_noncorrectable_guard_error_skips_correction_and_database(monkeypatch, tmp_path):
    events, replay, visited, _, repository = execute_scenario(
        monkeypatch,
        tmp_path,
        outcomes=["WRITE_OPERATION_DENIED"],
    )

    assert "correct_sql" not in visited
    assert "run_sql" not in visited
    assert repository.validate_calls == []
    assert repository.run_calls == []
    assert events[0]["code"] == "SQL_POLICY_DENIED"
    assert replay["error_code"] == "WRITE_OPERATION_DENIED"


def test_retrieval_failure_has_stable_terminal(monkeypatch, tmp_path):
    events, replay, visited, _, repository = execute_scenario(
        monkeypatch,
        tmp_path,
        outcomes=["success"],
        retrieval_failure=True,
    )

    assert "generate_sql" not in visited
    assert repository.run_calls == []
    assert [event["type"] for event in events] == ["error"]
    assert events[0]["code"] == "RETRIEVAL_UNAVAILABLE"
    assert replay["status"] == "failed"


def test_query_timeout_has_one_terminal_and_no_database_calls(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        query_service_module.app_config.query, "request_timeout_seconds", 0.01
    )
    events, replay, visited, _, repository = execute_scenario(
        monkeypatch,
        tmp_path,
        outcomes=["success"],
        slow=True,
    )

    assert "generate_sql" not in visited
    assert repository.validate_calls == []
    assert repository.run_calls == []
    assert [event["type"] for event in events] == ["error"]
    assert events[0]["code"] == "QUERY_TIMEOUT"
    assert replay["error_code"] == "QUERY_TIMEOUT"
