import re

from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.state import ClarificationState, DataAgentState

DATE_REQUIRED_METRICS = {"DAU"}
DATE_PATTERN = re.compile(
    r"(?:\d{4}\s*[年/-]\s*\d{1,2}(?:\s*[月/-]\s*\d{1,2}\s*日?)?|"
    r"今天|今日|昨天|昨日|前天|本周|上周|本月|上月|本季度|上季度|"
    r"今年|去年|最近\s*\d+\s*[天周月年])"
)
METRIC_EXPRESSION = re.compile(
    r"的\s*(?:DAU|日活(?:跃用户数)?|收入|流水|总付费|付费人数|"
    r"付费用户数|ARPU|通关率|关卡通过率)",
    re.IGNORECASE,
)
GENERIC_GAME_SCOPES = {"游戏", "各游戏", "所有游戏", "每个游戏", "全游戏"}
LEVEL_ID_PATTERN = re.compile(r"(?i)\bLEVEL_\d{3}\b")


def _specific_game_requested(query: str) -> bool:
    match = METRIC_EXPRESSION.search(query)
    if match is None:
        return False
    prefix = query[: match.start()]
    prefix = DATE_PATTERN.sub("", prefix)
    prefix = LEVEL_ID_PATTERN.sub("", prefix)
    prefix = re.sub(r"^(?:请|请问|帮我|查询|统计|看一下|看下)+", "", prefix)
    prefix = re.sub(r"(?:与|和|及|、|关卡|[\s，,。:：])+", "", prefix)
    return bool(prefix) and prefix not in GENERIC_GAME_SCOPES


def _clarification(
    code: str, missing_slots: list[str], message: str
) -> ClarificationState:
    return ClarificationState(
        code=code,
        missing_slots=missing_slots,
        message=message,
    )


async def check_query_context(
    state: DataAgentState, runtime: Runtime[DataAgentContext]
):
    """在生成 SQL 前做确定性槽位检查，不从当前日期或相似实体猜答案。"""

    writer = runtime.stream_writer
    step = "检查查询条件"
    writer({"type": "progress", "step": step, "status": "running"})

    query = state["query"]
    metric_names = {
        metric["name"] for metric in state.get("metric_infos", []) if "name" in metric
    }
    game_values = {
        value.value
        for value in state.get("retrieved_value_infos", [])
        if value.column_id == "dim_game.game_name"
    }

    clarification: ClarificationState | None = None
    if metric_names & DATE_REQUIRED_METRICS and not DATE_PATTERN.search(query):
        clarification = _clarification(
            "MISSING_DATE",
            ["date"],
            "该指标需要明确日期或时间范围，请补充后再查询。",
        )
    elif _specific_game_requested(query) and not game_values:
        clarification = _clarification(
            "UNKNOWN_GAME",
            ["game"],
            "没有匹配到问题中的游戏，请确认游戏名称。",
        )
    elif len(metric_names) > 1 and re.search(r"还是|或者|或是", query):
        clarification = _clarification(
            "CONFLICTING_METRICS",
            ["metric"],
            "问题包含多个备选指标，请明确要查询的指标口径。",
        )

    if clarification is not None:
        writer({"type": "clarification", **clarification})
        return {"clarification": clarification}

    writer({"type": "progress", "step": step, "status": "success"})
    return {"clarification": None}
