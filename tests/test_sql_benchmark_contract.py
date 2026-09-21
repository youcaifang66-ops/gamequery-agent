import json
from pathlib import Path


def test_benchmark_has_valid_repairable_and_unsafe_cases():
    payload = json.loads(
        (Path(__file__).resolve().parents[1] / "eval" / "sql_benchmark.json").read_text(
            encoding="utf-8"
        )
    )
    assert len(payload["valid"]) == 12
    assert len(payload["repairable"]) == 4
    assert len(payload["unsafe"]) == 4
