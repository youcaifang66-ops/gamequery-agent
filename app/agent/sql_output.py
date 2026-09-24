import re

SQL_FENCE = re.compile(r"```(?:sql)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)


def normalize_sql_output(value: str) -> str:
    """提取模型输出中的单条 SQL，兼容本地模型偶发的 Markdown 围栏。"""
    text = value.strip()
    fenced = SQL_FENCE.search(text)
    return (fenced.group(1) if fenced else text).strip()
