import importlib
import sys
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_reliability_dependencies_are_locked_in_the_right_groups():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    runtime = project["project"]["dependencies"]
    development = project["dependency-groups"]["dev"]

    assert any(item.startswith("aiosqlite") for item in runtime)
    assert any(item.startswith("locust") for item in development)
    assert not any(item.startswith("locust") for item in runtime)


def test_runtime_config_has_bounded_query_and_trace_settings(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("META_DB_PASSWORD", "test-meta-password")
    monkeypatch.setenv("DW_DB_PASSWORD", "test-dw-password")
    sys.modules.pop("app.conf.app_config", None)

    config_module = importlib.import_module("app.conf.app_config")
    config = config_module.app_config

    assert config.sql_policy.max_rows == 500
    assert config.sql_policy.statement_timeout_ms == 5_000
    assert config.query.request_timeout_seconds == 60
    assert config.query.max_correction_attempts == 2
    assert config.trace.database_path.endswith("traces.sqlite3")
    assert config.trace.busy_timeout_ms == 5_000


def test_committed_config_has_no_default_database_password():
    config_text = (ROOT / "conf" / "app_config.yaml").read_text(encoding="utf-8")
    payload = yaml.safe_load(config_text)

    assert "dili123" not in config_text
    assert "MYSQL_PASSWORD" not in config_text
    assert payload["db_meta"]["password"] == "${oc.env:META_DB_PASSWORD}"
    assert payload["db_dw"]["password"] == "${oc.env:DW_DB_PASSWORD}"
