from pathlib import Path

import pytest

from app.security.sql_guard import SQLGuard, SQLGuardError


GUARD = SQLGuard.from_meta_config(Path(__file__).resolve().parents[1] / "conf" / "meta_config.yaml")


def test_allows_read_only_query_and_injects_limit():
    result = GUARD.validate(
        "SELECT game_id, COUNT(DISTINCT player_id) AS dau FROM fact_player_daily "
        "WHERE is_active=1 GROUP BY game_id"
    )
    assert result.limit_applied is True
    assert "LIMIT 500" in result.sql
    assert result.tables == ("fact_player_daily",)


@pytest.mark.parametrize(
    "sql,error",
    [
        ("DELETE FROM fact_payment", "READ_ONLY_QUERY_REQUIRED"),
        ("SELECT * FROM mysql.user", "UNKNOWN_TABLE"),
        ("SELECT secret_token FROM dim_player", "UNKNOWN_COLUMN"),
        ("SELECT * FROM dim_player; SELECT * FROM dim_game", "MULTI_STATEMENT_DENIED"),
    ],
)
def test_rejects_unsafe_or_unknown_sql(sql, error):
    with pytest.raises(SQLGuardError, match=error):
        GUARD.validate(sql)
