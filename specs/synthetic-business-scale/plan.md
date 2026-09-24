# Technical Plan: 千万级合成业务数据与容量实证

## Spec Reference

Implements: `specs/synthetic-business-scale/spec.md` v1.0

## Architecture Overview

保留现有 CSV 星型模型，把均匀随机生成器升级为单遍流式生成：生成行时同步维护文件摘要、业务分布计数和六类标准答案账本，避免二次扫描千万行。独立校验器在导入前核对 manifest、摘要、行数与 smoke 全扫描答案。导入器使用已有 asyncmy 做有界多行批次，写入显式实验库；基准运行器直接执行固定标准 SQL，将正确性与延迟分开记录。大型产物放在 Git 忽略目录，小型报告保存到仓库。

## Component Breakdown

### Synthetic Profile and Streaming Generator

- **Responsibility:** 定义版本化业务分布、真实日历、长尾游戏热度、周末/活动效应、偏态付费与关卡失败，并单遍写出 CSV、摘要、统计和标准答案。
- **Location:** `eval/synthetic_profile.py`, `eval/generate_scale_data.py`
- **Accepts:** output directory, rows, seed, profile version
- **Returns:** dataset manifest and generation report
- **AC Coverage:** AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-15, AC-E1

### Dataset Validator

- **Responsibility:** 在不连接数据库的情况下核对安全路径、文件摘要、行数、维度引用抽样、分布阈值和标准答案；smoke 模式全扫描独立重算答案。
- **Location:** `eval/validate_scale_data.py`
- **Accepts:** dataset directory
- **Returns:** validation report or stable validation error
- **AC Coverage:** AC-02, AC-04, AC-06, AC-07, AC-12, AC-E1, AC-E2

### Isolated Experiment Importer

- **Responsibility:** 校验数据后创建显式实验 schema，使用有界批次写入维度和事实表，核对行数与标准答案并记录导入证据。
- **Location:** `eval/import_scale_data.py`, `eval/sql/scale_schema.sql`
- **Accepts:** validated dataset directory, explicit database name, admin/writer credentials
- **Returns:** import report
- **AC Coverage:** AC-08, AC-09, AC-12, AC-E2

### Database Benchmark Runner

- **Responsibility:** 预热并重复执行六类固定查询；并发执行时每 worker 使用独立连接；输出结果正确性、分位延迟、吞吐、超时与 EXPLAIN 摘要。
- **Location:** `eval/run_db_scale_benchmark.py`, `eval/scale_report.py`
- **Accepts:** validated dataset, experiment database, concurrency, iterations, timeout
- **Returns:** versioned database benchmark report
- **AC Coverage:** AC-09, AC-10, AC-11, AC-12

### CI and Evidence Integration

- **Responsibility:** smoke 生成/校验/真实 MySQL 小规模导入，检查报告不变式；忽略大型产物；说明复现命令和证据边界。
- **Location:** `tests/test_synthetic_scale.py`, `tests/integration/test_scale_import.py`, `.github/workflows/ci.yml`, `.gitignore`, `README.md`
- **AC Coverage:** AC-13, AC-14, AC-15, AC-E1, AC-E2

## Technology Choices

| Decision | Choice | Rationale |
|---|---|---|
| Large-file generation | Python generator + `csv.writer` + incremental SHA-256 | 已有实现、跨平台、单遍且无需引入新数据框架 |
| Memory measurement | existing `psutil` | Locust 已带入并锁定；Windows/Linux 一致获取 RSS |
| Bulk import | existing `asyncmy.executemany` with bounded batches | 复用现有驱动；符合 MySQL 官方多行 INSERT 建议；无需启用 LOCAL INFILE |
| Correctness oracle | streaming aggregate ledger + independent CSV scan | 账本支持 10m；独立 scan 防止生成逻辑与答案同错 |
| Query latency | `perf_counter_ns`, nearest-rank percentiles | 无新增依赖；每个原始样本保留供复算 |
| Public data | metadata/reference only | 避免第三方许可、隐私和 Schema 不匹配风险 |

## Data Flow

1. CLI 验证 output path、preset 与 seed。
2. profile 生成确定性玩家属性、游戏权重、日期权重和活动规则。
3. generator 单遍写维度/事实 CSV，同时累计 SHA、统计和 ground truth。
4. validator 核对文件与 manifest；smoke 对 CSV 全扫描重算。
5. importer 在任何数据库写入前要求 validator PASS，再创建实验 schema 并批量导入。
6. importer 对表行数与六类标准 SQL结果做一致性检查。
7. benchmark runner 预热后运行固定 workload，写出只适用于当前环境/规模的报告。

## AC Coverage Map

| AC | Component(s) | Contract(s) |
|---|---|---|
| AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07 | Generator, Validator | `contracts/dataset.md` |
| AC-08, AC-09 | Importer, Validator | `contracts/import.md`, `contracts/reports.md` |
| AC-10, AC-11, AC-12 | Benchmark Runner | `contracts/reports.md` |
| AC-13, AC-14, AC-15 | CI Integration | `contracts/dataset.md`, `contracts/reports.md` |
| AC-E1, AC-E2 | Generator, Validator, Importer | `contracts/dataset.md`, `contracts/import.md` |

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| 10m CSV 消耗大量磁盘或运行过久 | Medium | High | 生成前估算与检查空间；单遍哈希；逐文件进度；失败报告不宣称完成 |
| 生成账本和行由同一错误逻辑产生 | Medium | High | smoke 必须独立扫描 CSV 重算；数据库导入后再次用 SQL 验证 |
| 批量写入中途失败留下部分实验库 | Medium | High | 只写独立 schema；报告 failed；下次必须显式 replace；默认业务库拒绝 |
| 组合索引放大导入耗时 | High | Medium | 维度先导入、事实批量写入后创建二级索引；报告记录索引阶段 |
| Windows 文件路径/换行影响摘要 | Medium | Medium | 固定 UTF-8、LF、RFC4180 CSV；摘要按实际字节计算 |
| 本机 Docker 仍不可用 | Medium | High | 先完成 10m 生成实证；CI 验证真实 MySQL smoke；正式 10m DB 报告标记 not_run，绝不替代 |
| 合成分布被误称真实业务 | Medium | High | manifest、报告和 README 强制 synthetic/provenance 字段与 WONT 边界 |

## Out of Scope (Technical)

- 不修改在线 Agent API 或图结构。
- 不新增数据湖、列式数据库、队列或下载器。
- 不让 CI 生成或导入 10m。
- 不把数据库基准延迟混入 LLM 端到端延迟。
