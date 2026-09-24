import csv
import hashlib
import json

import pytest

from eval.generate_scale_data import generate
from eval.validate_scale_data import DatasetValidationError, validate_dataset


def _refresh_manifest_file(dataset, filename):
    path = dataset / filename
    manifest_path = dataset / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][filename]["bytes"] = path.stat().st_size
    manifest["files"][filename]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def test_validator_checks_integrity_distribution_and_independent_answers(tmp_path):
    dataset = tmp_path / "dataset"
    generate(dataset, rows=5_000)

    report = validate_dataset(dataset, full_scan=True)

    assert report["status"] == "measured"
    assert report["checks"]["checksums"] is True
    assert report["checks"]["row_counts"] is True
    assert report["checks"]["foreign_keys"] is True
    assert report["checks"]["distribution"] is True
    assert report["checks"]["ground_truth"] is True
    assert report["scope"]["max_claimed_rows"] == 5_000


def test_validator_rejects_missing_and_corrupt_files(tmp_path):
    missing = tmp_path / "missing"
    generate(missing, rows=1_000)
    (missing / "fact_payment.csv").unlink()
    with pytest.raises(DatasetValidationError, match="DATASET_INTEGRITY_FAILED"):
        validate_dataset(missing)

    corrupt = tmp_path / "corrupt"
    generate(corrupt, rows=1_000)
    with (corrupt / "fact_payment.csv").open("a", encoding="utf-8") as handle:
        handle.write("broken,row\n")
    with pytest.raises(DatasetValidationError, match="DATASET_INTEGRITY_FAILED"):
        validate_dataset(corrupt)


def test_full_scan_detects_foreign_key_and_ground_truth_mismatch(tmp_path):
    foreign_key = tmp_path / "foreign-key"
    generate(foreign_key, rows=1_000)
    fact_path = foreign_key / "fact_player_daily.csv"
    rows = list(csv.reader(fact_path.open(encoding="utf-8", newline="")))
    rows[1][1] = "P_NOT_FOUND"
    with fact_path.open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle, lineterminator="\n").writerows(rows)
    _refresh_manifest_file(foreign_key, "fact_player_daily.csv")
    with pytest.raises(DatasetValidationError, match="FOREIGN_KEY_MISMATCH"):
        validate_dataset(foreign_key, full_scan=True)

    wrong_answer = tmp_path / "wrong-answer"
    generate(wrong_answer, rows=1_000)
    truth_path = wrong_answer / "ground_truth.json"
    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    truth["cases"][0]["expected_rows"][0][2] += 1
    truth_path.write_text(
        json.dumps(truth, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _refresh_manifest_file(wrong_answer, "ground_truth.json")
    with pytest.raises(DatasetValidationError, match="GROUND_TRUTH_MISMATCH"):
        validate_dataset(wrong_answer, full_scan=True)
