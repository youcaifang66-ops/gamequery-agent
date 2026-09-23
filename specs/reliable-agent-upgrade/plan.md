# Technical Plan: GameQuery 可靠性与可验证能力补全

## Spec Reference

Implements: `specs/reliable-agent-upgrade/spec.md`

## Architecture Overview

升级保持 `/api/query` 和现有 LangGraph 主流程，但把在线链路拆成五个可独立验证的边界：检索证据、SQL 静态策略、数据库预检与执行、SSE 事件/审计、离线评测。所有外部依赖继续通过 Context/Service 注入；节点只读写可序列化 State。每个功能任务都先写失败测试，完成后运行全量门禁，并独立 commit、push 到 `origin/main`。

## Component Breakdown

### 1. SQL Safety Policy

- **Responsibility:** 解析单条 MySQL 查询，执行只读与对象白名单策略，展开安全通配列，封顶 LIMIT，注入查询超时，返回结构化错误分类。
- **Location:** `app/security/sql_guard.py`、`app/security/errors.py`、`conf/app_config.yaml`
- **Accepts:** 候选 SQL、允许 schema、最大行数、超时毫秒数。
- **Returns:** `GuardedSQL` 或带 `code/correctable/safe_message` 的策略错误。
- **AC Coverage:** AC-01–AC-06、AC-08、AC-21。

### 2. Guard → EXPLAIN → Run Execution Boundary

- **Responsibility:** 把 Guard 后的规范化 SQL写回 State；只对同一 SQL 做 `EXPLAIN` 与执行；区分可纠错错误和立即终止错误；双层超时。
- **Location:** `app/agent/nodes/validate_sql.py`、`app/agent/nodes/run_sql.py`、`app/repositories/mysql/dw/dw_mysql_repository.py`
- **Accepts:** State 中候选 SQL和注入的安全策略/数仓仓储。
- **Returns:** 规范化 SQL、验证结果、执行结果事件或稳定错误。
- **AC Coverage:** AC-01–AC-06、AC-08、AC-09、AC-18、AC-24。

### 3. Workflow Factory and Routing

- **Responsibility:** 显式声明三召回与双过滤 barrier；按错误分类路由；支持测试节点替换；保证纠错次数和唯一终态。
- **Location:** `app/agent/graph.py`、`app/agent/state.py`、`app/agent/context.py`
- **Accepts:** 节点集合与可选测试替身。
- **Returns:** 编译后的 LangGraph runnable。
- **AC Coverage:** AC-05、AC-06、AC-13、AC-18、AC-24。

### 4. Event Envelope and Async Trace Store

- **Responsibility:** 为节点事件补充 request id/sequence，统一 SSE 编码、清理异常、保证唯一终态；异步持久化并回放审计事件。
- **Location:** `app/api/sse.py`、`app/observability/trace_store.py`、`app/services/query_service.py`、`app/api/lifespan.py`
- **Accepts:** 原有节点 payload、请求 id、生命周期状态。
- **Returns:** 兼容旧 payload 的 SSE、可回放 Trace。
- **AC Coverage:** AC-09–AC-12、AC-18、AC-24、AC-25。

### 5. API and Frontend Contract

- **Responsibility:** 保持请求体不变，前端识别 request id、错误码和 done/error 终态，取消请求时释放资源。
- **Location:** `app/api/routers/query_router.py`、`frontend/src/types/agent.ts`、`frontend/src/lib/agentApi.ts`
- **Accepts:** 现有 `{query}` 请求和增强 SSE。
- **Returns:** 与旧客户端兼容的事件联合类型。
- **AC Coverage:** AC-09、AC-10、AC-24、AC-25。

### 6. Hybrid Retrieval and Evidence

- **Responsibility:** 构建每实体一个 point 的版本化 dense+BM25 索引；分别获取同类通道排名；RRF 去重并输出逐通道证据；业务值保留独立 ES 链路。
- **Location:** `app/repositories/qdrant/`、`app/services/meta_knowledge_service.py`、`app/retrieval/fusion.py`、三个 recall 节点。
- **Accepts:** 原关键词、扩展关键词、实体类型、Top-K 配置。
- **Returns:** `RetrievalCandidate` 列表及其 evidence。
- **AC Coverage:** AC-14–AC-16、AC-20。

### 7. Clarification Gate

- **Responsibility:** 在 SQL 生成前识别日期缺失、游戏无匹配或冲突指标口径，并输出结构化澄清事件。
- **Location:** `app/agent/nodes/check_query_context.py`、`app/agent/graph.py`、`app/agent/state.py`
- **Accepts:** 原问题、召回后的指标/业务值/日期信息。
- **Returns:** 可继续或 clarification payload。
- **AC Coverage:** AC-17。

### 8. Evaluation and CI

- **Responsibility:** 提供确定性完整工作流测试、30+检索黄金集、真实/预置纠错指标分离、合成数据与 Locust 场景，并把稳定子集纳入 CI。
- **Location:** `tests/`、`eval/`、`.github/workflows/ci.yml`、`pyproject.toml`
- **Accepts:** 黄金集、模式标识、固定随机种子、实验环境清单。
- **Returns:** 结构化质量/性能报告和 CI 退出码。
- **AC Coverage:** AC-18–AC-23。

### 9. Least-Privilege Deployment

- **Responsibility:** 区分元数据写账号与数仓只读账号；移除明文默认密码和 DW `ALL PRIVILEGES`；提供可核验初始化脚本。
- **Location:** `docker/docker-compose.yaml`、`docker/mysql/`、`conf/app_config.yaml`、`.env.example`
- **Accepts:** 部署环境变量。
- **Returns:** 只读查询账号和可复现权限检查。
- **AC Coverage:** AC-07、AC-22。

## Technology Choices

| Decision | Choice | Rationale |
|---|---|---|
| SQL AST | 已锁定 SQLGlot 29.0.1 | 已在项目内使用；AST 可改写；官方明确仍需真实数据库验证 |
| SQL 预检 | MySQL `EXPLAIN` | 使用目标数据库方言和 schema，不把 parser 当 validator |
| 查询超时 | MySQL `MAX_EXECUTION_TIME` + asyncio deadline | 同时覆盖服务端执行与客户端/连接等待 |
| 混合检索 | Qdrant dense + BM25 sparse | 当前服务版本已支持，无需新增检索服务 |
| 排名融合 | 现有 `ReciprocalRankFusion` | 保留通道排名与贡献，满足可解释合同 |
| 审计存储 | aiosqlite | 官方异步 SQLite 桥接，适合当前单实例轻量部署 |
| 负载测试 | Locust | 复用成熟 Python HTTP 负载框架，不自研并发统计器 |
| 异步单测 | 标准库 IsolatedAsyncioTestCase | 避免仅为少量 async 测试新增插件 |

详细来源与替代方案见 `decision_log.md`。

## Integration Points

- **FastAPI:** 路由生成/传递 request id，Service 输出 SSE。
- **LangGraph:** graph factory 负责编排；Context 注入 Guard、TraceStore 和 Repositories。
- **MySQL:** Meta 账号写元数据；DW reader 只读、预检和查询。
- **Qdrant:** v2 collection 保存 dense/sparse named vectors与实体 payload。
- **Elasticsearch:** 只负责业务值召回，不参与跨类型总排名。
- **Frontend:** 保留 data JSON 解析方式，扩展事件联合类型和终态处理。
- **GitHub Actions:** 运行确定性门禁，不连接真实 LLM。

## AC Coverage Map

| AC | Component(s) | Contract(s) |
|---|---|---|
| AC-01 | SQL Safety, Execution Boundary | `contracts/sql-safety.md` |
| AC-02 | SQL Safety | `contracts/sql-safety.md` |
| AC-03 | SQL Safety | `contracts/sql-safety.md` |
| AC-04 | SQL Safety, Execution Boundary | `contracts/sql-safety.md` |
| AC-05 | Execution Boundary, Workflow | `contracts/sql-safety.md` |
| AC-06 | SQL Safety, Workflow | `contracts/sql-safety.md` |
| AC-07 | Deployment | `contracts/sql-safety.md` |
| AC-08 | SQL Safety, Execution Boundary | `contracts/sql-safety.md` |
| AC-09 | Event/Trace, API | `contracts/query-api.md` |
| AC-10 | Event/Trace, API | `contracts/query-api.md` |
| AC-11 | Event/Trace | `contracts/trace-store.md` |
| AC-12 | Event/Trace | `contracts/trace-store.md` |
| AC-13 | Workflow | `contracts/workflow.md` |
| AC-14 | Retrieval | `contracts/retrieval.md` |
| AC-15 | Retrieval | `contracts/retrieval.md` |
| AC-16 | Retrieval | `contracts/retrieval.md` |
| AC-18 | Workflow, Event/Trace, Evaluation | `contracts/workflow.md`, `contracts/query-api.md` |
| AC-20 | Retrieval, Evaluation | `contracts/retrieval.md`, `contracts/evaluation.md` |
| AC-21 | SQL Safety, Evaluation | `contracts/evaluation.md` |
| AC-22 | Evaluation, Deployment | `contracts/evaluation.md` |
| AC-24 | Execution, Workflow, Event/Trace, API | `contracts/workflow.md`, `contracts/trace-store.md` |
| AC-25 | API | `contracts/query-api.md` |

## Implementation Sequence and Per-Step Gates

1. **Configuration/dependencies:** dependency lock and typed configuration tests; full baseline; commit/push.
2. **SQLGuard hardening:** boundary tests first; Guard implementation; micro-benchmark; full baseline; commit/push.
3. **Online safety loop:** fake Repository tests first; Guard→EXPLAIN→run, error routing and timeout; full baseline; commit/push.
4. **Least privilege:** static compose/grant tests first; account split; optional Docker permission test; full baseline; commit/push.
5. **Async trace + SSE:** contract/concurrency/cancellation tests first; implementation and frontend types; full backend/frontend gates; commit/push.
6. **Workflow factory:** fan-in/order/terminal tests first; factory and injectable nodes; full baseline; commit/push.
7. **Hybrid retrieval:** index/repository/fusion tests first; v2 build and recall integration; offline ablation; full baseline; commit/push.
8. **Evaluation truthfulness:** metric contract tests first; SQL metric rename, 30+ retrieval set, deterministic E2E; CI update; commit/push.
9. **Clarification:** missing-date/entity/conflict tests first; node and routing; full baseline; commit/push.
10. **Scale harness:** deterministic generator tests first; Locust scenario and report schema; smoke run; commit/push.
11. **Optional checkpoint:** only after all MUST/SHOULD gates pass; separate spec delta if state serialization or side-effect semantics changes.

Each gate runs at minimum: `uv run ruff check app tests eval`, `uv run pytest -q`, SQL/retrieval evaluators, and `pnpm build` when frontend changes.

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| SQLGlot宽松解析放过数据库不接受的 SQL | High | High | 永远保留 MySQL EXPLAIN；解析成功不视为可执行 |
| CTE/别名/星号导致错误白名单判断 | Medium | High | 作用域化测试；不能证明安全的形状显式拒绝 |
| Qdrant v2 collection与旧索引不兼容 | High | Medium | 新 collection 名并行构建；不原地改旧 schema |
| 本地 Qdrant BM25行为与文档版本差异 | Medium | Medium | Repository 合同测试 + Docker 集成标记；失败时回退现有 dense 通道且不伪报 hybrid 指标 |
| SQLite并发写锁 | Medium | High | 单异步连接、WAL、原子事务、20 并发测试；多实例明确不支持 |
| SSE增强破坏前端 | Medium | High | 保留 payload `type`；前后端合同测试与构建门禁 |
| 超时取消后连接污染 | Medium | High | rollback/close测试；下一请求复用验证 |
| 真实模型输出不确定导致 CI 抖动 | High | Medium | CI 全部使用确定性替身；真实评测单独标记 |
| 一次升级过大难以回滚 | Medium | High | 10 个独立任务和独立 push，不跨任务堆改动 |

## Out of Scope (Technical)

- 不新增独立鉴权服务、消息队列、分布式追踪平台或第二个向量数据库。
- 不原地迁移现有 Qdrant collection；使用版本化新 collection。
- 不在 CI 启动真实 LLM 或默认生成百万行数据。
- 不把 SQLite 方案描述为多实例生产数据库。
- 不把 checkpoint、审计事件和跨会话长期记忆混为同一存储。
