# Validation: 数据库工作负载与结构优化

## 结论

状态：**通过**。在 Windows 11、MySQL 8.0.26、本地隔离 `gamequery_scale_10m` 上，对 10,000,000 条事实记录完成真实结构迁移、配对 A/B 和玩家核查。所有保存报告均为实测值，不含外推。

## 验收矩阵

| AC | 状态 | 证据 |
|---|---|---|
| AC-01 玩家 360 正确 | PASS | `ten_million_player_audit.json` 保存画像、活跃、支付、关卡结果行数、预览与 SHA-256；420 次计时结果一致 |
| AC-02 C=1 P95 ≤ 50 ms | PASS | 活跃 0.6899 ms、支付 0.4690 ms、关卡 0.5715 ms |
| AC-03 C=20 P95 ≤ 200 ms | PASS | 活跃 4.3387 ms、支付 2.4376 ms、关卡 2.8927 ms |
| AC-04 禁止事实表全扫 | PASS | 存在/不存在玩家均由 `EXPLAIN ANALYZE` 证明命中三个 player-first 索引 |
| AC-05 六类运营查询不回退 | PASS | 同环境、同口径 before/after 720 个样本；12 个门槛全部通过，0 超时、0 错误 |
| AC-06 通过率真值一致 | PASS | 生成器、独立扫描器、指标目录和数据库 SQL 均为 `SUM(passed)/SUM(attempts)` |
| AC-07 迁移安全幂等 | PASS | 仅允许 `gamequery_scale_*`，拒绝 reader；在线 DDL；最终重复执行 `executed=[]`、无 planned step |
| AC-08 记录结构成本 | PASS | 初始、增量和最终迁移报告保存建索引耗时、rollback SQL、data/index bytes、ANALYZE 结果 |
| AC-09 兼容现有系统 | PASS | 全量 `179 passed, 3 skipped`；Ruff 通过；API/SSE/SQL Guard/Agent 测试无回退 |
| AC-E1 不存在玩家 | PASS | 三个事实域均返回 0 行并命中 player-first 索引 |
| AC-E2 错误目标拒绝 | PASS | default/system/非法库名和在线 reader 的单元测试均通过 |

## 关键实测

玩家 `P0000001` 的事实结果为活跃 26 行、支付 6 行、关卡 11 行。C=1 P95 均小于 0.70 ms；C=20 P95 均小于 4.34 ms。这里是分域数据库查询，不含 LLM、检索、SSE、网络和前端渲染。

运营查询采用同环境配对基线。新增索引 invisible 时，C=1 的收入/ARPU/通过率 P95 为 899.19/412.59/1009.55 ms；恢复索引后的最终值为 160.41/23.18/0.93 ms。C=20 对应从 729.00/1457.92/799.79 ms 降到 172.30/24.00/2.56 ms。

初始总索引 415,121,408 bytes，最终 931,610,624 bytes，净增 516,489,216 bytes（约 492.6 MiB）。首次 5 个索引创建 37.75 秒，选择性通过率索引另耗时 6.05 秒。六表 `ANALYZE TABLE` 均返回 OK。

## 失败与修正

1. 首次在线 DDL 把 `ALGORITHM` 和 `LOCK` 用逗号连接，MySQL 8.0.26 返回 1064；未创建索引。修为 `ALGORITHM=INPLACE LOCK=NONE` 后通过。
2. date-first 通过率覆盖索引扫描约 315,160 行，C=20 P95 66.34 ms；增加 game/level-first 覆盖索引后扫描约 675 行，最终 C=20 P95 2.56 ms。
3. 候选 `(game_id,date_id,amount)` 收入索引未被原 SQL 采用，强制使用更慢；已从目录和数据库回滚。
4. 被替代的 date-first 通过率覆盖索引未再被选择；删除后节省约 89.7 MiB，性能门槛仍通过。

## 证据文件

- `eval/results/ten_million_schema_optimization_initial.json`
- `eval/results/ten_million_schema_optimization_v2.json`
- `eval/results/ten_million_schema_optimization.json`
- `eval/results/ten_million_player_audit.json`
- `eval/results/ten_million_db_benchmark_before_v2.json`
- `eval/results/ten_million_db_benchmark_optimized.json`

## 边界

这是合成数据、固定工作负载和本地单机 MySQL 的数据库层证据，不是生产容量上限或端到端 Agent SLA。生产上线仍需真实分布、混合读写、连接池、故障恢复、复制拓扑、资源隔离和目标硬件复测。
