import asyncio
import importlib
from types import SimpleNamespace

import pytest

from app.retrieval.fusion import Candidate
from app.retrieval.online import (
    RetrievalUnavailableError,
    retrieve_metadata_candidates,
)

column_node = importlib.import_module("app.agent.nodes.recall_column")
metric_node = importlib.import_module("app.agent.nodes.recall_metric")


def column_candidate(identifier="fact_payment.amount"):
    return Candidate(
        "column",
        identifier,
        {
            "id": identifier,
            "name": identifier.split(".")[-1],
            "type": "decimal",
            "role": "measure",
            "examples": [30],
            "description": "支付金额",
            "alias": ["收入"],
            "table_id": identifier.split(".")[0],
        },
    )


def metric_candidate(identifier="Revenue"):
    return Candidate(
        "metric",
        identifier,
        {
            "id": identifier,
            "name": identifier,
            "description": "支付金额总和",
            "relevant_columns": ["fact_payment.amount"],
            "alias": ["收入"],
        },
    )


class FakeEmbedding:
    def __init__(self):
        self.queries = []

    async def aembed_query(self, text):
        self.queries.append(text)
        return [float(len(self.queries))]


class FakeRepository:
    def __init__(self, candidate, available=True):
        self.candidate = candidate
        self.available = available
        self.channel_queries = []
        self.exact_queries = []
        self.dense_queries = []

    async def is_available(self):
        return self.available

    async def search_channels(self, text, embedding, limit):
        self.channel_queries.append((text, embedding, limit))
        return {
            "dense": [self.candidate],
            "lexical": [self.candidate],
            "exact": [],
            "alias": [],
        }

    async def search_exact(self, text, field, limit):
        self.exact_queries.append((text, field, limit))
        return [self.candidate] if field == "alias" else []

    async def search_dense(self, embedding, limit):
        self.dense_queries.append((embedding, limit))
        return [self.candidate]


def test_online_retrieval_uses_original_exact_alias_lexical_and_expansion():
    async def scenario():
        embedding = FakeEmbedding()
        repository = FakeRepository(column_candidate())
        result = await retrieve_metadata_candidates(
            entity_type="column",
            query="星海远征收入",
            exact_terms=["收入", "收入"],
            expanded_terms=["付费金额", "付费金额"],
            embedding_client=embedding,
            repository=repository,
        )
        return result, embedding, repository

    result, embedding, repository = asyncio.run(scenario())
    assert embedding.queries == ["星海远征收入", "付费金额"]
    assert repository.channel_queries[0][0] == "星海远征收入"
    assert [(item[0], item[1]) for item in repository.exact_queries] == [
        ("收入", "name"),
        ("收入", "alias"),
    ]
    assert {item.channel for item in result[0].evidence} == {
        "dense",
        "lexical",
        "alias",
        "llm_expand",
    }


def test_missing_v2_collection_fails_explicitly():
    async def scenario():
        await retrieve_metadata_candidates(
            entity_type="column",
            query="收入",
            exact_terms=[],
            expanded_terms=[],
            embedding_client=FakeEmbedding(),
            repository=FakeRepository(column_candidate(), available=False),
        )

    with pytest.raises(RetrievalUnavailableError, match="RETRIEVAL_UNAVAILABLE"):
        asyncio.run(scenario())


def test_column_node_outputs_entities_and_serializable_evidence(monkeypatch):
    async def expansions(query):
        return ["付费金额"]

    async def scenario():
        monkeypatch.setattr(column_node, "_expand_keywords", expansions)
        events = []
        runtime = SimpleNamespace(
            stream_writer=events.append,
            context={
                "embedding_client": FakeEmbedding(),
                "column_qdrant_repository": FakeRepository(column_candidate()),
            },
        )
        result = await column_node.recall_column(
            {"query": "收入", "keywords": ["收入"]}, runtime
        )
        return result, events

    result, events = asyncio.run(scenario())
    assert result["retrieved_column_infos"][0].id == "fact_payment.amount"
    evidence = result["column_retrieval_evidence"][0]
    assert evidence["entity_type"] == "column"
    assert evidence["entity_id"] == "fact_payment.amount"
    assert {item["channel"] for item in evidence["evidence"]} >= {
        "dense",
        "lexical",
    }
    assert [event["status"] for event in events] == ["running", "success"]


def test_metric_node_never_fuses_with_column_candidates(monkeypatch):
    async def expansions(query):
        return ["总付费"]

    async def scenario():
        monkeypatch.setattr(metric_node, "_expand_keywords", expansions)
        runtime = SimpleNamespace(
            stream_writer=lambda event: None,
            context={
                "embedding_client": FakeEmbedding(),
                "metric_qdrant_repository": FakeRepository(metric_candidate()),
            },
        )
        return await metric_node.recall_metric(
            {"query": "收入", "keywords": ["收入"]}, runtime
        )

    result = asyncio.run(scenario())
    assert result["retrieved_metric_infos"][0].id == "Revenue"
    assert {item["entity_type"] for item in result["metric_retrieval_evidence"]} == {
        "metric"
    }
