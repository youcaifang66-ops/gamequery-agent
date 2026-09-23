from app.entities.metric_info import MetricInfo
from app.repositories.qdrant.hybrid_repository import HybridQdrantRepository


class MetricQdrantRepository(HybridQdrantRepository[MetricInfo]):
    collection_name = "metric_info_collection_v2"
    entity_type = "metric"
    entity_class = MetricInfo
