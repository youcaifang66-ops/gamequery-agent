import json
from pathlib import Path

import pytest

from eval.generate_scale_data import DEFAULT_SEED, PRESET_ROWS, generate

FACT_FILES = {
    "fact_player_daily.csv",
    "fact_payment.csv",
    "fact_level_event.csv",
}


def test_presets_include_actual_ten_million_rows():
    assert PRESET_ROWS["10m"] == 10_000_000


def test_generator_rejects_invalid_and_unsafe_outputs(tmp_path):
    with pytest.raises(ValueError, match="INVALID_ROW_COUNT"):
        generate(tmp_path / "invalid", rows=0)

    repository_root = Path(__file__).parents[1]
    with pytest.raises(ValueError, match="UNSAFE_OUTPUT_PATH"):
        generate(repository_root, rows=10)

    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "keep.txt").write_text("user data", encoding="utf-8")
    with pytest.raises(ValueError, match="OUTPUT_NOT_EMPTY"):
        generate(occupied, rows=10)
    assert (occupied / "keep.txt").read_text(encoding="utf-8") == "user data"


def test_generator_is_deterministic_but_seed_sensitive(tmp_path):
    first = generate(tmp_path / "first", rows=2_000, seed=DEFAULT_SEED)
    second = generate(tmp_path / "second", rows=2_000, seed=DEFAULT_SEED)
    different = generate(tmp_path / "different", rows=2_000, seed=DEFAULT_SEED + 1)

    for filename in FACT_FILES | {"ground_truth.json"}:
        assert first["files"][filename]["sha256"] == second["files"][filename]["sha256"]
    assert any(
        first["files"][filename]["sha256"] != different["files"][filename]["sha256"]
        for filename in FACT_FILES
    )


def test_manifest_has_exact_counts_business_shape_and_provenance(tmp_path):
    manifest = generate(tmp_path / "dataset", rows=5_000, seed=DEFAULT_SEED)

    assert manifest["synthetic"] is True
    assert manifest["actual_fact_rows"] == manifest["requested_fact_rows"] == 5_000
    assert sum(manifest["files"][name]["rows"] for name in FACT_FILES) == 5_000
    assert manifest["provenance"]
    assert all(
        "url" in source and "usage" in source for source in manifest["provenance"]
    )

    stats = manifest["business_statistics"]
    assert stats["long_tail_top_game_share"] >= 0.35
    assert stats["weekend_activity_lift"] >= 1.05
    assert stats["campaign_activity_lift"] >= 1.20
    assert stats["payment_mean"] > stats["payment_median"]
    assert stats["level_passed_rows"] > 0
    assert stats["level_failed_rows"] > 0

    profile = manifest["profile"]
    assert profile["campaign_date_id"] == 20260918
    assert profile["date_count"] == 365


def test_ground_truth_has_six_executable_answer_categories(tmp_path):
    output = tmp_path / "dataset"
    manifest = generate(output, rows=5_000, seed=DEFAULT_SEED)
    ledger = json.loads((output / "ground_truth.json").read_text(encoding="utf-8"))

    assert manifest["files"]["ground_truth.json"]["rows"] == 6
    assert {case["category"] for case in ledger["cases"]} == {
        "dau",
        "revenue",
        "payer_count",
        "arpu",
        "pass_rate",
        "channel_split",
    }
    for case in ledger["cases"]:
        assert case["question"]
        assert case["sql"].lstrip().upper().startswith("SELECT")
        assert case["params"]
        assert case["columns"]
        assert isinstance(case["expected_rows"], list)


def test_generation_report_records_measured_resource_scope(tmp_path):
    output = tmp_path / "dataset"
    generate(output, rows=1_000, seed=DEFAULT_SEED)
    report = json.loads((output / "generation_report.json").read_text(encoding="utf-8"))

    assert report["status"] == "measured"
    assert report["dataset"]["fact_rows"] == 1_000
    assert report["metrics"]["elapsed_seconds"] > 0
    assert report["metrics"]["peak_rss_bytes"] > 0
    assert report["metrics"]["output_bytes"] > 0
    assert report["scope"] == {
        "synthetic": True,
        "extrapolated": False,
        "max_claimed_rows": 1_000,
    }
