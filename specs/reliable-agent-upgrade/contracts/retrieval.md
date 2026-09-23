# Contract: Hybrid Retrieval and Evidence

## Index Contract

- Collections: `column_info_collection_v2`, `metric_info_collection_v2`.
- One point per business entity with deterministic UUID5 id.
- Named vectors: `dense` (configured dimension/cosine), `bm25` (sparse with IDF modifier).
- Payload follows `data-model.md`; `entity_type` prevents cross-type search.
- Rebuild is idempotent and does not mutate v1 collections.

## Query Channels

| Channel | Input | Output ranking |
|---|---|---|
| dense | original normalized query embedding | semantic entity ids |
| lexical | original normalized text BM25 | lexical entity ids |
| exact | normalized exact entity name | exact entity ids |
| alias | normalized exact alias | alias entity ids |
| llm_expand | expanded keyword embeddings | semantic entity ids |

Each channel returns ordered `Candidate` objects with stable business ids. Raw scores are diagnostic only and never directly added across channels.

## Fusion Contract

```text
fuse(entity_type, channels, top_k) -> list[RetrievalCandidate]
```

- One fusion call accepts exactly one entity type.
- RRF contribution for each item is reproducible from configured `k`, channel weight and 1-based rank.
- Duplicate business ids appear once with all evidence entries retained.
- Ties use deterministic first-seen rank then candidate id; 100 repeated runs are identical.
- Empty channels are valid; all-empty input returns an empty list.
- ValueES results remain `entity_type=value` and are relationally merged by `column_id`, never fused with columns or metrics.

## Fallback Contract

- If the v2 collection does not exist, startup/build status reports hybrid unavailable; it must not silently label v1 dense results as hybrid.
- Retrieval dependency errors become `RETRIEVAL_UNAVAILABLE`; SQL generation does not proceed with partial unknown context.

## Evaluation Contract

- Golden set contains at least 30 questions with expected ids and query category.
- Report includes per-channel and fused Hit@5/MRR, no-match false-positive rate, and sample-level evidence.
- Report field `mode` is `fixture` or `live`; fixture numbers cannot be presented as live Qdrant quality.
- Ablation reports fusion enabled and disabled over the same cases.
