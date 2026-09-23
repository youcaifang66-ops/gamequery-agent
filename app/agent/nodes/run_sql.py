"""
SQL 执行节点

负责执行最终 SQL，并记录查询结果。
它是当前 SQL 闭环的结束节点，执行完成后流程进入 END。
"""

from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.state import DataAgentState
from app.core.log import logger


async def run_sql(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    """执行 SQL 并产出最终问数结果"""

    writer = runtime.stream_writer
    step = "执行SQL"
    writer({"type": "progress", "step": step, "status": "running"})

    try:
        sql = state["sql"]
        validated_sql = state.get("validated_sql")
        policy = state.get("sql_policy")
        if validated_sql is None or sql != validated_sql or policy is None:
            raise RuntimeError("validated SQL invariant violated")

        dw_mysql_repository = runtime.context["dw_mysql_repository"]

        result = await dw_mysql_repository.run(
            validated_sql,
            timeout_ms=policy["timeout_ms"],
            max_rows=policy["max_rows"],
        )
        logger.info(f"SQL执行完成，返回 {len(result)} 行")
        writer({"type": "progress", "step": step, "status": "success"})
        writer({"type": "result", "data": result})

    except Exception as error:
        logger.error(f"{step} failed: {type(error).__name__}")
        writer({"type": "progress", "step": step, "status": "error"})
        raise
