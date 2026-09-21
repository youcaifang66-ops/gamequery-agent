import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_metadata_tables_exist_in_seed_sql():
    config = yaml.safe_load((ROOT / "conf" / "meta_config.yaml").read_text(encoding="utf-8"))
    sql = (ROOT / "docker" / "mysql" / "dw.sql").read_text(encoding="utf-8")
    created_tables = set(re.findall(r"CREATE TABLE\s+(\w+)", sql, flags=re.IGNORECASE))
    configured_tables = {table["name"] for table in config["tables"]}
    assert configured_tables == created_tables


def test_every_metric_references_known_columns():
    config = yaml.safe_load((ROOT / "conf" / "meta_config.yaml").read_text(encoding="utf-8"))
    columns = {
        f'{table["name"]}.{column["name"]}'
        for table in config["tables"]
        for column in table["columns"]
    }
    for metric in config["metrics"]:
        assert metric["relevant_columns"], metric["name"]
        assert set(metric["relevant_columns"]) <= columns, metric["name"]


def test_mvp_contains_required_game_metrics():
    config = yaml.safe_load((ROOT / "conf" / "meta_config.yaml").read_text(encoding="utf-8"))
    metric_names = {metric["name"] for metric in config["metrics"]}
    assert {"DAU", "Revenue", "PayerCount", "ARPU", "LevelPassRate"} <= metric_names
