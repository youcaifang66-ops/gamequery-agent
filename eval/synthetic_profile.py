from __future__ import annotations

from datetime import date, timedelta

PROFILE_VERSION = "game-ops-2026-v1"
GENERATOR_VERSION = "2.0.0"
CAMPAIGN_DATE_ID = 20260918
TARGET_GAME_ID = "G001"
TARGET_LEVEL_ID = "LEVEL_005"

REGIONS = ("华北", "华东", "华南", "西南")
PLATFORMS = ("iOS", "Android", "PC")
CHANNELS = ("自然量", "广告", "社区", "应用商店")
GENRES = ("策略", "竞速", "角色扮演")

GAME_POOL = tuple(
    game_id
    for index, weight in enumerate(
        (40, 16, 10, 7, 5, 4, 3, 3, 2, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1),
        start=1,
    )
    for game_id in [f"G{index:03d}"] * weight
)

PAYMENT_POOL_CENTS = (
    [100] * 35
    + [300] * 25
    + [600] * 18
    + [1200] * 10
    + [3000] * 6
    + [6800] * 3
    + [12800] * 2
    + [64800]
)

PROVENANCE = [
    {
        "name": "AWS Guidance for Game Analytics Pipeline",
        "url": "https://github.com/aws-solutions-library-samples/guidance-for-game-analytics-pipeline-on-aws",
        "usage": "event-generator and telemetry architecture reference only; no source data copied",
    },
    {
        "name": "MySQL 8.0 Reference Manual - Loading Data",
        "url": "https://dev.mysql.com/doc/refman/8.0/en/loading-tables.html",
        "usage": "bulk-loading design reference only",
    },
]


def calendar_rows() -> list[tuple[int, int, str, int, int]]:
    current = date(2026, 1, 1)
    end = date(2027, 1, 1)
    rows: list[tuple[int, int, str, int, int]] = []
    while current < end:
        rows.append(
            (
                int(current.strftime("%Y%m%d")),
                current.year,
                f"Q{(current.month - 1) // 3 + 1}",
                current.month,
                current.day,
            )
        )
        current += timedelta(days=1)
    return rows


def date_pool(calendar: list[tuple[int, int, str, int, int]]) -> tuple[int, ...]:
    values: list[int] = []
    for date_id, year, _quarter, month, day in calendar:
        weekday = date(year, month, day).weekday()
        weight = 13 if weekday >= 5 else 10
        if date_id == CAMPAIGN_DATE_ID:
            weight = 30
        values.extend([date_id] * weight)
    return tuple(values)


def player_attributes(index: int) -> tuple[str, str, str, str]:
    register_month = index % 9 + 1
    register_day = index % 28 + 1
    return (
        f"2026-{register_month:02d}-{register_day:02d}",
        REGIONS[index % len(REGIONS)],
        PLATFORMS[index % len(PLATFORMS)],
        CHANNELS[index % len(CHANNELS)],
    )
