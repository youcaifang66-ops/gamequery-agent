import argparse
import csv
import hashlib
import json
import random
from pathlib import Path

PRESET_ROWS = {"smoke": 1_000, "100k": 100_000, "1m": 1_000_000}
DEFAULT_SEED = 20260923


def _write_csv(path: Path, header: list[str], rows) -> tuple[int, str]:
    digest = hashlib.sha256()
    count = 0
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        for row in rows:
            writer.writerow(row)
            count += 1
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return count, digest.hexdigest()


def generate(output_dir: Path, *, rows: int, seed: int = DEFAULT_SEED) -> dict:
    if rows < 1:
        raise ValueError("rows must be positive")
    output_dir.mkdir(parents=True, exist_ok=True)
    randomizer = random.Random(seed)
    player_count = min(max(rows // 10, 100), 100_000)
    game_count = 20
    date_ids = [20260000 + month * 100 + day for month in range(1, 13) for day in range(1, 29)]
    player_ids = [f"P{index:07d}" for index in range(1, player_count + 1)]
    game_ids = [f"G{index:03d}" for index in range(1, game_count + 1)]

    files = {}
    count, digest = _write_csv(
        output_dir / "dim_player.csv",
        ["player_id", "register_date", "region", "platform", "acquisition_channel"],
        (
            (
                player_id,
                f"2026-{(index % 9) + 1:02d}-{(index % 28) + 1:02d}",
                ("华北", "华东", "华南", "西南")[index % 4],
                ("iOS", "Android", "PC")[index % 3],
                ("自然量", "广告", "社区", "应用商店")[index % 4],
            )
            for index, player_id in enumerate(player_ids)
        ),
    )
    files["dim_player.csv"] = {"rows": count, "sha256": digest}
    count, digest = _write_csv(
        output_dir / "dim_game.csv",
        ["game_id", "game_name", "genre"],
        ((game_id, f"合成游戏{index:02d}", ("策略", "竞速", "角色扮演")[index % 3]) for index, game_id in enumerate(game_ids, 1)),
    )
    files["dim_game.csv"] = {"rows": count, "sha256": digest}
    count, digest = _write_csv(
        output_dir / "dim_date.csv",
        ["date_id", "year", "quarter", "month", "day"],
        ((date_id, 2026, f"Q{((date_id // 100) % 100 - 1) // 3 + 1}", (date_id // 100) % 100, date_id % 100) for date_id in date_ids),
    )
    files["dim_date.csv"] = {"rows": count, "sha256": digest}

    daily_count = rows * 6 // 10
    payment_count = rows * 2 // 10
    level_count = rows - daily_count - payment_count

    def daily_rows():
        for index in range(1, daily_count + 1):
            yield (
                f"A{index:09d}",
                randomizer.choice(player_ids),
                randomizer.choice(game_ids),
                randomizer.choice(date_ids),
                randomizer.randint(1, 6),
                randomizer.randint(1, 360),
                randomizer.randint(1, 100),
                1,
            )

    count, digest = _write_csv(
        output_dir / "fact_player_daily.csv",
        ["event_id", "player_id", "game_id", "date_id", "login_count", "online_minutes", "level_reached", "is_active"],
        daily_rows(),
    )
    files["fact_player_daily.csv"] = {"rows": count, "sha256": digest}

    def payment_rows():
        for index in range(1, payment_count + 1):
            yield (
                f"PAY{index:09d}",
                randomizer.choice(player_ids),
                randomizer.choice(game_ids),
                randomizer.choice(date_ids),
                f"{randomizer.randint(1, 99999) / 100:.2f}",
                "CNY",
            )

    count, digest = _write_csv(
        output_dir / "fact_payment.csv",
        ["payment_id", "player_id", "game_id", "date_id", "amount", "currency"],
        payment_rows(),
    )
    files["fact_payment.csv"] = {"rows": count, "sha256": digest}

    def level_rows():
        for index in range(1, level_count + 1):
            yield (
                f"L{index:09d}",
                randomizer.choice(player_ids),
                randomizer.choice(game_ids),
                randomizer.choice(date_ids),
                f"LEVEL_{randomizer.randint(1, 100):03d}",
                randomizer.randint(1, 8),
                randomizer.randint(0, 1),
                randomizer.randint(10, 1800),
            )

    count, digest = _write_csv(
        output_dir / "fact_level_event.csv",
        ["event_id", "player_id", "game_id", "date_id", "level_id", "attempts", "passed", "duration_seconds"],
        level_rows(),
    )
    files["fact_level_event.csv"] = {"rows": count, "sha256": digest}

    manifest = {
        "seed": seed,
        "requested_fact_rows": rows,
        "actual_fact_rows": daily_count + payment_count + level_count,
        "files": files,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--preset", choices=PRESET_ROWS, default="100k")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            generate(args.output, rows=PRESET_ROWS[args.preset], seed=args.seed),
            ensure_ascii=False,
            indent=2,
        )
    )
