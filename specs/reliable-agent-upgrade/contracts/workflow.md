# Contract: Workflow Graph

## Barriers

- `merge_retrieved_info` has one explicit barrier requiring column, metric and value recalls.
- `add_extra_context` has one explicit barrier requiring table and metric filters.
- A barrier successor executes exactly once regardless of predecessor completion order.

## Routing after SQL Validation

| Validation outcome | Attempts | Route |
|---|---:|---|
| success | any | run_sql |
| correctable failure | 0 or 1 | correct_sql |
| correctable failure | 2 | terminal CORRECTION_EXHAUSTED |
| non-correctable failure | any | terminal SQL_POLICY_DENIED |

Corrected SQL always routes back to full validation.

## Test Injection

Graph construction accepts a complete default node set and optional named replacements used only by tests. Missing/unknown replacement names fail at construction. Production creates the graph from defaults.

## Deterministic End-to-End Scenarios

1. Success on first candidate.
2. One correctable failure then success.
3. Two repairs then exhaustion.
4. Non-correctable safety rejection with no correction call.
5. Retrieval dependency failure.
6. Query timeout.

Each scenario asserts visited nodes, SQL versions, Repository calls and exactly one stream terminal.

## Resource Cleanup

- Successful, failed, timed-out and cancelled runs all close request sessions through FastAPI dependencies.
- Timeout and cancellation do not close shared Qdrant/ES/Embedding clients; application lifespan closes them once.
- Query trace reaches `completed`, `failed` or `cancelled` exactly once.
