# Contract: Synthetic Dataset

## CLI

```text
python eval/generate_scale_data.py --preset smoke|100k|1m|10m --seed INT --output PATH
python eval/validate_scale_data.py --dataset PATH [--full-scan]
```

Generation exits 0 only after `manifest.json`, `ground_truth.json`, all CSV files and `generation_report.json` are atomically present. Validation exits 0 only with status `measured` and all checks passed.

## Files

Required exact set:

- `dim_player.csv`
- `dim_game.csv`
- `dim_date.csv`
- `fact_player_daily.csv`
- `fact_payment.csv`
- `fact_level_event.csv`
- `ground_truth.json`
- `manifest.json`
- `generation_report.json`

CSV encoding is UTF-8, newline is LF, header is included, and field order matches `docker/mysql/dw.sql`.

## Safety

- `rows <= 0`: `INVALID_ROW_COUNT` before output files.
- output resolves to repository root: `UNSAFE_OUTPUT_PATH` before output files.
- existing non-empty output: `OUTPUT_NOT_EMPTY` unless explicit `--replace`.
- checksum or row mismatch: `DATASET_INTEGRITY_FAILED`, names the file.
- large data files are ignored by Git.

## AC Coverage

AC-01~07, AC-12~15, AC-E1~E2.
