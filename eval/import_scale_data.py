from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import platform
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Callable, Iterator

import asyncmy

try:
    from eval.validate_scale_data import DatasetValidationError, validate_dataset
except ModuleNotFoundError:  # Direct script execution.
    from validate_scale_data import (  # type: ignore[no-redef]
        DatasetValidationError,
        validate_dataset,
    )

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = Path(__file__).parent / "sql" / "scale_schema.sql"
DATABASE_PATTERN = re.compile(r"^gamequery_scale_[a-z0-9_]+$")
RESERVED_DATABASES = {
    "dw",
    "meta",
    "mysql",
    "information_schema",
    "performance_schema",
    "sys",
}
TABLES = {
    "dim_player": ("dim_player.csv", 5),
    "dim_game": ("dim_game.csv", 3),
    "dim_date": ("dim_date.csv", 5),
    "fact_player_daily": ("fact_player_daily.csv", 8),
    "fact_payment": ("fact_payment.csv", 6),
    "fact_level_event": ("fact_level_event.csv", 8),
}
INDEX_STATEMENTS = (
    "CREATE INDEX idx_daily_date_game_player ON fact_player_daily(date_id, game_id, player_id)",
    "CREATE INDEX idx_payment_date_game_player ON fact_payment(date_id, game_id, player_id)",
    "CREATE INDEX idx_level_date_game_level ON fact_level_event(date_id, game_id, level_id)",
    "CREATE INDEX idx_player_channel_player ON dim_player(acquisition_channel, player_id)",
)


class ScaleImportError(ValueError):
    pass


def _fail(code: str, message: str) -> None:
    raise ScaleImportError(f"{code}: {message}")


def validate_database_target(
    database: str, *, username: str, reader_username: str | None = None
) -> None:
    if database in RESERVED_DATABASES or not DATABASE_PATTERN.fullmatch(database):
        _fail("INVALID_DATABASE_NAME", f"refusing database {database!r}")
    configured_reader = reader_username or os.getenv("DW_DB_USER", "gamequery_reader")
    if username == configured_reader:
        _fail("READ_ONLY_CREDENTIALS", "online reader account cannot import data")


def iter_csv_batches(path: Path, *, batch_size: int) -> Iterator[list[tuple[str, ...]]]:
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        next(reader)
        batch: list[tuple[str, ...]] = []
        for row in reader:
            batch.append(tuple(row))
            if len(batch) == batch_size:
                yield batch
                batch = []
        if batch:
            yield batch


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


def _normalize(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8")
    return value


def _normalize_rows(rows) -> list[list]:
    return [[_normalize(value) for value in row] for row in rows]


def _schema_statements() -> list[str]:
    return [
        statement.strip()
        for statement in SCHEMA_PATH.read_text(encoding="utf-8").split(";")
        if statement.strip()
    ]


async def import_dataset(
    dataset: Path,
    *,
    database: str,
    username: str,
    password: str,
    host: str = "127.0.0.1",
    port: int = 3306,
    batch_size: int = 10_000,
    replace: bool = False,
    reader_username: str | None = None,
    connection_factory: Callable = asyncmy.connect,
) -> dict:
    validate_database_target(
        database, username=username, reader_username=reader_username
    )
    try:
        validation = validate_dataset(dataset, full_scan=True)
    except DatasetValidationError as exc:
        _fail("DATASET_INTEGRITY_FAILED", str(exc))
    dataset = dataset.resolve()
    manifest = json.loads((dataset / "manifest.json").read_text(encoding="utf-8"))
    ledger = json.loads((dataset / "ground_truth.json").read_text(encoding="utf-8"))
    started = time.perf_counter()
    connection = None
    try:
        connection = await connection_factory(
            host=host,
            port=port,
            user=username,
            password=password,
            autocommit=False,
        )
    except Exception as exc:
        _fail("DATABASE_UNAVAILABLE", f"{type(exc).__name__}: connection failed")
    table_metrics: dict[str, dict] = {}
    try:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=%s",
                (database,),
            )
            exists = await cursor.fetchone()
            if exists and not replace:
                _fail("IMPORT_FAILED", "experiment database exists; pass --replace")
            if exists:
                await cursor.execute(f"DROP DATABASE `{database}`")
            await cursor.execute(
                f"CREATE DATABASE `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci"
            )
            await cursor.execute(f"USE `{database}`")
            for statement in _schema_statements():
                await cursor.execute(statement)
            await connection.commit()

            for table, (filename, column_count) in TABLES.items():
                table_started = time.perf_counter()
                imported = 0
                placeholders = ",".join(["%s"] * column_count)
                sql = f"INSERT INTO `{table}` VALUES ({placeholders})"
                for batch in iter_csv_batches(
                    dataset / filename, batch_size=batch_size
                ):
                    await cursor.executemany(sql, batch)
                    await connection.commit()
                    imported += len(batch)
                expected = manifest["files"][filename]["rows"]
                table_metrics[table] = {
                    "expected_rows": expected,
                    "imported_rows": imported,
                    "elapsed_seconds": round(time.perf_counter() - table_started, 6),
                }
                if imported != expected:
                    _fail("RESULT_MISMATCH", f"import count mismatch: {table}")

            index_started = time.perf_counter()
            for statement in INDEX_STATEMENTS:
                await cursor.execute(statement)
            await connection.commit()
            index_elapsed = time.perf_counter() - index_started

            for table, metrics in table_metrics.items():
                await cursor.execute(f"SELECT COUNT(*) FROM `{table}`")
                database_count = (await cursor.fetchone())[0]
                if database_count != metrics["expected_rows"]:
                    _fail("RESULT_MISMATCH", f"database count mismatch: {table}")

            for case in ledger["cases"]:
                await cursor.execute(case["sql"], case["params"])
                actual = _normalize_rows(await cursor.fetchall())
                if actual != case["expected_rows"]:
                    _fail("RESULT_MISMATCH", f"ground truth mismatch: {case['id']}")
            await cursor.execute("SELECT VERSION()")
            mysql_version = _normalize((await cursor.fetchone())[0])
        total_elapsed = time.perf_counter() - started
        total_rows = sum(metric["imported_rows"] for metric in table_metrics.values())
        report = {
            "schema_version": "1.0",
            "status": "measured",
            "dataset": validation["dataset"],
            "environment": {
                "git_sha": _git_sha(),
                "timestamp": datetime.now(UTC).isoformat(),
                "os": platform.platform(),
                "python_version": platform.python_version(),
                "mysql_version": mysql_version,
                "database": database,
            },
            "metrics": {
                "tables": table_metrics,
                "index_elapsed_seconds": round(index_elapsed, 6),
                "total_elapsed_seconds": round(total_elapsed, 6),
                "throughput_rows_per_second": round(total_rows / total_elapsed, 3),
                "ground_truth_passed": True,
            },
            "failure": None,
            "scope": {
                "synthetic": True,
                "extrapolated": False,
                "max_claimed_rows": manifest["actual_fact_rows"],
            },
        }
        (dataset / "import_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return report
    except ScaleImportError:
        if connection is not None:
            await connection.rollback()
        raise
    except Exception as exc:
        if connection is not None:
            await connection.rollback()
        _fail("IMPORT_FAILED", f"{type(exc).__name__}: import operation failed")
    finally:
        if connection is not None:
            connection.close()


async def _main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--batch-size", type=int, default=10_000)
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    username = os.environ.get("SCALE_DB_USER", "")
    password = os.environ.get("SCALE_DB_PASSWORD", "")
    if not username or not password:
        _fail(
            "DATABASE_UNAVAILABLE", "SCALE_DB_USER and SCALE_DB_PASSWORD are required"
        )
    report = await import_dataset(
        args.dataset,
        database=args.database,
        username=username,
        password=password,
        host=os.getenv("SCALE_DB_HOST", "127.0.0.1"),
        port=int(os.getenv("SCALE_DB_PORT", "3306")),
        batch_size=args.batch_size,
        replace=args.replace,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except ScaleImportError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc
