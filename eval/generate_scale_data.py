from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import random
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Iterable, Sequence

import psutil

try:
    from eval.synthetic_profile import (
        CAMPAIGN_DATE_ID,
        CHANNELS,
        GAME_POOL,
        GENERATOR_VERSION,
        GENRES,
        PAYMENT_POOL_CENTS,
        PROFILE_VERSION,
        PROVENANCE,
        TARGET_GAME_ID,
        TARGET_LEVEL_ID,
        calendar_rows,
        date_pool,
        player_attributes,
    )
except ModuleNotFoundError:  # Direct script execution.
    from synthetic_profile import (  # type: ignore[no-redef]
        CAMPAIGN_DATE_ID,
        CHANNELS,
        GAME_POOL,
        GENERATOR_VERSION,
        GENRES,
        PAYMENT_POOL_CENTS,
        PROFILE_VERSION,
        PROVENANCE,
        TARGET_GAME_ID,
        TARGET_LEVEL_ID,
        calendar_rows,
        date_pool,
        player_attributes,
    )

PRESET_ROWS = {
    "smoke": 1_000,
    "100k": 100_000,
    "1m": 1_000_000,
    "10m": 10_000_000,
}
DEFAULT_SEED = 20260923
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FACT_FILES = (
    "fact_player_daily.csv",
    "fact_payment.csv",
    "fact_level_event.csv",
)


class HashingWriter:
    def __init__(self, path: Path) -> None:
        self._handle = path.open("wb")
        self._digest = hashlib.sha256()
        self.bytes_written = 0

    def write(self, value: str) -> int:
        payload = value.encode("utf-8")
        self._handle.write(payload)
        self._digest.update(payload)
        self.bytes_written += len(payload)
        return len(value)

    def close(self) -> None:
        self._handle.close()

    @property
    def hexdigest(self) -> str:
        return self._digest.hexdigest()


def _write_csv(
    path: Path, header: Sequence[str], rows: Iterable[Sequence[object]]
) -> dict[str, int | str]:
    temporary = path.with_suffix(path.suffix + ".partial")
    handle = HashingWriter(temporary)
    count = 0
    try:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        for row in rows:
            writer.writerow(row)
            count += 1
    finally:
        handle.close()
    os.replace(temporary, path)
    return {"rows": count, "bytes": handle.bytes_written, "sha256": handle.hexdigest}


def _write_json(path: Path, payload: object, *, rows: int) -> dict[str, int | str]:
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_bytes(encoded)
    os.replace(temporary, path)
    return {
        "rows": rows,
        "bytes": len(encoded),
        "sha256": hashlib.sha256(encoded).hexdigest(),
    }


def _git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            check=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def _prepare_output(output_dir: Path) -> Path:
    resolved = output_dir.resolve()
    if resolved == REPOSITORY_ROOT:
        raise ValueError(
            "UNSAFE_OUTPUT_PATH: repository root is not a dataset directory"
        )
    if resolved.exists() and any(resolved.iterdir()):
        raise ValueError("OUTPUT_NOT_EMPTY: output directory contains files")
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def _median_from_histogram(histogram: Counter[int]) -> Decimal:
    total = sum(histogram.values())
    positions = ((total - 1) // 2, total // 2)
    values: list[int] = []
    seen = 0
    for amount in sorted(histogram):
        next_seen = seen + histogram[amount]
        for position in positions[len(values) :]:
            if seen <= position < next_seen:
                values.append(amount)
            else:
                break
        if len(values) == 2:
            break
        seen = next_seen
    return Decimal(sum(values)) / Decimal(200)


def _money(cents: int) -> str:
    return f"{Decimal(cents) / Decimal(100):.2f}"


def _ratio(numerator: Decimal, denominator: int) -> str:
    if denominator == 0:
        return "0.0000"
    return str(
        (numerator / Decimal(denominator)).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP
        )
    )


def _ground_truth(
    active_players: set[str],
    channel_players: dict[str, set[str]],
    september_revenue: Counter[str],
    payers: set[str],
    revenue_cents: int,
    level_passed: int,
    level_attempts: int,
) -> dict:
    target_params = {"game_id": TARGET_GAME_ID, "date_id": CAMPAIGN_DATE_ID}
    return {
        "schema_version": "1.0",
        "cases": [
            {
                "id": "dau_campaign_game",
                "category": "dau",
                "question": "2026年9月18日 G001 的 DAU 是多少？",
                "sql": "SELECT game_id, date_id, COUNT(DISTINCT player_id) AS dau FROM fact_player_daily WHERE game_id=%(game_id)s AND date_id=%(date_id)s GROUP BY game_id, date_id",
                "params": target_params,
                "columns": ["game_id", "date_id", "dau"],
                "expected_rows": [
                    [TARGET_GAME_ID, CAMPAIGN_DATE_ID, len(active_players)]
                ],
            },
            {
                "id": "revenue_september_by_game",
                "category": "revenue",
                "question": "2026年9月各游戏收入是多少？",
                "sql": "SELECT game_id, CAST(SUM(amount) AS CHAR) AS revenue FROM fact_payment WHERE date_id BETWEEN %(start_date)s AND %(end_date)s GROUP BY game_id ORDER BY game_id",
                "params": {"start_date": 20260901, "end_date": 20260930},
                "columns": ["game_id", "revenue"],
                "expected_rows": [
                    [game_id, _money(september_revenue[game_id])]
                    for game_id in sorted(september_revenue)
                ],
            },
            {
                "id": "payer_count_campaign_game",
                "category": "payer_count",
                "question": "2026年9月18日 G001 的付费人数是多少？",
                "sql": "SELECT game_id, date_id, COUNT(DISTINCT player_id) AS payer_count FROM fact_payment WHERE game_id=%(game_id)s AND date_id=%(date_id)s GROUP BY game_id, date_id",
                "params": target_params,
                "columns": ["game_id", "date_id", "payer_count"],
                "expected_rows": [[TARGET_GAME_ID, CAMPAIGN_DATE_ID, len(payers)]],
            },
            {
                "id": "arpu_campaign_game",
                "category": "arpu",
                "question": "2026年9月18日 G001 的 ARPU 是多少？",
                "sql": "SELECT %(game_id)s AS game_id, %(date_id)s AS date_id, CAST(ROUND((SELECT COALESCE(SUM(amount),0) FROM fact_payment WHERE game_id=%(game_id)s AND date_id=%(date_id)s)/(SELECT COUNT(DISTINCT player_id) FROM fact_player_daily WHERE game_id=%(game_id)s AND date_id=%(date_id)s),4) AS CHAR) AS arpu",
                "params": target_params,
                "columns": ["game_id", "date_id", "arpu"],
                "expected_rows": [
                    [
                        TARGET_GAME_ID,
                        CAMPAIGN_DATE_ID,
                        _ratio(
                            Decimal(revenue_cents) / Decimal(100), len(active_players)
                        ),
                    ]
                ],
            },
            {
                "id": "pass_rate_target_level",
                "category": "pass_rate",
                "question": "2026年9月 G001 的 LEVEL_005 通过率是多少？",
                "sql": "SELECT game_id, level_id, CAST(ROUND(SUM(passed) / NULLIF(SUM(attempts), 0),4) AS CHAR) AS pass_rate FROM fact_level_event WHERE game_id=%(game_id)s AND level_id=%(level_id)s AND date_id BETWEEN %(start_date)s AND %(end_date)s GROUP BY game_id, level_id",
                "params": {
                    "game_id": TARGET_GAME_ID,
                    "level_id": TARGET_LEVEL_ID,
                    "start_date": 20260901,
                    "end_date": 20260930,
                },
                "columns": ["game_id", "level_id", "pass_rate"],
                "expected_rows": [
                    [
                        TARGET_GAME_ID,
                        TARGET_LEVEL_ID,
                        _ratio(Decimal(level_passed), level_attempts),
                    ]
                ],
            },
            {
                "id": "channel_split_campaign_game",
                "category": "channel_split",
                "question": "2026年9月18日 G001 的 DAU 渠道构成是什么？",
                "sql": "SELECT p.acquisition_channel, COUNT(DISTINCT d.player_id) AS dau FROM fact_player_daily d JOIN dim_player p ON p.player_id=d.player_id WHERE d.game_id=%(game_id)s AND d.date_id=%(date_id)s GROUP BY p.acquisition_channel ORDER BY p.acquisition_channel",
                "params": target_params,
                "columns": ["acquisition_channel", "dau"],
                "expected_rows": [
                    [channel, len(channel_players[channel])]
                    for channel in sorted(channel_players)
                ],
            },
        ],
    }


def generate(output_dir: Path, *, rows: int, seed: int = DEFAULT_SEED) -> dict:
    if rows < 1:
        raise ValueError("INVALID_ROW_COUNT: rows must be positive")
    output_dir = _prepare_output(output_dir)
    started = time.perf_counter()
    process = psutil.Process()
    peak_rss = process.memory_info().rss
    randomizer = random.Random(seed)
    calendar = calendar_rows()
    weighted_dates = date_pool(calendar)
    date_weekend = {
        date_id: datetime(year, month, day).weekday() >= 5
        for date_id, year, _quarter, month, day in calendar
    }
    player_count = min(max(rows // 10, 100), 250_000)
    player_ids = [f"P{index:07d}" for index in range(1, player_count + 1)]
    game_ids = [f"G{index:03d}" for index in range(1, 21)]
    player_channels = {
        player_id: player_attributes(index)[3]
        for index, player_id in enumerate(player_ids)
    }
    files: dict[str, dict[str, int | str]] = {}

    files["dim_player.csv"] = _write_csv(
        output_dir / "dim_player.csv",
        ["player_id", "register_date", "region", "platform", "acquisition_channel"],
        (
            (player_id, *player_attributes(index))
            for index, player_id in enumerate(player_ids)
        ),
    )
    files["dim_game.csv"] = _write_csv(
        output_dir / "dim_game.csv",
        ["game_id", "game_name", "genre"],
        (
            (game_id, f"合成游戏{index:02d}", GENRES[(index - 1) % len(GENRES)])
            for index, game_id in enumerate(game_ids, 1)
        ),
    )
    files["dim_date.csv"] = _write_csv(
        output_dir / "dim_date.csv",
        ["date_id", "year", "quarter", "month", "day"],
        calendar,
    )

    daily_count = rows * 6 // 10
    payment_count = rows * 2 // 10
    level_count = rows - daily_count - payment_count
    game_counts: Counter[str] = Counter()
    daily_dates: Counter[int] = Counter()
    active_players: set[str] = set()
    channel_players: dict[str, set[str]] = defaultdict(set)
    september_revenue: Counter[str] = Counter()
    payers: set[str] = set()
    target_revenue_cents = 0
    payment_histogram: Counter[int] = Counter()
    payment_total_cents = 0
    target_level_attempts = 0
    target_level_passed = 0
    total_level_passed = 0

    def daily_records():
        nonlocal peak_rss
        for index in range(1, daily_count + 1):
            if index <= len(CHANNELS):
                player_id, game_id, date_id = (
                    player_ids[index - 1],
                    TARGET_GAME_ID,
                    CAMPAIGN_DATE_ID,
                )
            else:
                player_id = randomizer.choice(player_ids)
                game_id = randomizer.choice(GAME_POOL)
                date_id = randomizer.choice(weighted_dates)
            game_counts[game_id] += 1
            daily_dates[date_id] += 1
            if game_id == TARGET_GAME_ID and date_id == CAMPAIGN_DATE_ID:
                active_players.add(player_id)
                channel_players[player_channels[player_id]].add(player_id)
            if index % 50_000 == 0:
                peak_rss = max(peak_rss, process.memory_info().rss)
            yield (
                f"A{index:09d}",
                player_id,
                game_id,
                date_id,
                randomizer.randint(1, 6),
                randomizer.randint(1, 360),
                randomizer.randint(1, 100),
                1,
            )

    files["fact_player_daily.csv"] = _write_csv(
        output_dir / "fact_player_daily.csv",
        [
            "event_id",
            "player_id",
            "game_id",
            "date_id",
            "login_count",
            "online_minutes",
            "level_reached",
            "is_active",
        ],
        daily_records(),
    )

    def payment_records():
        nonlocal peak_rss, payment_total_cents, target_revenue_cents
        for index in range(1, payment_count + 1):
            if index <= 2:
                player_id, game_id, date_id = (
                    player_ids[index - 1],
                    TARGET_GAME_ID,
                    CAMPAIGN_DATE_ID,
                )
            else:
                player_id = randomizer.choice(player_ids)
                game_id = randomizer.choice(GAME_POOL)
                date_id = randomizer.choice(weighted_dates)
            amount_cents = randomizer.choice(PAYMENT_POOL_CENTS)
            game_counts[game_id] += 1
            payment_histogram[amount_cents] += 1
            payment_total_cents += amount_cents
            if 20260901 <= date_id <= 20260930:
                september_revenue[game_id] += amount_cents
            if game_id == TARGET_GAME_ID and date_id == CAMPAIGN_DATE_ID:
                payers.add(player_id)
                target_revenue_cents += amount_cents
            if index % 50_000 == 0:
                peak_rss = max(peak_rss, process.memory_info().rss)
            yield (
                f"PAY{index:09d}",
                player_id,
                game_id,
                date_id,
                _money(amount_cents),
                "CNY",
            )

    files["fact_payment.csv"] = _write_csv(
        output_dir / "fact_payment.csv",
        ["payment_id", "player_id", "game_id", "date_id", "amount", "currency"],
        payment_records(),
    )

    def level_records():
        nonlocal peak_rss, target_level_attempts, target_level_passed, total_level_passed
        for index in range(1, level_count + 1):
            if index <= 2:
                player_id, game_id, date_id = (
                    player_ids[index - 1],
                    TARGET_GAME_ID,
                    CAMPAIGN_DATE_ID,
                )
                level_id, passed = TARGET_LEVEL_ID, index % 2
            else:
                player_id = randomizer.choice(player_ids)
                game_id = randomizer.choice(GAME_POOL)
                date_id = randomizer.choice(weighted_dates)
                level_id = f"LEVEL_{randomizer.randint(1, 100):03d}"
                passed = int(randomizer.random() < 0.68)
            game_counts[game_id] += 1
            total_level_passed += passed
            attempts = randomizer.randint(1, 8)
            duration_seconds = randomizer.randint(10, 1800)
            if (
                game_id == TARGET_GAME_ID
                and 20260901 <= date_id <= 20260930
                and level_id == TARGET_LEVEL_ID
            ):
                target_level_attempts += attempts
                target_level_passed += passed
            if index % 50_000 == 0:
                peak_rss = max(peak_rss, process.memory_info().rss)
            yield (
                f"L{index:09d}",
                player_id,
                game_id,
                date_id,
                level_id,
                attempts,
                passed,
                duration_seconds,
            )

    files["fact_level_event.csv"] = _write_csv(
        output_dir / "fact_level_event.csv",
        [
            "event_id",
            "player_id",
            "game_id",
            "date_id",
            "level_id",
            "attempts",
            "passed",
            "duration_seconds",
        ],
        level_records(),
    )

    ledger = _ground_truth(
        active_players,
        channel_players,
        september_revenue,
        payers,
        target_revenue_cents,
        target_level_passed,
        target_level_attempts,
    )
    files["ground_truth.json"] = _write_json(
        output_dir / "ground_truth.json", ledger, rows=6
    )

    weekday_counts = [
        count
        for date_id, count in daily_dates.items()
        if not date_weekend[date_id] and date_id != CAMPAIGN_DATE_ID
    ]
    weekend_counts = [
        count for date_id, count in daily_dates.items() if date_weekend[date_id]
    ]
    weekday_average = sum(weekday_counts) / max(len(weekday_counts), 1)
    weekend_average = sum(weekend_counts) / max(len(weekend_counts), 1)
    statistics = {
        "long_tail_top_game_share": round(game_counts[TARGET_GAME_ID] / rows, 6),
        "weekend_activity_lift": round(weekend_average / weekday_average, 6),
        "campaign_activity_lift": round(
            daily_dates[CAMPAIGN_DATE_ID] / weekday_average, 6
        ),
        "payment_mean": float(
            Decimal(payment_total_cents) / Decimal(payment_count * 100)
        ),
        "payment_median": float(_median_from_histogram(payment_histogram)),
        "level_passed_rows": total_level_passed,
        "level_failed_rows": level_count - total_level_passed,
    }
    manifest = {
        "dataset_version": "1.0",
        "generator_version": GENERATOR_VERSION,
        "synthetic": True,
        "seed": seed,
        "requested_fact_rows": rows,
        "actual_fact_rows": daily_count + payment_count + level_count,
        "generated_at": datetime.now(UTC).isoformat(),
        "profile": {
            "version": PROFILE_VERSION,
            "date_count": len(calendar),
            "game_count": len(game_ids),
            "player_count": player_count,
            "campaign_date_id": CAMPAIGN_DATE_ID,
            "target_game_id": TARGET_GAME_ID,
            "target_level_id": TARGET_LEVEL_ID,
            "thresholds": {
                "long_tail_top_game_share_min": 0.35,
                "weekend_activity_lift_min": 1.05,
                "campaign_activity_lift_min": 1.20,
            },
        },
        "provenance": PROVENANCE,
        "files": files,
        "business_statistics": statistics,
        "ground_truth_file": "ground_truth.json",
    }
    _write_json(output_dir / "manifest.json", manifest, rows=1)
    peak_rss = max(peak_rss, process.memory_info().rss)
    elapsed = time.perf_counter() - started
    output_bytes = sum(
        path.stat().st_size for path in output_dir.iterdir() if path.is_file()
    )
    report = {
        "schema_version": "1.0",
        "status": "measured",
        "dataset": {
            "version": manifest["dataset_version"],
            "seed": seed,
            "fact_rows": rows,
            "manifest_sha256": hashlib.sha256(
                (output_dir / "manifest.json").read_bytes()
            ).hexdigest(),
        },
        "environment": {
            "git_sha": _git_sha(),
            "timestamp": datetime.now(UTC).isoformat(),
            "os": platform.platform(),
            "cpu": platform.processor() or "unavailable",
            "memory_bytes": psutil.virtual_memory().total,
            "python_version": platform.python_version(),
        },
        "metrics": {
            "elapsed_seconds": round(elapsed, 6),
            "peak_rss_bytes": peak_rss,
            "output_bytes": output_bytes,
            "rows_per_second": round(rows / elapsed, 3),
            "distribution_checks": statistics,
            "ground_truth_case_count": 6,
        },
        "failure": None,
        "scope": {"synthetic": True, "extrapolated": False, "max_claimed_rows": rows},
    }
    _write_json(output_dir / "generation_report.json", report, rows=1)
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--preset", choices=PRESET_ROWS, default="100k")
    parser.add_argument("--rows", type=int)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    selected_rows = args.rows if args.rows is not None else PRESET_ROWS[args.preset]
    try:
        result = generate(args.output, rows=selected_rows, seed=args.seed)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc
    print(json.dumps(result, ensure_ascii=False, indent=2))
