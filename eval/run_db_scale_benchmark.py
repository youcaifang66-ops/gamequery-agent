from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import subprocess
import sys
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Callable

import asyncmy

from eval.import_scale_data import validate_database_target
from eval.scale_report import summarize_samples, validate_scale_report
from eval.validate_scale_data import DatasetValidationError, validate_dataset

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class ScaleBenchmarkError(ValueError):
    pass


def _normalize(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8")
    return value


def _normalize_rows(rows) -> list[list]:
    return [[_normalize(value) for value in row] for row in rows]


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


async def _execute_case(connection, case: dict, timeout_seconds: float):
    async def execute():
        async with connection.cursor() as cursor:
            started = time.perf_counter_ns()
            await cursor.execute(case["sql"], case["params"])
            rows = _normalize_rows(await cursor.fetchall())
            elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
            return elapsed_ms, rows

    return await asyncio.wait_for(execute(), timeout=timeout_seconds)


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
        for _ in range(warmups):
            _elapsed, rows = await _execute_case(probe, case, timeout_seconds)
            if rows != case["expected_rows"]:
                raise ScaleBenchmarkError(f"RESULT_MISMATCH: {case['id']} warmup")
        async with probe.cursor() as cursor:
            await cursor.execute("EXPLAIN " + case["sql"], case["params"])
            plan = _normalize_rows(await cursor.fetchall())
    finally:
        probe.close()

    queue: asyncio.Queue[int] = asyncio.Queue()
    for iteration in range(iterations):
        queue.put_nowait(iteration)
    samples: list[float] = []
    timeouts = 0
    mismatches = 0
    errors = 0

    async def worker():
        nonlocal timeouts, mismatches, errors
        connection = await connection_factory(**connection_kwargs)
        try:
            while True:
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                try:
                    elapsed, rows = await _execute_case(
                        connection, case, timeout_seconds
                    )
                    if rows == case["expected_rows"]:
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
            "result_match": mismatches == 0 and errors == 0,
            "throughput_qps": round(iterations / elapsed_seconds, 6),
            "plan": plan,
        }
    )
    return metrics


async def run_benchmark(
    dataset: Path,
    *,
    database: str,
    username: str,
    password: str,
    host: str = "127.0.0.1",
    port: int = 3306,
    concurrency_levels: tuple[int, ...] = (1,),
    iterations: int = 30,
    warmups: int = 3,
    timeout_seconds: float = 10.0,
    connection_factory: Callable = asyncmy.connect,
) -> dict:
    validate_database_target(database, username=username)
    if iterations < 30:
        raise ScaleBenchmarkError("INVALID_WORKLOAD: iterations must be at least 30")
    if any(level < 1 for level in concurrency_levels):
        raise ScaleBenchmarkError("INVALID_WORKLOAD: concurrency must be positive")
    try:
        validation = validate_dataset(dataset, full_scan=False)
    except DatasetValidationError as exc:
        raise ScaleBenchmarkError(f"DATASET_INTEGRITY_FAILED: {exc}") from exc
    ledger = json.loads(
        (dataset / "ground_truth.json").read_text(encoding="utf-8")
    )
    connection_kwargs = {
        "host": host,
        "port": port,
        "user": username,
        "password": password,
        "db": database,
        "autocommit": True,
    }
    runs = []
    benchmark_started = time.perf_counter()
    for concurrency in concurrency_levels:
        queries = {}
        run_started = time.perf_counter()
        for case in ledger["cases"]:
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
        "dataset": validation["dataset"],
        "environment": {
            "git_sha": _git_sha(),
            "timestamp": datetime.now(UTC).isoformat(),
            "os": platform.platform(),
            "python_version": platform.python_version(),
            "database": database,
        },
        "metrics": {
            "workload": {
                "warmups_per_query": warmups,
                "iterations_per_query": iterations,
                "concurrency_levels": list(concurrency_levels),
                "timeout_seconds": timeout_seconds,
            },
            "elapsed_seconds": round(time.perf_counter() - benchmark_started, 6),
            "concurrency_runs": runs,
        },
        "failure": None,
        "scope": {
            "synthetic": True,
            "extrapolated": False,
            "max_claimed_rows": validation["dataset"]["fact_rows"],
        },
    }
    validate_scale_report(report)
    (dataset / "db_benchmark_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


async def _main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--concurrency", default="1")
    parser.add_argument("--iterations", type=int, default=30)
    parser.add_argument("--warmups", type=int, default=3)
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    args = parser.parse_args()
    username = os.environ.get("SCALE_DB_USER", "")
    password = os.environ.get("SCALE_DB_PASSWORD", "")
    if not username or not password:
        raise ScaleBenchmarkError(
            "DATABASE_UNAVAILABLE: SCALE_DB_USER and SCALE_DB_PASSWORD are required"
        )
    report = await run_benchmark(
        args.dataset,
        database=args.database,
        username=username,
        password=password,
        host=os.getenv("SCALE_DB_HOST", "127.0.0.1"),
        port=int(os.getenv("SCALE_DB_PORT", "3306")),
        concurrency_levels=tuple(int(value) for value in args.concurrency.split(",")),
        iterations=args.iterations,
        warmups=args.warmups,
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except ScaleBenchmarkError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc
