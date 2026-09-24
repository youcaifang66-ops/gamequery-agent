from __future__ import annotations

import math
from typing import Sequence


def nearest_rank(samples: Sequence[float], percentile: float) -> float | None:
    if not samples:
        return None
    if not 0 < percentile <= 1:
        raise ValueError("percentile must be in (0, 1]")
    ordered = sorted(samples)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return round(ordered[index], 6)


def summarize_samples(
    samples: Sequence[float], *, attempts: int, timeouts: int
) -> dict:
    if attempts < len(samples) or attempts < timeouts:
        raise ValueError("attempt counts are inconsistent")
    return {
        "samples_ms": [round(sample, 6) for sample in samples],
        "sample_count": len(samples),
        "success_rate": round(len(samples) / attempts, 6) if attempts else 0,
        "p50_ms": nearest_rank(samples, 0.50),
        "p95_ms": nearest_rank(samples, 0.95),
        "p99_ms": nearest_rank(samples, 0.99),
        "max_ms": round(max(samples), 6) if samples else None,
        "timeout_count": timeouts,
        "timeout_rate": round(timeouts / attempts, 6) if attempts else 0,
    }


def validate_scale_report(report: dict) -> None:
    status = report.get("status")
    if status not in {"measured", "failed", "not_run"}:
        raise ValueError("invalid report status")
    scope = report.get("scope", {})
    if scope.get("extrapolated") is not False:
        raise ValueError("scale reports cannot extrapolate")
    claimed = scope.get("max_claimed_rows", 0)
    fact_rows = report.get("dataset", {}).get("fact_rows", 0)
    if claimed > fact_rows:
        raise ValueError("claimed scale exceeds dataset")
    if status != "measured":
        if claimed != 0:
            raise ValueError("unmeasured database capacity must claim zero rows")
        if not report.get("failure"):
            raise ValueError("failed/not_run report needs a reason")
        return
    runs = report.get("metrics", {}).get("concurrency_runs", [])
    if not runs:
        raise ValueError("measured report needs concurrency runs")
    for run in runs:
        for query_id, query in run.get("queries", {}).items():
            if query.get("sample_count") != len(query.get("samples_ms", [])):
                raise ValueError(f"sample count mismatch: {query_id}")
            if query.get("result_match") is not True:
                raise ValueError(f"result mismatch: {query_id}")
