import pytest

from app.retrieval.fusion import Candidate, ReciprocalRankFusion


def candidate(identifier: str, entity_type="column"):
    return Candidate(entity_type, identifier, {"name": identifier})


def test_candidate_seen_by_dense_and_lexical_channels_ranks_first():
    result = ReciprocalRankFusion().fuse(
        "column",
        {
            "dense": [
                candidate("fact_payment.amount"),
                candidate("fact_player_daily.is_active"),
            ],
            "lexical": [candidate("fact_payment.amount")],
            "llm_expand": [candidate("fact_payment.player_id")],
        },
    )
    assert result[0].candidate_id == "fact_payment.amount"
    assert {item.channel for item in result[0].evidence} == {"dense", "lexical"}
    assert all(item.rank >= 1 for item in result[0].evidence)


def test_fusion_rejects_cross_type_candidates():
    with pytest.raises(ValueError, match="cannot fuse metric into column"):
        ReciprocalRankFusion().fuse(
            "column", {"dense": [candidate("Revenue", "metric")]}
        )


def test_duplicate_business_ids_are_one_result_with_all_evidence():
    result = ReciprocalRankFusion().fuse(
        "metric",
        {
            "exact": [candidate("DAU", "metric")],
            "alias": [candidate("DAU", "metric")],
            "lexical": [candidate("DAU", "metric")],
        },
    )
    assert [item.candidate_id for item in result] == ["DAU"]
    assert [evidence.channel for evidence in result[0].evidence] == [
        "exact",
        "alias",
        "lexical",
    ]


def test_empty_channels_and_nonpositive_top_k_return_empty():
    fusion = ReciprocalRankFusion()
    assert fusion.fuse("column", {}) == []
    assert fusion.fuse("column", {"dense": []}) == []
    assert fusion.fuse("column", {"dense": [candidate("a")]}, top_k=0) == []


def test_fusion_is_deterministic_across_one_hundred_runs():
    channels = {
        "dense": [candidate("b"), candidate("a")],
        "lexical": [candidate("a"), candidate("b")],
    }
    expected = ReciprocalRankFusion().fuse("column", channels)
    for _ in range(100):
        assert ReciprocalRankFusion().fuse("column", channels) == expected
    assert [item.candidate_id for item in expected] == ["b", "a"]
