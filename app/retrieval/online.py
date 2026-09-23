from collections.abc import Iterable

from app.retrieval.fusion import (
    Candidate,
    Channel,
    EntityType,
    FusedCandidate,
    ReciprocalRankFusion,
)


class RetrievalUnavailableError(RuntimeError):
    code = "RETRIEVAL_UNAVAILABLE"

    def __init__(self):
        super().__init__(self.code)


def _unique_candidates(candidates: Iterable[Candidate]) -> list[Candidate]:
    unique: dict[str, Candidate] = {}
    for candidate in candidates:
        unique.setdefault(candidate.candidate_id, candidate)
    return list(unique.values())


def _unique_terms(terms: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(term.strip() for term in terms if term.strip()))


async def retrieve_metadata_candidates(
    *,
    entity_type: EntityType,
    query: str,
    exact_terms: list[str],
    expanded_terms: list[str],
    embedding_client,
    repository,
    top_k: int = 20,
) -> list[FusedCandidate]:
    if not await repository.is_available():
        raise RetrievalUnavailableError()

    query_embedding = await embedding_client.aembed_query(query)
    channels: dict[Channel, list[Candidate]] = await repository.search_channels(
        query, query_embedding, limit=top_k
    )

    exact_candidates = list(channels["exact"])
    alias_candidates = list(channels["alias"])
    for term in _unique_terms(exact_terms):
        exact_candidates.extend(
            await repository.search_exact(term, field="name", limit=top_k)
        )
        alias_candidates.extend(
            await repository.search_exact(term, field="alias", limit=top_k)
        )
    channels["exact"] = _unique_candidates(exact_candidates)
    channels["alias"] = _unique_candidates(alias_candidates)

    expanded_candidates: list[Candidate] = []
    for term in _unique_terms(expanded_terms):
        embedding = await embedding_client.aembed_query(term)
        expanded_candidates.extend(
            await repository.search_dense(embedding, limit=top_k)
        )
    channels["llm_expand"] = _unique_candidates(expanded_candidates)
    return ReciprocalRankFusion().fuse(entity_type, channels, top_k=top_k)
