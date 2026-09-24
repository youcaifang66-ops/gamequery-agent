# Technical Plan: 数据库工作负载与结构优化

## Spec Reference

Implements: `specs/database-workload-optimization/spec.md`

## Architecture Overview

保留现有六表星型模型和 MySQL 8。把索引定义集中为版本化目录，导入器在新库装载后创建优化索引，独立迁移器负责安全升级既有实验库。玩家核查按三个事实域独立查询，基准器先校验结果再记录延迟与 `EXPLAIN ANALYZE`。指标真值生成器与在线指标目录使用同一业务公式。

## Component Breakdown

### 指标真值生成

- **Responsibility:** 生成关卡尝试次数账本和统一通过率标准答案。
- **Location:** `eval/generate_scale_data.py`
- **Accepts:** seed、规模、合成 profile。
- **Returns:** 数据文件、manifest、ground truth。
- **AC Coverage:** AC-06

### 索引目录与新库导入

- **Responsibility:** 声明工作负载驱动的索引，供新库导入复用并在建后刷新统计。
- **Location:** `eval/schema_optimization.py`、`eval/import_scale_data.py`
- **Accepts:** 目标结构版本。
- **Returns:** 稳定索引清单与创建结果。
- **AC Coverage:** AC-02、AC-03、AC-04、AC-05、AC-07、AC-08

### 既有实验库迁移

- **Responsibility:** 预检库名和权限，跳过已有索引，以在线 DDL 创建缺失索引，保存回滚语句和成本报告。
- **Location:** `eval/optimize_scale_database.py`
- **Accepts:** 显式实验库、管理凭据、dry-run/apply。
- **Returns:** 结构迁移 JSON 报告。
- **AC Coverage:** AC-07、AC-08、AC-E2

### 玩家核查基准

- **Responsibility:** 分域运行存在/不存在玩家查询，验证结果摘要，采集并发延迟和实际执行计划。
- **Location:** `eval/run_player_audit_benchmark.py`
- **Accepts:** 实验库、玩家标识、并发、样本和预热参数。
- **Returns:** 版本化玩家工作负载报告。
- **AC Coverage:** AC-01、AC-02、AC-03、AC-04、AC-E1

### 运营回归与证据

- **Responsibility:** 重跑既有固定负载、比较基线、保存结构成本与最终结论。
- **Location:** `eval/run_db_scale_benchmark.py`、`eval/results/`、`specs/database-workload-optimization/validation.md`
- **Accepts:** 优化后数据库和既有 ground truth。
- **Returns:** 可审计的优化前后报告。
- **AC Coverage:** AC-05、AC-08、AC-09

## Technology Choices

| Decision | Choice | Rationale |
|---|---|---|
| 玩家时间线访问 | B-tree `(player_id, date_id)` | 等值玩家定位后按日期范围/顺序读取；主键由 InnoDB 隐式附加 |
| 收入范围聚合 | 窄覆盖索引 `(date_id, game_id, amount)` | 避免回表读取金额，不把无关 payload 塞入索引 |
| 关卡指标聚合 | 覆盖索引 `(date_id, game_id, level_id, passed, attempts)` | 当前固定 SQL 所需过滤与度量均在索引中 |
| 现有库升级 | MySQL 原生 `ALGORITHM=INPLACE, LOCK=NONE` | 当前本地单机规模无需引入 gh-ost/Spirit；不支持时显式失败 |
| 计划证据 | `EXPLAIN ANALYZE` | 同时记录估算行、实际行、loops 与实际耗时 |
| 删除策略 | 本轮不删索引 | 先保存新负载证据；后续删除前使用 invisible index 观察 |
| 分区 | 不采用 | 玩家查询无法从日期裁剪获益，且当前 PK 不满足分区唯一键约束 |

## Integration Points

- MySQL 8.0.26：真实 1000 万事实行结构迁移和基准。
- 现有 import pipeline：新建实验库直接获得优化结构。
- 现有 ground truth：继续作为结果正确性门禁。
- Agent API：只做兼容回归，不向在线 reader 暴露 DDL。

## AC Coverage Map

| AC | Component(s) | Contract(s) |
|---|---|---|
| AC-01 | 玩家核查基准 | `contracts/player-audit-workload.md` |
| AC-02 | 索引目录、玩家核查基准 | `contracts/player-audit-workload.md` |
| AC-03 | 玩家核查基准 | `contracts/player-audit-workload.md` |
| AC-04 | 玩家核查基准 | `contracts/player-audit-workload.md` |
| AC-05 | 索引目录、运营回归 | `contracts/performance-gates.md` |
| AC-06 | 指标真值生成 | `contracts/metric-truth.md` |
| AC-07 | 导入、迁移 | `contracts/schema-migration.md` |
| AC-08 | 迁移、运营回归 | `contracts/schema-migration.md`、`contracts/performance-gates.md` |
| AC-09 | 运营回归 | `contracts/performance-gates.md` |
| AC-E1 | 玩家核查基准 | `contracts/player-audit-workload.md` |
| AC-E2 | 既有库迁移 | `contracts/schema-migration.md` |

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| 新索引占用磁盘并增加装载时间 | High | Medium | 报告前后 index bytes 和创建耗时；只建有负载证据的索引 |
| DDL 意外退化为 COPY 或阻塞 | Low | High | 显式 `INPLACE, LOCK=NONE`；不支持即失败 |
| 暖缓存制造虚假加速 | Medium | High | 固定预热、30 样本、保存全样本和并发 1/20 |
| 指标口径修正导致旧真值变化 | High | High | 重新生成账本并做独立扫描与数据库交叉验证 |
| 覆盖索引加速一类查询但拖慢其他查询 | Medium | High | 重跑全部六类基准并执行回退门槛 |
| 玩家历史过多造成无界返回 | Low | High | 基准只使用受控合成玩家；线上仍由 SQLGuard 行数上限保护 |

## Out of Scope (Technical)

- 不引入分区、分库分表、列式数据库、缓存或消息队列。
- 不删除或重命名现有索引、表和字段。
- 不修改 `/api/query` 或 SSE 合同。
- 不实现生产 gh-ost/Spirit 编排。

