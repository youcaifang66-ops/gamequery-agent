# Task List: 数据库工作负载与结构优化

## Plan Reference

Implements: `specs/database-workload-optimization/plan.md`

## Tasks

### 指标真值

- [x] **TASK-001** [S] 编写关卡通过率生成账本与独立扫描失败测试
  - Tests: AC-06
  - Files: `tests/test_synthetic_scale.py`、`tests/test_scale_validator.py`
  - Depends on: none

- [x] **TASK-002** [M] 修正关卡尝试次数账本、真值 SQL 与校验器
  - Contract: `contracts/metric-truth.md`
  - Satisfies: AC-06
  - Files: `eval/generate_scale_data.py`、`eval/validate_scale_data.py`
  - Depends on: TASK-001

### 索引目录与迁移

- [x] **TASK-003** [S] 编写索引目录和导入同步失败测试
  - Tests: AC-02、AC-04、AC-05、AC-07
  - Files: `tests/test_scale_importer.py`、`tests/test_schema_optimization.py`
  - Depends on: TASK-002

- [x] **TASK-004** [M] 实现版本化索引目录并接入新库导入
  - Contract: `contracts/schema-migration.md`
  - Satisfies: AC-02、AC-04、AC-05、AC-07、AC-08
  - Files: `eval/schema_optimization.py`、`eval/import_scale_data.py`
  - Depends on: TASK-003

- [x] **TASK-005** [S] 编写既有库 dry-run、幂等、权限和冲突测试
  - Tests: AC-07、AC-08、AC-E2
  - Files: `tests/test_scale_optimizer.py`
  - Depends on: TASK-004

- [x] **TASK-006** [M] 实现既有实验库结构优化 CLI
  - Contract: `contracts/schema-migration.md`
  - Satisfies: AC-07、AC-08、AC-E2
  - Files: `eval/optimize_scale_database.py`
  - Depends on: TASK-005

### 玩家核查基准

- [x] **TASK-007** [S] 编写玩家工作负载报告和门槛失败测试
  - Tests: AC-01、AC-02、AC-03、AC-04、AC-E1
  - Files: `tests/test_player_audit_benchmark.py`
  - Depends on: TASK-004

- [x] **TASK-008** [M] 实现玩家核查基准与 `EXPLAIN ANALYZE` 采集
  - Contract: `contracts/player-audit-workload.md`、`contracts/performance-gates.md`
  - Satisfies: AC-01、AC-02、AC-03、AC-04、AC-E1
  - Files: `eval/run_player_audit_benchmark.py`、`eval/player_audit_report.py`
  - Depends on: TASK-007

### 真实千万库验证

- [x] **TASK-009** [M] 在当前千万库执行迁移并保存结构成本证据
  - Tests: AC-07、AC-08、AC-E2
  - Files: `eval/results/ten_million_schema_optimization.json`
  - Depends on: TASK-006

- [x] **TASK-010** [M] 运行玩家 C=1/20 和既有六类回归基准
  - Tests: AC-01、AC-02、AC-03、AC-04、AC-05、AC-E1
  - Files: `eval/results/ten_million_player_audit.json`、`eval/results/ten_million_db_benchmark_optimized.json`
  - Depends on: TASK-008、TASK-009

### 集成与交付

- [x] **TASK-011** [M] 更新规模证据合同测试并运行全量门禁
  - Tests: AC-05、AC-06、AC-08、AC-09
  - Files: `tests/test_scale_evidence.py`、`tests/test_game_domain_contract.py`
  - Depends on: TASK-010

- [x] **TASK-012** [S] 生成验证矩阵、决策记录和维护者 walkthrough
  - Satisfies: AC-01 至 AC-09、AC-E1、AC-E2
  - Files: `specs/database-workload-optimization/validation.md`、`specs/database-workload-optimization/walkthrough.md`、`specs/database-workload-optimization/decision_log.md`
  - Depends on: TASK-011

- [x] **TASK-013** [S] 更新 README 性能边界和面试证据
  - Satisfies: AC-08、AC-09
  - Files: `README.md`、`docs/INTERVIEW.md`
  - Depends on: TASK-012

## Legend

- `[S]` Small — under 1 hour
- `[M]` Medium — 1–3 hours
- 每个实现任务均由前置测试任务约束；单任务不超过 3 个文件。
