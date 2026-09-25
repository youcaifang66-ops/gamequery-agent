from __future__ import annotations

from dataclasses import dataclass

SCHEMA_OPTIMIZATION_VERSION = "2026-09-26.2"


@dataclass(frozen=True)
class IndexSpec:
    table: str
    name: str
    columns: tuple[str, ...]

    @property
    def create_sql(self) -> str:
        columns = ", ".join(f"`{column}`" for column in self.columns)
        return (
            f"CREATE INDEX `{self.name}` ON `{self.table}` ({columns}) "
            "ALGORITHM=INPLACE LOCK=NONE"
        )

    @property
    def rollback_sql(self) -> str:
        return f"DROP INDEX `{self.name}` ON `{self.table}`"


_INDEX_CATALOG = (
    IndexSpec(
        "fact_player_daily",
        "idx_daily_date_game_player",
        ("date_id", "game_id", "player_id"),
    ),
    IndexSpec(
        "fact_payment",
        "idx_payment_date_game_player",
        ("date_id", "game_id", "player_id"),
    ),
    IndexSpec(
        "fact_level_event",
        "idx_level_date_game_level",
        ("date_id", "game_id", "level_id"),
    ),
    IndexSpec(
        "dim_player",
        "idx_player_channel_player",
        ("acquisition_channel", "player_id"),
    ),
    IndexSpec(
        "fact_player_daily",
        "idx_daily_player_date",
        ("player_id", "date_id"),
    ),
    IndexSpec(
        "fact_payment",
        "idx_payment_player_date",
        ("player_id", "date_id"),
    ),
    IndexSpec(
        "fact_level_event",
        "idx_level_player_date",
        ("player_id", "date_id"),
    ),
    IndexSpec(
        "fact_payment",
        "idx_payment_date_game_amount",
        ("date_id", "game_id", "amount"),
    ),
    IndexSpec(
        "fact_level_event",
        "idx_level_date_game_level_pass_attempts",
        ("date_id", "game_id", "level_id", "passed", "attempts"),
    ),
    IndexSpec(
        "fact_level_event",
        "idx_level_game_level_date_pass_attempts",
        ("game_id", "level_id", "date_id", "passed", "attempts"),
    ),
)


def index_catalog() -> tuple[IndexSpec, ...]:
    return _INDEX_CATALOG


def index_statements() -> tuple[str, ...]:
    return tuple(item.create_sql for item in _INDEX_CATALOG)
