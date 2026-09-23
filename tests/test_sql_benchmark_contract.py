import json
import re
from pathlib import Path

from eval.run_sql_eval import evaluate


def test_benchmark_has_valid_repairable_and_unsafe_cases():
    payload = json.loads(
        (Path(__file__).resolve().parents[1] / "eval" / "sql_benchmark.json").read_text(
            encoding="utf-8"
        )
    )
    assert len(payload["valid"]) == 12
    assert len(payload["repairable"]) == 4
    assert len(payload["unsafe"]) == 4


def test_static_report_separates_presets_from_agent_corrections():
    report = evaluate()

    assert report["mode"] == "static_fixture"
    assert report["dataset_version"] == "1.0"
    assert re.fullmatch(r"[0-9a-f]{64}", report["dataset_sha256"])
    assert report["generated_at"].endswith("+00:00")
    assert report["first_pass_fixture_rate"] == 0.75
    assert report["preset_repair_execution_accuracy"] == 1.0
    assert report["agent_correction_accuracy"] is None
    assert report["agent_correction_status"] == "not_run"
    assert "success_after_correction" not in report
    assert "first_pass_success" not in report


def test_committed_metrics_follow_truthful_contract():
    report = json.loads(
        (Path(__file__).resolve().parents[1] / "eval" / "latest_metrics.json").read_text(
            encoding="utf-8"
        )
    )

    assert report["mode"] == "static_fixture"
    assert report["agent_correction_accuracy"] is None
    assert report["agent_correction_status"] == "not_run"
