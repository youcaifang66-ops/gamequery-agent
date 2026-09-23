import hashlib
import json
import math
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.security.sql_guard import SQLGuard, SQLGuardError  # noqa: E402


def database():
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """
        CREATE TABLE dim_player(player_id TEXT,register_date TEXT,region TEXT,platform TEXT,acquisition_channel TEXT);
        INSERT INTO dim_player VALUES ('P001','2026-09-01','华北','iOS','自然量'),('P002','2026-09-02','华东','Android','广告'),('P003','2026-09-02','华北','PC','社区'),('P004','2026-09-03','华南','Android','商店');
        CREATE TABLE dim_game(game_id TEXT,game_name TEXT,genre TEXT);
        INSERT INTO dim_game VALUES ('G001','星海远征','策略'),('G002','极速竞技场','竞速');
        CREATE TABLE dim_date(date_id INTEGER,year INTEGER,quarter TEXT,month INTEGER,day INTEGER);
        INSERT INTO dim_date VALUES (20260918,2026,'Q3',9,18),(20260919,2026,'Q3',9,19),(20260920,2026,'Q3',9,20),(20260921,2026,'Q3',9,21);
        CREATE TABLE fact_player_daily(event_id TEXT,player_id TEXT,game_id TEXT,date_id INTEGER,login_count INTEGER,online_minutes INTEGER,level_reached INTEGER,is_active INTEGER);
        INSERT INTO fact_player_daily VALUES ('A001','P001','G001',20260918,2,65,8,1),('A002','P002','G001',20260918,1,31,4,1),('A003','P001','G001',20260919,3,82,10,1),('A004','P003','G002',20260919,1,24,3,1),('A005','P004','G001',20260920,2,50,6,1),('A006','P001','G001',20260921,2,70,12,1);
        CREATE TABLE fact_payment(payment_id TEXT,player_id TEXT,game_id TEXT,date_id INTEGER,amount REAL,currency TEXT);
        INSERT INTO fact_payment VALUES ('PAY001','P001','G001',20260918,30,'CNY'),('PAY002','P002','G001',20260918,6,'CNY'),('PAY003','P001','G001',20260920,68,'CNY'),('PAY004','P003','G002',20260921,18,'CNY');
        CREATE TABLE fact_level_event(event_id TEXT,player_id TEXT,game_id TEXT,date_id INTEGER,level_id TEXT,attempts INTEGER,passed INTEGER,duration_seconds INTEGER);
        INSERT INTO fact_level_event VALUES ('L001','P001','G001',20260918,'LEVEL_08',1,1,210),('L002','P002','G001',20260918,'LEVEL_05',3,0,480),('L003','P001','G001',20260919,'LEVEL_10',2,1,390),('L004','P004','G001',20260920,'LEVEL_07',4,0,520),('L005','P003','G002',20260921,'TRACK_03',2,1,175);
        """
    )
    return connection


def rows(connection, sql):
    return [list(row) for row in connection.execute(sql).fetchall()]


def evaluate():
    dataset_path = ROOT / "eval" / "sql_benchmark.json"
    dataset_bytes = dataset_path.read_bytes()
    workload = json.loads(dataset_bytes.decode("utf-8"))
    guard = SQLGuard.from_meta_config(ROOT / "conf" / "meta_config.yaml")
    connection = database()
    valid = workload["valid"]
    repairable = workload["repairable"]
    unsafe = workload["unsafe"]
    guard_correct = 0
    valid_result_correct = 0
    preset_repair_correct = 0
    latencies = []

    guard.validate(valid[0]["sql"])

    for case in valid:
        for _ in range(20):
            started = time.perf_counter()
            guarded = guard.validate(case["sql"])
            latencies.append((time.perf_counter() - started) * 1000)
        guard_correct += 1
        valid_result_correct += rows(connection, guarded.sql) == case["expected"]
    for case in repairable:
        try:
            guard.validate(case["sql"])
        except SQLGuardError:
            guard_correct += 1
        guarded = guard.validate(case["corrected_sql"])
        preset_repair_correct += rows(connection, guarded.sql) == case["expected"]
    for case in unsafe:
        try:
            guard.validate(case["sql"])
        except SQLGuardError:
            guard_correct += 1

    executable = len(valid) + len(repairable)
    total = executable + len(unsafe)
    result = {
        "mode": "static_fixture",
        "dataset_version": "1.0",
        "dataset_sha256": hashlib.sha256(dataset_bytes).hexdigest(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset_size": total,
        "guard_accuracy": round(guard_correct / total, 4),
        "first_pass_fixture_rate": round(len(valid) / executable, 4),
        "preset_repair_execution_accuracy": round(
            preset_repair_correct / len(repairable), 4
        ),
        "fixture_execution_accuracy": round(
            (valid_result_correct + preset_repair_correct) / executable, 4
        ),
        "agent_correction_accuracy": None,
        "agent_correction_status": "not_run",
        "guard_latency_p95_ms": round(
            sorted(latencies)[math.ceil(len(latencies) * 0.95) - 1], 3
        ),
    }
    (ROOT / "eval" / "latest_metrics.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    connection.close()
    return result


if __name__ == "__main__":
    print(json.dumps(evaluate(), ensure_ascii=False, indent=2))
