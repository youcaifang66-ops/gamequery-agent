import asyncio
import os
import uuid

import asyncmy
import pytest
from qdrant_client import AsyncQdrantClient, models

RUN_INTEGRATION = os.getenv("RUN_SERVICE_INTEGRATION") == "1"
pytestmark = pytest.mark.skipif(
    not RUN_INTEGRATION,
    reason="set RUN_SERVICE_INTEGRATION=1 with MySQL and Qdrant running",
)


def test_dw_reader_can_select_but_cannot_modify_or_define_schema():
    async def scenario():
        connection = await asyncmy.connect(
            host=os.getenv("DW_DB_HOST", "127.0.0.1"),
            port=int(os.getenv("DW_DB_PORT", "3306")),
            user=os.getenv("DW_DB_USER", "gamequery_reader"),
            password=os.environ["DW_DB_PASSWORD"],
            db="dw",
            autocommit=False,
        )
        try:
            async with connection.cursor() as cursor:
                await cursor.execute("SELECT COUNT(*) FROM fact_payment")
                assert (await cursor.fetchone())[0] >= 0
                denied = [
                    "INSERT INTO fact_payment VALUES ('DENIED','P001','G001',20260918,1,'CNY')",
                    "UPDATE fact_payment SET amount=0 WHERE payment_id='PAY001'",
                    "DELETE FROM fact_payment WHERE payment_id='PAY001'",
                    "CREATE TABLE denied_table(id INT)",
                    "DROP TABLE fact_payment",
                ]
                for statement in denied:
                    with pytest.raises(asyncmy.errors.OperationalError):
                        await cursor.execute(statement)
                    await connection.rollback()
                await cursor.execute("SELECT amount FROM fact_payment LIMIT 1")
                assert await cursor.fetchone() is not None
        finally:
            connection.close()

    asyncio.run(scenario())


def test_self_hosted_qdrant_supports_dense_and_native_bm25_channels():
    async def scenario():
        client = AsyncQdrantClient(
            url=os.getenv("QDRANT_URL", "http://127.0.0.1:6333"),
            cloud_inference=True,
            timeout=10,
        )
        collection = f"integration_{uuid.uuid4().hex}"
        try:
            for attempt in range(20):
                try:
                    await client.get_collections()
                    break
                except Exception:
                    if attempt == 19:
                        raise
                    await asyncio.sleep(0.5)
            await client.create_collection(
                collection_name=collection,
                vectors_config={
                    "dense": models.VectorParams(size=2, distance=models.Distance.COSINE)
                },
                sparse_vectors_config={
                    "bm25": models.SparseVectorParams(modifier=models.Modifier.IDF)
                },
            )
            document = models.Document(
                text="游戏支付金额 收入",
                model="Qdrant/bm25",
                options=models.Bm25Config(
                    tokenizer=models.TokenizerType.MULTILINGUAL,
                    lowercase=True,
                ),
            )
            await client.upsert(
                collection_name=collection,
                wait=True,
                points=[
                    models.PointStruct(
                        id=1,
                        vector={"dense": [1.0, 0.0], "bm25": document},
                        payload={"entity_type": "column"},
                    )
                ],
            )
            dense = await client.query_points(
                collection_name=collection,
                query=[1.0, 0.0],
                using="dense",
                limit=1,
            )
            lexical = await client.query_points(
                collection_name=collection,
                query=models.Document(
                    text="收入",
                    model="Qdrant/bm25",
                    options=models.Bm25Config(
                        tokenizer=models.TokenizerType.MULTILINGUAL,
                        lowercase=True,
                    ),
                ),
                using="bm25",
                limit=1,
            )
            assert dense.points[0].id == lexical.points[0].id == 1
        finally:
            if await client.collection_exists(collection):
                await client.delete_collection(collection)
            await client.close()

    asyncio.run(scenario())
