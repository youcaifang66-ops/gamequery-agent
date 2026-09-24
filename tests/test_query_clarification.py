import asyncio
from types import SimpleNamespace

from app.agent.nodes.check_query_context import check_query_context
from app.entities.value_info import ValueInfo


def metric(name):
    return {"name": name, "description": "", "relevant_columns": [], "alias": []}


def run_check(query, metrics, values=None):
    async def scenario():
        events = []
        result = await check_query_context(
            {
                "query": query,
                "metric_infos": metrics,
                "retrieved_value_infos": values or [],
            },
            SimpleNamespace(stream_writer=events.append),
        )
        return result, events

    return asyncio.run(scenario())


def test_dau_without_date_requests_date_instead_of_guessing_today():
    result, events = run_check("查询各游戏DAU", [metric("DAU")])

    assert result["clarification"]["code"] == "MISSING_DATE"
    assert result["clarification"]["missing_slots"] == ["date"]
    assert events[-1]["type"] == "clarification"


def test_named_game_without_value_match_requests_game_confirmation():
    result, _ = run_check(
        "查询2026年9月18日星际争霸的收入", [metric("Revenue")]
    )

    assert result["clarification"]["code"] == "UNKNOWN_GAME"
    assert result["clarification"]["missing_slots"] == ["game"]


def test_alternative_metrics_request_one_explicit_metric():
    result, _ = run_check(
        "2026年9月18日查收入还是付费人数",
        [metric("Revenue"), metric("PayerCount")],
    )

    assert result["clarification"]["code"] == "CONFLICTING_METRICS"
    assert result["clarification"]["missing_slots"] == ["metric"]


def test_complete_date_and_scope_continues_without_clarification():
    result, events = run_check(
        "统计2026年9月18日各游戏DAU", [metric("DAU")]
    )

    assert result == {"clarification": None}
    assert events[-1] == {
        "type": "progress",
        "step": "检查查询条件",
        "status": "success",
    }


def test_date_with_display_spacing_continues_without_clarification():
    result, _ = run_check(
        "统计 2026 年 9 月 18 日各游戏的 DAU", [metric("DAU")]
    )

    assert result == {"clarification": None}


def test_recognized_named_game_continues():
    result, _ = run_check(
        "查询2026年9月18日星海远征的收入",
        [metric("Revenue")],
        [
            ValueInfo(
                id="dim_game.game_name.星海远征",
                value="星海远征",
                column_id="dim_game.game_name",
            )
        ],
    )

    assert result == {"clarification": None}


def test_level_ids_are_not_misclassified_as_unknown_games():
    result, _ = run_check(
        "统计 LEVEL_005 与 LEVEL_007 的关卡通过率",
        [metric("LevelPassRate")],
    )

    assert result == {"clarification": None}
