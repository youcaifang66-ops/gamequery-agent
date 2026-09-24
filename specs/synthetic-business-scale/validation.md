# Validation: 千万级合成业务数据与容量实证

验证日期：2026-09-24。数据完全合成，不含真实玩家或企业数据；所有容量数字只适用于报告所记录的本机、MySQL 版本、Schema、索引和固定 SQL 工作负载。

## 验收结论

- 实际生成并独立全扫描 10,000,000 条事实记录，未做线性外推。
- 实际导入隔离的 MySQL 8.0.26 实验库；三张事实表共 10,000,000 行，三张维表共 250,385 行，六类 SQL 结果与标准答案完全一致。
- 实际运行并发 1/5/10/20，每档 6 类查询、每类 30 个计时样本，共 720 个原始样本；24 个组合全部结果匹配、0 超时、0执行错误，并保留 EXPLAIN。
- 本地 Python 全量回归在文档更新前为 138 passed、3 skipped；新增证据合同测试另有 3 passed。最终门禁结果见本文件末尾审计记录。
- 大型 CSV 和隔离数据库文件未进入 Git；仓库只保存生成、导入和查询的 JSON 证据。

## 实验环境

| 项目 | 实测值 |
|---|---|
| OS | Windows 11 10.0.26200 |
| CPU | AMD64 Family 25 Model 97 Stepping 2 |
| 主机内存 | 16,844,877,824 bytes |
| Python | 3.12.14 |
| MySQL | 8.0.26，本机隔离实例，端口 3307 |
| 数据集 | seed 20260923；manifest SHA-256 `b8cf43c1adf4636cef3a5e111dc92e3bb31b70af73875aff851230f6a112a615` |
| Schema | 250,000 玩家、20 游戏、365 日期；600 万日活、200 万支付、200 万关卡事件 |
| 索引 | daily(date,game,player)、payment(date,game,player)、level(date,game,level)、player(channel,player) |

## 生成与导入结果

| 阶段 | 结果 |
|---|---:|
| 10m 流式生成 | 28.313 s；353,189 facts/s；输出 473,341,644 bytes |
| 生成峰值 RSS | 52,670,464 bytes（50.23 MiB，低于 1 GiB 门槛） |
| 独立全扫描 | checksum、row count、全部 FK、distribution、六类 ground truth 全通过 |
| MySQL 数据与索引 | 156.001 s；65,707 rows/s；ground truth 全通过 |
| 其中事实写入 | daily 65.703 s；payment 20.759 s；level 24.017 s |
| 组合索引创建 | 41.842 s |

业务分布实测：G001 占全部事实 39.19%；周末活动量为普通工作日 1.299 倍；活动日为普通工作日 2.987 倍；支付均值 16.29 元、中位数 3 元；关卡成功 1,361,579 条、失败 638,421 条。

## 固定 SQL 延迟

每个单元格为 p50 / p95 / p99（ms）；每格 30 个成功样本。

| 查询 | C=1 | C=5 | C=10 | C=20 |
|---|---:|---:|---:|---:|
| DAU | 10.72 / 11.30 / 11.78 | 10.76 / 12.27 / 12.96 | 12.52 / 14.00 / 15.08 | 13.47 / 40.86 / 41.61 |
| 月收入 | 274.79 / 293.79 / 298.89 | 335.37 / 344.02 / 344.07 | 503.16 / 521.15 / 521.32 | 604.90 / 624.50 / 644.91 |
| 付费人数 | 3.05 / 3.61 / 3.75 | 3.51 / 4.33 / 4.37 | 3.72 / 4.32 / 4.36 | 4.59 / 6.76 / 6.79 |
| ARPU | 17.73 / 19.41 / 19.68 | 20.58 / 21.55 / 22.15 | 25.63 / 32.20 / 33.03 | 34.32 / 48.44 / 51.72 |
| 关卡通过率 | 17.86 / 21.71 / 84.16 | 17.35 / 18.07 / 18.43 | 18.95 / 20.41 / 20.58 | 22.07 / 33.92 / 35.06 |
| 渠道拆分 | 47.66 / 50.68 / 51.35 | 54.40 / 55.77 / 55.99 | 75.08 / 79.41 / 81.01 | 112.78 / 120.11 / 121.03 |

收入查询需要扫描当月并按 20 个游戏聚合，是本工作负载中最慢的固定查询；其并发 20 p95 为 624.50 ms。该结果是诊断信息，不等于生产 SLA。

## Acceptance Criteria 审计

| AC | 状态 | 权威证据 |
|---|---|---|
| AC-01 精确 10m | 通过 | `ten_million_generation.json` fact_rows；manifest 与独立 row count |
| AC-02 确定性 | 通过 | `tests/test_synthetic_scale.py` 同 seed 摘要一致、异 seed 事实摘要变化 |
| AC-03 资源报告 | 通过 | generation report 保存 elapsed/RSS/bytes/environment/git SHA |
| AC-04 业务分布 | 通过 | 报告分布值与 validator 阈值检查 |
| AC-05 六类标准答案 | 通过 | `ground_truth.json` 与 `tests/test_scale_validator.py` |
| AC-06 独立重算 | 通过 | 10m full scan 五项全 true；篡改答案回归测试 |
| AC-07 合成来源 | 通过 | manifest synthetic/provenance/generator version |
| AC-08 隔离安全导入 | 通过 | `tests/test_scale_importer.py`；仅允许 `gamequery_scale_*`，reader/系统库拒绝 |
| AC-09 导入正确 | 通过 | `ten_million_import.json` 逐表 expected=imported、六 SQL 全匹配 |
| AC-10 C=1 基准 | 通过 | 六类各 30 样本、p50/p95/p99/max、plan |
| AC-11 1/5/10/20 阶梯 | 通过 | `ten_million_db_benchmark.json` 4 档、720 原始样本 |
| AC-12 真实性 | 通过 | `measured`、`extrapolated=false`、scope=10m；失败报告合同测试 |
| AC-13 CI smoke | 通过（接线） | `.github/workflows/ci.yml` 与 `tests/integration/test_scale_pipeline.py`；CI 只跑 1k |
| AC-14 Agent 兼容 | 通过 | 全量 pytest 和 Ruff；在线 Agent 文件未修改 |
| AC-15 大文件治理 | 通过 | `/artifacts/scale/` 被忽略；`git ls-files artifacts/scale` 为空 |
| AC-E1 输入失败 | 通过 | 根目录、非正行数、非空输出目录测试 |
| AC-E2 导入前失败 | 通过 | 缺失/摘要/FK/答案篡改测试；损坏数据零连接测试 |

## 证据文件

- `eval/results/ten_million_generation.json`：生成资源、分布和独立验证结论。
- `eval/results/ten_million_import.json`：逐表导入耗时、行数、索引耗时和真值结论。
- `eval/results/ten_million_db_benchmark.json`：720 个原始样本、分位数、吞吐、错误与 EXPLAIN。
- `tests/test_scale_evidence.py`：防止提交后的证据字段、样本和真实性范围漂移。

## 失败案例与修正

首次正式运行暴露出 CLI 只在 pytest 模块导入下可用、直接执行 `python eval/generate_scale_data.py` 会找不到 `eval` 包。修复四个 CLI 的直接执行导入后，用真实 smoke 命令复验再重新运行 10m。隔离 MySQL 首次放在含中文路径时，8.0.26 判定 data directory 无效；改用纯 ASCII 的隔离目录和独立 3307 端口后完成实验。两次失败均未被计入 measured 结果。

## 结论边界

已证明的是：这台机器上的当前 Schema、四个组合索引和六类固定 SQL，能够在 1000 万合成事实行上完成正确导入和查询。没有证明真实企业数据分布、LLM Text-to-SQL 正确率、端到端 Agent P95、线上混合流量容量、业务提效或更大数据量；这些仍需在目标环境重新测量。
