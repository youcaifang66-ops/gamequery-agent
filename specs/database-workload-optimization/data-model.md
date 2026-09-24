# Data Model: 数据库工作负载与结构优化

## Spec Reference

Implements: `specs/database-workload-optimization/spec.md`

## Entities

现有六表、字段、主键和数据粒度保持不变；本轮不新增业务表。权威结构仍为 `eval/sql/scale_schema.sql`。

## Indexes

| Table | Columns | Type | Rationale |
|---|---|---|---|
| `fact_player_daily` | `(player_id, date_id)` | B-tree | 玩家活跃时间线、日期范围和稳定主键后缀 |
| `fact_payment` | `(player_id, date_id)` | B-tree | 玩家支付时间线和日期范围 |
| `fact_level_event` | `(player_id, date_id)` | B-tree | 玩家关卡时间线和日期范围 |
| `fact_payment` | `(date_id, game_id, amount)` | covering B-tree | 月收入按日期范围聚合，避免金额回表 |
| `fact_level_event` | `(date_id, game_id, level_id, passed, attempts)` | covering B-tree | 关卡通过率过滤和度量覆盖 |

保留现有四个索引，后续只有在 invisible-index 观察期和独立规格通过后才能删除。

## Constraints

- 玩家时间线索引不改变数据唯一性；`event_id` / `payment_id` 继续作为主键。
- `fact_player_daily` 允许同一玩家、游戏、日期出现多条合成事件；DAU 必须 `COUNT(DISTINCT player_id)`。
- `LevelPassRate = SUM(passed) / NULLIF(SUM(attempts), 0)` 是唯一口径。
- 在线 reader 仅保留 `SELECT`。

## Migrations

### Migration 001: 玩家时间线与运营覆盖索引

- 预检目标名符合 `gamequery_scale_*` 且账号不是在线 reader。
- 检查每个索引名称和有序列定义；一致则跳过，不一致则失败。
- 使用 `ALTER TABLE ... ADD INDEX ... ALGORITHM=INPLACE, LOCK=NONE` 创建缺失索引。
- 创建后执行 `ANALYZE TABLE`，记录结构、字节和耗时。
- **Rollback:** 逐个 `DROP INDEX <name> ON <table>`，随后 `ANALYZE TABLE`。

### Migration 002: 新库导入结构同步

- 新建实验库在数据装载后使用与 Migration 001 相同的索引目录。
- 导入报告记录全部索引创建时间和优化器统计。
- **Rollback:** 删除显式实验数据库；禁止针对默认业务库执行。

