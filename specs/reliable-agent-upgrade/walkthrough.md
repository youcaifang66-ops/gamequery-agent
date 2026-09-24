# Walkthrough: 从请求到可审计结果

## 1. 请求入口

`main.py` 创建 FastAPI 应用并安装请求 ID 中间件。`app/api/routers/query_router.py` 接收 `POST /api/query`，由 `app/api/dependencies.py` 为该请求组装仓储、SQLGuard、TraceStore 和 QueryService。返回类型是 `text/event-stream`。

## 2. 状态与编排

`app/services/query_service.py` 创建 trace 与 LangGraph state/context，并消费 `graph.astream`。`app/agent/graph.py` 使用显式 barrier 编排：

```text
extract_keywords
  ├─ recall_column ─┐
  ├─ recall_metric ─┼─ merge_retrieved_info
  └─ recall_value  ─┘
                        ├─ filter_table  ─┐
                        └─ filter_metric ─┼─ add_extra_context
                                           → check_query_context
                                           → generate_sql
                                           → validate_sql
                                               ├─ run_sql
                                               ├─ correct_sql → validate_sql（最多 2 次）
                                               └─ 安全拒绝/耗尽终止
```

State 只放可序列化业务数据；MySQL、Qdrant、Elasticsearch、Embedding、Guard 和 TraceStore 放在 runtime context 中，避免把连接对象混入检查点状态。

## 3. 为什么检索分三类

- 字段链路回答“SQL 应该用哪些表和列”。
- 指标链路回答“DAU、ARPU 等业务词按什么公式计算”。
- 字段值链路回答“星海远征、Android、华北这些字面值落在哪个列”。

字段与指标各自在 Qdrant 中做 dense、BM25 lexical、exact/alias、LLM-expand 等同类通道召回，再由应用层 RRF 融合并保存每个通道的 rank/contribution。业务值继续由 Elasticsearch 处理，不把异构分数强行相加。若问题超出已有 Schema/指标/值能力，系统应澄清或拒答；本轮没有自动切换 Agentic RAG。

## 4. SQL 安全链

`generate_sql` 产出的文本不能直接执行：

1. `SQLGuard` 用 SQLGlot 解析 AST，只接受单条只读 SQL；
2. 校验表、列、作用域、CTE/别名与星号边界；
3. 添加或收敛 `LIMIT 500`，并注入执行超时提示；
4. DW Repository 对同一规范化 SQL 执行 MySQL `EXPLAIN`；
5. 只有 `GuardedSQL` 能进入 `run_sql`；
6. 数据库账号自身只有 SELECT 权限，形成应用层与数据库层双保险。

安全策略违规不可交给模型“改写绕过”。语法、白名单或预检类可纠错错误最多修正两次，并且每个新候选都从完整 Guard 开始重验。

## 5. SSE 与追踪

每个事件包含 `request_id`、递增 `sequence`、时间、事件名以及保留兼容的 payload `type`。一条请求只允许一个 `done` 或 `error` 终态。SQLite TraceStore 使用 aiosqlite、WAL、事务与异步锁保存决策事件；查询结果本身不落 trace，减少敏感数据暴露。

前端 `frontend/src/lib/agentApi.ts` 同时消费 SSE `event:` 和 `data:`，并保持旧 payload 的解析兼容。

## 6. 六类确定性失败路径

`tests/test_agent_workflow_e2e.py` 不调用真实 LLM，而使用固定依赖覆盖：正常成功、一次纠错成功、纠错耗尽、安全拒绝、外部依赖失败、整请求超时。测试同时断言节点顺序、候选 SQL 版本、Repository 调用以及唯一终态。

## 7. 如何解释评测

- SQL fixture：20 条固定样例用于验证 Guard 和预设修复器。Guard accuracy 1.0 不等于 LLM Text-to-SQL 准确率。
- 检索 fixture：32 条固定候选排序用于验证评测器、RRF 与消融合同。融合 Hit@5/MRR 1.0 是 fixture 结果，不是线上 Qdrant 质量。
- 服务集成：CI 中真实 MySQL 与 Qdrant 证明权限和协议兼容，但没有覆盖真实 LLM、Elasticsearch 全链路或企业数据分布。
- 规模：该轮验收当时只具备 10 万/100 万生成器；后续千万级合成数据、隔离 MySQL 导入与固定查询实测见 `specs/synthetic-business-scale/validation.md`。新证据仍不代表生产容量上限或端到端 Agent P95。

## 8. 最短代码阅读顺序

1. `app/api/routers/query_router.py`
2. `app/services/query_service.py`
3. `app/agent/graph.py`
4. `app/agent/state.py` 与 `app/agent/context.py`
5. `app/agent/nodes/recall_column.py`、`recall_metric.py`、`recall_value.py`
6. `app/retrieval/fusion.py`
7. `app/agent/nodes/validate_sql.py` 与 `app/security/sql_guard.py`
8. `app/repositories/mysql/dw/dw_mysql_repository.py`
9. `app/agent/nodes/run_sql.py`
10. `app/observability/trace_store.py`
11. `tests/test_agent_workflow_e2e.py`
12. `tests/integration/test_services.py`
