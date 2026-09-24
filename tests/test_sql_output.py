from app.agent.sql_output import normalize_sql_output


def test_plain_sql_is_trimmed():
    assert normalize_sql_output("  SELECT 1;  ") == "SELECT 1;"


def test_markdown_sql_fence_is_removed():
    value = "说明如下：\n```sql\nSELECT game_id FROM dim_game;\n```\n完成"

    assert normalize_sql_output(value) == "SELECT game_id FROM dim_game;"
