import json
import os
import platform
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import gevent
import psutil
from locust import HttpUser, between, events, task

from eval.load_report import SSE_QUERIES, validate_report

ERROR_CODES: Counter[str] = Counter()


class GameQueryUser(HttpUser):
    wait_time = between(0.5, 1.5)

    def on_start(self):
        self.query_index = 0

    @task
    def stream_query(self):
        scenarios = list(SSE_QUERIES.items())
        query_name, query = scenarios[self.query_index % len(scenarios)]
        self.query_index += 1
        terminal = None
        with self.client.post(
            "/api/query",
            json={"query": query},
            headers={"Accept": "text/event-stream"},
            name=query_name,
            stream=True,
            timeout=float(os.getenv("LOAD_REQUEST_TIMEOUT", "65")),
            catch_response=True,
        ) as response:
            for raw_line in response.iter_lines(decode_unicode=True):
                if not raw_line or not raw_line.startswith("data:"):
                    continue
                event = json.loads(raw_line.removeprefix("data:").strip())
                if event.get("type") in {"done", "error"}:
                    terminal = event
                    break
            if terminal is None:
                response.failure("SSE stream ended without terminal event")
            elif terminal["type"] == "error":
                code = str(terminal.get("code", "UNKNOWN"))
                ERROR_CODES[code] += 1
                response.failure(code)


def _git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


@events.test_start.add_listener
def reset_after_warmup(environment, **kwargs):
    warmup = float(os.getenv("LOAD_WARMUP_SECONDS", "0"))
    if warmup > 0:
        gevent.spawn_later(warmup, environment.stats.reset_all)


@events.quitting.add_listener
def write_measured_report(environment, **kwargs):
    total = environment.stats.total
    request_count = total.num_requests
    failures = total.num_failures
    entries = sorted(
        environment.stats.entries.values(),
        key=lambda entry: entry.avg_response_time or 0,
        reverse=True,
    )
    metadata = {
        "git_sha": _git_sha(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "os": platform.platform(),
        "cpu": platform.processor() or "unknown",
        "memory": str(psutil.virtual_memory().total),
        "python_version": platform.python_version(),
        "mysql_version": os.getenv("LOAD_MYSQL_VERSION", "unverified"),
        "qdrant_version": os.getenv("LOAD_QDRANT_VERSION", "unverified"),
        "row_count": int(os.environ["LOAD_ROW_COUNT"]),
        "index_description": os.environ["LOAD_INDEX_DESCRIPTION"],
        "concurrency": int(os.getenv("LOAD_CONCURRENCY", "1")),
        "spawn_rate": float(os.getenv("LOAD_SPAWN_RATE", "1")),
        "duration_seconds": float(os.environ["LOAD_DURATION_SECONDS"]),
        "warmup_seconds": float(os.getenv("LOAD_WARMUP_SECONDS", "0")),
    }
    timeout_count = ERROR_CODES.get("QUERY_TIMEOUT", 0)
    report = {
        "metadata": metadata,
        "metrics": {
            "request_count": request_count,
            "success_rate": round(
                (request_count - failures) / request_count if request_count else 0, 4
            ),
            "throughput_rps": round(total.total_rps or 0, 4),
            "p50_ms": total.get_response_time_percentile(0.50) or 0,
            "p95_ms": total.get_response_time_percentile(0.95) or 0,
            "p99_ms": total.get_response_time_percentile(0.99) or 0,
            "timeout_rate": round(
                timeout_count / request_count if request_count else 0, 4
            ),
            "error_code_counts": dict(ERROR_CODES),
            "slowest_query_names": [entry.name for entry in entries[:5]],
        },
        "scope": {
            "extrapolated": False,
            "max_claimed_rows": metadata["row_count"],
            "statement": "Results apply only to the recorded row_count.",
        },
    }
    validate_report(report)
    output = Path(os.getenv("LOAD_REPORT_PATH", "eval/latest_load_report.json"))
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    print("Run with: uv run locust -f eval/locustfile.py --host http://localhost:8000")
