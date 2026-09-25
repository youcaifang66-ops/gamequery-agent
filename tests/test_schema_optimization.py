from eval.schema_optimization import (
    SCHEMA_OPTIMIZATION_VERSION,
    index_catalog,
    index_statements,
)


def test_index_catalog_covers_player_audit_and_aggregate_workloads():
    catalog = {(item.table, item.name): item.columns for item in index_catalog()}

    assert SCHEMA_OPTIMIZATION_VERSION == "2026-09-26.1"
    assert catalog[("fact_player_daily", "idx_daily_player_date")] == (
        "player_id",
        "date_id",
    )
    assert catalog[("fact_payment", "idx_payment_player_date")] == (
        "player_id",
        "date_id",
    )
    assert catalog[("fact_level_event", "idx_level_player_date")] == (
        "player_id",
        "date_id",
    )
    assert catalog[("fact_payment", "idx_payment_date_game_amount")] == (
        "date_id",
        "game_id",
        "amount",
    )
    assert catalog[
        ("fact_level_event", "idx_level_date_game_level_pass_attempts")
    ] == ("date_id", "game_id", "level_id", "passed", "attempts")


def test_catalog_statements_are_online_and_have_exact_rollbacks():
    catalog = index_catalog()
    statements = index_statements()

    assert len({(item.table, item.name) for item in catalog}) == len(catalog)
    assert len(statements) == len(catalog)
    for item, statement in zip(catalog, statements, strict=True):
        assert statement == item.create_sql
        assert f"CREATE INDEX `{item.name}` ON `{item.table}`" in statement
        assert statement.endswith("ALGORITHM=INPLACE, LOCK=NONE")
        assert item.rollback_sql == f"DROP INDEX `{item.name}` ON `{item.table}`"
