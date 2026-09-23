# Contract: Async Trace Store

## Lifecycle

```text
await open()
await start(trace_id, query_digest)
await append(trace_id, event_type, sanitized_payload) -> sequence
await finish(trace_id, status, error_code=None)
await replay(trace_id) -> Trace | None
await close()
```

## Invariants

- `start` is idempotent only for the exact same trace id and digest; conflicting reuse fails.
- `append` allocates the next sequence and inserts the event in one transaction.
- `finish` permits `running -> completed|failed|cancelled` once; a second different terminal state fails.
- `replay` always orders events by sequence.
- A result event persists only `row_count`, never row values.
- Exception payloads persist stable code/stage, never raw repr, traceback, credentials or connection URLs.
- All methods require `open`; use after `close` fails with a stable store error.

## Concurrency Contract

- One store instance supports at least 20 concurrent traces in one process.
- Concurrent append calls for the same trace produce unique continuous sequences.
- WAL mode and busy timeout are initialized before accepting writes.
- SQLite is explicitly a single-instance deployment choice; no cross-process correctness claim.

## Failure Handling

- If trace persistence fails, QueryService emits a sanitized `INTERNAL_ERROR` and does not execute further SQL.
- On client cancellation, QueryService attempts `finish(cancelled)` under a short shielded cleanup timeout, then re-raises cancellation.
