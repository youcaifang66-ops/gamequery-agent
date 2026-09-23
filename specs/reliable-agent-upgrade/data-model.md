# Data Model: GameQuery 可靠性补全

## Spec Reference

Implements: `specs/reliable-agent-upgrade/spec.md`

## Runtime Entities

### GuardedSQL

| Field | Type | Constraints | Description |
|---|---|---|---|
| sql | str | non-empty | 规范化、封顶并带超时策略的唯一可执行 SQL |
| tables | tuple[str, ...] | allow-list only | 物理业务表集合 |
| max_rows | int | 1..500 | 最终结果上限 |
| limit_action | enum | kept/added/capped | LIMIT 处理证据 |
| timeout_ms | int | >0 | 数据库执行预算 |

### QueryFailure

| Field | Type | Constraints | Description |
|---|---|---|---|
| code | str | stable enum | 机器错误码 |
| safe_message | str | no internal exception | 客户端消息 |
| correctable | bool | required | 是否允许进入自动纠错 |
| stage | str | stable enum | guard/explain/run/retrieval/workflow |

### RetrievalCandidate

| Field | Type | Constraints | Description |
|---|---|---|---|
| entity_type | enum | column/metric/value | 候选类型隔离键 |
| candidate_id | str | unique within type | 稳定业务 id |
| payload | object | type-specific | 下游所需实体数据 |
| score | float | derived | RRF 总分 |
| evidence | tuple[RetrievalEvidence, ...] | non-empty | 可复算通道证据 |

### RetrievalEvidence

| Field | Type | Constraints | Description |
|---|---|---|---|
| channel | enum | dense/lexical/exact/alias/llm_expand | 命中来源 |
| rank | int | >=1 | 通道内排名 |
| contribution | float | >=0 | 对融合分数贡献 |

## Persistence Entities

### query_trace

| Field | SQLite Type | Constraints | Description |
|---|---|---|---|
| trace_id | TEXT | PK | 与 request id 相同 |
| query_digest | TEXT | NOT NULL | 原问题 SHA-256，不存原文 |
| status | TEXT | CHECK running/completed/failed/cancelled | 生命周期状态 |
| started_at | TEXT | NOT NULL UTC ISO-8601 | 开始时间 |
| finished_at | TEXT | nullable UTC ISO-8601 | 终态时间 |
| error_code | TEXT | nullable | 安全错误码 |

### trace_event

| Field | SQLite Type | Constraints | Description |
|---|---|---|---|
| id | INTEGER | PK AUTOINCREMENT | 存储主键 |
| trace_id | TEXT | FK-like, NOT NULL | 所属 trace |
| sequence | INTEGER | UNIQUE(trace_id, sequence), >=1 | 严格顺序 |
| event_type | TEXT | allowed enum | progress/sql/result/error/done/clarification |
| payload | TEXT | valid sanitized JSON | 不含完整结果和凭据 |
| created_at | TEXT | NOT NULL UTC ISO-8601 | 事件时间 |

### Relationships and Indexes

- `query_trace` 1:N `trace_event`，删除 trace 时事件一并删除。
- `trace_event(trace_id, sequence)` 唯一索引保证回放顺序。
- `query_trace(started_at)` 索引用于可选保留清理。
- SQLite 初始化启用 WAL 和 busy timeout；单进程内 append 由异步锁包围事务。

## Qdrant v2 Point Shape

### Column Point

| Field | Type | Description |
|---|---|---|
| point id | UUID5(column id) | 重建稳定 |
| vector.dense | float[1024] | name + description + alias 的 dense 表示 |
| vector.bm25 | sparse Document | 同一检索文本的 lexical 表示 |
| payload.entity_type | `column` | 类型隔离 |
| payload.entity_id | str | `table.column` |
| payload.name/description/alias | typed fields | 精确与别名通道及下游实体 |
| payload.retrieval_text | str | 可审计索引文本 |

### Metric Point

与 Column Point 同结构，`entity_type=metric`，`entity_id` 为指标稳定 id，payload 额外保存 `relevant_columns`。

## Migration

- 不修改旧 `column_info_collection` 和 `metric_info_collection`。
- 新建 `column_info_collection_v2` 与 `metric_info_collection_v2`，构建成功后由配置切换读取。
- 构建过程使用稳定 point id，可重复 upsert；失败时继续读取旧 collection，不能声称 hybrid 已启用。
- SQLite trace schema 使用 `CREATE TABLE IF NOT EXISTS`；旧同步 TraceStore 数据不自动迁移，测试/演示环境可归档旧文件。
