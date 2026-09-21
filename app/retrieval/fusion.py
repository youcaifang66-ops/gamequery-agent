from dataclasses import dataclass


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    payload: dict


@dataclass(frozen=True)
class FusedCandidate:
    candidate_id: str
    payload: dict
    score: float
    evidence: tuple[dict, ...]


class ReciprocalRankFusion:
    """融合 Qdrant、ES、别名和 LLM 扩展等不同分数量纲的召回结果。"""

    def __init__(self, k: int = 60, channel_weights: dict[str, float] | None = None):
        self.k = k
        self.channel_weights = channel_weights or {
            "vector": 1.0,
            "exact": 1.25,
            "alias": 1.15,
            "llm_expand": 0.8,
        }

    def fuse(self, channels: dict[str, list[Candidate]], top_k: int = 10) -> list[FusedCandidate]:
        fused: dict[str, dict] = {}
        for channel, candidates in channels.items():
            weight = self.channel_weights.get(channel, 1.0)
            for rank, candidate in enumerate(candidates, start=1):
                item = fused.setdefault(
                    candidate.candidate_id,
                    {"payload": candidate.payload, "score": 0.0, "evidence": []},
                )
                contribution = weight / (self.k + rank)
                item["score"] += contribution
                item["evidence"].append(
                    {"channel": channel, "rank": rank, "contribution": round(contribution, 6)}
                )
        return [
            FusedCandidate(
                candidate_id=candidate_id,
                payload=item["payload"],
                score=round(item["score"], 6),
                evidence=tuple(item["evidence"]),
            )
            for candidate_id, item in sorted(
                fused.items(), key=lambda pair: (-pair[1]["score"], pair[0])
            )[:top_k]
        ]
