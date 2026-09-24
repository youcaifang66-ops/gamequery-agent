# Contract: 优化性能门禁

## Baseline

既有六类固定 SQL 使用 `eval/results/ten_million_db_benchmark.json` 作为优化前基线；运行环境变化时必须同时保存新的同环境 before 报告。

## Gates

- 所有查询结果与 ground truth 完全一致。
- 玩家事实查询：C=1 P95 ≤ 50 ms；C=20 P95 ≤ 200 ms。
- 既有五类非收入查询：P95 ≤ 基线 120%。
- 月收入：C=1 P95 ≤ 150 ms；C=20 P95 ≤ 500 ms。
- 超时、执行错误、结果不匹配均为 0。

## Evidence

每个门禁必须保存原始样本、查询计划、数据规模、索引定义、数据/index bytes、预热次数、迭代数、并发和硬件环境。

## AC Coverage

AC-02、AC-03、AC-05、AC-08、AC-09。
