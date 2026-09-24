# Research: 数据库工作负载与结构优化

Status: Approved
Date: 2026-09-25

## Problem Summary

当前千万级实验库已经证明六类日期/游戏聚合查询，但未证明按玩家下钻核查的性能。此次研究只描述现有表结构、索引、数据生成和性能证据，并核对指标口径是否一致。

## Relevant Files

| File | Role | Key entry point |
|---|---|---|
| `eval/sql/scale_schema.sql` | 千万实验库六表 DDL | 三张维表与三张事实表 — `eval/sql/scale_schema.sql:1-52` |
| `eval/import_scale_data.py` | 数据装载、索引和统计刷新 | `INDEX_STATEMENTS` — `eval/import_scale_data.py:48-53` |
| `eval/generate_scale_data.py` | 合成数据和六类真值 SQL | `_ground_truth()` — `eval/generate_scale_data.py:180-272` |
| `eval/run_db_scale_benchmark.py` | 固定 SQL 并发基准 | `_benchmark_case()` — `eval/run_db_scale_benchmark.py:77-146` |
| `conf/metrics.yaml` | 线上指标公式 | `LevelPassRate` — `conf/metrics.yaml:27-32` |
| `conf/meta_config.yaml` | Agent 可见表、字段和业务值 | 六表元数据 — `conf/meta_config.yaml:1-65` |
| `eval/results/ten_million_db_benchmark.json` | 现有 720 个样本与执行计划 | 六类查询结果 — `eval/results/ten_million_db_benchmark.json:1-1640` |
| `specs/synthetic-business-scale/validation.md` | 已发布性能边界 | 固定 SQL 延迟与结论边界 — `specs/synthetic-business-scale/validation.md:39-91` |

## Information Flow

1. 生成器按 60% 日活、20% 支付、20% 关卡事件产生 1000 万事实行 — `eval/generate_scale_data.py:54-66,323-331`。
2. 导入器先建无二级索引的六张表，再以 10,000 行批次装载 — `eval/import_scale_data.py:39-46,131-176`。
3. 装载完成后创建四个复合索引并执行 `ANALYZE TABLE` — `eval/import_scale_data.py:48-53,177-208`。
4. 基准器预热后对真值清单逐类执行 30 次，保存延迟、结果一致性和 `EXPLAIN` — `eval/run_db_scale_benchmark.py:65-95,149-232`。
5. Agent 在线查询使用只读账号，经 SQLGuard、数据库预检后执行 — `app/agent/nodes/validate_sql.py:43-113`、`app/agent/nodes/run_sql.py:14-44`。

**Where this feature intervenes:** 步骤 2–4 的实验结构、索引和工作负载证据；线上 API 与只读安全链路保持兼容。

## Key Findings

### F-1: 当前数据库是六表最小星型模型

三张维表是玩家、游戏、日期；三张事实表是玩家日活、支付、关卡事件 — `eval/sql/scale_schema.sql:1-52`。
**Consequence:** 表数不能直接证明或否定性能，验收必须按查询模式和执行计划进行。

### F-2: 现有索引只围绕日期运营聚合

三个事实索引分别以 `date_id` 开头，玩家索引仅存在于玩家维表的渠道组合索引 — `eval/import_scale_data.py:48-53`。
**Consequence:** 单独按 `player_id` 查询不满足事实表复合索引的最左前缀。

### F-3: 性能证据仅覆盖六类固定 SQL

真值集只有 DAU、收入、付费人数、ARPU、关卡通过率和渠道拆分 — `eval/generate_scale_data.py:189-271`；验证报告明确不得外推到未测场景 — `specs/synthetic-business-scale/validation.md:89-91`。
**Consequence:** 玩家全域核查、平台/地区拆分和玩家时间线目前没有可引用的千万级证据。

### F-4: 月收入是现有固定负载中最慢查询

并发 1 的月收入 P95 为 293.79 ms，并发 20 为 624.50 ms — `specs/synthetic-business-scale/validation.md:43-52`。
**Consequence:** 日期范围聚合需要纳入优化后的回归门槛。

### F-5: 关卡通过率存在口径冲突

线上指标定义为 `SUM(passed) / NULLIF(SUM(attempts), 0)` — `conf/metrics.yaml:27-32`；离线真值 SQL 使用 `AVG(passed)` — `eval/generate_scale_data.py:240-255`。
**Consequence:** 当前线上结果与离线性能真值不能同时作为指标真实性证据。

### F-6: 日活表名称暗示日粒度，但生成器未声明唯一日粒度约束

事实表仅以 `event_id` 为主键，没有 `(player_id, game_id, date_id)` 唯一约束 — `eval/sql/scale_schema.sql:23-32`；生成器随机选择玩家、游戏和日期 — `eval/generate_scale_data.py:333-366`。
**Consequence:** DAU 必须继续使用玩家去重，不能把行数当作活跃人数。

### F-7: 导入和查询职责已隔离

导入器拒绝系统库、默认库和只读账号 — `eval/import_scale_data.py:30-37,63-71`；在线查询账号权限由测试固定为只读 — `tests/test_database_privileges.py:1-58`。
**Consequence:** 结构迁移不能进入在线查询链路，也不能扩大 reader 权限。

## Existing Constraints Discovered

- 性能声明必须记录规模、硬件、预热、样本数和分位数 — `constitution.md:54-60`。
- 新增索引必须由具体查询模式证明，不能为每列盲目建索引 — `constitution.md:78-84`。
- SQL 仍需经过 AST 白名单、数据库预检、只读权限、超时和结果上限 — `constitution.md:16-23`。
- 大型 CSV 和原始负载结果不得进入 Git — `specs/synthetic-business-scale/spec.md:30-44,132-136`。
- 现有 `/api/query` 与 SSE 合同必须保持兼容 — `constitution.md:5-9`。

## Prior Art in This Codebase

- 规模导入器已具备目标库白名单、全扫描校验、批量装载、建索引和统计刷新流程 — `eval/import_scale_data.py:63-71,119-208`。
- 基准器已具备预热、并发阶梯、结果精确比对和查询计划留档 — `eval/run_db_scale_benchmark.py:77-146,149-232`。
- 报告合同会拒绝外推和不完整性能元数据 — `eval/load_report.py:9-50`。

## Options Considered

### Option A: 基于工作负载增加和调整索引

**Description:** 保留六表模型，用玩家前导索引和窄覆盖索引服务已证实查询模式。
**Pros:** 变更可回滚；沿用 MySQL、导入器和现有基准框架。
**Cons:** 不增加新的业务事件域；索引增加装载和存储成本。
**Estimated effort:** M

### Option B: 日期分区

**Description:** 对事实表按日期范围分区。
**Pros:** 日期裁剪和历史归档可能受益。
**Cons:** 当前主键不包含日期；仅按玩家查询仍会跨分区；迁移和约束复杂。
**Estimated effort:** L

### Option C: 引入列式分析数据库

**Description:** 把分析负载迁移到新的 OLAP 引擎。
**Pros:** 更适合超大规模聚合。
**Cons:** 改变已批准技术栈，扩大部署、同步和面试解释成本。
**Estimated effort:** L

## Decision

**Chosen:** Option A
**Rationale:** 当前 1000 万行规模的直接缺口是工作负载与索引不匹配；先用可复现证据优化现有 MySQL，避免因“千万级”盲目分区或换库。
**Date:** 2026-09-25
**Decided by:** 用户授权自动执行；项目宪章约束。

## Open Questions for the Spec

- 玩家核查是否允许把三张事实表直接 JOIN？现有字段会产生多对多膨胀，规格需明确结果合同。
- 优化目标应同时约束玩家查询和现有运营查询，避免单场景优化导致回归。
- 关卡通过率的唯一权威口径需要与 `conf/metrics.yaml` 对齐。

## Not Investigated

- 未研究真实生产写入吞吐、复制拓扑、停机窗口和云数据库限制，因为当前环境是本地隔离实验库。
- 未研究超过 1000 万行的分区收益，因为仓库没有更大规模实测数据。
- 未研究真实玩家数据和隐私合规，因为数据集明确为 synthetic。

## References

- [MySQL 8.0 Multiple-Column Indexes](https://dev.mysql.com/doc/refman/8.0/en/multiple-column-indexes.html)
- [MySQL 8.0 EXPLAIN ANALYZE](https://dev.mysql.com/doc/refman/8.0/en/explain.html)
- [MySQL 8.0 Invisible Indexes](https://dev.mysql.com/doc/refman/8.0/en/invisible-indexes.html)
- [MySQL 8.0 Partitioning Limitations](https://dev.mysql.com/doc/refman/8.0/en/partitioning-limitations.html)
- [GitHub gh-ost](https://github.com/github/gh-ost)
- [Percona Toolkit](https://github.com/percona/percona-toolkit)
- [Snowplow dbt user/session models](https://github.com/snowplow/dbt-snowplow-web)
- [GameAnalytics warehouse datasets](https://docs.gameanalytics.com/products-and-features/pipeline-iq/data-warehouse/datasets-and-schemas/datasets-and-schemas-overview/)
