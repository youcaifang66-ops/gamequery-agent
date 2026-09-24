import asyncio

import httpx

from app.clients.embedding_client_manager import (
    EmbeddingClientManager,
    OllamaEmbeddings,
)
from app.conf.app_config import EmbeddingConfig


def test_manager_selects_ollama_provider():
    manager = EmbeddingClientManager(
        EmbeddingConfig(
            provider="ollama", host="127.0.0.1", port=11434, model="bge-m3"
        )
    )

    manager.init()

    assert isinstance(manager.client, OllamaEmbeddings)


def test_ollama_async_embedding_contract(monkeypatch):
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/embed"
        return httpx.Response(200, json={"embeddings": [[0.1, 0.2, 0.3]]})

    transport = httpx.MockTransport(handler)

    class FakeAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            super().__init__(transport=transport)

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    client = OllamaEmbeddings(base_url="http://127.0.0.1:11434", model="bge-m3")

    result = asyncio.run(client.aembed_query("日活"))

    assert result == [0.1, 0.2, 0.3]
