# GameQuery 可靠性补全：现状研究

日期：2026-09-23
阶段：SDD Phase 0.5
范围：在线查询链路、检索、SQL 安全、追踪、评测、部署与测试

## 相关文件清单

- API 与服务：`app/api/routers/query_router.py`、`app/api/dependencies.py`、`app/api/schemas/query_schema.py`、`app/api/sse.py`、`app/services/query_service.py`。（`app/api/routers/query_router.py:14-34`；`app/api/dependencies.py:15-27`）
- 工作流：`app/agent/graph.py`、`app/agent/state.py`、`app/agent/context.py` 与 `app/agent/nodes/` 下的召回、合并、校验、纠错、执行节点。（`app/agent/graph.py:15-40`）
- 安全与执行：`app/security/sql_guard.py`、`app/repositories/mysql/dw/dw_mysql_repository.py`、`docker/mysql/dw.sql`。（`app/security/sql_guard.py:20-72`；`app/repositories/mysql/dw/dw_mysql_repository.py:14-54`）
- 检索与追踪：`app/retrieval/fusion.py`、`app/observability/trace_store.py`。（`app/retrieval/fusion.py:1-54`；`app/observability/trace_store.py:1-69`）
- 配置与部署：`conf/app_config.yaml`、`conf/meta_config.yaml`、`docker/docker-compose.yaml`、`pyproject.toml`。（`conf/app_config.yaml:1-44`；`docker/docker-compose.yaml:1-93`）
- 验证证据：`tests/`、`eval/sql_benchmark.json`、`eval/run_sql_eval.py`、`.github/workflows/ci.yml`。（`.github/workflows/ci.yml:1-35`；`eval/run_sql_eval.py:39-87`）

## 入口与依赖组装

- `POST /api/query` 接收 `QuerySchema`，通过 FastAPI `Depends` 获取 `QueryService`，并把服务的异步生成器作为 `text/event-stream` 返回。（`app/api/routers/query_router.py:22-34`）
- 请求体目前只有 `query` 字段，长度范围为 2–1000；没有调用方提供的 `thread_id`、`trace_id` 或会话字段。（`app/api/schemas/query_schema.py:11-15`）
- 依赖层为一次请求组装 Meta MySQL、DW MySQL、Embedding、两个 Qdrant Repository 和一个 Elasticsearch Repository。（`app/api/dependencies.py:85-110`）
- Meta 与 DW 数据库会话均通过请求级异步上下文创建并在请求结束时释放。（`app/api/dependencies.py:30-35`；`app/api/dependencies.py:52-56`）

## 在线执行流

- `QueryService` 将用户问题放入 `DataAgentState`，将六个外部依赖放入 `DataAgentContext`，再调用已编译图的 `astream`。（`app/services/query_service.py:46-65`）
- 服务为整次查询设置 60 秒超时；超时返回 `QUERY_TIMEOUT`，其他异常直接把异常字符串放入 SSE 消息。（`app/services/query_service.py:60-75`）
- 服务目前手工拼接只有 `data:` 行的 SSE；仓库中另有会校验事件类型并同时输出 `event:` 与 `data:` 的 `encode_sse`，但该服务没有调用它。（`app/services/query_service.py:66-75`；`app/api/sse.py:3-12`）
- 图注册 12 个节点，顺序是关键词抽取、三路召回、召回合并、表/指标双路过滤、上下文补全、SQL 生成、校验、最多两次纠错和执行。（`app/agent/graph.py:42-57`；`app/agent/graph.py:59-97`）
- 三路召回从同一个关键词抽取节点并行发出，分别写入字段、字段值和指标结果；随后汇合到同一个合并节点。（`app/agent/graph.py:59-70`；`app/agent/state.py:66-73`）
- 当前锁定的 LangGraph 图通过无参数 `compile()` 构建，没有注入 checkpointer；调用 `astream` 时也没有传入 `thread_id` 配置。（`app/agent/graph.py:99-100`；`app/services/query_service.py:61-65`）

## 状态与上下文

- `DataAgentState` 包含问题、关键词、三类召回实体、表/指标/日期/数据库上下文、SQL、错误和纠错次数。（`app/agent/state.py:63-80`）
- `DataAgentContext` 只保存 Embedding、Qdrant、Elasticsearch 和两个 MySQL Repository 等运行时依赖。（`app/agent/context.py:22-36`）
- SQL 执行结果不进入 State，而是由执行节点直接写为自定义流事件。（`app/agent/nodes/run_sql.py:15-31`）

## 三路召回与合并

- 字段召回对每个关键词先调用 LLM 扩展，再对扩展词逐个做 Embedding 和 Qdrant 查询，最终按对象 `id` 去重。（`app/agent/nodes/recall_column.py:35-67`）
- 指标召回采用同样的“LLM 扩词→Embedding→Qdrant→按 `id` 去重”结构。（`app/agent/nodes/recall_metric.py:35-67`）
- 字段值召回对每个关键词先调用 LLM 扩展，再逐个查询 Elasticsearch，最终按对象 `id` 去重。（`app/agent/nodes/recall_value.py:34-65`）
- 合并节点按字段 `id` 去重，补齐指标依赖字段，把值召回写入字段 examples，并补齐候选表主外键。（`app/agent/nodes/merge_retrieved_info.py:45-102`）
- 合并节点最后只输出按表组织的字段上下文和指标上下文；输出结构没有检索通道、原始排名或融合分数。（`app/agent/nodes/merge_retrieved_info.py:104-154`）
- 仓库已有通用 RRF 类，可按 `vector`、`exact`、`alias`、`llm_expand` 通道累积分数并保存贡献证据，但在线召回节点没有导入或调用它。（`app/retrieval/fusion.py:18-54`；`app/agent/nodes/recall_column.py:1-14`；`app/agent/nodes/recall_metric.py:1-14`）

## SQL 校验、纠错与执行

- `validate_sql` 当前只把候选 SQL 交给 DW Repository；Repository 使用 `EXPLAIN <sql>` 判断数据库是否接受该语句。（`app/agent/nodes/validate_sql.py:23-40`；`app/repositories/mysql/dw/dw_mysql_repository.py:46-49`）
- `run_sql` 从 State 取出同一 SQL 字符串并直接交给 DW Repository 执行，Repository 使用 SQLAlchemy `text(sql)` 并返回全部结果行。（`app/agent/nodes/run_sql.py:22-31`；`app/repositories/mysql/dw/dw_mysql_repository.py:51-54`）
- 在线 `validate_sql` 和 `run_sql` 均没有导入或调用仓库中已有的 `SQLGuard`。（`app/agent/nodes/validate_sql.py:8-13`；`app/agent/nodes/run_sql.py:8-12`）
- `SQLGuard` 使用 SQLGlot 的 MySQL 方言解析 SQL，拒绝多语句、非 Query、写操作、未知表和未知字段。（`app/security/sql_guard.py:34-64`）
- `SQLGuard` 对 `*` 跳过字段级检查；仅在没有 `LIMIT` 时补 500，不会压低已有的超大 `LIMIT`。（`app/security/sql_guard.py:56-68`）
- 校验失败时图最多进入两次 LLM 纠错，每次纠错结果都会返回 `validate_sql`；两次后仍失败则直接结束。（`app/agent/graph.py:82-97`；`app/agent/nodes/correct_sql.py:72-74`）
- 校验节点把数据库异常文本写入 State，服务层也会把未处理异常文本返回给客户端。（`app/agent/nodes/validate_sql.py:36-40`；`app/services/query_service.py:72-75`）

## 数据库权限与配置

- DW 初始化脚本把 `dw.*` 的 `ALL PRIVILEGES` 授给 `didilili`，在线配置也使用该用户访问 DW。（`docker/mysql/dw.sql:1-4`；`conf/app_config.yaml:19-24`）
- 应用与 MySQL 容器配置包含同一个明文默认密码 `dili123`。（`docker/docker-compose.yaml:9-16`；`docker/docker-compose.yaml:28-40`；`conf/app_config.yaml:12-24`）
- Docker Compose 使用 MySQL 8.0、Elasticsearch 8.19.10、Qdrant 1.16 和 Hugging Face TEI CPU 1.8。（`docker/docker-compose.yaml:28-29`；`docker/docker-compose.yaml:44-56`；`docker/docker-compose.yaml:66-77`）
- 当前元数据定义 6 张表、35 个字段和 5 个业务指标。（`conf/meta_config.yaml:1-66`；`conf/meta_config.yaml:67-87`）

## 追踪与恢复

- `SQLiteTraceStore` 已定义 query trace 与有序事件表，并提供 start、append、finish 和 replay 操作。（`app/observability/trace_store.py:7-69`）
- `SQLiteTraceStore` 使用同步 `sqlite3` 连接和同步 commit；依赖组装与查询服务没有创建或注入该存储。（`app/observability/trace_store.py:7-10`；`app/observability/trace_store.py:23-52`；`app/api/dependencies.py:85-110`）
- 现有追踪测试只验证单线程内两个事件的顺序和回放结果。（`tests/test_trace_store.py:4-14`）

## 当前测试与评测证据

- SQLGuard 测试覆盖“合法查询自动补 LIMIT”以及 DELETE、系统表、未知字段和多语句四类拒绝场景。（`tests/test_sql_guard.py:10-31`）
- RRF 测试覆盖多通道候选优先和同分确定性排序，但没有覆盖在线召回链路。（`tests/test_retrieval_fusion.py:8-22`）
- 离线 SQL 工作集包含 12 条合法 SQL、4 条带人工 `corrected_sql` 的可修复 SQL和 4 条不安全 SQL。（`eval/sql_benchmark.json:2-27`）
- 评测器没有运行 LangGraph 或 LLM；它直接执行合法 SQL，并对可修复样本直接使用数据集中的 `corrected_sql`。（`eval/run_sql_eval.py:39-70`）
- `success_after_correction` 与 `execution_result_accuracy` 都使用上述预置修复后的结果计数，因此当前指标不能证明在线 Agent 的自动纠错成功率。（`eval/run_sql_eval.py:59-79`）
- CI 后端依次执行依赖冻结安装、Ruff、pytest 和离线 SQL 评测；前端执行冻结安装与 Vite 构建。（`.github/workflows/ci.yml:7-17`；`.github/workflows/ci.yml:19-35`）

## 现有约束

- Python 版本范围为 `>=3.12,<3.14`，主要运行依赖通过 `pyproject.toml` 声明并由 `uv.lock` 固定解析结果。（`pyproject.toml:1-25`）
- Ruff 目标版本是 Python 3.12，启用 E、F、I 规则；pytest 将项目根目录加入模块路径。（`pyproject.toml:35-44`）
- API 当前依赖流式 SSE，异常发生在响应开始后不能改写 HTTP 状态码。（`app/api/routers/query_router.py:31-34`；`app/services/query_service.py:72-75`）

## 冲突与核验结论

- `[CONFLICT]` 图中三路汇合使用三条独立入边而不是显式列表入边；在当前 LangGraph 1.1.6 的本地行为核验中只调度一次，但仓库没有把这一版本相关语义固定成回归测试。（`app/agent/graph.py:67-70`；`pyproject.toml:18`）
- `[CONFLICT]` 仓库同时存在 RRF、TraceStore 和 SSE 编码器的独立实现与测试，但在线服务链路没有消费这三项能力。（`app/retrieval/fusion.py:18-54`；`app/observability/trace_store.py:7-69`；`app/api/sse.py:3-12`；`app/services/query_service.py:46-75`）

## 未调查范围

- 未启动完整 Docker Compose，因此尚未核验真实 MySQL 用户权限、Qdrant/Elasticsearch 索引内容和跨服务端到端时延。
- 未调用真实 LLM，因此尚未核验关键词扩展、过滤、SQL 生成和自动纠错的实际质量。
- 未进行并发压测，因此尚无可复现的吞吐量、p95/p99 或最大数据规模结论。
- 未检查生产网关、鉴权和部署平台；仓库只呈现本地/容器配置。

## 供规格阶段回答的问题

1. 哪些安全错误允许进入 LLM 纠错，哪些必须立即终止？
2. 在线兼容是否要求保留现有 SSE `data:` 结构，还是允许新增 `event:`、`trace_id` 和终止事件？
3. RRF 应当融合哪些同类检索通道，Top-K 和评测阈值如何定义？
4. 持久化目标是请求审计、失败回放、会话续跑，还是三者都需要？
5. 首个可验证的数据规模与并发目标应设为多少，真实 LLM 评测是否作为可选人工门禁？
