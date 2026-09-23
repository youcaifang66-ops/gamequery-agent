# Contract: Evaluation and CI

## SQL Evaluation Output

```json
{
  "mode": "static_fixture",
  "dataset_size": 20,
  "guard_accuracy": 1.0,
  "first_pass_fixture_rate": 0.75,
  "preset_repair_execution_accuracy": 1.0,
  "agent_correction_accuracy": null,
  "agent_correction_status": "not_run",
  "guard_latency_p95_ms": 0.0
}
```

- `preset_repair_execution_accuracy` only measures curated repaired SQL.
- `agent_correction_accuracy` is null unless the graph actually generated corrections for every repair case.
- Every report records mode, dataset version/hash and timestamp.

## Retrieval Evaluation Output

```json
{
  "mode": "fixture",
  "dataset_size": 30,
  "channels": {"dense":{"hit_at_5":0.0,"mrr":0.0}},
  "fused": {"hit_at_5":0.0,"mrr":0.0,"no_match_false_positive_rate":0.0},
  "ablation": {"fusion_delta_hit_at_5":0.0},
  "cases": []
}
```

## Load Report Output

Required metadata: git SHA, timestamp, OS, CPU, memory, Python/MySQL/Qdrant versions, row count, index description, concurrency, spawn rate, duration and warm-up.

Required metrics: request count, success rate, throughput, p50/p95/p99, timeout rate, error-code counts and slowest query names.

No report may claim a scale larger than its recorded row count.

## CI Gates

1. Dependency install from lock.
2. Ruff over `app`, `tests`, and `eval` Python files.
3. Full pytest suite with no real network/LLM dependency.
4. Static SQL evaluator and metric contract assertion.
5. Fixture retrieval evaluator and dataset/metric contract assertion.
6. Frontend frozen install and build.

Optional Docker/live/load jobs are explicitly labeled and never counted as passed when skipped.
