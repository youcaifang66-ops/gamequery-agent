from app.retrieval.fusion import Candidate, ReciprocalRankFusion


def candidate(identifier):
    return Candidate(identifier, {"name": identifier})


def test_candidate_seen_by_multiple_channels_ranks_first():
    result = ReciprocalRankFusion().fuse(
        {
            "vector": [candidate("fact_payment.amount"), candidate("fact_player_daily.is_active")],
            "exact": [candidate("fact_payment.amount")],
            "llm_expand": [candidate("fact_payment.player_id")],
        }
    )
    assert result[0].candidate_id == "fact_payment.amount"
    assert {item["channel"] for item in result[0].evidence} == {"vector", "exact"}


def test_fusion_is_deterministic_for_equal_scores():
    result = ReciprocalRankFusion().fuse({"vector": [candidate("b"), candidate("a")]})
    assert [item.candidate_id for item in result] == ["b", "a"]
