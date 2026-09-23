import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.retrieval.fusion import Candidate, ReciprocalRankFusion  # noqa: E402

CHANNELS = ("dense", "lexical", "exact", "alias", "llm_expand")


def ranking_metrics(cases: list[dict], rankings: dict[str, list[str]]) -> dict:
    match_cases = [case for case in cases if case["expected_ids"]]
    no_match_cases = [case for case in cases if not case["expected_ids"]]
    hits = 0
    reciprocal_ranks = 0.0
    for case in match_cases:
        expected = set(case["expected_ids"])
        ranking = rankings[case["id"]]
        rank = next(
            (index for index, entity_id in enumerate(ranking, start=1) if entity_id in expected),
            None,
        )
        if rank is not None and rank <= 5:
            hits += 1
        if rank is not None:
            reciprocal_ranks += 1 / rank
    false_positives = sum(bool(rankings[case["id"]]) for case in no_match_cases)
    return {
        "hit_at_5": round(hits / len(match_cases), 4),
        "mrr": round(reciprocal_ranks / len(match_cases), 4),
        "no_match_false_positive_rate": round(
            false_positives / len(no_match_cases), 4
        ),
    }


def value_ranking(case: dict) -> tuple[list[str], list[dict]]:
    ranking = list(
        dict.fromkeys(
            case["fixture_rankings"].get("exact", [])
            + case["fixture_rankings"].get("lexical", [])
        )
    )
    evidence = [
        {"entity_id": entity_id, "channels": ["exact_or_lexical"]}
        for entity_id in ranking
    ]
    return ranking, evidence


def fused_ranking(case: dict) -> tuple[list[str], list[dict], bool]:
    if case["entity_type"] == "value":
        ranking, evidence = value_ranking(case)
        return ranking, evidence, False
    channels = {
        channel: [
            Candidate(case["entity_type"], entity_id, {"id": entity_id})
            for entity_id in case["fixture_rankings"].get(channel, [])
        ]
        for channel in CHANNELS
    }
    fused = ReciprocalRankFusion().fuse(case["entity_type"], channels, top_k=5)
    return (
        [candidate.candidate_id for candidate in fused],
        [
            {
                "entity_id": candidate.candidate_id,
                "score": candidate.score,
                "evidence": [
                    {
                        "channel": item.channel,
                        "rank": item.rank,
                        "contribution": item.contribution,
                    }
                    for item in candidate.evidence
                ],
            }
            for candidate in fused
        ],
        True,
    )


def evaluate(mode: str = "fixture") -> dict:
    if mode != "fixture":
        raise RuntimeError("live mode requires configured Qdrant and embedding services")
    dataset_path = ROOT / "eval" / "retrieval_benchmark.json"
    dataset_bytes = dataset_path.read_bytes()
    dataset = json.loads(dataset_bytes.decode("utf-8"))
    cases = dataset["cases"]
    channel_rankings = {
        channel: {
            case["id"]: case["fixture_rankings"].get(channel, []) for case in cases
        }
        for channel in CHANNELS
    }
    fused_rankings = {}
    case_reports = []
    for case in cases:
        ranking, evidence, fusion_applied = fused_ranking(case)
        fused_rankings[case["id"]] = ranking
        case_reports.append(
            {
                "id": case["id"],
                "query": case["query"],
                "category": case["category"],
                "entity_type": case["entity_type"],
                "expected_ids": case["expected_ids"],
                "channel_rankings": {
                    channel: channel_rankings[channel][case["id"]]
                    for channel in CHANNELS
                },
                "fused_ranking": ranking,
                "fusion_applied": fusion_applied,
                "evidence": evidence,
            }
        )
    channels = {
        channel: ranking_metrics(cases, rankings)
        for channel, rankings in channel_rankings.items()
    }
    fused = ranking_metrics(cases, fused_rankings)
    report = {
        "mode": mode,
        "dataset_version": dataset["version"],
        "dataset_sha256": hashlib.sha256(dataset_bytes).hexdigest(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset_size": len(cases),
        "channels": channels,
        "fused": fused,
        "ablation": {
            "baseline": "dense_only",
            "fusion_delta_hit_at_5": round(
                fused["hit_at_5"] - channels["dense"]["hit_at_5"], 4
            ),
            "fusion_delta_mrr": round(fused["mrr"] - channels["dense"]["mrr"], 4),
        },
        "cases": case_reports,
    }
    (ROOT / "eval" / "latest_retrieval_metrics.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["fixture", "live"], default="fixture")
    args = parser.parse_args()
    print(json.dumps(evaluate(args.mode), ensure_ascii=False, indent=2))
