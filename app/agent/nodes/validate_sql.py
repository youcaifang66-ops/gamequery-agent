"""
SQL 校验节点

负责在真正执行查询前，用数据库解析一次生成的 SQ
校验结果不在这里决定流程走向，而是通过 state["error"] 交给 graph.py 的条件边判断
"""

import asyncio

from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.state import DataAgentState
from app.core.log import logger
from app.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository
from app.security.errors import SQLPolicyError
from app.security.sql_guard import GuardedSQL

FALLBACK_TIMEOUT_MS = 5_000


def _policy_state(guarded: GuardedSQL) -> dict:
    return {
        "tables": list(guarded.tables),
        "max_rows": guarded.max_rows,
        "limit_action": guarded.limit_action,
        "timeout_ms": guarded.timeout_ms,
    }


def _failure(code: str, message: str, *, correctable: bool) -> dict:
    return {
        "validated_sql": None,
        "sql_policy": None,
        "error": message,
        "error_code": code,
        "error_correctable": correctable,
    }


async def validate_sql(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    """校验 SQL，并返回 error 字段控制后续条件分支"""

    writer = runtime.stream_writer
    step = "校验SQL"
    writer({"type": "progress", "step": step, "status": "running"})

    try:
        candidate_sql = state["sql"]

        dw_mysql_repository: DWMySQLRepository = runtime.context["dw_mysql_repository"]
        sql_guard = runtime.context.get("sql_guard")

        try:
            if sql_guard is None:
                # 只用于旧的本地调用兼容；在线依赖接线完成后不会进入该分支。
                guarded = GuardedSQL(
                    sql=candidate_sql,
                    tables=(),
                    max_rows=500,
                    limit_action="kept",
                    timeout_ms=FALLBACK_TIMEOUT_MS,
                )
            else:
                guarded = sql_guard.validate(candidate_sql)
        except SQLPolicyError as error:
            logger.info(f"SQL策略拒绝：{error.code}")
            writer({"type": "progress", "step": step, "status": "error"})
            return _failure(
                error.code,
                error.safe_message,
                correctable=error.correctable,
            )

        try:
            async with asyncio.timeout(guarded.timeout_ms / 1_000):
                await dw_mysql_repository.validate(
                    guarded.sql,
                    timeout_ms=guarded.timeout_ms,
                )
            writer({"type": "progress", "step": step, "status": "success"})
            logger.info("SQL安全策略与数据库预检通过")
            return {
                "sql": guarded.sql,
                "validated_sql": guarded.sql,
                "sql_policy": _policy_state(guarded),
                "error": None,
                "error_code": None,
                "error_correctable": False,
            }
        except TimeoutError:
            logger.info("SQL数据库预检超时")
            writer({"type": "progress", "step": step, "status": "error"})
            return _failure(
                "QUERY_TIMEOUT",
                "数据库预检超时。",
                correctable=False,
            )
        except Exception:
            logger.info("SQL数据库预检失败")
            writer({"type": "progress", "step": step, "status": "error"})
            return _failure(
                "SQL_EXPLAIN_FAILED",
                "数据库无法预检该查询。",
                correctable=True,
            )

    except Exception as error:
        logger.error(f"{step} failed: {type(error).__name__}")
        writer({"type": "progress", "step": step, "status": "error"})
        raise
