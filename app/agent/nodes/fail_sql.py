from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.state import DataAgentState
from app.conf.app_config import app_config


async def fail_sql(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    """把校验分支的终止原因显式写入事件流。"""

    exhausted = (
        state.get("error_correctable", False)
        and state.get("correction_attempts", 0)
        >= app_config.query.max_correction_attempts
    )
    code = "CORRECTION_EXHAUSTED" if exhausted else state.get("error_code")
    runtime.stream_writer(
        {
            "type": "error",
            "code": code or "INTERNAL_ERROR",
            "message": (
                "SQL 校验未通过，已停止执行。"
                if exhausted
                else state.get("error") or "查询不符合安全策略。"
            ),
        }
    )
    return {}
