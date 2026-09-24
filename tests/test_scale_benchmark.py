import pytest

from eval.scale_report import nearest_rank, summarize_samples, validate_scale_report


def test_nearest_rank_percentiles_are_reproducible():
    samples = [100.0, 1.0, 50.0, 20.0, 10.0]

    assert nearest_rank(samples, 0.50) == 20.0
    assert nearest_rank(samples, 0.95) == 100.0
    assert nearest_rank(samples, 0.99) == 100.0


def test_empty_and_partial_samples_keep_unavailable_metrics_null():
    empty = summarize_samples([], attempts=4, timeouts=4)
    assert empty["sample_count"] == 0
    assert empty["success_rate"] == 0
    assert empty["p50_ms"] is None
    assert empty["p95_ms"] is None
    assert empty["p99_ms"] is None
    assert empty["max_ms"] is None
    assert empty["timeout_rate"] == 1

    partial = summarize_samples([5.0, 10.0, 15.0], attempts=4, timeouts=1)
    assert partial["success_rate"] == 0.75
    assert partial["timeout_rate"] == 0.25
    assert partial["p50_ms"] == 10.0


def test_failed_or_not_run_reports_cannot_claim_database_capacity():
    report = {
        "status": "not_run",
        "dataset": {"fact_rows": 10_000_000},
        "metrics": {},
        "failure": {"code": "DATABASE_UNAVAILABLE", "message": "not available"},
        "scope": {
            "synthetic": True,
            "extrapolated": False,
            "max_claimed_rows": 0,
        },
    }
    validate_scale_report(report)

    report["scope"]["max_claimed_rows"] = 10_000_000
    with pytest.raises(ValueError, match="unmeasured database capacity"):
        validate_scale_report(report)


def test_measured_report_requires_raw_samples_and_result_match():
    report = {
        "status": "measured",
        "dataset": {"fact_rows": 1_000},
        "metrics": {
            "concurrency_runs": [
                {
                    "concurrency": 1,
                    "queries": {
                        "dau_campaign_game": {
                            "samples_ms": [1.2] * 30,
                            "sample_count": 30,
                            "result_match": True,
                        }
                    },
                }
            ]
        },
        "failure": None,
        "scope": {
            "synthetic": True,
            "extrapolated": False,
            "max_claimed_rows": 1_000,
        },
    }
    validate_scale_report(report)

    report["metrics"]["concurrency_runs"][0]["queries"]["dau_campaign_game"][
        "result_match"
    ] = False
    with pytest.raises(ValueError, match="result mismatch"):
        validate_scale_report(report)
