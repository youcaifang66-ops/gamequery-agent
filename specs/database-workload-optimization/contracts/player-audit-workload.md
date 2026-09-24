# Contract: 玩家核查工作负载

## Inputs

| Field | Type | Constraint |
|---|---|---|
| database | string | 必须匹配实验库命名规则 |
| player_id | string | 非空；默认使用合成目标玩家 |
| concurrency | integer list | 必须包含 1 和 20 |
| iterations | integer | 每类每档至少 30 |
| warmups | integer | 至少 3 |
| timeout_seconds | number | 正数 |

## Query Cases

- `player_profile`: 玩家画像，主键等值查询。
- `player_activity_timeline`: 活跃明细，玩家等值过滤，按日期和事件主键排序。
- `player_payment_timeline`: 支付明细，玩家等值过滤，按日期和支付主键排序。
- `player_level_timeline`: 关卡明细，玩家等值过滤，按日期和事件主键排序。
- 每个事实 case 另运行不存在玩家版本。
- 三个事实域不得互相 JOIN。

## Report

报告必须包含 schema version、git SHA、数据摘要、环境、查询文本、参数、结果行数与摘要、完整计时样本、p50/p95/p99/max、吞吐、超时、错误、结果不匹配和 `EXPLAIN ANALYZE` 文本。

失败时 `status=failed`，性能值不得伪装成 measured。

## AC Coverage

AC-01、AC-02、AC-03、AC-04、AC-E1。

