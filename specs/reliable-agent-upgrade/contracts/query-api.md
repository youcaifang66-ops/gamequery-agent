# Contract: Query API and SSE

## HTTP Request

`POST /api/query`

```json
{"query":"统计2026年9月18日各游戏DAU"}
```

- `query`: required string, 2–1000 characters.
- Request body remains backward compatible; caller-provided ids are not trusted in this iteration.
- Response content type: `text/event-stream`.
- Response header: `X-Request-ID: <uuid>`.

## SSE Encoding

Each message contains an SSE `event:` line and one JSON `data:` line. The JSON keeps the legacy top-level `type` field.

```text
event: progress
data: {"type":"progress","request_id":"...","sequence":1,"step":"校验SQL","status":"running"}

```

Common fields:

| Field | Type | Required | Rule |
|---|---|---|---|
| type | enum | yes | progress/sql/result/clarification/error/done |
| request_id | UUID string | yes | same for entire stream |
| sequence | integer | yes | starts at 1, strictly increments |

## Event Variants

### progress

```json
{"type":"progress","request_id":"...","sequence":1,"step":"召回字段","status":"running"}
```

`status`: `running | success | error`.

### sql

```json
{"type":"sql","request_id":"...","sequence":8,"version":1,"sql":"SELECT ... LIMIT 500"}
```

Only GuardedSQL may be emitted as executable SQL. Trace persistence may store SQL metadata but must not store credentials or results.

### result

```json
{"type":"result","request_id":"...","sequence":10,"data":[{"game_id":"G001","dau":2}]}
```

Result is sent to the client but persisted trace replaces `data` with `{"row_count":N}`.

### clarification

```json
{"type":"clarification","request_id":"...","sequence":6,"code":"MISSING_DATE","missing_slots":["date"],"message":"请提供要查询的日期。"}
```

Clarification is terminal for the current request and is followed by `done` with status `clarification`.

### error

```json
{"type":"error","request_id":"...","sequence":9,"code":"SQL_POLICY_DENIED","message":"查询不符合只读安全策略。"}
```

Error is terminal and no later events are emitted.

### done

```json
{"type":"done","request_id":"...","sequence":11,"status":"completed"}
```

`status`: `completed | clarification`. A successful/clarification stream has exactly one `done`; a failed/timeout stream has exactly one `error` and no `done`.

## Stable Error Codes

| Code | Stage | Correctable | Client message class |
|---|---|---:|---|
| INVALID_QUERY | api | no | 输入格式错误 |
| SQL_PARSE_ERROR | guard | yes | SQL 无法解析 |
| SQL_POLICY_DENIED | guard | no | 非只读/多语句/系统对象 |
| UNKNOWN_TABLE | guard | yes | 未知业务表 |
| UNKNOWN_COLUMN | guard | yes | 未知业务字段 |
| UNSUPPORTED_QUERY_SHAPE | guard | yes | 当前不支持的安全形状 |
| SQL_EXPLAIN_FAILED | explain | yes | 数据库预检失败 |
| CORRECTION_EXHAUSTED | workflow | no | 两次纠错仍失败 |
| QUERY_TIMEOUT | any I/O | no | 查询超时 |
| RETRIEVAL_UNAVAILABLE | retrieval | no | 检索依赖不可用 |
| DATABASE_UNAVAILABLE | explain/run | no | 数据库不可用 |
| INTERNAL_ERROR | workflow | no | 已清理内部错误 |

## Compatibility

- Existing frontend parsing only `data:` remains valid because named `event:` is additive.
- Existing `progress`, `result`, and `error` payload fields remain at the top level.
- `/health` response remains unchanged.
