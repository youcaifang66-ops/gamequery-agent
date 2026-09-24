# GameQuery 源码导学（可靠性升级版）

## 学习目标与事实边界

GameQuery 接收游戏运营自然语言问题，召回字段、指标和字段值上下文，生成并校验 SQL，用只读账号查询模拟数仓，再通过 SSE 返回可追踪事件。本课程沿升级后的真实在线调用链阅读源码。

项目由上游 fork 后改造，不是从零原创；数据是可复现模拟数据，不代表企业线上效果。固定 SQL/检索 fixture、真实服务集成和规模工具分别证明不同事情，不能混成“准确率 100%”或“支持千万级”。

项目绝对根目录：`D:\Code\求职之路\Agent JD与简历\projects\gamequery`

## 阅读路径总表

按顺序读重点符号，不要从目录第一行开始通读。

| 顺序 | 路径 | 重点符号 | 读完要回答的问题 |
|---:|---|---|---|
| 01 | `main.py` | `app`、请求 ID 中间件、`health` | 应用入口和请求标识如何建立？ |
| 02 | `app/api/routers/query_router.py` | `query_handler` | `/api/query` 如何返回 SSE？ |
| 03 | `app/api/dependencies.py` | `get_query_service` | 一次请求如何组装依赖并关闭 DB session？ |
| 04 | `app/api/lifespan.py` | `lifespan` | 共享客户端和 TraceStore 何时开关？ |
| 05 | `app/services/query_service.py` | `QueryService.query` | trace、截止时间、graph stream、唯一终态如何串联？ |
| 06 | `app/agent/state.py` | `DataAgentState` | 哪些数据能跨节点传递？ |
| 07 | `app/agent/context.py` | `DataAgentContext` | 为什么连接和 Guard 不放 State？ |
| 08 | `app/agent/graph.py` | `DEFAULT_NODES`、`build_graph`、`route_after_validation` | 14 节点、两个 barrier 与纠错环如何工作？ |
| 09 | `app/agent/nodes/extract_keywords.py` | `extract_keywords` | 问题如何拆成召回关键词？ |
| 10 | `app/agent/nodes/recall_column.py` | `recall_column` | 字段多通道排名如何产生 evidence？ |
| 11 | `app/agent/nodes/recall_metric.py` | `recall_metric` | 指标口径如何召回且与字段隔离？ |
| 12 | `app/agent/nodes/recall_value.py` | `recall_value` | 游戏名、渠道等真实值如何定位？ |
| 13 | `app/retrieval/fusion.py` | `ReciprocalRankFusion.fuse` | 为什么用 rank 而不直接加原始分数？ |
| 14 | `app/agent/nodes/merge_retrieved_info.py` | `merge_retrieved_info` | 三种实体怎样合并而不混分？ |
| 15 | `app/agent/nodes/filter_table.py` | `filter_table` | 如何缩小表/字段上下文？ |
| 16 | `app/agent/nodes/filter_metric.py` | `filter_metric` | 如何选定指标口径？ |
| 17 | `app/agent/nodes/check_query_context.py` | `check_query_context` | 哪些缺失会触发澄清？ |
| 18 | `app/agent/nodes/generate_sql.py` | `generate_sql` | 提示词获得哪些可信上下文？ |
| 19 | `app/security/sql_guard.py` | `SQLGuard.validate` | AST、作用域、白名单与 LIMIT 如何校验？ |
| 20 | `app/agent/nodes/validate_sql.py` | `validate_sql` | GuardedSQL 怎样进入 EXPLAIN？ |
| 21 | `app/agent/nodes/correct_sql.py` | `correct_sql` | 修正次数和候选版本如何记录？ |
| 22 | `app/repositories/mysql/dw/dw_mysql_repository.py` | `validate`、`run` | 同一 SQL 如何预检、超时、回滚、限量？ |
| 23 | `app/agent/nodes/run_sql.py` | `run_sql` | 为什么不能传入原始 SQL？ |
| 24 | `app/agent/nodes/fail_sql.py` | `fail_sql` | 失败怎样变成稳定终态？ |
| 25 | `app/api/sse.py` | `encode_sse` | event/data 和兼容 payload 如何编码？ |
| 26 | `app/observability/trace_store.py` | `SQLiteTraceStore` | 并发序号、事务、唯一终态和脱敏如何实现？ |
| 27 | `frontend/src/lib/agentApi.ts` | SSE parser | 前端怎样消费并识别终态？ |
| 28 | `tests/test_agent_workflow_e2e.py` | 六类场景 | 怎样在不调用真实 LLM 时验证工作流？ |
| 29 | `tests/integration/test_services.py` | MySQL/Qdrant tests | 哪些结论由真实服务而非 mock 支撑？ |
| 30 | `specs/reliable-agent-upgrade/validation.md` | AC matrix | 哪些已验证、哪些仍未验证？ |

## 第一课：HTTP、SSE 与请求生命周期

先读 01~05 和 25。调用链是：

```text
POST /api/query
  → FastAPI dependency graph
  → QueryService.query
  → graph.astream(stream_mode="custom")
  → EventEnvelope
  → encode_sse
  → 浏览器
```

重点区分三种资源：请求级 MySQL session 用 context manager 关闭；Qdrant/ES/Embedding 是应用级共享客户端，由 lifespan 关闭；SQLite TraceStore 是应用级实例，但每条请求建立独立 trace。超时发生在响应流开始后，因此不能再可靠地改 HTTP 状态码，要用稳定的 SSE error 终态表达。

练习：指出 request_id 在 HTTP header、SSE envelope 和 trace 中如何保持一致；再解释为什么同一请求不能同时发 `done` 和 `error`。

## 第二课：LangGraph State、Context 与 14 节点 DAG

读 06~08。`DataAgentState` 是可序列化业务快照，`DataAgentContext` 是运行时能力。连接池若放进 State，会破坏序列化、测试替换和检查点边界。

图中有两个显式列表 barrier：三路 recall 全完成后才 merge；table/metric filter 都完成后才 add context。它们把“并行分支汇合一次”写成结构，而不是依赖碰巧的调度顺序。

验证节点的三条分支：无错误执行；错误可纠正且次数小于 2 时修正；否则进入 `fail_sql`。`correct_sql` 必须回到 `validate_sql`，不能把新 SQL 直接交给执行节点。

练习：画出安全拒绝和一次纠错成功两条节点序列，并在 `tests/test_agent_graph.py` 找到对应断言。

## 第三课：三类召回与同类多通道融合

读 09~14，再看：

- `app/repositories/qdrant/column_qdrant_repository.py`
- `app/repositories/qdrant/metric_qdrant_repository.py`
- `app/repositories/es/value_es_repository.py`
- `app/services/meta_knowledge_service.py`

字段、指标、字段值必须先做实体类型隔离。字段和指标在各自 Qdrant v2 collection 中保存 deterministic point、dense vector 与 BM25 sparse document；在线节点同时利用原词、扩词、exact/alias 和 lexical 排名。RRF 的输入是同类候选排名，输出包含总分和逐通道贡献。值检索走 ES，并不拿 ES 分数和 Qdrant 分数硬加。

练习：用“统计 2026-09-18 星海远征的 DAU”分别写出三条链路要找的对象。再解释 dense 相似度和 BM25 分数为什么不能未经标定直接相加。

## 第四课：从候选上下文到澄清或 SQL

读 15~18，并对照：

- `conf/metrics.yaml`
- `prompts/filter_table_info.prompt`
- `prompts/filter_metric_info.prompt`
- `prompts/generate_sql.prompt`

过滤节点不是新的检索器，而是从已召回候选中挑选与问题相关的 Schema 和指标。`check_query_context` 在 SQL 生成前检查日期、游戏匹配和指标冲突；缺失时返回 clarification。这里的原则是“不猜关键业务槽位”。

练习：分别说明“星际争霸的 DAU”和“2026-09-18 星际争霸的 DAU”为什么可能走不同分支；如果游戏存在但当天无记录，为什么应返回空结果而不是错误或编造值。

## 第五课：不可绕过的 SQL 安全链

读 19~24，再看 `conf/meta_config.yaml` 与 `docker/mysql/99-grants.sh`。

```text
LLM candidate
  → SQLGlot AST parse
  → 单条只读/作用域/表列白名单
  → LIMIT 500 与超时提示
  → GuardedSQL
  → MySQL EXPLAIN
  → SELECT-only reader 执行
```

AST Guard 和 EXPLAIN 不能互相替代：前者执行应用安全策略，后者检查真实数据库方言与对象。最小权限则是最后防线。不可纠错的策略违规不应发送给模型，以免模型被激励去绕过策略；可纠错错误最多两次，且每次重新走全链。

练习：在 `tests/test_sql_guard.py` 中分别找多语句、写操作、系统对象、未知字段、CTE/别名、`COUNT(*)` 和动态 LIMIT 的期望；在服务集成测试中找数据库拒绝五类写操作的证据。

## 第六课：Trace、并发与资源清理

读 25~27，并看：

- `tests/test_trace_store.py`
- `tests/test_trace_dependencies.py`
- `tests/test_query_service.py`
- `tests/test_dw_repository.py`

TraceStore 使用 aiosqlite、WAL、事务和 async lock。事件 sequence 在同一 trace 内递增，终态只能写一次；结果明细不落 trace。取消或超时后，数据库 session 要 rollback/close，TraceStore 与 QueryService 仍能服务下一请求。

练习：解释“20 个并发 append 不重号”证明了什么、没证明什么。它证明单进程异步写的一致性，不证明多实例共享 SQLite 的生产可扩展性。

## 第七课：测试与指标真实性

优先阅读：

- `tests/test_agent_workflow_e2e.py`
- `tests/test_api_routes.py`
- `tests/integration/test_services.py`
- `eval/run_sql_eval.py`
- `eval/run_retrieval_eval.py`
- `eval/latest_metrics.json`
- `eval/latest_retrieval_metrics.json`

确定性 E2E 用 fake 节点/依赖覆盖成功、一次纠错成功、纠错耗尽、安全拒绝、外部依赖失败和超时，不调用真实 LLM。真实服务集成在 GitHub CI 中验证 MySQL 权限和 Qdrant dense/BM25 协议兼容。

SQL fixture 的 75% 是 12/16 个可执行目标首轮通过；预设修复率 100% 来自人工给定修复 SQL；真实 Agent 纠错是 `not_run`。检索 fixture 融合 Hit@5/MRR 1.0 也只是固定排名回归。面试时先说 `mode`、数据集、分母和未覆盖项，再说数字。

## 第八课：规模边界与生产差距

读：

- `eval/generate_scale_data.py`
- `eval/locustfile.py`
- `eval/load_report.schema.json`
- `.github/workflows/ci.yml`

生成器支持固定随机种子的 10 万/100 万事实行预设，Locust 描述 SSE 用户行为，报告 schema 强制记录硬件、版本、索引、并发、预热和 p50/p95/p99。CI 只跑 smoke，因此当前没有可引用的端到端 QPS、P95 或容量上限。

走向生产还需要：真实自然语言黄金集、目标硬件正式负载、Elasticsearch/LLM 全链路集成、鉴权与多租户、监控告警、灰度和数据治理。千万级不是代码开关，而是数据模型、索引/分区、预聚合、查询模式和 SLA 的联合验收。

## 面试前自测

如果下面 10 题能不看稿回答，才算真正读懂：

1. 三条召回链路分别解决什么映射？
2. Qdrant 与 Embedding 为什么不是二选一？
3. RRF 为什么比直接加分更稳？
4. 两个 LangGraph barrier 防什么回归？
5. 什么错误可纠错，什么错误必须立即终止？
6. Guard、EXPLAIN、只读账号各自防哪一层风险？
7. SSE 为什么要 request_id、sequence 和唯一终态？
8. SQL 75%/100% 和检索 Hit@5 1.0 分别不能证明什么？
9. 为什么目前不能回答“支持多少数据量/QPS”？
10. fork、AI 辅助与你本人可核验贡献的边界是什么？

答不上时回到对应课程和测试，不要背 README。最终验收边界以 `specs/reliable-agent-upgrade/validation.md` 为准。
