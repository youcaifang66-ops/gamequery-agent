import asyncio
from unittest.mock import MagicMock

from app.entities.column_info import ColumnInfo
from app.entities.metric_info import MetricInfo
from app.services.meta_knowledge_service import MetaKnowledgeService


class FakeEmbedding:
    def __init__(self):
        self.batches = []

    async def aembed_documents(self, texts):
        self.batches.append(texts)
        return [[float(index), 0.5] for index, _ in enumerate(texts, start=1)]


class FakeHybridRepository:
    def __init__(self):
        self.ensure_calls = 0
        self.upserts = []

    async def ensure_collection(self):
        self.ensure_calls += 1

    async def upsert_entities(self, payloads, embeddings):
        self.upserts.append((payloads, embeddings))


def make_service(column_repository, metric_repository, embedding):
    return MetaKnowledgeService(
        meta_mysql_repository=MagicMock(),
        dw_mysql_repository=MagicMock(),
        column_qdrant_repository=column_repository,
        embedding_client=embedding,
        value_es_repository=MagicMock(),
        metric_qdrant_repository=metric_repository,
    )


def test_column_index_has_one_hybrid_payload_per_entity():
    async def scenario():
        repository = FakeHybridRepository()
        embedding = FakeEmbedding()
        service = make_service(repository, FakeHybridRepository(), embedding)
        columns = [
            ColumnInfo(
                id="fact_payment.amount",
                name="amount",
                type="decimal",
                role="measure",
                examples=[30],
                description="支付金额",
                alias=["收入", "付费金额"],
                table_id="fact_payment",
            )
        ]
        await service._save_column_info_to_qdrant(columns)
        return repository, embedding

    repository, embedding = asyncio.run(scenario())
    assert repository.ensure_calls == 1
    payloads, embeddings = repository.upserts[0]
    assert len(payloads) == len(embeddings) == 1
    assert payloads[0]["entity_type"] == "column"
    assert payloads[0]["entity_id"] == "fact_payment.amount"
    assert payloads[0]["normalized_aliases"] == ["收入", "付费金额"]
    assert "支付金额" in payloads[0]["retrieval_text"]
    assert embedding.batches == [[payloads[0]["retrieval_text"]]]


def test_metric_rebuild_inputs_are_stable_and_idempotent():
    async def scenario():
        repository = FakeHybridRepository()
        embedding = FakeEmbedding()
        service = make_service(FakeHybridRepository(), repository, embedding)
        metrics = [
            MetricInfo(
                id="DAU",
                name="DAU",
                description="每日活跃玩家去重数",
                relevant_columns=["fact_player_daily.player_id"],
                alias=["日活"],
            )
        ]
        await service._save_metrics_to_qdrant(metrics)
        await service._save_metrics_to_qdrant(metrics)
        return repository

    repository = asyncio.run(scenario())
    first_payloads, first_embeddings = repository.upserts[0]
    second_payloads, second_embeddings = repository.upserts[1]
    assert first_payloads == second_payloads
    assert first_embeddings == second_embeddings
    assert first_payloads[0]["entity_type"] == "metric"
    assert "fact_player_daily.player_id" in first_payloads[0]["retrieval_text"]
