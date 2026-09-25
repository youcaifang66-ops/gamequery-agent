from copy import deepcopy

import pytest

from eval.player_audit_report import (
    PlayerAuditReportError,
    validate_player_audit_report,
)
from eval.run_player_audit_benchmark import (
    build_player_audit_cases,
    validate_workload,
)


def _query_metrics(p95_ms):
    return {
        "samples_ms": [p95_ms] * 30,
        "sample_count": 30,
        "p50_ms": p95_ms,
        "p95_ms": p95_ms,
        "p99_ms": p95_ms,
        "max_ms": p95_ms,
        "timeout_count": 0,
        "error_count": 0,
        "result_mismatch_count": 0,
        "result_match": True,
        "result_row_count": 2,
        "result_sha256": "abc123",
        "explain_analyze": "-> Index lookup using idx_daily_player_date",
    }


def _report():
    cases = build_player_audit_cases("P0000001", "P_NOT_FOUND")
    return {
        "schema_version": "1.0",
        "status": "measured",
        "dataset": {"fact_rows": 10_000_000},
        "metrics": {
            "workload": {"warmups_per_query": 3, "iterations_per_query": 30},
            "concurrency_runs": [
                {
                    "concurrency": concurrency,
                    "queries": {
                        case["id"]: _query_metrics(20 if concurrency == 1 else 80)
                        for case in cases
                    },
                }
                for concurrency in (1, 20)
            ],
        },
        "scope": {
            "synthetic": True,
            "extrapolated": False,
            "max_claimed_rows": 10_000_000,
        },
        "failure": None,
    }


def test_player_audit_cases_are_isolated_by_domain_and_cover_missing_player():
    cases = build_player_audit_cases("P0000001", "P_NOT_FOUND")

    assert {case["id"] for case in cases} == {
        "player_profile",
        "player_activity_timeline",
        "player_payment_timeline",
        "player_level_timeline",
        "missing_player_activity_timeline",
        "missing_player_payment_timeline",
        "missing_player_level_timeline",
    }
    for case in cases:
        fact_tables = [
            table
            for table in (
                "fact_player_daily",
                "fact_payment",
                "fact_level_event",
            )
            if table in case["sql"]
        ]
        assert len(fact_tables) <= 1
        assert " JOIN " not in case["sql"].upper()
        assert case["params"]["player_id"]


def test_workload_requires_contract_minimums():
    validate_workload((1, 20), iterations=30, warmups=3, timeout_seconds=1)

    with pytest.raises(PlayerAuditReportError, match="INVALID_WORKLOAD"):
        validate_workload((1,), iterations=30, warmups=3, timeout_seconds=1)
    with pytest.raises(PlayerAuditReportError, match="INVALID_WORKLOAD"):
        validate_workload((1, 20), iterations=29, warmups=3, timeout_seconds=1)
    with pytest.raises(PlayerAuditReportError, match="INVALID_WORKLOAD"):
        validate_workload((1, 20), iterations=30, warmups=2, timeout_seconds=1)


def test_report_accepts_complete_samples_and_performance_gates():
    validate_player_audit_report(_report())


@pytest.mark.parametrize(
    ("concurrency", "p95_ms", "message"),
    [(1, 50.001, "PLAYER_P95_GATE_FAILED"), (20, 200.001, "PLAYER_P95_GATE_FAILED")],
)
def test_report_rejects_player_fact_latency_regression(concurrency, p95_ms, message):
    report = _report()
    run = next(
        item
        for item in report["metrics"]["concurrency_runs"]
        if item["concurrency"] == concurrency
    )
    run["queries"]["player_activity_timeline"] = _query_metrics(p95_ms)

    with pytest.raises(PlayerAuditReportError, match=message):
        validate_player_audit_report(report)


def test_report_rejects_missing_player_rows_and_full_table_scan():
    report = _report()
    report["metrics"]["concurrency_runs"][0]["queries"][
        "missing_player_payment_timeline"
    ]["result_row_count"] = 1
    with pytest.raises(PlayerAuditReportError, match="MISSING_PLAYER_RESULT"):
        validate_player_audit_report(report)

    report = _report()
    query = report["metrics"]["concurrency_runs"][0]["queries"]
    query["player_level_timeline"]["explain_analyze"] = "-> Table scan"
    with pytest.raises(PlayerAuditReportError, match="FULL_SCAN_DETECTED"):
        validate_player_audit_report(report)


def test_report_rejects_partial_or_failed_measurements():
    report = _report()
    broken = deepcopy(report)
    broken["metrics"]["concurrency_runs"][0]["queries"][
        "player_activity_timeline"
    ]["samples_ms"].pop()
    with pytest.raises(PlayerAuditReportError, match="SAMPLE_COUNT_MISMATCH"):
        validate_player_audit_report(broken)

    failed = deepcopy(report)
    failed["metrics"]["concurrency_runs"][0]["queries"][
        "player_activity_timeline"
    ]["error_count"] = 1
    with pytest.raises(PlayerAuditReportError, match="QUERY_FAILURE"):
        validate_player_audit_report(failed)
