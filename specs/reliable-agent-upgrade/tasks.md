# Tasks: GameQuery 可靠性与可验证能力补全

规则：严格按依赖顺序执行；每个 `TEST` 任务先提交失败证据，每个 `IMPL` 任务完成后运行任务测试与全量回归；每个功能对独立 commit 并立即 push `origin/main`。

## Milestone A — 配置与 SQL 安全

### T01-TEST 配置与依赖合同 [S]

- **Files:** `tests/test_runtime_config.py`
- **ACs:** AC-03, AC-08, AC-11, AC-23
- **Work:** 添加最大行数、数据库超时、追踪路径、无默认密码以及开发依赖分组的失败测试。
- **Depends on:** none

### T01-IMPL-A 类型化运行配置 [S]

- **Files:** `app/conf/app_config.py`, `conf/app_config.yaml`
- **Contracts:** `sql-safety.md`, `trace-store.md`, `evaluation.md`
- **Satisfies:** AC-03, AC-08, AC-11, AC-23
- **Work:** 添加最大行数、数据库超时、请求边界、追踪路径和 busy timeout 类型化配置，移除数据库默认密码。
- **Depends on:** T01-TEST

### T01-IMPL-B 成熟依赖与锁文件 [S]

- **Files:** `pyproject.toml`, `uv.lock`
- **Contracts:** `trace-store.md`, `evaluation.md`
- **Satisfies:** AC-11, AC-23
- **Work:** 运行时加入 aiosqlite；开发依赖加入 Locust；更新锁文件。
- **Depends on:** T01-IMPL-A
- **Commit:** `build: add reliability runtime configuration`

### T02-TEST SQLGuard 边界矩阵 [M]

- **Files:** `tests/test_sql_guard.py`
- **ACs:** AC-01, AC-02, AC-03, AC-04, AC-06, AC-08
- **Work:** 先覆盖写操作、多语句、系统对象、CTE/别名、投影星号、COUNT(*)、LIMIT 缺失/保留/封顶/动态拒绝、超时提示和结构化错误。
- **Depends on:** T01-IMPL

### T02-IMPL SQLGuard 结构化策略 [M]

- **Files:** `app/security/errors.py`, `app/security/sql_guard.py`
- **Contracts:** `sql-safety.md`
- **Satisfies:** AC-01, AC-02, AC-03, AC-04, AC-06, AC-08
- **Work:** 实现安全错误分类、作用域校验、星号策略、LIMIT 策略和超时改写。
- **Depends on:** T02-TEST
- **Commit:** `feat: harden sql guard policy`

### T03-TEST 在线 Guard→EXPLAIN→Run [M]

- **Files:** `tests/test_agent_sql_safety.py`
- **ACs:** AC-01, AC-04, AC-05, AC-06, AC-08, AC-09, AC-24
- **Work:** 使用 fake Guard/Repository验证同一规范化 SQL、可纠错/不可纠错路由、每次重验和超时清理。
- **Depends on:** T02-IMPL

### T03-IMPL 在线安全上下文与校验节点 [M]

- **Files:** `app/agent/state.py`, `app/agent/context.py`, `app/agent/nodes/validate_sql.py`
- **Contracts:** `sql-safety.md`, `workflow.md`
- **Satisfies:** AC-01, AC-04, AC-05, AC-06, AC-09
- **Work:** 注入 Guard，写回 GuardedSQL，输出结构化失败并区分是否允许纠错。
- **Depends on:** T03-TEST
- **Commit:** 与 T04-IMPL 合并为一个在线安全功能提交。

### T04-TEST Repository 执行与取消 [S]

- **Files:** `tests/test_dw_repository.py`
- **ACs:** AC-04, AC-08, AC-24
- **Work:** 验证 EXPLAIN 和 run 接收同一 SQL、受截止时间控制、异常时 rollback 且结果有界。
- **Depends on:** T03-IMPL

### T04-IMPL Repository 与执行节点 [S]

- **Files:** `app/repositories/mysql/dw/dw_mysql_repository.py`, `app/agent/nodes/run_sql.py`
- **Contracts:** `sql-safety.md`, `workflow.md`
- **Satisfies:** AC-04, AC-08, AC-24
- **Work:** 增加 timeout/rollback 和 GuardedSQL 执行边界，移除原始 SQL 直跑路径。
- **Depends on:** T04-TEST
- **Commit:** `feat: enforce guarded sql execution loop`

## Milestone B — 工作流与最小权限

### T05-TEST 图汇合与错误路由 [M]

- **Files:** `tests/test_agent_graph.py`
- **ACs:** AC-05, AC-06, AC-13, AC-18
- **Work:** 用可替换节点验证乱序并行汇合只执行一次、不可纠错直接结束、两次纠错耗尽。
- **Depends on:** T04-IMPL

### T05-IMPL 可测试 Graph Factory [M]

- **Files:** `app/agent/graph.py`
- **Contracts:** `workflow.md`
- **Satisfies:** AC-05, AC-06, AC-13, AC-18
- **Work:** 显式列表 barrier、节点覆盖校验和结构化终止路由。
- **Depends on:** T05-TEST
- **Commit:** `refactor: make agent workflow deterministic`

### T06-TEST 部署权限与秘密 [S]

- **Files:** `tests/test_deployment_security.py`
- **ACs:** AC-07, AC-22
- **Work:** 静态验证无明文默认密码、DW reader 无 ALL/写权限、必需环境变量和权限验收脚本。
- **Depends on:** T01-IMPL

### T06-IMPL 账号配置拆分 [S]

- **Files:** `conf/app_config.yaml`, `docker/docker-compose.yaml`, `.env.example`
- **Contracts:** `sql-safety.md`
- **Satisfies:** AC-07
- **Work:** 区分 meta 与 DW reader 账号，移除默认密码，向容器传递必需环境变量。
- **Depends on:** T06-TEST

### T07-IMPL MySQL 最小权限初始化 [S]

- **Files:** `docker/mysql/dw.sql`, `docker/mysql/02-users.sh`
- **Contracts:** `sql-safety.md`
- **Satisfies:** AC-07
- **Work:** 移除 ALL GRANT；创建/收敛 meta writer 与 DW reader 权限并提供可重复初始化。
- **Depends on:** T06-IMPL
- **Commit:** `security: enforce least privilege database users`

## Milestone C — SSE 与异步审计

### T08-TEST 异步 TraceStore [M]

- **Files:** `tests/test_trace_store.py`
- **ACs:** AC-11, AC-12, AC-24
- **Work:** 先覆盖 open/close、连续序号、20 并发、唯一终态、结果脱敏和错误清理。
- **Depends on:** T01-IMPL

### T08-IMPL 异步 TraceStore [M]

- **Files:** `app/observability/trace_store.py`
- **Contracts:** `trace-store.md`, `data-model.md`
- **Satisfies:** AC-11, AC-12, AC-24
- **Work:** 使用 aiosqlite、WAL、busy timeout、事务与 async lock 实现合同。
- **Depends on:** T08-TEST
- **Commit:** `feat: add concurrent async query traces`

### T09-TEST SSE 与 QueryService 终态 [M]

- **Files:** `tests/test_api_contracts.py`, `tests/test_query_service.py`
- **ACs:** AC-09, AC-10, AC-11, AC-24, AC-25
- **Work:** 验证 request id/sequence、唯一 done/error、异常清理、结果追踪脱敏和取消终态。
- **Depends on:** T08-IMPL, T05-IMPL

### T09-IMPL SSE 与服务编排 [M]

- **Files:** `app/api/sse.py`, `app/services/query_service.py`
- **Contracts:** `query-api.md`, `trace-store.md`
- **Satisfies:** AC-09, AC-10, AC-11, AC-24, AC-25
- **Work:** 统一事件 envelope/编码、追踪追加、稳定错误和取消清理。
- **Depends on:** T09-TEST

### T10-TEST 生命周期依赖 [S]

- **Files:** `tests/test_trace_dependencies.py`
- **ACs:** AC-11, AC-24
- **Work:** 验证应用启动打开一次 store、请求注入同一实例、关闭时释放。
- **Depends on:** T09-IMPL

### T10-IMPL 生命周期依赖 [S]

- **Files:** `app/api/lifespan.py`, `app/api/dependencies.py`, `main.py`
- **Contracts:** `trace-store.md`, `query-api.md`
- **Satisfies:** AC-11, AC-24, AC-25
- **Work:** 管理 TraceStore 生命周期与请求 ID header/context。
- **Depends on:** T10-TEST
- **Commit:** `feat: stream traceable terminal events`

### T11-TEST 前端类型合同 [S]

- **Files:** `frontend/src/types/agent.contract.ts`
- **ACs:** AC-09, AC-10, AC-25
- **Work:** 添加 request id、done、错误码和 clarification 的编译期 `satisfies` 断言，先让构建失败。
- **Depends on:** T09-IMPL

### T11-IMPL 前端事件兼容 [S]

- **Files:** `frontend/src/types/agent.ts`, `frontend/src/lib/agentApi.ts`
- **Contracts:** `query-api.md`
- **Satisfies:** AC-09, AC-10, AC-25
- **Work:** 扩展事件联合类型；保持 data 行解析兼容并识别终态。
- **Depends on:** T11-TEST
- **Commit:** `feat: consume traceable agent events`

## Milestone D — 同类混合检索

### T12-TEST RRF 证据与类型隔离 [S]

- **Files:** `tests/test_retrieval_fusion.py`
- **ACs:** AC-14, AC-15, AC-16
- **Work:** 覆盖 entity type、lexical 通道、重复证据、空输入和 100 次确定性。
- **Depends on:** T01-IMPL

### T12-IMPL 融合数据模型 [S]

- **Files:** `app/retrieval/fusion.py`
- **Contracts:** `retrieval.md`, `data-model.md`
- **Satisfies:** AC-14, AC-15, AC-16
- **Work:** 增加 entity type 和稳定证据排序，禁止跨类型融合。
- **Depends on:** T12-TEST
- **Commit:** 与 T14-IMPL 合并为混合检索功能提交。

### T13-TEST Qdrant v2 Repository [M]

- **Files:** `tests/test_hybrid_qdrant_repository.py`
- **ACs:** AC-14, AC-15, AC-16
- **Work:** fake AsyncQdrantClient 验证版本化 collection、dense/BM25 schema、确定性 point 和分通道查询。
- **Depends on:** T12-IMPL

### T13-IMPL Qdrant v2 Repository [M]

- **Files:** `app/repositories/qdrant/column_qdrant_repository.py`, `app/repositories/qdrant/metric_qdrant_repository.py`
- **Contracts:** `retrieval.md`, `data-model.md`
- **Satisfies:** AC-14, AC-15, AC-16
- **Work:** 每实体一个 deterministic point，named vectors与通道排名 API。
- **Depends on:** T13-TEST

### T14-TEST 元数据索引构建 [M]

- **Files:** `tests/test_meta_knowledge_hybrid.py`
- **ACs:** AC-14, AC-15
- **Work:** 验证字段/指标 retrieval_text、稳定 id、dense/BM25输入和幂等 upsert。
- **Depends on:** T13-IMPL

### T14-IMPL 元数据 v2 构建 [M]

- **Files:** `app/services/meta_knowledge_service.py`
- **Contracts:** `retrieval.md`, `data-model.md`
- **Satisfies:** AC-14, AC-15
- **Work:** 改为每实体一个 dense+BM25 point并构建 v2 collection。
- **Depends on:** T14-TEST

### T15-TEST 在线召回证据 [M]

- **Files:** `tests/test_recall_evidence.py`
- **ACs:** AC-14, AC-15, AC-16, AC-18
- **Work:** fake Embedding/Repository验证原词、扩词、exact/alias/lexical通道与状态输出。
- **Depends on:** T14-IMPL

### T15-IMPL 字段/指标召回 [M]

- **Files:** `app/agent/nodes/recall_column.py`, `app/agent/nodes/recall_metric.py`, `app/agent/state.py`
- **Contracts:** `retrieval.md`, `workflow.md`
- **Satisfies:** AC-14, AC-15, AC-16, AC-18
- **Work:** 接入分通道排名和 RRF evidence，保留三种实体分离。
- **Depends on:** T15-TEST
- **Commit:** `feat: add explainable hybrid metadata retrieval`

## Milestone E — 真实评测与端到端稳定性

### T16-TEST SQL 指标真实性 [S]

- **Files:** `tests/test_sql_benchmark_contract.py`
- **ACs:** AC-21, AC-22
- **Work:** 先要求 preset 与 agent correction 字段分离、mode/hash/timestamp存在、未运行 agent 时为 null。
- **Depends on:** T02-IMPL

### T16-IMPL SQL 评测修正 [S]

- **Files:** `eval/run_sql_eval.py`, `eval/latest_metrics.json`
- **Contracts:** `evaluation.md`
- **Satisfies:** AC-21, AC-22
- **Work:** 重命名误导指标并输出可复现元数据。
- **Depends on:** T16-TEST
- **Commit:** `fix: report truthful sql evaluation metrics`

### T17-TEST 30 条检索黄金集合同 [S]

- **Files:** `tests/test_retrieval_eval_contract.py`
- **ACs:** AC-20, AC-22
- **Work:** 验证样本数/类别/no-match覆盖和 Hit@5/MRR/消融输出结构。
- **Depends on:** T12-IMPL

### T17-IMPL 检索黄金集与评测器 [M]

- **Files:** `eval/retrieval_benchmark.json`, `eval/run_retrieval_eval.py`, `eval/latest_retrieval_metrics.json`
- **Contracts:** `retrieval.md`, `evaluation.md`
- **Satisfies:** AC-20, AC-22
- **Work:** 实现 fixture/live 模式隔离、各通道/融合指标和样本证据。
- **Depends on:** T17-TEST
- **Commit:** `test: add retrieval golden set and ablation`

### T18-TEST 确定性工作流 E2E [M]

- **Files:** `tests/test_agent_workflow_e2e.py`
- **ACs:** AC-05, AC-06, AC-09, AC-13, AC-18, AC-24
- **Work:** 覆盖六类合同场景、节点顺序、SQL版本、Repository调用和唯一终态。
- **Depends on:** T05-IMPL, T09-IMPL, T15-IMPL

### T18-IMPL 测试夹具缺口修复 [S]

- **Files:** 最多 3 个由失败 E2E 精确指出的生产文件
- **Contracts:** `workflow.md`, `query-api.md`, `sql-safety.md`
- **Satisfies:** AC-05, AC-06, AC-09, AC-13, AC-18, AC-24
- **Work:** 只修复 E2E 揭示的合同偏差，不新增规格外行为。
- **Depends on:** T18-TEST
- **Commit:** `test: cover deterministic agent workflows`

### T19-TEST 澄清路由 [S]

- **Files:** `tests/test_query_clarification.py`
- **ACs:** AC-17
- **Work:** 覆盖缺日期、游戏无匹配、冲突指标和信息完整四类输入。
- **Depends on:** T15-IMPL

### T19-IMPL 澄清节点 [M]

- **Files:** `app/agent/nodes/check_query_context.py`, `app/agent/graph.py`, `app/agent/state.py`
- **Contracts:** `query-api.md`, `workflow.md`
- **Satisfies:** AC-17
- **Work:** SQL生成前输出 clarification 或继续；不猜测缺失槽位。
- **Depends on:** T19-TEST
- **Commit:** `feat: clarify incomplete analytics questions`

## Milestone F — 规模工具与 CI

### T20-TEST 合成数据与报告合同 [S]

- **Files:** `tests/test_scale_harness.py`
- **ACs:** AC-23
- **Work:** 固定种子、行数、外键一致性、10万/100万参数和禁止外推字段测试。
- **Depends on:** T01-IMPL

### T20-IMPL 规模测试工具 [M]

- **Files:** `eval/generate_scale_data.py`, `eval/locustfile.py`, `eval/load_report.schema.json`
- **Contracts:** `evaluation.md`
- **Satisfies:** AC-23
- **Work:** 可复现数据生成、SSE用户场景和报告 schema；CI只跑小规模 smoke。
- **Depends on:** T20-TEST
- **Commit:** `perf: add reproducible scale harness`

### T21-TEST CI 门禁合同 [S]

- **Files:** `tests/test_ci_contract.py`
- **ACs:** AC-22
- **Work:** 验证 lint、pytest、SQL评测、检索评测和前端构建均存在，且没有真实 LLM步骤。
- **Depends on:** T16-IMPL, T17-IMPL, T20-IMPL

### T21-IMPL CI 门禁 [S]

- **Files:** `.github/workflows/ci.yml`
- **Contracts:** `evaluation.md`
- **Satisfies:** AC-22
- **Work:** 加入检索评测和合成数据 smoke，保持离线确定性。
- **Depends on:** T21-TEST
- **Commit:** `ci: enforce reliability evaluation gates`

## Milestone G — 最终验证与交付

### T22-VALIDATE 全量验证 [M]

- **Files:** `specs/reliable-agent-upgrade/validation.md`, `specs/reliable-agent-upgrade/walkthrough.md`
- **ACs:** all MUST/SHOULD
- **Work:** 运行后端 lint/test/eval、前端构建、可用时 Docker 集成和负载 smoke；生成 AC traceability、漂移报告、未验证项和复现实验命令。
- **Depends on:** T21-IMPL, T19-IMPL
- **Commit:** `docs: validate reliable agent upgrade`

### T23-COMPREHENSION 面试可解释性复核 [S]

- **Files:** `README.md`, `tutorial.md`, `docs/INTERVIEW.md`
- **ACs:** evidence-only documentation
- **Work:** 只写已验证指标，更新调用链、失败案例、个人贡献和复现命令；删除过时或误导表述。
- **Depends on:** T22-VALIDATE
- **Commit:** `docs: document verified agent reliability`

## DAG Summary

```text
T01 → T02 → T03 → T04 → T05
  ├→ T06 → T07
  ├→ T08 → T09 → T10 → T11
  ├→ T12 → T13 → T14 → T15 → T18 → T19
  ├→ T16
  └→ T20
T12 → T17
T16 + T17 + T20 → T21
T07 + T10 + T11 + T18 + T19 + T21 → T22 → T23
```
