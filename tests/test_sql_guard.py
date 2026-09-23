from pathlib import Path

import pytest
import sqlglot
from sqlglot import exp

from app.security.sql_guard import SQLGuard, SQLGuardError

GUARD = SQLGuard.from_meta_config(
    Path(__file__).resolve().parents[1] / "conf" / "meta_config.yaml",
    max_rows=500,
    statement_timeout_ms=5_000,
)


def assert_policy_error(sql: str, code: str, *, correctable: bool):
    with pytest.raises(SQLGuardError) as captured:
        GUARD.validate(sql)

    assert captured.value.code == code
    assert captured.value.correctable is correctable
    assert captured.value.safe_message
    assert sql not in str(captured.value)


def test_allows_read_only_query_and_adds_limit_and_timeout():
    result = GUARD.validate(
        "SELECT game_id, COUNT(DISTINCT player_id) AS dau FROM fact_player_daily "
        "WHERE is_active=1 GROUP BY game_id"
    )

    assert result.limit_action == "added"
    assert result.limit_applied is True
    assert "LIMIT 500" in result.sql
    assert "MAX_EXECUTION_TIME(5000)" in result.sql
    assert result.max_rows == 500
    assert result.timeout_ms == 5_000
    assert result.tables == ("fact_player_daily",)


def test_keeps_small_limit_and_caps_large_limit():
    kept = GUARD.validate("SELECT amount FROM fact_payment LIMIT 25")
    capped = GUARD.validate("SELECT amount FROM fact_payment LIMIT 999")

    assert kept.limit_action == "kept"
    assert "LIMIT 25" in kept.sql
    assert capped.limit_action == "capped"
    assert "LIMIT 500" in capped.sql
    assert "999" not in capped.sql


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT amount FROM fact_payment LIMIT 0",
        "SELECT amount FROM fact_payment LIMIT ?",
    ],
)
def test_rejects_non_positive_or_dynamic_limit(sql):
    assert_policy_error(sql, "INVALID_LIMIT", correctable=False)


def test_expands_projection_star_but_preserves_count_star():
    projection = GUARD.validate("SELECT * FROM dim_game")
    aggregate = GUARD.validate("SELECT COUNT(*) FROM dim_game")

    projection_ast = sqlglot.parse_one(projection.sql, read="mysql")
    assert not any(isinstance(item, exp.Star) for item in projection_ast.expressions)
    assert "game_id" in projection.sql
    assert "game_name" in projection.sql
    assert "COUNT(*)" in aggregate.sql


def test_validates_alias_and_cte_scopes_against_physical_tables():
    result = GUARD.validate(
        "WITH totals AS ("
        "SELECT game_id, SUM(amount) AS revenue FROM fact_payment GROUP BY game_id"
        ") SELECT g.game_name, t.revenue FROM totals t "
        "JOIN dim_game g ON g.game_id=t.game_id"
    )

    assert result.tables == ("dim_game", "fact_payment")
    assert "totals" not in result.tables
    assert "LIMIT 500" in result.sql


@pytest.mark.parametrize(
    ("sql", "code", "correctable"),
    [
        ("DELETE FROM fact_payment", "READ_ONLY_QUERY_REQUIRED", False),
        ("SELECT * FROM mysql.user", "SYSTEM_OBJECT_DENIED", False),
        ("SELECT amount FROM dw.fact_payment", "SYSTEM_OBJECT_DENIED", False),
        ("SELECT secret_token FROM dim_player", "UNKNOWN_COLUMN", True),
        ("SELECT amount FROM fact_payments", "UNKNOWN_TABLE", True),
        ("SELECT (", "SQL_PARSE_ERROR", True),
        (
            "SELECT * FROM dim_player; SELECT * FROM dim_game",
            "MULTI_STATEMENT_DENIED",
            False,
        ),
        ("SELECT SLEEP(10) FROM dim_game", "DANGEROUS_FUNCTION_DENIED", False),
        ("SELECT * FROM dim_game FOR UPDATE", "LOCKING_QUERY_DENIED", False),
    ],
)
def test_rejects_unsafe_or_unknown_sql(sql, code, correctable):
    assert_policy_error(sql, code, correctable=correctable)


def test_unknown_column_inside_cte_is_correctable():
    assert_policy_error(
        "WITH totals AS (SELECT SUM(ammount) AS total FROM fact_payment) "
        "SELECT total FROM totals",
        "UNKNOWN_COLUMN",
        correctable=True,
    )


def test_union_remains_single_read_only_statement():
    result = GUARD.validate(
        "SELECT game_id FROM fact_payment UNION SELECT game_id FROM fact_player_daily"
    )

    assert result.tables == ("fact_payment", "fact_player_daily")
    assert result.sql.count("MAX_EXECUTION_TIME(5000)") == 1
    assert result.sql.endswith("LIMIT 500")
