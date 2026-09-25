import pytest

from eval.optimize_scale_database import (
    SchemaOptimizationError,
    build_migration_plan,
    validate_optimization_target,
)
from eval.schema_optimization import index_catalog


def _existing_catalog():
    existing = {}
    for item in index_catalog():
        existing.setdefault(item.table, {})[item.name] = item.columns
    return existing


def test_empty_schema_plan_creates_every_catalog_index_without_mutating_input():
    existing = {}

    plan = build_migration_plan(existing)

    assert existing == {}
    assert len(plan) == len(index_catalog())
    assert {step["status"] for step in plan} == {"planned"}
    assert all("ALGORITHM=INPLACE" in step["sql"] for step in plan)
    assert all(step["rollback_sql"].startswith("DROP INDEX") for step in plan)


def test_existing_exact_indexes_make_the_plan_idempotent():
    plan = build_migration_plan(_existing_catalog())

    assert len(plan) == len(index_catalog())
    assert {step["status"] for step in plan} == {"already_present"}
    assert all(step["sql"] is None for step in plan)


def test_same_name_with_different_columns_is_a_stable_conflict():
    existing = _existing_catalog()
    existing["fact_payment"]["idx_payment_player_date"] = (
        "date_id",
        "player_id",
    )

    with pytest.raises(
        SchemaOptimizationError, match="INDEX_DEFINITION_CONFLICT"
    ):
        build_migration_plan(existing)


@pytest.mark.parametrize("database", ["dw", "mysql", "gamequery_scale_bad-name"])
def test_optimizer_rejects_default_system_and_invalid_databases(database):
    with pytest.raises(SchemaOptimizationError, match="INVALID_DATABASE_NAME"):
        validate_optimization_target(database, username="root")


def test_optimizer_rejects_online_reader_credentials():
    with pytest.raises(SchemaOptimizationError, match="READ_ONLY_CREDENTIALS"):
        validate_optimization_target(
            "gamequery_scale_10m",
            username="gamequery_reader",
            reader_username="gamequery_reader",
        )
