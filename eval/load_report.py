from typing import Any

SSE_QUERIES = {
    "dau_by_game": "统计2026年9月18日各游戏DAU",
    "monthly_revenue": "查询2026年9月各游戏总收入",
    "level_pass_rate": "统计2026年9月LEVEL_05关卡通关率",
}

REQUIRED_METADATA = {
    "git_sha",
    "timestamp",
    "os",
    "cpu",
    "memory",
    "python_version",
    "mysql_version",
    "qdrant_version",
    "row_count",
    "index_description",
    "concurrency",
    "spawn_rate",
    "duration_seconds",
    "warmup_seconds",
}
REQUIRED_METRICS = {
    "request_count",
    "success_rate",
    "throughput_rps",
    "p50_ms",
    "p95_ms",
    "p99_ms",
    "timeout_rate",
    "error_code_counts",
    "slowest_query_names",
}


def validate_report(report: dict[str, Any]) -> None:
    if set(report.get("metadata", {})) != REQUIRED_METADATA:
        raise ValueError("load report metadata fields do not match contract")
    if set(report.get("metrics", {})) != REQUIRED_METRICS:
        raise ValueError("load report metric fields do not match contract")
    scope = report.get("scope", {})
    if scope.get("extrapolated") is not False:
        raise ValueError("load report must not extrapolate")
    if scope.get("max_claimed_rows") != report["metadata"]["row_count"]:
        raise ValueError("claimed scale must equal measured row count")
    for field in ("success_rate", "timeout_rate"):
        if not 0 <= report["metrics"][field] <= 1:
            raise ValueError(f"{field} must be between 0 and 1")
