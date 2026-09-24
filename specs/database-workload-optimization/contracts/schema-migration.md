# Contract: 实验库结构迁移

## Modes

- `dry-run`: 只读取当前结构并输出将执行的语句。
- `apply`: 执行缺失索引创建和统计刷新。

## Preconditions

- 目标库必须匹配 `gamequery_scale_*`。
- 默认库、系统库和线上 reader 必须拒绝。
- 同名索引列序一致时标记 `already_present`；同名不同定义时失败。

## Execution

- 每条创建语句显式要求 `ALGORITHM=INPLACE, LOCK=NONE`。
- 失败不吞异常；报告标记稳定失败码和已完成步骤。
- 完成后执行 `ANALYZE TABLE`。

## Report

记录 migration version、before/after 索引、执行/跳过语句、rollback SQL、每步耗时、data/index bytes、MySQL 版本和提交 SHA。

## AC Coverage

AC-07、AC-08、AC-E2。

