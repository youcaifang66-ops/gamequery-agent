# Data Model: 千万级合成业务数据与容量实证

## Dataset Artifacts

### Manifest

| Field | Type | Constraints | Description |
|---|---|---|---|
| dataset_version | string | required | 数据合同版本 |
| generator_version | string | required | 生成实现版本 |
| synthetic | bool | const true | 不含真实玩家数据 |
| seed | int | required | 随机种子 |
| requested_fact_rows | int | > 0 | 请求事实行数 |
| actual_fact_rows | int | exact match | 实际三表合计 |
| generated_at | ISO-8601 string | required | 生成时间，不参与内容摘要 |
| profile | object | required | 分布规则和阈值 |
| provenance | array | non-empty | 公开参考及许可/文档类型 |
| files | object | exact known files | 行数、字节数、SHA-256 |
| business_statistics | object | required | 分布实测值 |
| ground_truth_file | string | `ground_truth.json` | 标准答案路径 |

### GroundTruthCase

| Field | Type | Constraints | Description |
|---|---|---|---|
| id | string | unique | 稳定案例 ID |
| category | enum | six categories | DAU/revenue/payers/ARPU/pass-rate/channel |
| question | string | non-empty | 中文业务问题 |
| sql | string | single read-only query | 标准 SQL |
| params | object | required | 查询参数 |
| columns | string[] | non-empty | 有序结果列 |
| expected_rows | array[] | deterministic | 有序精确结果 |

### GenerationReport

包含 status、dataset version/seed/rows、git SHA、时间、OS/CPU/总内存/Python、elapsed seconds、peak RSS、output bytes、manifest SHA 和 scope。status 只能是 `measured`、`failed`、`not_run`。

## Experiment Database

实验数据库复制现有六表结构，不修改默认 `dw`。事实表导入完成后创建下列组合索引：

| Table | Columns | Rationale |
|---|---|---|
| fact_player_daily | `(date_id, game_id, player_id)` | DAU、ARPU 和渠道按日期/游戏去重 |
| fact_payment | `(date_id, game_id, player_id)` | 收入与付费人数按日期/游戏聚合 |
| fact_level_event | `(date_id, game_id, level_id)` | 月份/游戏/关卡通过率 |
| dim_player | `(acquisition_channel, player_id)` | 渠道拆分 Join |

所有主键仍使用生成器提供的稳定字符串 ID。实验表不声明外键，以便测量与现有 DW 一致的分析型装载路径；引用完整性由导入前 validator 与导入后查询验证。

## ImportReport

| Field | Type | Constraints |
|---|---|---|
| status | enum | measured/failed/not_run |
| dataset | object | version, seed, fact rows, manifest SHA |
| environment | object | git SHA, timestamp, host, MySQL version, database |
| tables | object | expected rows, imported rows, elapsed seconds |
| index_elapsed_seconds | number/null | measured only |
| total_elapsed_seconds | number/null | measured only |
| throughput_rows_per_second | number/null | measured only |
| ground_truth_passed | bool/null | measured only |
| failure | object/null | stable code and message |
| scope | object | synthetic=true, extrapolated=false, max_claimed_rows |

## DatabaseBenchmarkReport

每个并发档包含 query cases；每个 case 保存 samples_ms、sample_count、success rate、p50/p95/p99/max、timeout count、result_match 和 EXPLAIN 摘要。顶层保存数据集、环境、预热、迭代、并发、总吞吐与 truthful scope。

## Migrations

无生产 Schema 迁移。`eval/sql/scale_schema.sql` 只用于显式命名的可删除实验数据库；`--replace` 是重建该实验库的唯一入口，且 `dw`、`meta`、`mysql`、`information_schema`、`performance_schema`、`sys` 永远拒绝。
