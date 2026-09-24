# Research: 千万级合成业务数据与容量实证

Status: Approved (standing user authorization)
Date: 2026-09-24

## Problem Summary

当前仓库能够生成固定规模 CSV，并提供 Locust 报告合同，但尚没有千万级 preset、数据库批量导入入口、可从数据生成规则复算的业务标准答案，也没有落盘的千万行生成证据。本研究只描述现状与外部先例，不定义新增行为。

## Relevant Files

| File | Current role | Entry point |
|---|---|---|
| `eval/generate_scale_data.py` | 生成维度表、三张事实表和 manifest | `generate()` — `eval/generate_scale_data.py:27` |
| `eval/load_report.py` | 定义负载查询与报告字段校验 | `validate_report()` — `eval/load_report.py:38` |
| `eval/locustfile.py` | 发送 SSE 查询并落盘负载报告 | `GameQueryUser.stream_query()` — `eval/locustfile.py:24` |
| `tests/test_scale_harness.py` | 验证生成确定性、外键和报告边界 | generator tests — `tests/test_scale_harness.py:21` |
| `docker/mysql/dw.sql` | 创建当前 DW 表和小型演示种子数据 | table DDL — `docker/mysql/dw.sql:12` |
| `docker/mysql/99-grants.sh` | 拆分 meta writer 与 DW reader 权限 | grant script — `docker/mysql/99-grants.sh:1` |
| `.github/workflows/ci.yml` | 在 CI 运行生成器 smoke | scale step — `.github/workflows/ci.yml:61` |

## Information Flow

1. CLI 把 preset 转换为总事实行数，并调用 `generate()` — `eval/generate_scale_data.py:141`。
2. 生成器先完整构造玩家 ID 和游戏 ID 列表，再逐行写出三个维度 CSV — `eval/generate_scale_data.py:32`。
3. 总事实行数按 60% 日活、20% 支付、20% 关卡拆分 — `eval/generate_scale_data.py:67`。
4. 每条事实随机选择玩家、游戏和日期；分布是均匀随机 — `eval/generate_scale_data.py:71`。
5. 每个 CSV 写完后重新扫描文件计算 SHA-256，manifest 记录行数与摘要 — `eval/generate_scale_data.py:12`、`eval/generate_scale_data.py:129`。
6. CI 只生成 1,000 行 smoke 数据，不导入 MySQL — `.github/workflows/ci.yml:61`。
7. Locust 通过 `/api/query` 发送三种自然语言查询，统计 SSE 成功与错误 — `eval/locustfile.py:18`、`eval/load_report.py:3`。

## Key Findings

### F-1: 规模上限目前停在 100 万

CLI 仅声明 `smoke`、`100k` 和 `1m` 三个 preset；测试精确锁定该字典，因此新增规模必须同步修改合同测试。— `eval/generate_scale_data.py:8`、`tests/test_scale_harness.py:21`

### F-2: 当前数据可复现但业务分布过于简单

生成器使用固定 seed，但玩家、游戏、日期以及金额、时长、等级均采用均匀抽样；没有活动峰值、周末效应、新增玩家增长、留存或长尾付费。— `eval/generate_scale_data.py:31`、`eval/generate_scale_data.py:71`

### F-3: 大规模生成会占用不必要内存

玩家上限是 100,000，因此当前 1m/未来 10m 规模的玩家 ID 列表可控；但 CSV 摘要需要二次读取每个完整文件，增加一轮磁盘 I/O。— `eval/generate_scale_data.py:21`、`eval/generate_scale_data.py:32`

### F-4: 没有导入工具

仓库的 DW SQL 只创建表并插入极小演示数据；没有读取 manifest、限制输入目录、执行批量导入或核对导入行数的脚本。— `docker/mysql/dw.sql:1`、`docker/mysql/dw.sql:56`

### F-5: 索引不覆盖核心组合查询

事实表目前只有单列日期、玩家或关卡索引，而 Locust 查询主要按日期/月份和游戏聚合；DDL 没有 `(date_id, game_id)` 组合索引。— `docker/mysql/dw.sql:45`、`docker/mysql/dw.sql:64`、`docker/mysql/dw.sql:79`、`eval/load_report.py:3`

### F-6: 现有报告禁止外推但缺少导入和数据库查询指标

负载报告要求声明行数并禁止超出实测规模，但没有数据生成时间、文件字节数、导入吞吐、数据库查询 p50/p95/p99 或 `EXPLAIN` 摘要。— `eval/load_report.py:9`、`eval/load_report.py:38`

### F-7: CI 已具备真实 MySQL 服务但只装载小种子

CI 启动 MySQL 8.0，执行 `dw.sql` 并验证最小权限，当前没有千万行导入步骤；这使 CI 适合验证导入合同的 smoke，不适合作为正式容量机器。— `.github/workflows/ci.yml:20`、`.github/workflows/ci.yml:43`

## Existing Constraints Discovered

- 生成结果必须由固定 seed 重现，事实总行数必须精确等于请求值。— `tests/test_scale_harness.py:25`
- 三张事实表的玩家、游戏和日期必须引用已生成维度。— `tests/test_scale_harness.py:35`
- 负载报告的最大声明行数必须等于实际测量行数，禁止外推。— `eval/load_report.py:43`
- CI 不调用真实 LLM，并要求测试不修改已跟踪评测文件。— `.github/workflows/ci.yml:55`、`.github/workflows/ci.yml:63`
- DW 在线账号为只读用户，大规模导入不能复用该账号。— `constitution.md:43`、`constitution.md:61`

## Prior Art and External Evidence

- AWS 的游戏分析参考架构包含 Python 示例事件生成器，并以高体量遥测事件作为容量建模单位；许可为 MIT-0。<https://github.com/aws-solutions-library-samples/guidance-for-game-analytics-pipeline-on-aws>
- MySQL 8.0 官方文档提供 `LOAD DATA LOCAL INFILE`，并说明客户端与服务端都必须显式允许本地文件。<https://dev.mysql.com/doc/refman/8.0/en/loading-tables.html>
- MySQL 官方 InnoDB 批量装载指南建议关闭逐行 autocommit、按主键顺序装载，并仅在安全前提下调整约束检查；正式报告必须记录实际配置。<https://dev.mysql.com/doc/refman/8.0/en/optimizing-innodb-bulk-data-loading.html>
- ESTA 论文公开了 8.6m 动作与 7.9m 游戏帧，说明千万级游戏遥测是合理的测试量级；其电竞动作结构与本项目运营星型模型不同，因此不直接导入。<https://arxiv.org/abs/2209.09861>

## Open Questions for the Spec

- 千万级目标是“成功生成并校验”还是必须在固定数据库环境完成正式负载？
- 外部公开数据应直接混入事实表，还是只用于确定事件类型与分布形状？
- 本机 Docker 不可用时，哪些结果可以在 CI 验证，哪些必须明确为未运行？

## Not Investigated

- 未下载或审计第三方原始数据文件；许可证、隐私和 Schema 不明确的数据不进入实现。
- 未运行真实 LLM；本轮业务标准答案可验证 SQL/结果，不代表模型质量。
- 未测目标硬件容量；研究阶段不产生吞吐或延迟数字。
