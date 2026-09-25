# Walkthrough: 数据库工作负载与结构优化

## 结构入口

`eval/schema_optimization.py` 是唯一索引目录。新建实验库由 `eval/import_scale_data.py` 复用该目录；既有库由 `eval/optimize_scale_database.py` 做预检、差异规划、在线 DDL、统计刷新和成本报告。这样重建库与升级库不会出现两套结构。

最终新增索引：

- `fact_player_daily(player_id, date_id)`
- `fact_payment(player_id, date_id)`
- `fact_level_event(player_id, date_id)`
- `fact_payment(date_id, game_id, amount)`
- `fact_level_event(game_id, level_id, date_id, passed, attempts)`

## 迁移调用链

1. `validate_optimization_target` 拒绝默认库、系统库、非法名称和在线 reader。
2. `_read_indexes` 按列顺序读取 `information_schema.STATISTICS`。
3. `build_migration_plan` 将同名同定义标记为 `already_present`；同名异构直接失败。
4. apply 模式只执行缺失项，使用 `ALGORITHM=INPLACE LOCK=NONE`。
5. 六表执行 `ANALYZE TABLE`，保存前后索引、表空间、耗时、rollback SQL、MySQL 版本和 Git SHA。
6. 第二次 apply 没有执行项，证明幂等。

## 玩家核查调用链

`eval/run_player_audit_benchmark.py` 把玩家画像、活跃、支付、关卡拆成四条独立查询，不把三个事实表 JOIN 成乘法结果。另对不存在玩家运行三个事实查询。

每个 case 先取结果快照和 SHA-256，再做 3 次预热、30 次采样和 `EXPLAIN ANALYZE`。C=1 与 C=20 分开运行；超时、异常、结果变化、全表扫描或 P95 超线都会使报告失败。

## 指标真值

`eval/generate_scale_data.py` 在生成关卡事实时累加 `attempts`，ground truth SQL 使用 `SUM(passed)/NULLIF(SUM(attempts),0)`；`eval/validate_scale_data.py` 独立全扫描 CSV 重算相同业务口径。测试会篡改某条 `attempts` 并要求校验器报 `GROUND_TRUTH_MISMATCH`，防止生成器和校验器共享同一个错误。

## 复现

```powershell
$env:SCALE_DB_HOST='127.0.0.1'
$env:SCALE_DB_PORT='3307'
$env:SCALE_DB_USER='root'
$env:SCALE_DB_PASSWORD=''

uv run --frozen python -m eval.optimize_scale_database `
  --database gamequery_scale_10m --apply `
  --output eval/results/ten_million_schema_optimization.json

uv run --frozen python -m eval.run_player_audit_benchmark `
  --database gamequery_scale_10m --concurrency 1,20 `
  --iterations 30 --warmups 3 `
  --output eval/results/ten_million_player_audit.json

uv run --frozen python -m eval.run_db_scale_benchmark `
  --dataset artifacts/scale/ten-million-metric-v2 `
  --database gamequery_scale_10m --concurrency 1,20 `
  --iterations 30 --warmups 3
```

生产环境不要照搬 root 或空密码。本地实验使用隔离实例；生产迁移应使用专用 DDL 账号，并根据复制拓扑评估 gh-ost、pt-online-schema-change 或 Spirit。
