import asyncio
from types import SimpleNamespace

import pytest

from app.agent.nodes.run_sql import run_sql
from app.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository


class FakeMappings:
    def __init__(self, rows):
        self.rows = rows

    def fetchmany(self, size):
        return self.rows[:size]


class FakeResult:
    def __init__(self, rows=()):
        self.rows = rows

    def mappings(self):
        return FakeMappings(self.rows)


class FakeSession:
    def __init__(self, rows=(), delay=0):
        self.rows = rows
        self.delay = delay
        self.executed = []
        self.rollback_calls = 0
        self.started = asyncio.Event()

    async def execute(self, statement):
        self.executed.append(str(statement))
        self.started.set()
        if self.delay:
            await asyncio.sleep(self.delay)
        return FakeResult(self.rows)

    async def rollback(self):
        self.rollback_calls += 1


def test_validate_explains_the_exact_guarded_sql():
    session = FakeSession()
    repository = DWMySQLRepository(session)
    sql = "SELECT amount FROM fact_payment LIMIT 500"

    asyncio.run(repository.validate(sql, timeout_ms=5_000))

    assert session.executed == [f"EXPLAIN {sql}"]
    assert session.rollback_calls == 0


def test_validate_timeout_rolls_back_session():
    session = FakeSession(delay=0.02)
    repository = DWMySQLRepository(session)

    with pytest.raises(TimeoutError):
        asyncio.run(repository.validate("SELECT 1", timeout_ms=1))

    assert session.rollback_calls == 1


def test_session_can_be_reused_after_validation_timeout():
    async def scenario():
        session = FakeSession(delay=0.02)
        repository = DWMySQLRepository(session)
        with pytest.raises(TimeoutError):
            await repository.validate("SELECT 1", timeout_ms=1)
        session.delay = 0
        await repository.validate("SELECT 2", timeout_ms=5_000)
        return session

    session = asyncio.run(scenario())
    assert session.rollback_calls == 1
    assert session.executed == ["EXPLAIN SELECT 1", "EXPLAIN SELECT 2"]


def test_run_uses_exact_sql_and_defensively_bounds_fetched_rows():
    session = FakeSession(rows=[{"id": 1}, {"id": 2}, {"id": 3}])
    repository = DWMySQLRepository(session)
    sql = "SELECT game_id FROM dim_game LIMIT 2"

    rows = asyncio.run(repository.run(sql, timeout_ms=5_000, max_rows=2))

    assert session.executed == [sql]
    assert rows == [{"id": 1}, {"id": 2}]


def test_run_cancellation_rolls_back_session():
    async def scenario():
        session = FakeSession(delay=10)
        repository = DWMySQLRepository(session)
        task = asyncio.create_task(
            repository.run("SELECT 1", timeout_ms=20_000, max_rows=1)
        )
        await session.started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return session

    session = asyncio.run(scenario())
    assert session.rollback_calls == 1


class FakeRunRepository:
    def __init__(self):
        self.calls = []

    async def run(self, sql, *, timeout_ms, max_rows):
        self.calls.append((sql, timeout_ms, max_rows))
        return [{"game_id": "G001", "dau": 2}]


def test_run_node_only_executes_the_exact_validated_sql():
    repository = FakeRunRepository()
    events = []
    runtime = SimpleNamespace(
        context={"dw_mysql_repository": repository},
        stream_writer=events.append,
    )
    sql = "SELECT game_id FROM fact_player_daily LIMIT 500"

    asyncio.run(
        run_sql(
            {
                "sql": sql,
                "validated_sql": sql,
                "sql_policy": {
                    "tables": ["fact_player_daily"],
                    "max_rows": 500,
                    "limit_action": "added",
                    "timeout_ms": 5_000,
                },
            },
            runtime,
        )
    )

    assert repository.calls == [(sql, 5_000, 500)]
    assert events[-1] == {
        "type": "result",
        "data": [{"game_id": "G001", "dau": 2}],
    }


def test_run_node_rejects_unvalidated_or_changed_sql_before_repository():
    repository = FakeRunRepository()
    runtime = SimpleNamespace(
        context={"dw_mysql_repository": repository},
        stream_writer=lambda event: None,
    )

    with pytest.raises(RuntimeError, match="validated SQL invariant"):
        asyncio.run(
            run_sql(
                {
                    "sql": "SELECT secret FROM dim_player",
                    "validated_sql": "SELECT player_id FROM dim_player LIMIT 500",
                    "sql_policy": {
                        "tables": ["dim_player"],
                        "max_rows": 500,
                        "limit_action": "added",
                        "timeout_ms": 5_000,
                    },
                },
                runtime,
            )
        )

    assert repository.calls == []
