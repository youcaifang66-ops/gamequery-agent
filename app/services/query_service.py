"""可追踪的 LangGraph 查询编排与 SSE 输出。"""

import asyncio
import hashlib
import uuid
from collections.abc import AsyncIterator
from typing import Any

from langchain_huggingface import HuggingFaceEndpointEmbeddings

from app.agent.context import DataAgentContext
from app.agent.graph import graph
from app.agent.state import DataAgentState
from app.api.sse import ALLOWED_EVENT_TYPES, encode_sse
from app.conf.app_config import app_config
from app.observability.trace_store import AsyncSQLiteTraceStore
from app.repositories.es.value_es_repository import ValueESRepository
from app.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository
from app.repositories.mysql.meta.meta_mysql_repository import MetaMySQLRepository
from app.repositories.qdrant.column_qdrant_repository import ColumnQdrantRepository
from app.repositories.qdrant.metric_qdrant_repository import MetricQdrantRepository
from app.security.sql_guard import SQLGuard

SAFE_RUNTIME_ERRORS = {
    "RETRIEVAL_UNAVAILABLE": "检索服务暂时不可用，请稍后重试。",
}
NON_CORRECTABLE_GUARD_CODES = {
    "MULTI_STATEMENT_DENIED",
    "NON_QUERY_DENIED",
    "WRITE_OPERATION_DENIED",
    "SYSTEM_OBJECT_DENIED",
    "LOCKING_READ_DENIED",
    "DANGEROUS_FUNCTION_DENIED",
}


class QueryService:
    """执行一次问数工作流，并将客户端事件与审计事件保持同序。"""

    def __init__(
        self,
        meta_mysql_repository: MetaMySQLRepository,
        embedding_client: HuggingFaceEndpointEmbeddings,
        dw_mysql_repository: DWMySQLRepository,
        column_qdrant_repository: ColumnQdrantRepository,
        metric_qdrant_repository: MetricQdrantRepository,
        value_es_repository: ValueESRepository,
        sql_guard: SQLGuard,
        trace_store: AsyncSQLiteTraceStore,
    ):
        self.meta_mysql_repository = meta_mysql_repository
        self.dw_mysql_repository = dw_mysql_repository
        self.embedding_client = embedding_client
        self.column_qdrant_repository = column_qdrant_repository
        self.metric_qdrant_repository = metric_qdrant_repository
        self.value_es_repository = value_es_repository
        self.sql_guard = sql_guard
        self.trace_store = trace_store

    def _context(self) -> DataAgentContext:
        return DataAgentContext(
            column_qdrant_repository=self.column_qdrant_repository,
            embedding_client=self.embedding_client,
            metric_qdrant_repository=self.metric_qdrant_repository,
            value_es_repository=self.value_es_repository,
            meta_mysql_repository=self.meta_mysql_repository,
            dw_mysql_repository=self.dw_mysql_repository,
            sql_guard=self.sql_guard,
        )

    @staticmethod
    def _trace_payload(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        if event_type == "result":
            data = payload.get("data", [])
            return {"row_count": len(data) if isinstance(data, list) else 0}
        return {
            key: value
            for key, value in payload.items()
            if key not in {"type", "request_id", "sequence", "data"}
        }

    async def _event(
        self,
        request_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> tuple[int, str]:
        trace_payload = self._trace_payload(event_type, payload)
        sequence = await self.trace_store.append(
            request_id, event_type, trace_payload
        )
        envelope = {
            **payload,
            "type": event_type,
            "request_id": request_id,
            "sequence": sequence,
        }
        return sequence, encode_sse(event_type, envelope)

    async def _finish_cancelled(self, request_id: str) -> None:
        try:
            await asyncio.wait_for(
                asyncio.shield(self.trace_store.finish(request_id, "cancelled")),
                timeout=1,
            )
        except Exception:
            # 客户端已经断开，清理失败只能留给日志/运维，不能覆盖取消异常。
            return

    async def _graph_error_event(
        self, request_id: str, payload: dict[str, Any]
    ) -> tuple[int, str]:
        internal_code = str(payload.get("code") or "INTERNAL_ERROR")
        trace_payload = self._trace_payload("error", payload)
        sequence = await self.trace_store.append(request_id, "error", trace_payload)
        await self.trace_store.finish(
            request_id, "failed", error_code=internal_code
        )
        public_code = (
            "SQL_POLICY_DENIED"
            if internal_code in NON_CORRECTABLE_GUARD_CODES
            else internal_code
        )
        envelope = {
            "type": "error",
            "request_id": request_id,
            "sequence": sequence,
            "code": public_code,
            "message": str(payload.get("message") or "查询失败，请稍后重试。"),
        }
        return sequence, encode_sse("error", envelope)

    async def _failed_event(
        self,
        request_id: str,
        *,
        code: str,
        message: str,
        last_sequence: int,
    ) -> tuple[int, str]:
        payload = {"code": code, "message": message}
        try:
            sequence, encoded = await self._event(request_id, "error", payload)
            await self.trace_store.finish(request_id, "failed", error_code=code)
            return sequence, encoded
        except Exception:
            try:
                await self.trace_store.finish(request_id, "failed", error_code=code)
            except Exception:
                pass
            sequence = last_sequence + 1
            fallback = {
                **payload,
                "type": "error",
                "request_id": request_id,
                "sequence": sequence,
            }
            return sequence, encode_sse("error", fallback)

    async def query(
        self, query: str, *, request_id: str | None = None
    ) -> AsyncIterator[str]:
        request_id = request_id or str(uuid.uuid4())
        digest = hashlib.sha256(query.encode("utf-8")).hexdigest()
        terminal_sent = False
        result_seen = False
        clarification_seen = False
        last_sequence = 0
        try:
            await self.trace_store.start(request_id, digest)
            state = DataAgentState(query=query)
            async with asyncio.timeout(app_config.query.request_timeout_seconds):
                async for raw_chunk in graph.astream(
                    input=state,
                    context=self._context(),
                    stream_mode="custom",
                ):
                    event_type = raw_chunk.get("type", "progress")
                    if event_type not in ALLOWED_EVENT_TYPES - {"done"}:
                        raise RuntimeError("unsupported graph event")
                    if event_type == "error":
                        last_sequence, message = await self._graph_error_event(
                            request_id, raw_chunk
                        )
                        terminal_sent = True
                        yield message
                        return
                    if event_type == "result":
                        result_seen = True
                    if event_type == "clarification":
                        clarification_seen = True
                    last_sequence, message = await self._event(
                        request_id, event_type, raw_chunk
                    )
                    yield message
                    if clarification_seen:
                        break

            if clarification_seen:
                last_sequence, message = await self._event(
                    request_id, "done", {"status": "clarification"}
                )
                await self.trace_store.finish(request_id, "completed")
                terminal_sent = True
                yield message
                return

            if not result_seen:
                last_sequence, message = await self._failed_event(
                    request_id,
                    code="CORRECTION_EXHAUSTED",
                    message="SQL 校验未通过，已停止执行。",
                    last_sequence=last_sequence,
                )
                terminal_sent = True
                yield message
                return

            last_sequence, message = await self._event(
                request_id, "done", {"status": "completed"}
            )
            await self.trace_store.finish(request_id, "completed")
            terminal_sent = True
            yield message
        except (asyncio.CancelledError, GeneratorExit):
            await self._finish_cancelled(request_id)
            raise
        except TimeoutError:
            if not terminal_sent:
                last_sequence, message = await self._failed_event(
                    request_id,
                    code="QUERY_TIMEOUT",
                    message="查询超时，请缩小范围后重试。",
                    last_sequence=last_sequence,
                )
                terminal_sent = True
                yield message
        except Exception as error:
            if not terminal_sent:
                code = getattr(error, "code", "INTERNAL_ERROR")
                if code not in SAFE_RUNTIME_ERRORS:
                    code = "INTERNAL_ERROR"
                last_sequence, message = await self._failed_event(
                    request_id,
                    code=code,
                    message=SAFE_RUNTIME_ERRORS.get(
                        code, "查询失败，请稍后重试。"
                    ),
                    last_sequence=last_sequence,
                )
                terminal_sent = True
                yield message
