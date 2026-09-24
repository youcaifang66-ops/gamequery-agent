import csv
import json
from pathlib import Path

import pytest

from eval.generate_scale_data import DEFAULT_SEED, PRESET_ROWS, generate
from eval.load_report import (
    REQUIRED_METADATA,
    REQUIRED_METRICS,
    SSE_QUERIES,
    validate_report,
)


def read_ids(path: Path, column: str) -> set[str]:
    with path.open(encoding="utf-8", newline="") as handle:
        return {row[column] for row in csv.DictReader(handle)}


def test_presets_include_smoke_one_hundred_thousand_and_one_million():
    assert PRESET_ROWS == {"smoke": 1_000, "100k": 100_000, "1m": 1_000_000}


def test_generator_is_deterministic_and_fact_count_is_exact(tmp_path):
    first = generate(tmp_path / "first", rows=1_000, seed=DEFAULT_SEED)
    second = generate(tmp_path / "second", rows=1_000, seed=DEFAULT_SEED)

    assert first == second
    assert first["actual_fact_rows"] == first["requested_fact_rows"] == 1_000
    fact_files = [name for name in first["files"] if name.startswith("fact_")]
    assert sum(first["files"][name]["rows"] for name in fact_files) == 1_000


def test_generated_fact_foreign_keys_reference_dimensions(tmp_path):
    output = tmp_path / "dataset"
    generate(output, rows=1_000)
    players = read_ids(output / "dim_player.csv", "player_id")
    games = read_ids(output / "dim_game.csv", "game_id")
    dates = read_ids(output / "dim_date.csv", "date_id")

    for filename in (
        "fact_player_daily.csv",
        "fact_payment.csv",
        "fact_level_event.csv",
    ):
        with (output / filename).open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                assert row["player_id"] in players
                assert row["game_id"] in games
                assert row["date_id"] in dates


def valid_report():
    return {
        "metadata": {
            field: (
                1000
                if field == "row_count"
                else 10
                if field == "concurrency"
                else 1.0
                if field in {"spawn_rate", "duration_seconds", "warmup_seconds"}
                else "recorded"
            )
            for field in REQUIRED_METADATA
        },
        "metrics": {
            "request_count": 100,
            "success_rate": 0.99,
            "throughput_rps": 5.0,
            "p50_ms": 100,
            "p95_ms": 200,
            "p99_ms": 300,
            "timeout_rate": 0.01,
            "error_code_counts": {"QUERY_TIMEOUT": 1},
            "slowest_query_names": ["monthly_revenue"],
        },
        "scope": {
            "extrapolated": False,
            "max_claimed_rows": 1000,
            "statement": "Results apply only to the recorded row_count.",
        },
    }


def test_report_contract_rejects_scale_extrapolation():
    report = valid_report()
    validate_report(report)
    report["scope"]["max_claimed_rows"] = 1_000_000
    with pytest.raises(ValueError, match="claimed scale"):
        validate_report(report)


def test_json_schema_and_locust_scenarios_cover_required_contract():
    schema = json.loads(
        (Path(__file__).parents[1] / "eval" / "load_report.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert schema["properties"]["scope"]["properties"]["extrapolated"]["const"] is False
    assert set(SSE_QUERIES) == {
        "dau_by_game",
        "monthly_revenue",
        "level_pass_rate",
    }
    assert set(schema["properties"]["metadata"]["required"]) == REQUIRED_METADATA
    assert set(schema["properties"]["metrics"]["required"]) == REQUIRED_METRICS
