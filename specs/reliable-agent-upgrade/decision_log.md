# Decision Log: GameQuery 可靠性补全

Last updated: 2026-09-23

## D-01 SQL 安全采用 SQLGlot AST + MySQL 预检

- **Decision:** 继续使用已锁定的 SQLGlot 解析 MySQL AST，负责语句类型、对象白名单、通配列、LIMIT 和超时提示改写；数据库可执行性继续由 MySQL `EXPLAIN` 判定。
- **Why:** SQLGlot 官方明确说明解析器是宽松的 transpiler，不是数据库 validator；MySQL 官方文档说明 `EXPLAIN` 用于检查执行计划，两者职责互补。
- **Sources:** [SQLGlot GitHub](https://github.com/tobymao/sqlglot)，[MySQL EXPLAIN](https://dev.mysql.com/doc/refman/8.0/en/using-explain.html)。
- **Rejected:** 只依赖 SQLGlot；只依赖 `EXPLAIN`；引入完整 Text-to-SQL 框架替换现有图。
- **Exit:** 若未来切换数据库方言，先添加对应方言黄金测试，再替换策略适配器。

## D-02 查询超时使用数据库提示 + asyncio 截止时间

- **Decision:** 安全策略为每条只读查询注入受控的 `MAX_EXECUTION_TIME`，Repository 调用同时受 asyncio 截止时间约束。
- **Why:** MySQL 8.0 官方支持仅作用于单条只读 SELECT 的 `MAX_EXECUTION_TIME(N)`，应用层截止时间覆盖连接、驱动和取消路径。
- **Source:** [MySQL Optimizer Hints](https://dev.mysql.com/doc/refman/8.0/en/optimizer-hints.html#optimizer-hints-execution-time)。
- **Rejected:** 只依赖 60 秒请求总超时；修改全局数据库变量。

## D-03 同类混合检索采用 Qdrant 通道查询 + 现有 RRF

- **Decision:** 字段与指标分别使用版本化 Qdrant collection，每个实体一个 point，同时保存 dense 与 BM25 sparse 表示；在线分别取 dense、lexical、exact/alias、LLM-expand 排名，再交给现有 `ReciprocalRankFusion` 输出融合分数和逐通道贡献。
- **Why:** Qdrant 1.10+ Query API 支持混合查询，1.16 支持可配置 RRF；官方建议没有已校准分数时用 RRF。直接使用 Qdrant 最终融合结果无法满足本项目逐通道证据合同，因此保留应用层融合。
- **Sources:** [Qdrant Hybrid Queries](https://qdrant.tech/documentation/search/hybrid-queries/)，[Qdrant Hybrid Search](https://qdrant.tech/documentation/search/text-search/hybrid-search/)。
- **Rejected:** 把字段、指标、业务值混成一个排名；对 dense cosine 与 BM25 原始分数直接加权；继续使用随机多 point 后只按 id 去重。
- **Exit:** 若黄金集证明原生 Qdrant RRF质量更好且 API 可返回通道证据，再迁移融合位置。

## D-04 审计追踪采用 aiosqlite，不把 checkpointer 当审计库

- **Decision:** 用 `aiosqlite` 重写追踪存储为异步生命周期组件，SQLite WAL + 原子序号保证单实例并发；事件只保存清理后的 payload，不保存完整结果集。
- **Why:** aiosqlite 官方通过每连接单共享线程和请求队列避免阻塞 asyncio 主循环，适合当前轻量单实例部署。
- **Source:** [aiosqlite GitHub](https://github.com/omnilib/aiosqlite)。
- **Rejected:** 请求链路直接调用同步 sqlite3；把 LangGraph checkpoint 表作为审计事件表。
- **Exit:** 多实例部署时迁移到已有 MySQL/PostgreSQL，并保持 TraceStore 合同不变。

## D-05 LangGraph SQLite checkpointer延后到可选续跑任务

- **Decision:** 主线先完成审计追踪；只有 MUST 项全部通过后，才评估 `AsyncSqliteSaver` 完成 AC-C1。
- **Why:** 官方将 SQLite saver定位为本地、测试和轻量部署，并要求严格 msgpack 白名单；当前 State 含自定义实体且执行节点有外部副作用，直接启用会扩大反序列化和重复执行风险。
- **Sources:** [LangGraph SQLite Checkpoint](https://github.com/langchain-ai/langgraph/blob/main/libs/checkpoint-sqlite/README.md)，[LangGraph Persistence](https://github.com/langchain-ai/docs/blob/main/src/oss/langgraph/persistence.mdx)。
- **Rejected:** 为了“有记忆”直接给当前全图加 checkpointer。

## D-06 负载测试采用 Locust，数据生成器保持项目内确定性

- **Decision:** Locust 作为开发依赖描述 HTTP/SSE 用户场景；项目内生成器用固定随机种子创建 10 万/100 万行事实数据并写出实验清单。
- **Why:** Locust 官方支持用 Python 编写场景、无 UI 运行和分布式扩展，避免自研并发统计器。
- **Source:** [Locust GitHub](https://github.com/locustio/locust)。
- **Rejected:** 用单次 `time.perf_counter` 冒充容量测试；CI 默认生成百万行数据。

## D-07 异步测试不新增 pytest 插件

- **Decision:** 单元和工作流测试使用标准库 `unittest.IsolatedAsyncioTestCase` 或 `asyncio.run`，继续由 pytest 发现执行。
- **Why:** 当前只需测试少量 async 合同，不必为测试事件循环再增加依赖。
- **Exit:** 当 async fixture 复用明显复杂化时，再评估 pytest-asyncio。
