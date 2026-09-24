# Contract: 关卡通过率真值

## Formula

`LevelPassRate = SUM(passed) / NULLIF(SUM(attempts), 0)`

## Required Agreement

- 生成期账本累加目标事件的 `attempts`，不是事件行数。
- ground-truth SQL 使用 `SUM(passed) / SUM(attempts)`。
- 独立 CSV 扫描按相同公式复算。
- 数据库导入验收与在线指标目录结果一致。

## Edge Cases

- 分母为零时结果为 `NULL`，不得抛除零异常或返回伪造的 0。
- 结果比较采用报告中声明的统一四位小数规范。

## AC Coverage

AC-06。

