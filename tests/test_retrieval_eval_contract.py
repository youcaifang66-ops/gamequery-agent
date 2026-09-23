import json
import re
from pathlib import Path

import pytest

from eval.run_retrieval_eval import CHANNELS, evaluate

ROOT = Path(__file__).resolve().parents[1]


def test_golden_set_has_required_size_categories_and_types():
    dataset = json.loads(
        (ROOT / "eval" / "retrieval_benchmark.json").read_text(encoding="utf-8")
    )
    cases = dataset["cases"]

    assert len(cases) >= 30
    assert len({case["id"] for case in cases}) == len(cases)
    assert {"name", "alias", "semantic", "value", "no_match"} <= {
        case["category"] for case in cases
    }
    assert {"column", "metric", "value"} <= {
        case["entity_type"] for case in cases
    }
    assert sum(not case["expected_ids"] for case in cases) >= 5


def test_fixture_report_has_channels_fusion_ablation_and_sample_evidence():
    report = evaluate("fixture")

    assert report["mode"] == "fixture"
    assert report["dataset_size"] >= 30
    assert re.fullmatch(r"[0-9a-f]{64}", report["dataset_sha256"])
    assert set(report["channels"]) == set(CHANNELS)
    for metrics in [*report["channels"].values(), report["fused"]]:
        assert set(metrics) == {"hit_at_5", "mrr", "no_match_false_positive_rate"}
        assert all(0 <= value <= 1 for value in metrics.values())
    assert report["ablation"]["baseline"] == "dense_only"
    assert "fusion_delta_hit_at_5" in report["ablation"]
    assert len(report["cases"]) == report["dataset_size"]
    assert all("evidence" in case for case in report["cases"])
    value_cases = [case for case in report["cases"] if case["entity_type"] == "value"]
    assert value_cases and all(not case["fusion_applied"] for case in value_cases)


def test_fixture_cannot_be_relabelled_as_live():
    with pytest.raises(RuntimeError, match="live mode requires"):
        evaluate("live")


def test_committed_retrieval_report_is_explicitly_fixture():
    report = json.loads(
        (ROOT / "eval" / "latest_retrieval_metrics.json").read_text(encoding="utf-8")
    )
    assert report["mode"] == "fixture"
    assert report["dataset_size"] >= 30
