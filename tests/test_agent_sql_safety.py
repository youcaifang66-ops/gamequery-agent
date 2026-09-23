import asyncio
from types import SimpleNamespace

from app.agent.nodes.validate_sql import validate_sql
from app.security.errors import SQLPolicyError
from app.security.sql_guard import GuardedSQL


class FakeGuard:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def validate(self, sql):
        self.calls.append(sql)
        if self.error:
            raise self.error
        return self.result


class FakeRepository:
    def __init__(self, error=None, delay=0):
        self.error = error
        self.delay = delay
        self.validated = []

    async def validate(self, sql):
        self.validated.append(sql)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise self.error


def runtime(guard, repository, events):
    return SimpleNamespace(
        context={"sql_guard": guard, "dw_mysql_repository": repository},
        stream_writer=events.append,
    )


def guarded(sql="SELECT amount FROM fact_payment LIMIT 500", timeout_ms=5_000):
    return GuardedSQL(
        sql=sql,
        tables=("fact_payment",),
        max_rows=500,
        limit_action="added",
        timeout_ms=timeout_ms,
    )


def test_guarded_sql_is_the_exact_sql_explained_and_saved_for_execution():
    guard = FakeGuard(result=guarded())
    repository = FakeRepository()
    events = []

    result = asyncio.run(
        validate_sql(
            {"sql": "SELECT amount FROM fact_payment"},
            runtime(guard, repository, events),
        )
    )

    assert guard.calls == ["SELECT amount FROM fact_payment"]
    assert repository.validated == [guard.result.sql]
    assert result["sql"] == guard.result.sql
    assert result["validated_sql"] == guard.result.sql
    assert result["error"] is None
    assert result["error_code"] is None
    assert result["error_correctable"] is False
    assert result["sql_policy"]["limit_action"] == "added"


def test_policy_failure_never_reaches_database_and_preserves_correctability():
    error = SQLPolicyError(
        "UNKNOWN_COLUMN",
        "查询包含未知字段。",
        correctable=True,
    )
    guard = FakeGuard(error=error)
    repository = FakeRepository()

    result = asyncio.run(
        validate_sql(
            {"sql": "SELECT secret FROM dim_player"},
            runtime(guard, repository, []),
        )
    )

    assert repository.validated == []
    assert result["validated_sql"] is None
    assert result["error_code"] == "UNKNOWN_COLUMN"
    assert result["error_correctable"] is True
    assert result["error"] == "查询包含未知字段。"


def test_non_correctable_policy_failure_is_marked_terminal():
    guard = FakeGuard(
        error=SQLPolicyError(
            "WRITE_OPERATION_DENIED",
            "查询包含写入操作。",
            correctable=False,
        )
    )
    repository = FakeRepository()

    result = asyncio.run(
        validate_sql(
            {"sql": "DELETE FROM fact_payment"},
            runtime(guard, repository, []),
        )
    )

    assert repository.validated == []
    assert result["error_code"] == "WRITE_OPERATION_DENIED"
    assert result["error_correctable"] is False


def test_database_error_is_sanitized_and_correctable():
    guard = FakeGuard(result=guarded())
    repository = FakeRepository(error=RuntimeError("password=super-secret host=10.0.0.8"))

    result = asyncio.run(
        validate_sql(
            {"sql": "SELECT amount FROM fact_payment"},
            runtime(guard, repository, []),
        )
    )

    assert result["error_code"] == "SQL_EXPLAIN_FAILED"
    assert result["error_correctable"] is True
    assert result["error"] == "数据库无法预检该查询。"
    assert "super-secret" not in str(result)


def test_database_validation_timeout_is_terminal():
    guard = FakeGuard(result=guarded(timeout_ms=1))
    repository = FakeRepository(delay=0.02)

    result = asyncio.run(
        validate_sql(
            {"sql": "SELECT amount FROM fact_payment"},
            runtime(guard, repository, []),
        )
    )

    assert result["error_code"] == "QUERY_TIMEOUT"
    assert result["error_correctable"] is False
    assert result["validated_sql"] is None


def test_every_corrected_candidate_is_guarded_again():
    guard = FakeGuard(result=guarded())
    repository = FakeRepository()
    fake_runtime = runtime(guard, repository, [])

    asyncio.run(validate_sql({"sql": "SELECT broken"}, fake_runtime))
    guard.result = guarded("SELECT amount FROM fact_payment LIMIT 500")
    asyncio.run(
        validate_sql(
            {"sql": "SELECT amount FROM fact_payment"},
            fake_runtime,
        )
    )

    assert guard.calls == ["SELECT broken", "SELECT amount FROM fact_payment"]
    assert repository.validated == [
        "SELECT amount FROM fact_payment LIMIT 500",
        "SELECT amount FROM fact_payment LIMIT 500",
    ]
