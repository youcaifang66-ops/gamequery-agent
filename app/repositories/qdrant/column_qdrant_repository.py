from app.entities.column_info import ColumnInfo
from app.repositories.qdrant.hybrid_repository import HybridQdrantRepository


class ColumnQdrantRepository(HybridQdrantRepository[ColumnInfo]):
    collection_name = "column_info_collection_v2"
    entity_type = "column"
    entity_class = ColumnInfo
