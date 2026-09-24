# Contract: Experiment Database Import

## CLI

```text
python eval/import_scale_data.py \
  --dataset PATH --database NAME --batch-size 10000 [--replace]
```

Connection settings come only from `SCALE_DB_HOST`, `SCALE_DB_PORT`, `SCALE_DB_USER`, and `SCALE_DB_PASSWORD`.

## Preconditions

1. Dataset validation PASS occurs before opening a database connection.
2. Database name matches `gamequery_scale_[a-z0-9_]+`.
3. Reserved/default schemas are always rejected.
4. Username must not equal configured DW reader username.
5. Existing experiment schema requires `--replace`.

## Behavior

- Create isolated schema from `eval/sql/scale_schema.sql`.
- Import dimensions before facts in bounded batches.
- Create secondary indexes after fact import.
- Compare all table counts and six ground-truth queries.
- Write `import_report.json` for measured, failed or not_run outcomes without credentials.

## Stable Errors

| Code | Condition |
|---|---|
| INVALID_DATABASE_NAME | database is not an experiment name |
| READ_ONLY_CREDENTIALS | online reader credentials selected |
| DATASET_INTEGRITY_FAILED | validator did not pass |
| DATABASE_UNAVAILABLE | connection cannot be established |
| IMPORT_FAILED | a batch or index step fails |
| RESULT_MISMATCH | count or standard answer differs |

## AC Coverage

AC-08, AC-09, AC-12, AC-E2.
