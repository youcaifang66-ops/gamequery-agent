from __future__ import annotations

FACT_QUERY_IDS = {
    "player_activity_timeline",
    "player_payment_timeline",
    "player_level_timeline",
    "missing_player_activity_timeline",
    "missing_player_payment_timeline",
    "missing_player_level_timeline",
}
MISSING_QUERY_IDS = {
    "missing_player_activity_timeline",
    "missing_player_payment_timeline",
    "missing_player_level_timeline",
}


class PlayerAuditReportError(ValueError):
    pass


def _fail(code: str, message: str) -> None:
    raise PlayerAuditReportError(f"{code}: {message}")


def validate_player_audit_report(report: dict) -> None:
    if report.get("status") != "measured":
        _fail("UNMEASURED_REPORT", "player audit report must be measured")
    scope = report.get("scope", {})
    if scope.get("extrapolated") is not False:
        _fail("INVALID_SCOPE", "player audit evidence cannot be extrapolated")
    if scope.get("max_claimed_rows") != report.get("dataset", {}).get("fact_rows"):
        _fail("INVALID_SCOPE", "claimed rows must equal measured fact rows")

    runs = report.get("metrics", {}).get("concurrency_runs", [])
    by_concurrency = {run.get("concurrency"): run for run in runs}
    if not {1, 20}.issubset(by_concurrency):
        _fail("INVALID_WORKLOAD", "concurrency runs 1 and 20 are required")

    for concurrency in (1, 20):
        queries = by_concurrency[concurrency].get("queries", {})
        if not FACT_QUERY_IDS.issubset(queries):
            _fail("INVALID_WORKLOAD", "all player fact cases are required")
        for query_id, metrics in queries.items():
            samples = metrics.get("samples_ms", [])
            if metrics.get("sample_count") != len(samples):
                _fail("SAMPLE_COUNT_MISMATCH", query_id)
            if (
                metrics.get("timeout_count") != 0
                or metrics.get("error_count") != 0
                or metrics.get("result_mismatch_count") != 0
                or metrics.get("result_match") is not True
            ):
                _fail("QUERY_FAILURE", query_id)
            if query_id in MISSING_QUERY_IDS and metrics.get("result_row_count") != 0:
                _fail("MISSING_PLAYER_RESULT", query_id)
            if query_id in FACT_QUERY_IDS:
                plan = metrics.get("explain_analyze", "").lower()
                if not plan or "table scan" in plan:
                    _fail("FULL_SCAN_DETECTED", query_id)
                threshold = 50 if concurrency == 1 else 200
                if metrics.get("p95_ms") is None or metrics["p95_ms"] > threshold:
                    _fail(
                        "PLAYER_P95_GATE_FAILED",
                        f"{query_id} C={concurrency} p95={metrics.get('p95_ms')}",
                    )
