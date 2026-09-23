import asyncio
from unittest.mock import AsyncMock, MagicMock

from app.api import lifespan as lifespan_module
from app.api.dependencies import get_trace_store


def test_dependency_returns_lifespan_singleton():
    assert asyncio.run(get_trace_store()) is lifespan_module.trace_store


def test_lifespan_opens_and_closes_trace_store(monkeypatch):
    managers = [
        lifespan_module.qdrant_client_manager,
        lifespan_module.embedding_client_manager,
        lifespan_module.es_client_manager,
        lifespan_module.meta_mysql_client_manager,
        lifespan_module.dw_mysql_client_manager,
    ]
    for manager in managers:
        monkeypatch.setattr(manager, "init", MagicMock())
    closable_managers = [
        lifespan_module.qdrant_client_manager,
        lifespan_module.es_client_manager,
        lifespan_module.meta_mysql_client_manager,
        lifespan_module.dw_mysql_client_manager,
    ]
    for manager in closable_managers:
        monkeypatch.setattr(manager, "close", AsyncMock())
    open_store = AsyncMock()
    close_store = AsyncMock()
    monkeypatch.setattr(lifespan_module.trace_store, "open", open_store)
    monkeypatch.setattr(lifespan_module.trace_store, "close", close_store)

    async def scenario():
        async with lifespan_module.lifespan(MagicMock()):
            open_store.assert_awaited_once_with()
            close_store.assert_not_awaited()

    asyncio.run(scenario())
    close_store.assert_awaited_once_with()
    for manager in closable_managers:
        manager.close.assert_awaited_once_with()
