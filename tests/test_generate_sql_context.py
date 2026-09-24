from app.agent.nodes.generate_sql import (
    _compile_governed_metric_sql,
    _enrich_metric_infos,
)


def test_level_pass_rate_context_contains_versioned_formula():
    context = _enrich_metric_infos(
        "统计关卡通过率",
        [
            {
                "name": "LevelPassRate",
                "description": "指定关卡通过率",
                "relevant_columns": [
                    "fact_level_event.passed",
                    "fact_level_event.attempts",
                ],
                "alias": ["关卡通过率"],
            }
        ],
    )

    assert context[0]["formula"] == (
        "SUM(f.passed) / NULLIF(SUM(f.attempts), 0)"
    )
    assert context[0]["source_table"] == "fact_level_event"


def test_level_pass_rate_uses_governed_formula_instead_of_event_count():
    sql = _compile_governed_metric_sql(
        "统计 LEVEL_005 与 LEVEL_007 的关卡通过率",
        [{"name": "LevelPassRate"}],
    )

    assert sql is not None
    assert "SUM(passed) / NULLIF(SUM(attempts), 0)" in sql
    assert "'LEVEL_005', 'LEVEL_007'" in sql
    assert "COUNT(" not in sql
