# GameQuery 面试深挖与责任边界

## 30 秒项目介绍

GameQuery 是面向游戏运营分析的 Text-to-SQL Agent。我在保留上游 FastAPI、LangGraph 和数据访问主体框架的基础上，按 SDD 重构了可靠性链路：把 SQLGlot Guard、MySQL EXPLAIN、有限纠错和只读执行串成不可绕过的执行边界；把字段/指标检索升级为 Qdrant dense+BM25 多通道 RRF；接入异步 TraceStore 与结构化 SSE；最后用确定性 E2E、真实 MySQL/Qdrant CI 集成和诚实的离线评测固定证据。项目使用模拟数仓，目标是证明工程机制，不冒充企业生产效果。

## 个人贡献怎么讲

可以说：这是 fork 后的适应性改造，不是从零原创。我的个人动作包括读源码和调用链、写规格与验收标准、设计测试、借助 AI 实现并逐提交验证、修复线上链路中“组件存在但未接线”的问题、建立 CI 证据。应主动区分三部分：上游保留的框架、自己改造的代码、AI 辅助生成后由自己审查和测试的内容。

不要说：独立原创全部架构、在真实企业数据上验证、生产环境已经稳定支撑千万级、线上准确率 100%。可以说“在本机隔离 MySQL 上完成千万事实行固定工作负载实测”，并主动给出环境和边界。

## 为什么分三条召回链路

三条链路不是“同一个问题搜三遍”，而是解决三种 Schema Linking 子问题：

- 字段：把“在线时长”映射到 `fact_player_daily.online_minutes`。
- 指标：把“DAU”绑定到去重玩家数、日期粒度和依赖表。
- 字段值：把“星海远征”识别为 `dim_game.game_name` 的取值。

字段与指标在各自 Qdrant collection 内做 dense、BM25、exact/alias、LLM-expand 等同类通道召回，再用加权 RRF 融合排名并保存贡献证据。字段值继续使用 Elasticsearch。实体类型先隔离，避免把“字段相似度、指标相似度、值匹配分数”直接相加。

## Qdrant 检索和 Embedding 检索的区别

Embedding 是把文本变成向量的表示方法；Qdrant 是保存向量/稀疏表示、建立索引并执行 Top-K 查询的数据库。项目中 Embedding 客户端负责生成 dense vector，Qdrant 同时承载 dense 与服务端 BM25 sparse 查询。两者不是竞争关系，而是“表示模型 + 检索引擎”。

## 为什么用 RRF 而不直接加原始分数

dense 相似度、BM25、精确别名和扩词候选的分数分布不同，未经标定直接相加会让数值范围较大的通道支配结果。RRF 只依赖各通道名次，以 `weight / (k + rank)` 计算贡献，稳定且可复算。本项目仍允许配置通道权重，但权重作用在排名贡献上；每个结果保留 channel、rank、contribution，便于解释。

## 用户问“某日星际争霸的 DAU”时怎么处理

1. 抽取时间、游戏实体和 DAU 指标词。
2. 字段链路找日期、game_id 等列；指标链路绑定 DAU 口径；值链路验证游戏名是否存在。
3. 合并候选，补齐指标依赖表和 Join 键，再过滤无关上下文。
4. 如果日期缺失、游戏无匹配或指标冲突，返回 clarification，不猜值。
5. 信息完整时生成按日期和游戏过滤、对 player_id 去重的 SQL。
6. SQL 依次经过 AST、白名单、LIMIT、超时提示和 EXPLAIN；通过后才用只读账号执行。
7. SSE 返回进度、SQL、结果或稳定错误码，TraceStore 保存不含结果明细的决策轨迹。

如果用户提供了有效日期和存在的游戏，正常终态是：返回规范化 SQL、查询列和数据行；若该组合没有事实数据，返回成功但空结果，而不是编造 DAU。真实回答值取决于数仓数据，不能凭面试现场猜数字。

## 问题超出三条链路能力怎么办

先判断是否仍属于当前结构化数仓范围。缺槽位就澄清；Schema/指标不存在就明确无法回答；只有当问题需要非结构化知识、多步工具或跨系统证据，并且固定工作流的失败率和收益数据支持升级时，才考虑 Agentic RAG。判断信号应来自路由分类、低置信/无召回、任务复杂度、历史失败类型和成本预算，而不是让模型无条件自主调用工具。

本轮明确不做自动 Agentic RAG。原因是优先把高频 Text-to-SQL 路径做成确定、可审计、可评测的 DAG；过早开放动态规划会增加成本、延迟和安全面。

## SQL 安全与纠错怎么实现

安全链是 `生成 SQL → SQLGlot AST Guard → MySQL EXPLAIN → 只读执行`。Guard 拒绝多语句、写操作、系统对象、未知表列和无法证明安全的动态 LIMIT；缺少 LIMIT 时补 500，过大时收敛。EXPLAIN 验证真实 MySQL 方言与 Schema，执行节点只接受 `GuardedSQL`。

错误分两类：策略违规不可纠错，立即终止；语法、白名单或预检类错误可以进入 LLM 修正，但最多两次，每次新 SQL 都重新跑完整安全链。底层 DW reader 只有 SELECT 权限，所以即使应用 Guard 漏判，数据库仍拒绝写操作。CI 已在真实 MySQL 8.0 上验证 INSERT、UPDATE、DELETE、CREATE、DROP 均被拒绝。

## LangGraph 如何编排

图有 14 个节点。关键词抽取后，字段、指标、字段值三路并行，通过显式列表 barrier 汇入 merge；merge 后表过滤与指标过滤并行，再经第二个 barrier 汇入上下文补充。之后先做信息完整性检查，完整才生成 SQL；校验节点条件路由到执行、纠错或失败节点，纠错后回到校验。

使用显式 barrier 是为了避免依赖隐含调度语义，并用乱序完成测试证明 merge 只运行一次。State 保存可序列化业务数据，连接与 Guard 通过 Runtime Context 注入，便于替换 fake 依赖做确定性测试。

## SSE 是什么，项目里为什么使用

SSE 是服务端通过一个 HTTP 连接持续推送文本事件的协议。Text-to-SQL 一次请求会经历召回、过滤、生成、校验和执行，SSE 能让前端逐步展示状态，而不必轮询。项目事件含 request_id、递增 sequence、event、timestamp 和兼容旧版的 payload `type`，且只能有一个 `done` 或 `error` 终态。

它适合服务端单向推送；如果需要浏览器与服务端双向实时交互，WebSocket 更合适。

## 三层记忆怎么回答

当前项目可严格证明的是三种不同生命周期的数据，而不是成熟的“通用三层记忆系统”：

- 请求内状态：LangGraph State，保存当前问题、召回候选、SQL 和错误。
- 可回放轨迹：SQLite TraceStore，保存事件序列和终态，不保存查询结果明细。
- 长期业务知识：MySQL 元数据、Qdrant 字段/指标索引、Elasticsearch 字段值索引。

项目没有实现跨会话用户画像、情景记忆总结或长期偏好学习。面试官若把“三层记忆”定义为短期/情景/语义记忆，应先说明这里是工程数据分层，不要偷换概念。

## 指标真实性怎么解释

SQL fixture 共 20 条：12 条合法、4 条人工植入错误且带预设修复、4 条攻击/越权。Guard accuracy 1.0、首轮 fixture rate 0.75、预设修复执行率 1.0。真实 Agent 纠错没有运行，因此报告明确是 `null / not_run`。

检索 fixture 共 32 条，融合 Hit@5/MRR 为 1.0，no-match false-positive rate 为 0.2。这些数字验证评测器与固定候选融合，不是实时调用 Embedding/Qdrant 的线上召回率。真实模型生成准确率、业务正确率和线上延迟目前都没有证据。

## 项目能处理多大数据库、查询速度如何

仍然不能给出“容量上限”。现在能引用的是一次可复现的本机实证：Windows 11、16.84 GB 内存、MySQL 8.0.26、1000 万事实行和 25 万玩家维度，六类固定 SQL 在预热后各跑 30 次。单并发 P95 分别为 DAU 11.30 ms、收入 293.79 ms、付费人数 3.61 ms、ARPU 19.41 ms、通过率 21.71 ms、渠道拆分 50.68 ms；并发 20 对应 40.86/624.50/6.76/48.44/33.92/120.11 ms，全部结果匹配且 0 超时。

回答时紧接一句边界：这是合成数据、固定 SQL 和隔离数据库的局部性能，不含 LLM、Qdrant、ES、SSE 和网络，所以不能冒充端到端 Agent 延迟或生产承诺。AST Guard P95 1.724 ms 仍只是另一个 fixture 局部指标。若问更大规模，先明确 SLA 与查询模型，再做分区/预聚合、混合负载、资源隔离和目标硬件复测。

## “这不就是 Demo 吗”怎么回应

数据确实是模拟的，业务价值尚未通过真实流量验证，所以不能称为生产系统。但它不只是页面演示：关键价值是把 Agent 风险变成可测试的工程合同——SQL 不可绕过的安全边界、最小权限、确定性工作流、可解释检索、唯一终态、并发追踪、真实服务集成和 CI 门禁。虽然已做本机千万事实行固定 SQL 压测，离生产仍缺真实业务集、鉴权/多租户、目标环境混合负载压测、监控告警和线上灰度。

## 一个真实失败案例

升级前仓库已经有 SQLGuard、RRF、TraceStore 和 SSE encoder，但源码追踪发现它们主要停留在独立组件测试，在线 `QueryService → graph` 没有真正消费。README 的能力描述领先于实现。修复方法不是再写新组件，而是先建立合同测试，再把 Guard 接到 validate/run 边界、把 RRF evidence 接到召回节点、把异步 TraceStore 和统一 SSE 接到服务生命周期，最后用 API/E2E/真实服务 CI 防回退。

另一个失败是原评测把人工预设修复的 100% 写得像 Agent 自动纠错效果。现在拆分指标并把真实 Agent 纠错标记为未运行。这体现的是“宁可少一个漂亮数字，也不把不可证明的结果写进简历”。

## 证据入口

- `specs/reliable-agent-upgrade/validation.md`：验收矩阵与未验证项。
- `specs/reliable-agent-upgrade/walkthrough.md`：升级后完整调用链。
- `tests/test_agent_workflow_e2e.py`：六类确定性路径。
- `tests/integration/test_services.py`：真实 MySQL/Qdrant 证据。
- `eval/latest_metrics.json`、`eval/latest_retrieval_metrics.json`：带 mode 的最新 fixture 报告。
