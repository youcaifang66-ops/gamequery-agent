import asyncio
import uuid
from typing import Any, Generic, TypeVar

from qdrant_client import AsyncQdrantClient, models

from app.conf.app_config import app_config
from app.retrieval.fusion import Candidate, Channel, EntityType

Entity = TypeVar("Entity")
POINT_NAMESPACE = uuid.UUID("766a92fe-43c9-4c42-bcad-6373ef7bf6d1")
BM25_MODEL = "Qdrant/bm25"


def bm25_document(text: str) -> models.Document:
    return models.Document(
        text=text,
        model=BM25_MODEL,
        options=models.Bm25Config(
            tokenizer=models.TokenizerType.MULTILINGUAL,
            lowercase=True,
        ),
    )


def normalize_term(value: str) -> str:
    return " ".join(value.casefold().split())


class HybridQdrantRepository(Generic[Entity]):
    """Qdrant dense/BM25 双通道仓储；子类只声明实体类型与转换器。"""

    collection_name: str
    entity_type: EntityType
    entity_class: type[Entity]

    def __init__(self, client: AsyncQdrantClient):
        self.client = client

    @classmethod
    def stable_point_id(cls, entity_id: str) -> uuid.UUID:
        return uuid.uuid5(POINT_NAMESPACE, f"{cls.entity_type}:{entity_id}")

    async def is_available(self) -> bool:
        return await self.client.collection_exists(self.collection_name)

    async def ensure_collection(self) -> None:
        if not await self.is_available():
            await self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config={
                    "dense": models.VectorParams(
                        size=app_config.qdrant.embedding_size,
                        distance=models.Distance.COSINE,
                    )
                },
                sparse_vectors_config={
                    "bm25": models.SparseVectorParams(modifier=models.Modifier.IDF)
                },
            )

    async def upsert_entities(
        self,
        payloads: list[dict[str, Any]],
        embeddings: list[list[float]],
        *,
        batch_size: int = 10,
    ) -> None:
        if len(payloads) != len(embeddings):
            raise ValueError("payloads and embeddings must have equal length")
        points = []
        for payload, embedding in zip(payloads, embeddings, strict=True):
            if payload.get("entity_type") != self.entity_type:
                raise ValueError("payload entity_type does not match repository")
            entity_id = str(payload["entity_id"])
            points.append(
                models.PointStruct(
                    id=self.stable_point_id(entity_id),
                    vector={
                        "dense": embedding,
                        "bm25": bm25_document(str(payload["retrieval_text"])),
                    },
                    payload=payload,
                )
            )
        for index in range(0, len(points), batch_size):
            await self.client.upsert(
                collection_name=self.collection_name,
                points=points[index : index + batch_size],
                wait=True,
            )

    @staticmethod
    def _business_payload(payload: dict[str, Any]) -> dict[str, Any]:
        metadata_fields = {
            "entity_type",
            "entity_id",
            "retrieval_text",
            "normalized_name",
            "normalized_aliases",
        }
        return {key: value for key, value in payload.items() if key not in metadata_fields}

    def _candidate(self, point: Any) -> Candidate:
        payload = dict(point.payload or {})
        if payload.get("entity_type") != self.entity_type:
            raise ValueError("Qdrant returned a cross-type payload")
        return Candidate(
            entity_type=self.entity_type,
            candidate_id=str(payload["entity_id"]),
            payload=self._business_payload(payload),
        )

    def _type_filter(self, *conditions: models.FieldCondition) -> models.Filter:
        return models.Filter(
            must=[
                models.FieldCondition(
                    key="entity_type", match=models.MatchValue(value=self.entity_type)
                ),
                *conditions,
            ]
        )

    async def search_dense(
        self, embedding: list[float], *, limit: int = 20
    ) -> list[Candidate]:
        result = await self.client.query_points(
            collection_name=self.collection_name,
            query=embedding,
            using="dense",
            query_filter=self._type_filter(),
            limit=limit,
            with_payload=True,
        )
        return [self._candidate(point) for point in result.points]

    async def search_lexical(self, text: str, *, limit: int = 20) -> list[Candidate]:
        result = await self.client.query_points(
            collection_name=self.collection_name,
            query=bm25_document(normalize_term(text)),
            using="bm25",
            query_filter=self._type_filter(),
            limit=limit,
            with_payload=True,
        )
        return [self._candidate(point) for point in result.points]

    async def search_exact(
        self, text: str, *, field: str = "name", limit: int = 20
    ) -> list[Candidate]:
        payload_field = {
            "name": "normalized_name",
            "alias": "normalized_aliases",
        }.get(field)
        if payload_field is None:
            raise ValueError("field must be name or alias")
        points, _ = await self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=self._type_filter(
                models.FieldCondition(
                    key=payload_field,
                    match=models.MatchValue(value=normalize_term(text)),
                )
            ),
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        return [self._candidate(point) for point in points]

    async def search_channels(
        self, text: str, embedding: list[float], *, limit: int = 20
    ) -> dict[Channel, list[Candidate]]:
        dense, lexical, exact, alias = await asyncio.gather(
            self.search_dense(embedding, limit=limit),
            self.search_lexical(text, limit=limit),
            self.search_exact(text, field="name", limit=limit),
            self.search_exact(text, field="alias", limit=limit),
        )
        return {
            "dense": dense,
            "lexical": lexical,
            "exact": exact,
            "alias": alias,
        }

    async def search(
        self, embedding: list[float], score_threshold: float = 0.0, limit: int = 20
    ) -> list[Entity]:
        """兼容迁移期旧调用方；v2 dense 结果仍还原为业务实体。"""

        del score_threshold
        candidates = await self.search_dense(embedding, limit=limit)
        return [self.entity_class(**candidate.payload) for candidate in candidates]
