import asyncio
from types import SimpleNamespace

from qdrant_client import models

from app.clients import qdrant_client_manager as manager_module
from app.conf.app_config import QdrantConfig
from app.repositories.qdrant.column_qdrant_repository import ColumnQdrantRepository
from app.repositories.qdrant.metric_qdrant_repository import MetricQdrantRepository


class FakeQdrantClient:
    def __init__(self):
        self.exists = False
        self.created = []
        self.upserts = []
        self.queries = []
        self.scrolls = []
        self.points = []

    async def collection_exists(self, collection_name):
        return self.exists

    async def create_collection(self, **kwargs):
        self.created.append(kwargs)
        self.exists = True

    async def upsert(self, **kwargs):
        self.upserts.append(kwargs)

    async def query_points(self, **kwargs):
        self.queries.append(kwargs)
        return SimpleNamespace(points=self.points)

    async def scroll(self, **kwargs):
        self.scrolls.append(kwargs)
        return self.points, None


def column_payload():
    return {
        "entity_type": "column",
        "entity_id": "fact_payment.amount",
        "retrieval_text": "amount 付费金额 收入",
        "normalized_name": "amount",
        "normalized_aliases": ["付费金额", "收入"],
        "id": "fact_payment.amount",
        "name": "amount",
        "type": "decimal",
        "role": "measure",
        "examples": ["30.00"],
        "description": "支付金额",
        "alias": ["付费金额", "收入"],
        "table_id": "fact_payment",
    }


def test_v2_collection_has_named_dense_and_bm25_vectors():
    async def scenario():
        client = FakeQdrantClient()
        repository = ColumnQdrantRepository(client)
        await repository.ensure_collection()
        await repository.ensure_collection()
        return client.created

    created = asyncio.run(scenario())
    assert len(created) == 1
    assert created[0]["collection_name"] == "column_info_collection_v2"
    assert set(created[0]["vectors_config"]) == {"dense"}
    assert set(created[0]["sparse_vectors_config"]) == {"bm25"}
    assert created[0]["sparse_vectors_config"]["bm25"].modifier == models.Modifier.IDF


def test_upsert_uses_one_deterministic_hybrid_point_per_entity():
    async def scenario():
        client = FakeQdrantClient()
        repository = ColumnQdrantRepository(client)
        await repository.upsert_entities([column_payload()], [[0.1, 0.2]])
        await repository.upsert_entities([column_payload()], [[0.1, 0.2]])
        return client.upserts

    upserts = asyncio.run(scenario())
    first = upserts[0]["points"][0]
    second = upserts[1]["points"][0]
    assert first.id == second.id == ColumnQdrantRepository.stable_point_id(
        "fact_payment.amount"
    )
    assert set(first.vector) == {"dense", "bm25"}
    assert first.vector["bm25"].text == "amount 付费金额 收入"
    assert (
        first.vector["bm25"].options.tokenizer == models.TokenizerType.MULTILINGUAL
    )
    assert upserts[0]["wait"] is True


def test_dense_lexical_exact_and_alias_queries_are_separate_channels():
    async def scenario():
        client = FakeQdrantClient()
        client.points = [SimpleNamespace(payload=column_payload())]
        repository = ColumnQdrantRepository(client)
        channels = await repository.search_channels(" 收入 ", [0.1, 0.2], limit=5)
        return channels, client

    channels, client = asyncio.run(scenario())
    assert set(channels) == {"dense", "lexical", "exact", "alias"}
    assert all(items[0].entity_type == "column" for items in channels.values())
    assert all(items[0].candidate_id == "fact_payment.amount" for items in channels.values())
    assert client.queries[0]["using"] == "dense"
    assert client.queries[1]["using"] == "bm25"
    assert client.queries[1]["query"].text == "收入"
    assert len(client.scrolls) == 2


def test_column_and_metric_point_ids_are_type_isolated():
    assert ColumnQdrantRepository.stable_point_id(
        "shared"
    ) != MetricQdrantRepository.stable_point_id("shared")


def test_repository_rejects_cross_type_payload():
    async def scenario():
        repository = ColumnQdrantRepository(FakeQdrantClient())
        payload = {**column_payload(), "entity_type": "metric"}
        await repository.upsert_entities([payload], [[0.1]])

    try:
        asyncio.run(scenario())
    except ValueError as error:
        assert "entity_type" in str(error)
    else:
        raise AssertionError("cross-type payload must fail")


def test_client_passes_documents_to_self_hosted_server_inference(monkeypatch):
    captured = {}

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(manager_module, "AsyncQdrantClient", FakeAsyncClient)
    manager = manager_module.QdrantClientManager(
        QdrantConfig(host="qdrant", port=6333, embedding_size=1024)
    )
    manager.init()

    assert captured == {
        "url": "http://qdrant:6333",
        "cloud_inference": True,
    }
