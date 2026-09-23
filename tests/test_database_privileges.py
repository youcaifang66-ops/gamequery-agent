from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_compose_requires_separate_database_secrets():
    compose_text = (ROOT / "docker" / "docker-compose.yaml").read_text(
        encoding="utf-8"
    )
    compose = yaml.safe_load(compose_text)
    api_environment = compose["services"]["api"]["environment"]
    mysql_environment = compose["services"]["mysql"]["environment"]

    assert "dili123" not in compose_text
    assert "MYSQL_PASSWORD" not in api_environment
    assert api_environment["META_DB_USER"] == "gamequery_meta"
    assert api_environment["DW_DB_USER"] == "gamequery_reader"
    assert "META_DB_PASSWORD" in api_environment
    assert "DW_DB_PASSWORD" in api_environment
    assert "MYSQL_ROOT_PASSWORD" in mysql_environment


def test_init_scripts_never_grant_all_and_dw_is_select_only():
    init_dir = ROOT / "docker" / "mysql"
    scripts = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(init_dir.iterdir())
        if path.suffix in {".sql", ".sh"}
    )
    normalized = " ".join(scripts.upper().split())

    assert "GRANT ALL" not in normalized
    assert "GRANT SELECT ON DW.* TO 'GAMEQUERY_READER'@'%'" in normalized
    assert (
        "GRANT SELECT, INSERT, UPDATE, DELETE ON META.* "
        "TO 'GAMEQUERY_META'@'%'"
    ) in normalized
    dw_grant = normalized.split("GRANT SELECT ON DW.*", 1)[1].split(";", 1)[0]
    assert "INSERT" not in dw_grant
    assert "UPDATE" not in dw_grant
    assert "DELETE" not in dw_grant


def test_example_environment_lists_every_required_secret():
    keys = {
        line.split("=", 1)[0]
        for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    }

    assert {
        "LLM_API_KEY",
        "MYSQL_ROOT_PASSWORD",
        "META_DB_PASSWORD",
        "DW_DB_PASSWORD",
    } <= keys
