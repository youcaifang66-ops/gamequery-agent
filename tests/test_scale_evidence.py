import json
from pathlib import Path

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
