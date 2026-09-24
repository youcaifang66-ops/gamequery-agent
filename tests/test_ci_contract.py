from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def workflow_text() -> str:
    return (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")


def test_ci_contains_every_offline_reliability_gate():
    text = workflow_text()

    required_commands = [
        "uv sync --frozen --group dev",
        "uv run ruff check app tests eval main.py",
        "uv run pytest -q",
        "Initialize least-privilege MySQL fixtures",
        "run_sql_eval",
        "run_retrieval_eval",
        "generate_scale_data.py --preset smoke",
        "pnpm install --frozen-lockfile",
        "pnpm build",
        "git diff --exit-code",
    ]
    for command in required_commands:
        assert command in text


def test_ci_never_calls_real_llm_or_live_services():
    text = workflow_text().lower()

    forbidden = [
        "--mode live",
        "build_meta_knowledge",
        "docker compose up",
        "locust -f",
        "siliconflow",
        "llm_api_key:",
    ]
    for value in forbidden:
        assert value not in text


def test_ci_yaml_has_backend_and_frontend_jobs_with_read_only_permissions():
    workflow = yaml.load(workflow_text(), Loader=yaml.BaseLoader)

    assert workflow["permissions"] == {"contents": "read"}
    assert set(workflow["jobs"]) == {"backend", "frontend"}
    assert workflow["jobs"]["backend"]["runs-on"] == "ubuntu-latest"
    assert workflow["jobs"]["frontend"]["runs-on"] == "ubuntu-latest"
    assert set(workflow["jobs"]["backend"]["services"]) == {"mysql", "qdrant"}
