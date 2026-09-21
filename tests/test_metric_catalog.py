from pathlib import Path

from app.semantic.metric_catalog import MetricCatalog


CATALOG = MetricCatalog.load(Path(__file__).resolve().parents[1] / "conf" / "metrics.yaml")


def test_resolves_aliases_to_stable_metric_definitions():
    metrics = CATALOG.resolve("对比各游戏日活和总付费")
    assert [metric.name for metric in metrics] == ["DAU", "Revenue"]


def test_arpu_declares_cross_fact_dependencies():
    context = CATALOG.prompt_context("计算ARPU")
    assert context[0]["required_tables"] == ("fact_payment", "fact_player_daily")
    assert "NULLIF" in context[0]["formula"]
