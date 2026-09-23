from dataclasses import dataclass
from typing import Literal

EntityType = Literal["column", "metric", "value"]
Channel = Literal["dense", "lexical", "exact", "alias", "llm_expand"]


@dataclass(frozen=True)
class Candidate:
    entity_type: EntityType
    candidate_id: str
    payload: dict


@dataclass(frozen=True)
class RetrievalEvidence:
    channel: Channel
    rank: int
    contribution: float


@dataclass(frozen=True)
class FusedCandidate:
    entity_type: EntityType
    candidate_id: str
    payload: dict
    score: float
    evidence: tuple[RetrievalEvidence, ...]


class ReciprocalRankFusion:
    """只在同类实体内融合排名，不直接相加不同检索器的原始分数。"""

    def __init__(self, k: int = 60, channel_weights: dict[str, float] | None = None):
        if k < 1:
            raise ValueError("k must be positive")
        self.k = k
        self.channel_weights = channel_weights or {
            "dense": 1.0,
            "lexical": 1.0,
            "exact": 1.25,
            "alias": 1.15,
            "llm_expand": 0.8,
        }

    def fuse(
        self,
        entity_type: EntityType,
        channels: dict[Channel, list[Candidate]],
        top_k: int = 10,
    ) -> list[FusedCandidate]:
        if top_k < 1:
            return []
        fused: dict[str, dict] = {}
        for channel_index, (channel, candidates) in enumerate(channels.items()):
            weight = self.channel_weights.get(channel, 1.0)
            for rank, candidate in enumerate(candidates, start=1):
                if candidate.entity_type != entity_type:
                    raise ValueError(
                        f"cannot fuse {candidate.entity_type} into {entity_type}"
                    )
                item = fused.setdefault(
                    candidate.candidate_id,
                    {
                        "payload": candidate.payload,
                        "score": 0.0,
                        "evidence": [],
                        "first_seen": (channel_index, rank),
                    },
                )
                contribution = weight / (self.k + rank)
                item["score"] += contribution
                item["evidence"].append(
                    RetrievalEvidence(
                        channel=channel,
                        rank=rank,
                        contribution=round(contribution, 8),
                    )
                )
        ranked = sorted(
            fused.items(),
            key=lambda pair: (
                -pair[1]["score"],
                pair[1]["first_seen"],
                pair[0],
            ),
        )[:top_k]
        return [
            FusedCandidate(
                entity_type=entity_type,
                candidate_id=candidate_id,
                payload=item["payload"],
                score=round(item["score"], 8),
                evidence=tuple(item["evidence"]),
            )
            for candidate_id, item in ranked
        ]
