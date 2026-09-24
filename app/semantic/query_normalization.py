"""面向游戏数仓枚举值的确定性查询规范化。"""

import re

_LEVEL_ID_PATTERN = re.compile(r"(?i)\bLEVEL_(\d{1,2})\b")


def normalize_query(query: str) -> str:
    """把关卡简称转换成数仓使用的三位数关卡 ID。"""

    return _LEVEL_ID_PATTERN.sub(
        lambda match: f"LEVEL_{int(match.group(1)):03d}",
        query,
    )
