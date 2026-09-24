from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

try:
    from eval.synthetic_profile import CAMPAIGN_DATE_ID, TARGET_GAME_ID, TARGET_LEVEL_ID
except ModuleNotFoundError:  # Direct script execution.
    from synthetic_profile import (  # type: ignore[no-redef]
        CAMPAIGN_DATE_ID,
        TARGET_GAME_ID,
        TARGET_LEVEL_ID,
    )

REQUIRED_FILES = {
    "dim_player.csv",
    "dim_game.csv",
    "dim_date.csv",
    "fact_player_daily.csv",
    "fact_payment.csv",
    "fact_level_event.csv",
    "ground_truth.json",
    "manifest.json",
    "generation_report.json",
}


class DatasetValidationError(ValueError):
    pass


def _fail(code: str, message: str) -> None:
    raise DatasetValidationError(f"{code}: {message}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rows(path: Path):
    with path.open(encoding="utf-8", newline="") as handle:
        yield from csv.DictReader(handle)


def _money(amount: Decimal) -> str:
    return f"{amount.quantize(Decimal('0.01')):.2f}"


def _ratio(numerator: Decimal, denominator: int) -> str:
    if denominator == 0:
        return "0.0000"
    return str(
        (numerator / Decimal(denominator)).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP
        )
    )


def _scan_dataset(
    dataset: Path, *, calculate_answers: bool
) -> tuple[dict[str, int], dict]:
    players: set[str] = set()
    player_channels: dict[str, str] = {}
    for row in _rows(dataset / "dim_player.csv"):
        players.add(row["player_id"])
        player_channels[row["player_id"]] = row["acquisition_channel"]
    games = {row["game_id"] for row in _rows(dataset / "dim_game.csv")}
    dates = {row["date_id"] for row in _rows(dataset / "dim_date.csv")}
    counts = {
        "dim_player.csv": len(players),
        "dim_game.csv": len(games),
        "dim_date.csv": len(dates),
    }
    active_players: set[str] = set()
    channel_players: dict[str, set[str]] = defaultdict(set)
    revenue: Counter[str] = Counter()
    payers: set[str] = set()
    target_revenue = Decimal(0)
    level_total = 0
    level_passed = 0

    fact_specs = (
        ("fact_player_daily.csv", "daily"),
        ("fact_payment.csv", "payment"),
        ("fact_level_event.csv", "level"),
    )
    for filename, kind in fact_specs:
        count = 0
        for row in _rows(dataset / filename):
            count += 1
            if row["player_id"] not in players:
                _fail(
                    "FOREIGN_KEY_MISMATCH", f"{filename}: player_id={row['player_id']}"
                )
            if row["game_id"] not in games:
                _fail("FOREIGN_KEY_MISMATCH", f"{filename}: game_id={row['game_id']}")
            if row["date_id"] not in dates:
                _fail("FOREIGN_KEY_MISMATCH", f"{filename}: date_id={row['date_id']}")
            if not calculate_answers:
                continue
            date_id = int(row["date_id"])
            game_id = row["game_id"]
            player_id = row["player_id"]
            if (
                kind == "daily"
                and game_id == TARGET_GAME_ID
                and date_id == CAMPAIGN_DATE_ID
            ):
                active_players.add(player_id)
                channel_players[player_channels[player_id]].add(player_id)
            elif kind == "payment":
                amount = Decimal(row["amount"])
                if 20260901 <= date_id <= 20260930:
                    revenue[game_id] += amount
                if game_id == TARGET_GAME_ID and date_id == CAMPAIGN_DATE_ID:
                    payers.add(player_id)
                    target_revenue += amount
            elif (
                kind == "level"
                and game_id == TARGET_GAME_ID
                and row["level_id"] == TARGET_LEVEL_ID
                and 20260901 <= date_id <= 20260930
            ):
                level_total += 1
                level_passed += int(row["passed"])
        counts[filename] = count

    answers = {
        "dau_campaign_game": [[TARGET_GAME_ID, CAMPAIGN_DATE_ID, len(active_players)]],
        "revenue_september_by_game": [
            [game_id, _money(revenue[game_id])] for game_id in sorted(revenue)
        ],
        "payer_count_campaign_game": [[TARGET_GAME_ID, CAMPAIGN_DATE_ID, len(payers)]],
        "arpu_campaign_game": [
            [
                TARGET_GAME_ID,
                CAMPAIGN_DATE_ID,
                _ratio(target_revenue, len(active_players)),
            ]
        ],
        "pass_rate_target_level": [
            [
                TARGET_GAME_ID,
                TARGET_LEVEL_ID,
                _ratio(Decimal(level_passed), level_total),
            ]
        ],
        "channel_split_campaign_game": [
            [channel, len(channel_players[channel])]
            for channel in sorted(channel_players)
        ],
    }
    return counts, answers


def validate_dataset(dataset: Path, *, full_scan: bool = False) -> dict:
    dataset = dataset.resolve()
    if not dataset.is_dir():
        _fail("DATASET_INTEGRITY_FAILED", "dataset directory does not exist")
    missing = sorted(REQUIRED_FILES - {path.name for path in dataset.iterdir()})
    if missing:
        _fail("DATASET_INTEGRITY_FAILED", f"missing files: {', '.join(missing)}")
    try:
        manifest = json.loads((dataset / "manifest.json").read_text(encoding="utf-8"))
        ledger = json.loads((dataset / "ground_truth.json").read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        _fail("DATASET_INTEGRITY_FAILED", f"invalid metadata: {exc}")
    if manifest.get("synthetic") is not True or not manifest.get("provenance"):
        _fail("DATASET_INTEGRITY_FAILED", "synthetic provenance is required")

    for filename, metadata in manifest.get("files", {}).items():
        path = dataset / filename
        if not path.is_file():
            _fail("DATASET_INTEGRITY_FAILED", f"missing file: {filename}")
        if path.stat().st_size != metadata.get("bytes"):
            _fail("DATASET_INTEGRITY_FAILED", f"byte count mismatch: {filename}")
        if _sha256(path) != metadata.get("sha256"):
            _fail("DATASET_INTEGRITY_FAILED", f"checksum mismatch: {filename}")

    counts, answers = _scan_dataset(dataset, calculate_answers=full_scan)
    for filename, actual in counts.items():
        expected = manifest["files"][filename]["rows"]
        if actual != expected:
            _fail(
                "DATASET_INTEGRITY_FAILED",
                f"row count mismatch: {filename} expected={expected} actual={actual}",
            )
    actual_fact_rows = sum(counts[name] for name in counts if name.startswith("fact_"))
    if actual_fact_rows != manifest.get("actual_fact_rows"):
        _fail("DATASET_INTEGRITY_FAILED", "total fact row count mismatch")

    statistics = manifest.get("business_statistics", {})
    thresholds = manifest.get("profile", {}).get("thresholds", {})
    for metric in (
        "long_tail_top_game_share",
        "weekend_activity_lift",
        "campaign_activity_lift",
    ):
        threshold = thresholds.get(f"{metric}_min")
        if threshold is None or statistics.get(metric, 0) < threshold:
            _fail("DISTRIBUTION_CHECK_FAILED", f"threshold not met: {metric}")
    if statistics.get("payment_mean", 0) <= statistics.get("payment_median", 0):
        _fail("DISTRIBUTION_CHECK_FAILED", "payment distribution is not right-skewed")
    if (
        statistics.get("level_passed_rows", 0) < 1
        or statistics.get("level_failed_rows", 0) < 1
    ):
        _fail("DISTRIBUTION_CHECK_FAILED", "level outcomes lack both classes")

    if full_scan:
        expected_by_id = {case["id"]: case["expected_rows"] for case in ledger["cases"]}
        if answers != expected_by_id:
            mismatches = sorted(
                case_id
                for case_id in answers
                if answers[case_id] != expected_by_id.get(case_id)
            )
            _fail("GROUND_TRUTH_MISMATCH", f"cases: {', '.join(mismatches)}")

    return {
        "schema_version": "1.0",
        "status": "measured",
        "dataset": {
            "version": manifest["dataset_version"],
            "seed": manifest["seed"],
            "fact_rows": actual_fact_rows,
            "manifest_sha256": _sha256(dataset / "manifest.json"),
        },
        "checks": {
            "checksums": True,
            "row_counts": True,
            "foreign_keys": True,
            "distribution": True,
            "ground_truth": True if full_scan else None,
        },
        "failure": None,
        "scope": {
            "synthetic": True,
            "extrapolated": False,
            "max_claimed_rows": actual_fact_rows,
        },
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--full-scan", action="store_true")
    args = parser.parse_args()
    try:
        result = validate_dataset(args.dataset, full_scan=args.full_scan)
    except DatasetValidationError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc
    print(json.dumps(result, ensure_ascii=False, indent=2))
