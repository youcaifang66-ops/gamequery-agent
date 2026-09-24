# Tasks: 千万级合成业务数据与容量实证

状态：计划已完成，等待按顺序执行。每个 `TEST` 任务先提交失败测试对应的变更，再由配对 `IMPL` 任务实现并通过；每个功能批次都独立 commit/push。

## Phase A — 数据生成与验证

### T01-TEST 生成合同与业务分布测试 [M]

- **Files:** `tests/test_synthetic_scale.py`
- **Work:** 先覆盖 `10m` preset、非法行数/根目录/非空目录、确定性、真实日期、三事实表精确总数、长尾/周末/活动/偏态付费/失败事件、六类 ground truth 和 provenance。
- **Verify:** 新测试因实现缺失而失败，旧 `tests/test_scale_harness.py` 不回归。
- **Covers:** AC-01, AC-02, AC-04, AC-05, AC-07, AC-E1

### T01-IMPL 流式业务数据生成器 [M]

- **Files:** `eval/synthetic_profile.py`, `eval/generate_scale_data.py`, `.gitignore`
- **Work:** 建立版本化分布；单遍流式写 CSV、增量 SHA、统计与标准答案；记录生成耗时、RSS、环境和真实性范围；忽略大型实验目录。
- **Verify:** T01 测试通过；同 seed 文件摘要一致；不同 seed 至少一个事实摘要不同。
- **Depends on:** T01-TEST
- **Covers:** AC-01~05, AC-07, AC-15, AC-E1

### T02-TEST 完整性与独立答案测试 [M]

- **Files:** `tests/test_scale_validator.py`
- **Work:** 先覆盖摘要篡改、行数篡改、缺文件、外键错误、分布阈值失败，以及 smoke 独立扫描六类答案。
- **Verify:** 新测试因 validator 缺失而失败。
- **Covers:** AC-04, AC-06, AC-12, AC-E2

### T02-IMPL 数据集校验器 [M]

- **Files:** `eval/validate_scale_data.py`
- **Work:** 在数据库连接前验证路径、文件集合、SHA、行数、引用和分布；`--full-scan` 独立重算六类答案并产出稳定错误码。
- **Verify:** T02 测试通过；smoke dataset full scan PASS。
- **Depends on:** T02-TEST, T01-IMPL
- **Covers:** AC-04, AC-06, AC-07, AC-12, AC-E1, AC-E2

## Phase B — 隔离导入与数据库基准

### T03-TEST 导入安全与批处理测试 [M]

- **Files:** `tests/test_scale_importer.py`
- **Work:** 先覆盖实验库命名、保留库/reader 拒绝、校验失败时零连接、批次边界、报告脱敏、计数/答案不一致失败。
- **Verify:** 新测试因 importer 缺失而失败。
- **Covers:** AC-08, AC-09, AC-12, AC-E2

### T03-IMPL 隔离实验库导入器 [L]

- **Files:** `eval/import_scale_data.py`, `eval/sql/scale_schema.sql`
- **Work:** 先校验再连接；显式创建/替换 `gamequery_scale_*`；有界 `executemany` 导入；事实后建索引；执行表计数与六类真值核对；输出脱敏报告。
- **Verify:** T03 测试通过；真实 MySQL smoke 导入与答案核对通过。
- **Depends on:** T03-TEST, T02-IMPL
- **Covers:** AC-08, AC-09, AC-12, AC-E2

### T04-TEST 延迟统计与真实性测试 [M]

- **Files:** `tests/test_scale_benchmark.py`
- **Work:** 先覆盖 nearest-rank p50/p95/p99、空样本 null、成功率/超时率、答案不匹配、failed/not_run 不得产生容量结论。
- **Verify:** 新测试因 benchmark/report 模块缺失而失败。
- **Covers:** AC-10, AC-11, AC-12

### T04-IMPL 固定工作负载基准器 [L]

- **Files:** `eval/scale_report.py`, `eval/run_db_scale_benchmark.py`
- **Work:** 六类标准 SQL 预热后重复执行；worker 独立连接；保存原始样本、分位数、吞吐、超时、结果核对与 EXPLAIN 摘要；支持并发阶梯。
- **Verify:** T04 测试通过；smoke 数据库至少 30 次/查询基准 PASS。
- **Depends on:** T04-TEST, T03-IMPL
- **Covers:** AC-09, AC-10, AC-11, AC-12

## Phase C — 自动化、正式实验与交付

### T05-TEST CI 端到端 smoke 入口 [M]

- **Files:** `tests/integration/test_scale_pipeline.py`
- **Work:** 先定义真实 MySQL 下生成→校验→导入→六查询基准的端到端测试，禁止真实 LLM 和 10m CI 负载。
- **Verify:** 测试在缺少 CI wiring 时可本地跳过，在提供 MySQL 时执行。
- **Covers:** AC-13, AC-14

### T05-IMPL CI 与兼容性接线 [M]

- **Files:** `.github/workflows/ci.yml`, `tests/integration/test_scale_pipeline.py`
- **Work:** 将 smoke 数据管道接入已有 MySQL job，并运行现有 Agent 全量测试。
- **Verify:** workflow 语法检查、集成测试、全量 pytest、ruff、mypy PASS。
- **Depends on:** T05-TEST, T04-IMPL
- **Covers:** AC-13, AC-14, AC-15

### T06 正式生成 10,000,000 行数据 [L]

- **Files:** `eval/results/ten_million_generation.json`
- **Work:** 在本机忽略目录实际生成 10m 事实行并执行完整 integrity validation；只将小型、脱敏、可复核报告保存入库。
- **Verify:** 报告 actual rows=10,000,000、摘要/行数/分布 PASS、peak RSS <= 1 GiB、无 CSV 被 Git 跟踪。
- **Depends on:** T02-IMPL
- **Covers:** AC-01, AC-03, AC-04, AC-05, AC-07, AC-12, AC-15

### T07 正式数据库导入与容量实验 [L]

- **Files:** `eval/results/ten_million_import.json`, `eval/results/ten_million_db_benchmark.json`
- **Work:** 若本机 MySQL 可用，实际导入 10m 并运行并发 1 的正式基准及 1/5/10/20 阶梯；若基础设施不可用，提交 `not_run` 报告及稳定原因，绝不外推。
- **Verify:** measured 时表计数/六类答案一致、每查询 >=30 样本并有 p50/p95/p99/plan；not_run 时所有不可用指标为 null 且 max_claimed_rows=0。
- **Depends on:** T04-IMPL, T06
- **Covers:** AC-09, AC-10, AC-11, AC-12

### T08 全量审计与文档交付 [M]

- **Files:** `README.md`, `specs/synthetic-business-scale/tasks.md`
- **Work:** 写复现命令、指标口径、合成数据边界、实际/未运行结果；逐条回填任务状态和 AC 证据。
- **Verify:** full pytest、ruff、mypy、manifest audit、Git 大文件检查、clean worktree、remote commit 一致。
- **Depends on:** T05-IMPL, T06, T07
- **Covers:** AC-01~15, AC-E1, AC-E2

## Dependency Path

```text
T01-TEST → T01-IMPL → T02-TEST → T02-IMPL
                              ├→ T03-TEST → T03-IMPL → T04-TEST → T04-IMPL → T05
                              └→ T06 ────────────────────────────────┬→ T07
T05 ─────────────────────────────────────────────────────────────────┘
T05 + T06 + T07 → T08
```

## Gate 3 Checklist

- [x] 测试任务先于配对实现任务。
- [x] 每个任务最多三个主要代码文件。
- [x] 所有 AC 与失败路径均映射。
- [x] 依赖顺序可执行，无循环。
- [x] 10m 与 CI smoke 明确分离。
- [x] 正式结果允许诚实 `not_run`，不以外推替代。
