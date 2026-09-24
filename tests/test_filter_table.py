from copy import deepcopy

from app.agent.nodes.filter_table import apply_table_selection

TABLES = [
    {
        "id": "fact_player_daily",
        "name": "fact_player_daily",
        "role": "fact",
        "description": "日活事实表",
        "columns": [
            {"name": "game_id"},
            {"name": "player_id"},
            {"name": "date_id"},
        ],
    }
]


def test_valid_selection_is_applied():
    result = apply_table_selection(
        deepcopy(TABLES), {"fact_player_daily": ["game_id", "date_id"]}
    )

    assert [column["name"] for column in result[0]["columns"]] == [
        "game_id",
        "date_id",
    ]


def test_unusable_model_selection_prefers_metric_dependency_tables():
    unrelated = {
        "id": "dim_game",
        "name": "dim_game",
        "role": "dim",
        "description": "游戏维表",
        "columns": [{"name": "game_name"}],
    }
    result = apply_table_selection(
        deepcopy([*TABLES, unrelated]), {}, {"fact_player_daily"}
    )

    assert [table["name"] for table in result] == ["fact_player_daily"]
    assert [column["name"] for column in result[0]["columns"]] == [
        "game_id",
        "player_id",
        "date_id",
    ]


def test_selection_missing_metric_dependency_falls_back_to_required_table():
    unrelated = {
        "id": "fact_payment",
        "name": "fact_payment",
        "role": "fact",
        "description": "支付事实表",
        "columns": [{"name": "amount"}],
    }
    result = apply_table_selection(
        deepcopy([*TABLES, unrelated]),
        {"fact_payment": ["amount"]},
        {"fact_player_daily"},
    )

    assert [table["name"] for table in result] == ["fact_player_daily"]
