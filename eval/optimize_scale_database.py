from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import subprocess
import sys
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Mapping, NoReturn

import asyncmy

try:
    from eval.import_scale_data import (
        ANALYZE_TABLES,
        ScaleImportError,
        validate_database_target,
    )
    from eval.schema_optimization import SCHEMA_OPTIMIZATION_VERSION, index_catalog
except ModuleNotFoundError:  # Direct script execution.
    from import_scale_data import (  # type: ignore[no-redef]
        ANALYZE_TABLES,
        ScaleImportError,
        validate_database_target,
    )
    from schema_optimization import (  # type: ignore[no-redef]
        SCHEMA_OPTIMIZATION_VERSION,
        index_catalog,
    )

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class SchemaOptimizationError(ValueError):
    pass


def _fail(code: str, message: str) -> NoReturn:
    raise SchemaOptimizationError(f"{code}: {message}")


def validate_optimization_target(
    database: str, *, username: str, reader_username: str | None = None
) -> None:
    try:
        validate_database_target(
            database, username=username, reader_username=reader_username
        )
    except ScaleImportError as exc:
        raise SchemaOptimizationError(str(exc)) from exc


def build_migration_plan(
    existing_indexes: Mapping[str, Mapping[str, tuple[str, ...]]],
) -> list[dict]:
    plan = []
    for item in index_catalog():
        actual = existing_indexes.get(item.table, {}).get(item.name)
        if actual is not None and tuple(actual) != item.columns:
            _fail(
                "INDEX_DEFINITION_CONFLICT",
                f"{item.table}.{item.name}: expected {item.columns}, found {tuple(actual)}",
            )
        present = actual is not None
        plan.append(
            {
                "table": item.table,
                "index": item.name,
                "columns": list(item.columns),
                "status": "already_present" if present else "planned",
                "sql": None if present else item.create_sql,
                "rollback_sql": item.rollback_sql,
            }
        )
    return plan


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


async def _read_indexes(cursor, database: str) -> dict[str, dict[str, tuple[str, ...]]]:
    await cursor.execute(
        "SELECT TABLE_NAME, INDEX_NAME, COLUMN_NAME, SEQ_IN_INDEX "
        "FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=%s "
        "ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX",
        (database,),
    )
    grouped: defaultdict[str, defaultdict[str, list[str]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for table, name, column, _sequence in await cursor.fetchall():
        grouped[table][name].append(column)
    return {
        table: {name: tuple(columns) for name, columns in indexes.items()}
        for table, indexes in grouped.items()
    }


async def _read_table_statistics(cursor, database: str) -> dict[str, dict]:
    await cursor.execute(
        "SELECT TABLE_NAME, TABLE_ROWS, DATA_LENGTH, INDEX_LENGTH "
        "FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME",
        (database,),
    )
    return {
        row[0]: {
            "estimated_rows": row[1],
            "data_bytes": row[2],
            "index_bytes": row[3],
        }
        for row in await cursor.fetchall()
    }


async def optimize_database(
    *,
    database: str,
    username: str,
    password: str,
    host: str = "127.0.0.1",
    port: int = 3306,
    apply: bool = False,
    reader_username: str | None = None,
    connection_factory: Callable = asyncmy.connect,
) -> dict:
    validate_optimization_target(
        database, username=username, reader_username=reader_username
    )
    started = time.perf_counter()
    try:
        connection = await connection_factory(
            host=host,
            port=port,
            user=username,
            password=password,
            database=database,
            autocommit=False,
        )
    except Exception as exc:
        _fail("DATABASE_UNAVAILABLE", f"{type(exc).__name__}: connection failed")

    try:
        async with connection.cursor() as cursor:
            before_indexes = await _read_indexes(cursor, database)
            before_statistics = await _read_table_statistics(cursor, database)
            plan = build_migration_plan(before_indexes)
            executed = []
            if apply:
                for step in plan:
                    if step["sql"] is None:
                        continue
                    step_started = time.perf_counter()
                    await cursor.execute(step["sql"])
                    executed.append(
                        {
                            **step,
                            "status": "created",
                            "elapsed_seconds": round(
                                time.perf_counter() - step_started, 6
                            ),
                        }
                    )
                analyze_started = time.perf_counter()
                targets = ", ".join(f"`{table}`" for table in ANALYZE_TABLES)
                await cursor.execute(f"ANALYZE TABLE {targets}")
                analyze_results = [list(row) for row in await cursor.fetchall()]
                analyze_elapsed = time.perf_counter() - analyze_started
                await connection.commit()
            else:
                analyze_results = []
                analyze_elapsed = 0.0

            after_indexes = await _read_indexes(cursor, database)
            after_statistics = await _read_table_statistics(cursor, database)
            await cursor.execute("SELECT VERSION()")
            mysql_version = (await cursor.fetchone())[0]

        return {
            "schema_version": "1.0",
            "migration_version": SCHEMA_OPTIMIZATION_VERSION,
            "status": "measured",
            "mode": "apply" if apply else "dry-run",
            "environment": {
                "git_sha": _git_sha(),
                "timestamp": datetime.now(UTC).isoformat(),
                "os": platform.platform(),
                "python_version": platform.python_version(),
                "mysql_version": mysql_version,
                "database": database,
            },
            "plan": plan,
            "executed": executed,
            "rollback_sql": [item["rollback_sql"] for item in executed],
            "before": {
                "indexes": before_indexes,
                "table_statistics": before_statistics,
            },
            "after": {
                "indexes": after_indexes,
                "table_statistics": after_statistics,
            },
            "metrics": {
                "analyze_elapsed_seconds": round(analyze_elapsed, 6),
                "analyze_results": analyze_results,
                "total_elapsed_seconds": round(time.perf_counter() - started, 6),
            },
            "failure": None,
        }
    except SchemaOptimizationError:
        await connection.rollback()
        raise
    except Exception as exc:
        await connection.rollback()
        _fail("SCHEMA_OPTIMIZATION_FAILED", f"{type(exc).__name__}: {exc}")
    finally:
        connection.close()


async def _main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    username = os.environ.get("SCALE_DB_USER", "")
    password = os.environ.get("SCALE_DB_PASSWORD")
    if not username or password is None:
        _fail(
            "DATABASE_UNAVAILABLE", "SCALE_DB_USER and SCALE_DB_PASSWORD are required"
        )
    report = await optimize_database(
        database=args.database,
        username=username,
        password=password,
        host=os.getenv("SCALE_DB_HOST", "127.0.0.1"),
        port=int(os.getenv("SCALE_DB_PORT", "3306")),
        apply=args.apply,
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except SchemaOptimizationError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc
