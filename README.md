# GameQuery：游戏运营 Text-to-SQL Agent

GameQuery 将游戏运营问题转成可追踪、可修正、受安全策略约束的 SQL。系统使用 LangGraph 编排关键词抽取、多路召回、上下文补全、SQL 生成、AST 校验、有限纠错和结果执行，并通过 SSE 返回执行轨迹。

## 已实现能力

- **12 节点 LangGraph DAG**：字段、指标、字段值三路并行召回，合并后并行过滤表与指标，再进入 SQL 闭环。
- **指标语义层**：DAU、Revenue、PayerCount、ARPU、LevelPassRate 显式定义公式、别名、粒度、时间字段和依赖表。
- **多策略召回**：Qdrant 向量检索、Elasticsearch 精确值检索、别名与 LLM 扩展候选，通过带通道证据的加权 RRF 融合。
- **SQL AST 护栏**：SQLGlot 解析后执行只读、单语句、表白名单、字段白名单检查；未指定行数时自动添加 `LIMIT 500`。
- **有限纠错**：`validate → correct → validate`，最多修正两次；记录每个 SQL 版本与错误，避免无限修正或未经复验直接执行。
- **轨迹回放**：SQLite 顺序保存 progress、SQL、result 和 error 事件，可按 trace ID 重放与审计。
- **工程交付**：60 秒查询超时、请求 ID、SSE 契约、Python 3.12、uv、Ruff、pytest、前端构建、Docker Compose 和双端 CI。

## 游戏数据模型

- 维度：`dim_player`、`dim_game`、`dim_date`
- 事实：`fact_player_daily`、`fact_payment`、`fact_level_event`
- 典型问题：日活、在线时长、收入、付费人数、ARPU、关卡通过率

## 可复现评测

```bash
uv sync --frozen --group dev
uv run pytest -q
uv run python eval/run_sql_eval.py
```

`eval/sql_benchmark.json` 包含 12 条正确 SQL、4 条可修正 SQL 和 4 条攻击或越权 SQL。当前固定数据实测：

| 指标 | 结果 |
|---|---:|
| AST 护栏判定准确率 | 100% |
| 候选 SQL 首次通过率 | 75% |
| 有限修正后成功率 | 100% |
| SQL 执行结果准确率 | 100% |
| AST 护栏 P95 | 0.554 ms |

该评测验证 SQL 安全、修正与执行组件，不把固定 SQL 样例描述为 LLM 端到端生成准确率。模型效果需要配置真实 API 后另建独立实验集。

## 启动

复制配置并填写模型密钥：

```bash
cp .env.example .env
uv sync --frozen --group dev
docker compose -f docker/docker-compose.yaml up -d
uv run python -m app.scripts.build_meta_knowledge -c conf/meta_config.yaml
uv run uvicorn main:app --host 0.0.0.0 --port 8000
```

前端：

```bash
cd frontend
pnpm install --frozen-lockfile
pnpm dev
```

## 文档

- [系统架构](docs/ARCHITECTURE.md)
- [十次迭代路线](docs/ROADMAP.md)
- [面试深挖与责任边界](docs/INTERVIEW.md)
- [评测结果](eval/latest_metrics.json)

## 来源与许可证

本项目基于 [didilili/shopkeeper-agent](https://github.com/didilili/shopkeeper-agent) 的 MIT 许可代码改造，通过 GitHub Fork 保留上游关系、版权声明和 Git 历史。
