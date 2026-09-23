# GameQuery 源码课程

## 项目与学习目标

GameQuery 是一个面向游戏运营分析的 Text-to-SQL Agent：接收自然语言问题，召回 Schema、指标和字段值上下文，生成 SQL，经过校验与有限纠错后查询数仓，并通过 SSE 返回执行过程。

本课程面向“目前能运行项目，但还不能独立讲清源码”的学习阶段。目标不是背诵 README，而是沿真实调用链回答四类问题：一次请求如何流动、LangGraph 如何控制状态与分支、SQL 为什么可能不安全、简历中的指标究竟证明了什么。

## 源码版本与本地状态

- 仓库：`projects/gamequery`
- 当前版本：`fe89a9f`（`docs: redesign repository homepage`）
- 上游：`didilili/shopkeeper-agent`
- 课程生成前，除本课程文件外未发现待提交源码改动。
- 影响结论的重要实现差异：README 把 SQL AST 护栏、RRF 融合和 SQLite 轨迹描述为系统主链能力，但当前源码引用关系显示 `SQLGuard`、`ReciprocalRankFusion`、`SQLiteTraceStore` 和 `BoundedSQLCorrector` 主要由测试或离线评测调用，尚未接入 `QueryService -> graph` 的在线主链。课程会分别讲“已接入链路”和“独立组件”，不把两者混为一谈。

## 前置基础

- Python：函数、类、异常、`async/await`、异步生成器。
- Web：HTTP 请求、FastAPI 路由、依赖注入、SSE 的基本含义。
- 数据库：SELECT、表与字段、MySQL `EXPLAIN`。
- AI Agent：先知道“状态 + 节点 + 边”即可；课程中再学习 LangGraph。
- 检索：先知道关键词检索与向量检索是两种找候选的方法即可。

## 覆盖范围

本轮覆盖后端查询主链、LangGraph 编排、三路召回、SQL 生成与纠错、AST 安全组件、离线评测和可观测组件。前端 React 页面、Docker 基础设施细节、Embedding 模型原理和上游仓库的逐提交对比暂不展开；它们可在主链掌握后追加课程。

## 源码阅读路径总表

项目绝对根目录：`D:\Code\求职之路\Agent JD与简历\projects\gamequery`

下面所有路径均相对于该根目录。不要一次读完；按表中的顺序逐个打开，只关注“重点符号”指定的部分。

### 第一轮：必须读懂的在线主链

| 顺序 | 源码路径 | 重点符号 | 你要理解什么 | 对应课程 |
| ---: | --- | --- | --- | --- |
| 01 | `main.py` | `app`、`add_request_id`、`health` | FastAPI 应用如何创建、挂载路由并加入请求 ID | 01 |
| 02 | `app/api/schemas/query_schema.py` | `QuerySchema` | `/api/query` 请求体的数据形状 | 01 |
| 03 | `app/api/routers/query_router.py` | `query_handler` | HTTP 请求如何交给服务层并返回 SSE | 01 |
| 04 | `app/api/dependencies.py` | `get_meta_session`、`get_dw_session`、`get_query_service` | FastAPI 如何递归组装仓储和 `QueryService` | 01、03 |
| 05 | `app/api/lifespan.py` | `lifespan` | 外部客户端何时初始化、何时关闭 | 03 |
| 06 | `app/services/query_service.py` | `QueryService.__init__`、`QueryService.query` | State、Context、`graph.astream` 和 SSE 的衔接 | 01、03 |
| 07 | `app/agent/state.py` | `DataAgentState` 及嵌套 TypedDict | 哪些业务数据会在节点之间流转 | 02 |
| 08 | `app/agent/context.py` | `DataAgentContext` | 为什么 Repository 和客户端不放进 State | 02、03 |
| 09 | `app/agent/graph.py` | `graph_builder`、`route_after_validation`、`graph` | 12 个节点、并行分支、汇合点和有限纠错循环 | 02、06 |
| 10 | `app/agent/nodes/extract_keywords.py` | `extract_keywords` | 原问题如何被扩展为三类召回关键词 | 04 |
| 11 | `app/agent/nodes/recall_column.py` | `recall_column` | 字段向量召回及按字段 ID 去重 | 04 |
| 12 | `app/agent/nodes/recall_metric.py` | `recall_metric` | 指标向量召回如何产生候选指标 | 04 |
| 13 | `app/agent/nodes/recall_value.py` | `recall_value` | Elasticsearch 如何召回游戏名、渠道等字段值 | 04 |
| 14 | `app/agent/nodes/merge_retrieved_info.py` | `merge_retrieved_info` | 三路候选如何补齐依赖并组织成表、字段和指标上下文 | 04 |
| 15 | `app/agent/nodes/filter_table.py` | `filter_table` | LLM 如何从候选 Schema 中选择表与字段 | 05 |
| 16 | `app/agent/nodes/filter_metric.py` | `filter_metric` | LLM 如何从候选指标中选择业务口径 | 05 |
| 17 | `app/agent/nodes/add_extra_context.py` | `add_extra_context` | SQL 生成前如何补充日期和数据库信息 | 05 |
| 18 | `app/agent/nodes/generate_sql.py` | `generate_sql` | 上下文如何进入提示词并生成候选 SQL | 05 |
| 19 | `app/agent/nodes/validate_sql.py` | `validate_sql` | 当前在线校验实际只调用哪一层能力 | 06、07 |
| 20 | `app/agent/nodes/correct_sql.py` | `correct_sql` | 数据库错误如何与原上下文一起交给 LLM 修正 | 06 |
| 21 | `app/agent/nodes/run_sql.py` | `run_sql` | 通过校验后的 SQL 如何执行并输出结果事件 | 06 |
| 22 | `app/repositories/mysql/dw/dw_mysql_repository.py` | `DWMySQLRepository.validate`、`run` | `EXPLAIN` 与真实执行的区别 | 06、07 |
| 23 | `app/agent/llm.py` | `llm` | 所有提示词链最终使用的模型实例如何配置 | 05、06 |
| 24 | `app/prompt/prompt_loader.py` | `load_prompt` | 节点怎样加载独立提示词文件 | 05 |

### 第二轮：必须理解的安全、检索与工程组件

| 顺序 | 源码路径 | 重点符号 | 你要理解什么 | 当前接入状态 |
| ---: | --- | --- | --- | --- |
| 25 | `app/security/sql_guard.py` | `SQLGuard.validate`、`GuardedSQL`、`SQLGuardError` | AST 解析、只读限制、表/字段白名单和自动 LIMIT | 独立组件，未接入在线图 |
| 26 | `app/agent/correction_policy.py` | `BoundedSQLCorrector.run`、`CorrectionExhausted` | 有限修正与每次重新校验的通用实现 | 独立组件，在线图使用另一套分支逻辑 |
| 27 | `app/retrieval/fusion.py` | `ReciprocalRankFusion.fuse` | RRF 如何只使用排名融合不同检索通道 | 独立组件，未接入在线三路召回 |
| 28 | `app/semantic/metric_catalog.py` | `MetricCatalog`、`MetricDefinition` | YAML 指标定义如何变成可查询的语义目录 | 独立组件，主链未直接引用该类 |
| 29 | `app/observability/trace_store.py` | `SQLiteTraceStore` | 轨迹事件如何按顺序持久化和回放 | 独立组件，未接入在线 SSE 链路 |
| 30 | `app/services/meta_knowledge_service.py` | `MetaKnowledgeService` 及 `_save_*` 方法 | 表、字段、指标和字段值如何预先写入各检索存储 | 离线知识构建链路 |
| 31 | `app/scripts/build_meta_knowledge.py` | 脚本入口 | 元数据知识构建如何被命令行触发 | 离线知识构建链路 |
| 32 | `app/repositories/qdrant/column_qdrant_repository.py` | `ColumnQdrantRepository.search` | 字段向量查询的仓储边界 | 在线字段召回已接入 |
| 33 | `app/repositories/qdrant/metric_qdrant_repository.py` | `MetricQdrantRepository.search` | 指标向量查询的仓储边界 | 在线指标召回已接入 |
| 34 | `app/repositories/es/value_es_repository.py` | `ValueESRepository.search` | 字段值全文检索的仓储边界 | 在线字段值召回已接入 |
| 35 | `app/repositories/mysql/meta/meta_mysql_repository.py` | `get_column_info_by_id`、`get_table_info_by_id`、`get_key_columns_by_table_id` | 合并候选时如何补齐元数据 | 在线合并节点已接入 |

### 第三轮：配置和提示词，必须结合调用方阅读

| 顺序 | 路径 | 与哪个调用方一起看 | 你要理解什么 |
| ---: | --- | --- | --- |
| 36 | `conf/meta_config.yaml` | `MetaKnowledgeService`、`SQLGuard.from_meta_config` | 表、字段、角色、别名以及指标依赖字段的静态定义 |
| 37 | `conf/metrics.yaml` | `MetricCatalog` | DAU、Revenue、PayerCount、ARPU、LevelPassRate 的公式与粒度 |
| 38 | `conf/app_config.yaml` | 各 client manager | MySQL、Qdrant、Elasticsearch、Embedding 的配置入口 |
| 39 | `prompts/extend_keywords_for_column_recall.prompt` | `recall_column` | 字段召回关键词如何扩展 |
| 40 | `prompts/extend_keywords_for_metric_recall.prompt` | `recall_metric` | 指标召回关键词如何扩展 |
| 41 | `prompts/extend_keywords_for_value_recall.prompt` | `recall_value` | 字段值召回关键词如何扩展 |
| 42 | `prompts/filter_table_info.prompt` | `filter_table` | 候选表和字段的过滤输出契约 |
| 43 | `prompts/filter_metric_info.prompt` | `filter_metric` | 候选指标的过滤输出契约 |
| 44 | `prompts/generate_sql.prompt` | `generate_sql` | SQL 生成获得的完整上下文和输出约束 |
| 45 | `prompts/correct_sql.prompt` | `correct_sql` | SQL 修正获得的错误信息和最小修改要求 |

### 第四轮：测试与评测证据，用来确认你是否理解正确

| 顺序 | 路径 | 验证对象 | 阅读目标 |
| ---: | --- | --- | --- |
| 46 | `tests/test_api_contracts.py` | API、超时和 SSE | 区分流式响应中的成功事件与错误事件 |
| 47 | `tests/test_game_domain_contract.py` | 数仓 Schema 与指标配置 | 确认指标引用的表和字段真实存在 |
| 48 | `tests/test_retrieval_fusion.py` | `ReciprocalRankFusion` | 看懂多通道、权重和稳定排序的预期结果 |
| 49 | `tests/test_metric_catalog.py` | `MetricCatalog` | 看懂指标别名查找和定义加载 |
| 50 | `tests/test_sql_guard.py` | `SQLGuard` | 看懂允许、拒绝与自动补 LIMIT 的边界 |
| 51 | `tests/test_correction_policy.py` | `BoundedSQLCorrector` | 看懂修正成功和达到上限两条路径 |
| 52 | `tests/test_trace_store.py` | `SQLiteTraceStore` | 看懂轨迹事件的保存顺序和回放结果 |
| 53 | `tests/test_sql_benchmark_contract.py` | 评测数据结构 | 确认 12 条合法、4 条可修正、4 条越权样例 |
| 54 | `eval/sql_benchmark.json` | 固定 SQL 样例 | 逐条确认 valid、repairable、unsafe 的构造方式 |
| 55 | `eval/run_sql_eval.py` | 评测计算过程 | 找出 75%、100% 和 P95 的真实计算公式 |
| 56 | `eval/latest_metrics.json` | 最近一次组件结果 | 学会只按真实口径解释数字 |

### 第五轮：主链掌握后再读的前端文件

| 顺序 | 路径 | 重点符号 | 阅读目标 |
| ---: | --- | --- | --- |
| 57 | `frontend/src/lib/agentApi.ts` | 查询请求与 SSE 解析函数 | 浏览器如何消费后端事件流 |
| 58 | `frontend/src/types/agent.ts` | Agent 事件类型 | 前后端事件结构如何对齐 |
| 59 | `frontend/src/App.tsx` | 页面状态和请求入口 | 用户操作怎样触发查询并更新页面 |
| 60 | `frontend/src/components/StepRail.tsx` | `StepRail` | 工作流步骤如何可视化 |
| 61 | `frontend/src/components/ResultTable.tsx` | `ResultTable` | SQL 查询结果如何显示 |

### 第一阶段明确不用读

- `app/models/**`：ORM 字段声明，在学习 Repository 时按需回看。
- `app/entities/**`：领域数据类，在节点看到具体类型时按需回看。
- `frontend/src/components/ui/**`：通用 UI 组件，与 Agent 主链无关。
- `docker/**`：等主链读懂后再学习部署和基础设施。
- `uv.lock`、`frontend/pnpm-lock.yaml`：依赖锁文件，不作为源码阅读材料。
- `docs/ROADMAP.md`：记录迭代路线，不能替代对当前实现的检查。

---

## 第 01 课：一条 HTTP 查询如何变成 SSE 响应

**状态：大纲**

**读完能回答：** 用户提交一个自然语言问题后，哪个函数最先接收它，哪个对象启动 Agent，结果为什么能一段段返回？

**主链：** `POST /api/query` → `query_handler` → FastAPI 依赖组装 `QueryService` → `QueryService.query` → `graph.astream` → 节点自定义事件 → SSE 文本 → `StreamingResponse`

### 必读路径

1. `main.py`：`app.include_router` 与 `add_request_id`
   - 输入：HTTP 请求。
   - 下一步：把 `/api/query` 分发给查询路由。
   - 输出：挂载路由且带请求 ID 的 FastAPI 应用。
2. `app/api/routers/query_router.py`：`query_handler`
   - 输入：`QuerySchema` 与注入的 `QueryService`。
   - 下一步：调用 `query_service.query(query.query)`。
   - 输出：`text/event-stream` 响应。
3. `app/api/dependencies.py`：`get_query_service`
   - 输入：数据库会话和各检索客户端依赖。
   - 下一步：组装仓储及服务对象。
   - 输出：一次请求使用的 `QueryService`。
4. `app/services/query_service.py`：`QueryService.query`
   - 输入：自然语言字符串。
   - 下一步：创建 State 与 Context，消费 `graph.astream`。
   - 输出：逐条 `yield` 的 SSE 消息；超时或异常也包装为 SSE。

**选读证据：** `tests/test_api_contracts.py`，验证 API 与 SSE 契约。

**暂缓阅读：** 图内部的 12 个节点由第 02-06 课负责；客户端初始化与关闭由第 03 课负责。

---

## 第 02 课：LangGraph 如何保存状态并决定下一步

**状态：大纲**

**读完能回答：** State、Runtime Context、节点和边分别解决什么问题？三路并行和纠错循环在代码里如何表达？

**主链：** 初始 `DataAgentState(query=...)` → 图节点读取并返回局部状态 → 三路召回汇合 → SQL 生成 → 校验条件路由 → 执行、纠错或结束

### 必读路径

1. `app/agent/state.py`：`DataAgentState` 及其嵌套 TypedDict
   - 输入：查询及节点逐步产生的数据。
   - 下一步：作为节点间可序列化的数据契约。
   - 输出：SQL、错误、召回候选、修正次数等共享状态。
2. `app/agent/context.py`：`DataAgentContext`
   - 输入：仓储与外部客户端对象。
   - 下一步：由节点通过 `runtime.context` 获取。
   - 输出：不进入 State 的运行时依赖。
3. `app/agent/graph.py`：节点注册与边定义
   - 输入：各节点函数。
   - 下一步：构造并编译 `StateGraph`。
   - 输出：12 节点查询图。
4. `app/agent/graph.py`：`route_after_validation`
   - 输入：`error` 与 `correction_attempts`。
   - 下一步：选择 `run_sql`、`correct_sql` 或 `END`。
   - 输出：有限纠错分支。

**选读证据：** `tests/test_correction_policy.py`，观察“成功停止”和“达到上限”两个独立组件测试。

**暂缓阅读：** 每个召回节点内部行为由第 04 课负责；SQL 校验究竟检查什么由第 06-07 课负责。

---

## 第 03 课：外部服务如何初始化并注入节点

**状态：大纲**

**读完能回答：** 为什么 MySQL、Qdrant、Elasticsearch 和 Embedding 客户端不直接放进 LangGraph State？它们何时创建、何时释放？

**主链：** FastAPI 启动 → `lifespan` 初始化 manager → 依赖函数取得客户端或会话 → 构造 Repository → 注入 `QueryService` → 构造 `DataAgentContext` → 节点运行时读取

### 必读路径

1. `app/api/lifespan.py`：`lifespan`
   - 输入：应用启动与关闭事件。
   - 下一步：初始化或关闭共享客户端。
   - 输出：应用级资源生命周期。
2. `app/api/dependencies.py`：`get_meta_session`、`get_dw_session`、`get_query_service`
   - 输入：已初始化的 manager。
   - 下一步：构造会话、Repository 和 Service。
   - 输出：请求级依赖对象。
3. `app/services/query_service.py`：`DataAgentContext(...)`
   - 输入：`QueryService` 持有的依赖。
   - 下一步：传入 `graph.astream`。
   - 输出：节点可访问的运行时上下文。

**选读证据：** `app/clients/*_client_manager.py` 与 `app/repositories/**`。

**暂缓阅读：** 每个 Repository 的具体查询语句只在相关业务课中按需展开。

---

## 第 04 课：三路召回如何从问题找到 SQL 上下文

**状态：大纲**

**读完能回答：** 字段、指标和字段值为什么分三路检索？它们如何并行，最后怎样合并成表与指标上下文？

**主链：** `extract_keywords` → 并行 `recall_column` / `recall_metric` / `recall_value` → `merge_retrieved_info` → 补齐指标依赖字段、键字段和命中值 → 形成 `table_infos` 与 `metric_infos`

### 必读路径

1. `app/agent/nodes/extract_keywords.py`：`extract_keywords`
   - 输入：原始问题。
   - 下一步：为不同检索通道生成关键词。
   - 输出：关键词状态。
2. `app/agent/nodes/recall_column.py`：`recall_column`
   - 输入：字段关键词与 Embedding/字段仓储。
   - 下一步：Qdrant 字段召回并按字段 ID 去重。
   - 输出：`retrieved_column_infos`。
3. `app/agent/nodes/recall_metric.py`：`recall_metric`
   - 输入：指标关键词。
   - 下一步：Qdrant 指标召回。
   - 输出：`retrieved_metric_infos`。
4. `app/agent/nodes/recall_value.py`：`recall_value`
   - 输入：字段值关键词。
   - 下一步：Elasticsearch 精确值召回。
   - 输出：`retrieved_value_infos`。
5. `app/agent/nodes/merge_retrieved_info.py`：`merge_retrieved_info`
   - 输入：三路候选及元数据仓储。
   - 下一步：按字段和表归并，补齐依赖。
   - 输出：生成 SQL 所需的表与指标上下文。

**选读证据：** `app/services/meta_knowledge_service.py`，理解元数据如何预先写入 MySQL、Qdrant 和 Elasticsearch。

**实现边界：** `app/retrieval/fusion.py` 的 `ReciprocalRankFusion` 有独立测试，但当前三路 Agent 节点没有调用它；因此在线主链不能直接宣称已经使用该加权 RRF 实现。

**暂缓阅读：** 过滤提示词和 SQL 生成由第 05 课负责；RRF 组件的算法细节放入第 07 课的“独立组件与接线差异”。

---

## 第 05 课：召回候选如何变成 SQL

**状态：大纲**

**读完能回答：** 系统如何缩小候选表和指标，怎样补充数据库信息，最终给 LLM 哪些上下文？

**主链：** 合并候选 → 并行 `filter_table` / `filter_metric` → `add_extra_context` → `generate_sql` → SQL 字符串写回 State

### 必读路径

1. `app/agent/nodes/filter_table.py`：`filter_table`
   - 输入：问题与候选表结构。
   - 下一步：提示模型选择表与字段。
   - 输出：过滤后的 `table_infos`。
2. `app/agent/nodes/filter_metric.py`：`filter_metric`
   - 输入：问题与候选指标。
   - 下一步：提示模型选择指标。
   - 输出：过滤后的 `metric_infos`。
3. `app/agent/nodes/add_extra_context.py`：`add_extra_context`
   - 输入：过滤结果及数仓 Repository。
   - 下一步：补充日期与数据库方言等信息。
   - 输出：`date_info` 与 `db_info`。
4. `app/agent/nodes/generate_sql.py`：`generate_sql`
   - 输入：问题、表、指标、日期和数据库上下文。
   - 下一步：调用 LLM 与字符串解析器。
   - 输出：候选 SQL。
5. `prompts/*.prompt`
   - 输入：各节点模板变量。
   - 下一步：约束模型任务和输出格式。
   - 输出：实际发送给模型的提示词结构。

**选读证据：** `conf/metrics.yaml`、`app/semantic/metric_catalog.py` 和 `tests/test_metric_catalog.py`，区分“指标配置组件”与“在线提示词实际使用的数据”。

**暂缓阅读：** SQL 是否允许执行由第 06-07 课负责。

---

## 第 06 课：当前在线链路如何校验、纠错和执行 SQL

**状态：大纲**

**读完能回答：** 候选 SQL 失败后如何进入最多两次的修正循环？当前 `validate_sql` 真正验证了什么？

**主链：** `generate_sql` → `validate_sql` 调用数仓 `EXPLAIN` → 成功则 `run_sql` → 失败且次数小于 2 则 `correct_sql` → 回到 `validate_sql` → 达到上限则结束

### 必读路径

1. `app/agent/nodes/validate_sql.py`：`validate_sql`
   - 输入：候选 SQL 与 DW Repository。
   - 下一步：调用 `dw_mysql_repository.validate(sql)`。
   - 输出：`error=None` 或数据库错误字符串。
2. `app/repositories/mysql/dw/dw_mysql_repository.py`：`validate`、`run`
   - 输入：SQL 文本。
   - 下一步：分别执行 `EXPLAIN` 或真实查询。
   - 输出：可规划性结论或查询结果。
3. `app/agent/nodes/correct_sql.py`：`correct_sql`
   - 输入：原问题、错误 SQL、数据库错误和完整上下文。
   - 下一步：调用 LLM 生成修正版 SQL。
   - 输出：新 SQL 与递增的 `correction_attempts`。
4. `app/agent/graph.py`：`route_after_validation`
   - 输入：校验结果和修正次数。
   - 下一步：控制循环上限。
   - 输出：执行、纠错或停止。
5. `app/agent/nodes/run_sql.py`：`run_sql`
   - 输入：通过当前校验的 SQL。
   - 下一步：调用 Repository 执行。
   - 输出：结果事件。

**选读证据：** `tests/test_correction_policy.py`；注意它测试的是独立 `BoundedSQLCorrector`，不是完整 LangGraph + LLM 链路。

**暂缓阅读：** AST 安全策略和为什么 `EXPLAIN` 不等于权限检查，由第 07 课负责。

---

## 第 07 课：SQL 安全护栏实现了什么，主链还缺什么

**状态：大纲**

**读完能回答：** SQLGlot AST 检查和 MySQL `EXPLAIN` 有何区别？为什么当前项目还不能声称在线链路已完整执行 AST 护栏？

**主链：** SQL 文本 → SQLGlot 解析 → 单语句/只读检查 → 表白名单 → 字段白名单 → 补 `LIMIT 500` → 应再进入 MySQL `EXPLAIN` → 才允许执行

### 必读路径

1. `app/security/sql_guard.py`：`SQLGuard.validate`
   - 输入：SQL 文本与允许的 Schema。
   - 下一步：解析 AST 并执行静态策略。
   - 输出：`GuardedSQL` 或 `SQLGuardError`。
2. `conf/meta_config.yaml`
   - 输入：允许的表与字段定义。
   - 下一步：`SQLGuard.from_meta_config` 构造白名单。
   - 输出：静态 Schema 策略。
3. `tests/test_sql_guard.py`
   - 输入：合法、写操作、系统表、未知字段和多语句样例。
   - 下一步：直接调用独立 Guard。
   - 输出：允许、补 LIMIT 或拒绝。
4. `app/agent/nodes/validate_sql.py`
   - 输入：在线候选 SQL。
   - 下一步：只调用 DW Repository 的 `EXPLAIN`。
   - 输出：数据库可解析/可规划结论。

**选读证据：** `eval/run_sql_eval.py`，观察 Guard 如何在离线组件基准中被调用。

**实现边界：** 当前 `SQLGuard` 未被 `QueryService`、`graph.py` 或 `validate_sql` 引用。合理的目标顺序应是 `SQLGuard -> EXPLAIN -> run_sql`，且 LLM 每次修正后都必须重新经过两层校验；这是待实现项，不是当前已接入事实。

**暂缓阅读：** 具体改造方案可在学完现状后作为实战任务，不在大纲阶段直接修改源码。

---

## 第 08 课：20 条评测到底证明了什么

**状态：大纲**

**读完能回答：** 75% 和 100% 的分母是什么？为什么这不是 LLM Text-to-SQL 准确率？

**主链：** 读取 12 条 valid + 4 条 repairable + 4 条 unsafe → Guard 检查 → 对 repairable 直接使用预设 `corrected_sql` → SQLite 执行并比对预期结果 → 写入 `latest_metrics.json`

### 必读路径

1. `eval/sql_benchmark.json`
   - 输入：人工构造的 SQL、预设修正版和预期结果。
   - 下一步：交给评测脚本分类处理。
   - 输出：20 条固定组件样例。
2. `eval/run_sql_eval.py`：`database`、`evaluate`
   - 输入：固定数据集与内存 SQLite。
   - 下一步：执行 Guard、预设修正版与结果比对。
   - 输出：组件指标及本机延迟。
3. `eval/latest_metrics.json`
   - 输入：最近一次脚本运行结果。
   - 下一步：供 README 展示。
   - 输出：20 条样例上的固定指标。
4. `tests/test_sql_benchmark_contract.py`
   - 输入：评测 JSON。
   - 下一步：检查三类样例数量。
   - 输出：12/4/4 的数据集结构约束。

**选读证据：** `docs/INTERVIEW.md` 与 README 的“数据与评测边界”。

**实现边界：** `first_pass_success = 12/16 = 75%`；`success_after_correction = 16/16 = 100%` 使用人工预设修正版，不调用生成节点或 LLM 纠错节点。可用于回归 Guard、执行和结果比对，不可用于证明 Agent 端到端生成或纠错准确率。

**暂缓阅读：** 如何设计自然语言到 SQL 的端到端评测，可作为后续扩展课程。

---

## 第 09 课：可观测组件与文档声明如何核对

**状态：大纲**

**读完能回答：** SSE 进度、SQLite 轨迹存储和前端步骤展示分别处于什么接入状态？如何避免把“有这个类”说成“主链已落地”？

**主链：** 节点调用 `runtime.stream_writer` → `graph.astream(stream_mode="custom")` → `QueryService` 包装 SSE → 前端消费；独立 `SQLiteTraceStore` 当前只在组件测试中出现，尚未从 SSE 或图节点写入

### 必读路径

1. `app/agent/nodes/*.py`：`runtime.stream_writer`
   - 输入：节点开始、成功、错误和结果事件。
   - 下一步：交给 LangGraph 自定义流。
   - 输出：实时事件。
2. `app/services/query_service.py`：`graph.astream`
   - 输入：图事件。
   - 下一步：JSON 序列化并包装 SSE。
   - 输出：前端可消费的流。
3. `app/observability/trace_store.py`：`SQLiteTraceStore`
   - 输入：trace 元数据与事件。
   - 下一步：写入、读取和回放 SQLite。
   - 输出：可持久化轨迹组件。
4. `tests/test_trace_store.py`
   - 输入：模拟事件。
   - 下一步：验证顺序保存与回放。
   - 输出：组件级证据。

**选读证据：** `frontend/src/lib/agentApi.ts`、`frontend/src/types/agent.ts`、`frontend/src/components/StepRail.tsx`。

**实现边界：** 在线 SSE 已接入；SQLite Trace Store 目前未发现主链调用。两者不能合并描述为“在线执行轨迹已经持久化并可回放”。

**暂缓阅读：** React 组件细节和真正接入 trace ID 的工程改造属于后续实战。

---

## 建议学习顺序与节奏

按 `01 → 02 → 06 → 07 → 08 → 03 → 04 → 05 → 09` 学习。前五课先建立面试最急需的主链、安全边界和指标口径；其余课程再补依赖注入、检索和观测。

每课采用同一节奏：

1. 先用自己的话预测调用链。
2. 跟着必读路径逐个定位函数。
3. 只展开本课必要代码。
4. 回答 2-4 道理解题。
5. 用一分钟口述完整流程；说不清就回到具体输入和输出。

## 尚未覆盖与待确认

- 上游仓库与当前 fork 的逐文件 diff，以及每项改动是否由本人设计、AI 生成或人工修订。
- 真实 Qdrant、Elasticsearch、MySQL 与外部模型联合运行的端到端结果。
- LLM 生成 SQL、LLM 自动纠错、Schema Linking 的独立准确率。
- 并发、连接池、鉴权、租户隔离、成本与真实数据规模表现。
- 前端完整交互和 Docker 部署故障排查。
