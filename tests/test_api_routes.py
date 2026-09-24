import json
import uuid
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from app.api import lifespan as lifespan_module
from app.api.dependencies import get_query_service
from app.api.sse import encode_sse
from main import app


class FakeQueryService:
    async def query(self, query: str, *, request_id: str):
        assert query == "统计2026年9月18日各游戏DAU"
        yield encode_sse(
            "done",
            {
                "type": "done",
                "request_id": request_id,
                "sequence": 1,
                "status": "completed",
            },
        )


def test_health_and_query_entrypoints_remain_compatible(monkeypatch):
    managers = [
        lifespan_module.qdrant_client_manager,
        lifespan_module.embedding_client_manager,
        lifespan_module.es_client_manager,
        lifespan_module.meta_mysql_client_manager,
        lifespan_module.dw_mysql_client_manager,
    ]
    for manager in managers:
        monkeypatch.setattr(manager, "init", MagicMock())
    for manager in (
        lifespan_module.qdrant_client_manager,
        lifespan_module.es_client_manager,
        lifespan_module.meta_mysql_client_manager,
        lifespan_module.dw_mysql_client_manager,
    ):
        monkeypatch.setattr(manager, "close", AsyncMock())
    monkeypatch.setattr(lifespan_module.trace_store, "open", AsyncMock())
    monkeypatch.setattr(lifespan_module.trace_store, "close", AsyncMock())
    app.dependency_overrides[get_query_service] = lambda: FakeQueryService()

    try:
        with TestClient(app) as client:
            health = client.get("/health")
            response = client.post(
                "/api/query",
                json={"query": "统计2026年9月18日各游戏DAU"},
            )
    finally:
        app.dependency_overrides.clear()

    assert health.status_code == 200
    assert health.json() == {
        "status": "ok",
        "service": "gamequery-agent",
        "version": "1.0.0",
    }
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    request_id = response.headers["x-request-id"]
    uuid.UUID(request_id)
    payload = json.loads(response.text.split("data: ", 1)[1])
    assert payload["type"] == "done"
    assert payload["request_id"] == request_id
