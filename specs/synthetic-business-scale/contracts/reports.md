# Contract: Scale Evidence Reports

## Common Envelope

Every report includes:

```json
{
  "schema_version": "1.0",
  "status": "measured | failed | not_run",
  "dataset": {"version": "...", "seed": 1, "fact_rows": 10000000, "manifest_sha256": "..."},
  "environment": {"git_sha": "...", "timestamp": "...", "os": "...", "cpu": "...", "memory_bytes": 1, "python_version": "..."},
  "metrics": {},
  "failure": null,
  "scope": {"synthetic": true, "extrapolated": false, "max_claimed_rows": 10000000}
}
```

For `failed` or `not_run`, unavailable metrics are null/empty and `failure` contains a stable code and sanitized message. `max_claimed_rows` is zero unless that stage measured the dataset at the stated scale.

## Generation Metrics

`elapsed_seconds`, `peak_rss_bytes`, `output_bytes`, `rows_per_second`, `distribution_checks`, `ground_truth_case_count`.

## Import Metrics

Per-table expected/imported rows and elapsed time, index time, total time, throughput, MySQL version, ground-truth comparison.

## Database Benchmark Metrics

- workload: warmup count, iterations per query, concurrency, timeout.
- each case: raw samples, count, success rate, p50/p95/p99/max, timeout count, result match, plan summary.
- aggregate: total queries, throughput, success rate and timeout rate.

Percentiles use nearest-rank over successful measured samples. No samples means percentile fields are null, never zero.

## Truthfulness Invariants

- `extrapolated` is always false.
- `max_claimed_rows <= dataset.fact_rows`.
- database reports use max 0 unless import/benchmark status is measured.
- generated-only evidence cannot populate database latency.
- database-only evidence cannot populate real LLM accuracy or user productivity.

## AC Coverage

AC-03, AC-09~13.
