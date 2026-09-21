# GameQuery：游戏运营 Text-to-SQL Agent

GameQuery 将游戏运营人员的自然语言问题转换为可校验、可执行的 SQL，并通过 SSE 返回 LangGraph 执行轨迹与查询结果。当前数据域覆盖玩家活跃、在线时长、付费和关卡表现。

> 当前版本：`v0.1.0`，完成游戏数仓 MVP 与 Python 3.12 工程基线。SQL AST 安全策略、有限重试、评测集和轨迹回放会在后续里程碑实现。

## 核心链路

现有 LangGraph 包含 12 个节点：

```text
关键词提取
  -> 字段 / 指标 / 字段值并行召回
  -> 召回合并与表、指标过滤
  -> 上下文补全
  -> SQL 生成
  -> SQL 校验
  -> SQL 修正或执行
```

- Qdrant：字段与指标的向量语义召回。
- Elasticsearch：字段值精确检索。
- MySQL：元数据与游戏运营数仓。
- FastAPI + SSE：流式输出节点状态、SQL 和结果。
- React + Vite：自然语言问数与执行轨迹界面。

## 游戏数据模型

- 维度表：`dim_player`、`dim_game`、`dim_date`
- 事实表：`fact_player_daily`、`fact_payment`、`fact_level_event`
- 语义指标：DAU、Revenue、PayerCount、ARPU、LevelPassRate

示例问题：

- 统计 2026 年 9 月 18 日各游戏的 DAU。
- 查询 2026 年 9 月各游戏的总收入和付费人数。
- 统计 LEVEL_05 与 LEVEL_07 的关卡通过率。

## 本地启动

需要 Python 3.12、uv、Docker 与 Node.js/pnpm。

```bash
uv sync --python 3.12
cp .env.example .env
docker compose -f docker/docker-compose.yml up -d
uv run python main.py
```

前端：

```bash
cd frontend
pnpm install
pnpm dev
```

## 验证

```bash
uv run ruff check app main.py tests
uv run pytest
```

Docker 服务启动后，再执行索引初始化与端到端查询。当前自动测试首先保证元数据配置、建表 SQL 和游戏指标语义一致。

## 版本路线

详见 [docs/ROADMAP.md](docs/ROADMAP.md)。路线按可验证增量拆成十次提交，最终形成带 SQL 护栏、回归评测、轨迹回放和部署文档的面试版本。

## 来源与许可证

本项目基于 [didilili/shopkeeper-agent](https://github.com/didilili/shopkeeper-agent) 的 MIT 许可代码改造，保留原作者版权声明、`LICENSE` 与 Git 历史。领域数据、配置、界面与后续工程能力由本项目继续迭代。
