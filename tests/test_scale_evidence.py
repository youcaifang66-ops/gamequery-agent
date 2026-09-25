import json
from pathlib import Path

from eval.player_audit_report import validate_player_audit_report
from eval.scale_report import validate_scale_report

RESULTS = Path(__file__).parents[1] / "eval" / "results"


def _load(filename):
    return json.loads((RESULTS / filename).read_text(encoding="utf-8"))


def test_ten_million_generation_evidence_is_independently_validated():
    report = _load("ten_million_generation.json")

    assert report["status"] == "measured"
    assert report["dataset"]["fact_rows"] == 10_000_000
    assert report["metrics"]["peak_rss_bytes"] <= 1024**3
    assert report["scope"] == {
        "synthetic": True,
        "extrapolated": False,
        "max_claimed_rows": 10_000_000,
    }
    assert all(
        value is True
        for key, value in report["validation"].items()
        if key != "mode"
    )


def test_ten_million_import_evidence_matches_every_table_and_ground_truth():
    report = _load("ten_million_import.json")

    assert report["status"] == "measured"
    assert report["dataset"]["fact_rows"] == 10_000_000
    assert report["metrics"]["ground_truth_passed"] is True
    assert all(
        table["expected_rows"] == table["imported_rows"]
        for table in report["metrics"]["tables"].values()
    )
    fact_tables = {
        key: value
        for key, value in report["metrics"]["tables"].items()
        if key.startswith("fact_")
    }
    assert sum(table["imported_rows"] for table in fact_tables.values()) == 10_000_000
    refreshed = report["metrics"]["post_import_statistics_refresh"]
    assert refreshed["status"] == "measured"
    for table_name in fact_tables:
        assert refreshed["tables"][table_name]["estimated_rows"] > 0
        assert refreshed["tables"][table_name]["index_bytes"] > 0


def test_ten_million_benchmark_keeps_all_raw_samples_and_plans():
    report = _load("ten_million_db_benchmark.json")
    validate_scale_report(report)

    runs = report["metrics"]["concurrency_runs"]
    assert [run["concurrency"] for run in runs] == [1, 5, 10, 20]
    assert all(len(run["queries"]) == 6 for run in runs)
    for run in runs:
        for query in run["queries"].values():
            assert query["sample_count"] == len(query["samples_ms"]) == 30
            assert query["success_rate"] == 1
            assert query["timeout_count"] == 0
            assert query["error_count"] == 0
            assert query["result_match"] is True
            assert query["plan"]


def test_schema_optimization_evidence_is_final_idempotent_and_costed():
    initial = _load("ten_million_schema_optimization_initial.json")
    selective = _load("ten_million_schema_optimization_v2.json")
    final = _load("ten_million_schema_optimization.json")

    assert initial["status"] == selective["status"] == final["status"] == "measured"
    assert len(initial["executed"]) == 5
    assert [item["index"] for item in selective["executed"]] == [
        "idx_level_game_level_date_pass_attempts"
    ]
    assert final["migration_version"] == "2026-09-26.5"
    assert final["executed"] == []
    assert all(step["status"] == "already_present" for step in final["plan"])
    assert all(
        row[3] == "OK" for row in initial["metrics"]["analyze_results"]
    )

    before_bytes = sum(
        table["index_bytes"]
        for table in initial["before"]["table_statistics"].values()
    )
    after_bytes = sum(
        table["index_bytes"]
        for table in final["after"]["table_statistics"].values()
    )
    assert after_bytes > before_bytes


def test_player_audit_evidence_is_indexed_exact_and_within_gates():
    report = _load("ten_million_player_audit.json")
    validate_player_audit_report(report)

    assert report["dataset"]["fact_rows"] == 10_000_000
    for run in report["metrics"]["concurrency_runs"]:
        for query_id, query in run["queries"].items():
            assert query["sample_count"] == len(query["samples_ms"]) == 30
            assert query["error_count"] == query["timeout_count"] == 0
            if "timeline" in query_id:
                assert "index lookup" in query["explain_analyze"].lower()


def test_paired_operational_benchmark_passes_regression_gates():
    before = _load("ten_million_db_benchmark_before_v2.json")
    after = _load("ten_million_db_benchmark_optimized.json")
    validate_scale_report(before)
    validate_scale_report(after)

    before_runs = {
        run["concurrency"]: run for run in before["metrics"]["concurrency_runs"]
    }
    for run in after["metrics"]["concurrency_runs"]:
        concurrency = run["concurrency"]
        for query_id, query in run["queries"].items():
            baseline = before_runs[concurrency]["queries"][query_id]["p95_ms"]
            limit = baseline * 1.2
            if query_id == "revenue_september_by_game":
                limit = 175 if concurrency == 1 else 500
            assert query["p95_ms"] <= limit, (concurrency, query_id)
            assert query["result_match"] is True
            assert query["error_count"] == query["timeout_count"] == 0
