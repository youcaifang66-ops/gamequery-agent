from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from datetime import UTC, date, datetime
from datetime import time as datetime_time
from decimal import Decimal
from pathlib import Path
from typing import Callable

import asyncmy

try:
    from eval.import_scale_data import validate_database_target
    from eval.player_audit_report import (
        PlayerAuditReportError,
        validate_player_audit_report,
    )
    from eval.scale_report import summarize_samples
except ModuleNotFoundError:  # Direct script execution.
    from import_scale_data import validate_database_target  # type: ignore[no-redef]
    from player_audit_report import (  # type: ignore[no-redef]
        PlayerAuditReportError,
        validate_player_audit_report,
    )
    from scale_report import summarize_samples  # type: ignore[no-redef]

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def build_player_audit_cases(player_id: str, missing_player_id: str) -> list[dict]:
    definitions = (
        (
            "player_profile",
            "SELECT player_id, register_date, region, platform, acquisition_channel "
            "FROM dim_player WHERE player_id=%(player_id)s",
            player_id,
        ),
        (
            "player_activity_timeline",
            "SELECT event_id, player_id, game_id, date_id, login_count, online_minutes, "
            "level_reached, is_active FROM fact_player_daily "
            "WHERE player_id=%(player_id)s ORDER BY date_id, event_id",
            player_id,
        ),
        (
            "player_payment_timeline",
            "SELECT payment_id, player_id, game_id, date_id, amount, currency "
            "FROM fact_payment WHERE player_id=%(player_id)s ORDER BY date_id, payment_id",
            player_id,
        ),
        (
            "player_level_timeline",
            "SELECT event_id, player_id, game_id, date_id, level_id, attempts, passed, "
            "duration_seconds FROM fact_level_event WHERE player_id=%(player_id)s "
            "ORDER BY date_id, event_id",
            player_id,
        ),
        (
            "missing_player_activity_timeline",
            "SELECT event_id, player_id, game_id, date_id, login_count, online_minutes, "
            "level_reached, is_active FROM fact_player_daily "
            "WHERE player_id=%(player_id)s ORDER BY date_id, event_id",
            missing_player_id,
        ),
        (
            "missing_player_payment_timeline",
            "SELECT payment_id, player_id, game_id, date_id, amount, currency "
            "FROM fact_payment WHERE player_id=%(player_id)s ORDER BY date_id, payment_id",
            missing_player_id,
        ),
        (
            "missing_player_level_timeline",
            "SELECT event_id, player_id, game_id, date_id, level_id, attempts, passed, "
            "duration_seconds FROM fact_level_event WHERE player_id=%(player_id)s "
            "ORDER BY date_id, event_id",
            missing_player_id,
        ),
    )
    return [
        {"id": query_id, "sql": sql, "params": {"player_id": target}}
        for query_id, sql, target in definitions
    ]


def validate_workload(
    concurrency_levels: tuple[int, ...],
    *,
    iterations: int,
    warmups: int,
    timeout_seconds: float,
) -> None:
    if not {1, 20}.issubset(concurrency_levels):
        raise PlayerAuditReportError(
            "INVALID_WORKLOAD: concurrency levels 1 and 20 are required"
        )
    if iterations < 30 or warmups < 3 or timeout_seconds <= 0:
        raise PlayerAuditReportError(
            "INVALID_WORKLOAD: iterations>=30, warmups>=3 and timeout>0 are required"
        )


def _normalize(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (date, datetime, datetime_time)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8")
    return value


def _normalize_rows(rows) -> list[list]:
    return [[_normalize(value) for value in row] for row in rows]


def _result_hash(rows: list[list]) -> str:
    payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


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


async def _execute(connection, case: dict, timeout_seconds: float):
    async def execute():
        async with connection.cursor() as cursor:
            started = time.perf_counter_ns()
            await cursor.execute(case["sql"], case["params"])
            rows = _normalize_rows(await cursor.fetchall())
            return (time.perf_counter_ns() - started) / 1_000_000, rows

    return await asyncio.wait_for(execute(), timeout_seconds)


async def _benchmark_case(
    case: dict,
    *,
    connection_kwargs: dict,
    concurrency: int,
    iterations: int,
    warmups: int,
    timeout_seconds: float,
    connection_factory: Callable,
) -> dict:
    probe = await connection_factory(**connection_kwargs)
    try:
        _elapsed, expected_rows = await _execute(probe, case, timeout_seconds)
        for _ in range(warmups):
            _elapsed, rows = await _execute(probe, case, timeout_seconds)
            if rows != expected_rows:
                raise PlayerAuditReportError(f"RESULT_MISMATCH: {case['id']} warmup")
        async with probe.cursor() as cursor:
            await cursor.execute("EXPLAIN ANALYZE " + case["sql"], case["params"])
            explain_analyze = "\n".join(
                str(row[0]) for row in await cursor.fetchall()
            )
    finally:
        probe.close()

    queue: asyncio.Queue[int] = asyncio.Queue()
    for iteration in range(iterations):
        queue.put_nowait(iteration)
    samples: list[float] = []
    timeouts = 0
    errors = 0
    mismatches = 0

    async def worker():
        nonlocal timeouts, errors, mismatches
        connection = await connection_factory(**connection_kwargs)
        try:
            while True:
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                try:
                    elapsed, rows = await _execute(connection, case, timeout_seconds)
                    if rows == expected_rows:
                        samples.append(elapsed)
                    else:
                        mismatches += 1
                except TimeoutError:
                    timeouts += 1
                except Exception:
                    errors += 1
                finally:
                    queue.task_done()
        finally:
            connection.close()

    started = time.perf_counter()
    await asyncio.gather(*(worker() for _ in range(concurrency)))
    elapsed_seconds = time.perf_counter() - started
    metrics = summarize_samples(samples, attempts=iterations, timeouts=timeouts)
    metrics.update(
        {
            "error_count": errors,
            "result_mismatch_count": mismatches,
            "result_match": not (errors or timeouts or mismatches),
            "result_row_count": len(expected_rows),
            "result_sha256": _result_hash(expected_rows),
            "result_preview": expected_rows[:3],
            "throughput_qps": round(iterations / elapsed_seconds, 6),
            "explain_analyze": explain_analyze,
            "sql": case["sql"],
            "params": case["params"],
        }
    )
    return metrics


async def _database_evidence(connection, database: str) -> tuple[dict, list[dict]]:
    async with connection.cursor() as cursor:
        await cursor.execute(
            "SELECT TABLE_NAME, TABLE_ROWS, DATA_LENGTH, INDEX_LENGTH "
            "FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME",
            (database,),
        )
        tables = {
            row[0]: {
                "estimated_rows": row[1],
                "data_bytes": row[2],
                "index_bytes": row[3],
            }
            for row in await cursor.fetchall()
        }
        for table in tables:
            if table.startswith("fact_"):
                await cursor.execute(f"SELECT COUNT(*) FROM `{table}`")
                tables[table]["actual_rows"] = (await cursor.fetchone())[0]
        await cursor.execute(
            "SELECT TABLE_NAME, INDEX_NAME, COLUMN_NAME, SEQ_IN_INDEX "
            "FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=%s "
            "ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX",
            (database,),
        )
        indexes = [
            {
                "table": row[0],
                "index": row[1],
                "column": row[2],
                "sequence": row[3],
            }
            for row in await cursor.fetchall()
        ]
    return tables, indexes


async def run_player_audit_benchmark(
    *,
    database: str,
    username: str,
    password: str,
    player_id: str = "P0000001",
    missing_player_id: str = "P_NOT_FOUND",
    host: str = "127.0.0.1",
    port: int = 3306,
    concurrency_levels: tuple[int, ...] = (1, 20),
    iterations: int = 30,
    warmups: int = 3,
    timeout_seconds: float = 10.0,
    connection_factory: Callable = asyncmy.connect,
) -> dict:
    validate_database_target(database, username=username)
    validate_workload(
        concurrency_levels,
        iterations=iterations,
        warmups=warmups,
        timeout_seconds=timeout_seconds,
    )
    if not player_id or not missing_player_id or player_id == missing_player_id:
        raise PlayerAuditReportError("INVALID_WORKLOAD: distinct player ids required")
    connection_kwargs = {
        "host": host,
        "port": port,
        "user": username,
        "password": password,
        "db": database,
        "autocommit": True,
    }
    evidence_connection = await connection_factory(**connection_kwargs)
    try:
        tables, indexes = await _database_evidence(evidence_connection, database)
        async with evidence_connection.cursor() as cursor:
            await cursor.execute("SELECT VERSION()")
            mysql_version = _normalize((await cursor.fetchone())[0])
    finally:
        evidence_connection.close()
    fact_rows = sum(
        item["actual_rows"]
        for name, item in tables.items()
        if name.startswith("fact_")
    )

    cases = build_player_audit_cases(player_id, missing_player_id)
    runs = []
    started = time.perf_counter()
    for concurrency in concurrency_levels:
        queries = {}
        run_started = time.perf_counter()
        for case in cases:
            queries[case["id"]] = await _benchmark_case(
                case,
                connection_kwargs=connection_kwargs,
                concurrency=concurrency,
                iterations=iterations,
                warmups=warmups,
                timeout_seconds=timeout_seconds,
                connection_factory=connection_factory,
            )
        runs.append(
            {
                "concurrency": concurrency,
                "elapsed_seconds": round(time.perf_counter() - run_started, 6),
                "queries": queries,
            }
        )
    report = {
        "schema_version": "1.0",
        "status": "measured",
        "dataset": {"fact_rows": fact_rows, "tables": tables},
        "environment": {
            "git_sha": _git_sha(),
            "timestamp": datetime.now(UTC).isoformat(),
            "os": platform.platform(),
            "python_version": platform.python_version(),
            "mysql_version": mysql_version,
            "database": database,
        },
        "metrics": {
            "workload": {
                "player_id": player_id,
                "missing_player_id": missing_player_id,
                "warmups_per_query": warmups,
                "iterations_per_query": iterations,
                "concurrency_levels": list(concurrency_levels),
                "timeout_seconds": timeout_seconds,
            },
            "indexes": indexes,
            "elapsed_seconds": round(time.perf_counter() - started, 6),
            "concurrency_runs": runs,
        },
        "failure": None,
        "scope": {
            "synthetic": True,
            "extrapolated": False,
            "max_claimed_rows": fact_rows,
        },
    }
    validate_player_audit_report(report)
    return report


async def _main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True)
    parser.add_argument("--player-id", default="P0000001")
    parser.add_argument("--missing-player-id", default="P_NOT_FOUND")
    parser.add_argument("--concurrency", default="1,20")
    parser.add_argument("--iterations", type=int, default=30)
    parser.add_argument("--warmups", type=int, default=3)
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    username = os.environ.get("SCALE_DB_USER", "")
    password = os.environ.get("SCALE_DB_PASSWORD")
    if not username or password is None:
        raise PlayerAuditReportError(
            "DATABASE_UNAVAILABLE: SCALE_DB_USER and SCALE_DB_PASSWORD are required"
        )
    report = await run_player_audit_benchmark(
        database=args.database,
        username=username,
        password=password,
        player_id=args.player_id,
        missing_player_id=args.missing_player_id,
        host=os.getenv("SCALE_DB_HOST", "127.0.0.1"),
        port=int(os.getenv("SCALE_DB_PORT", "3306")),
        concurrency_levels=tuple(int(item) for item in args.concurrency.split(",")),
        iterations=args.iterations,
        warmups=args.warmups,
        timeout_seconds=args.timeout_seconds,
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except PlayerAuditReportError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc
