from app.semantic.query_normalization import normalize_query


def test_short_level_ids_are_padded_to_warehouse_format():
    assert normalize_query("统计 LEVEL_05 与 level_7 的关卡通过率") == (
        "统计 LEVEL_005 与 LEVEL_007 的关卡通过率"
    )


def test_canonical_level_ids_are_unchanged():
    assert normalize_query("查询 LEVEL_005 和 LEVEL_100") == (
        "查询 LEVEL_005 和 LEVEL_100"
    )
