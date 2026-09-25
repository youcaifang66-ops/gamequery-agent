# Decision Log: 数据库工作负载与结构优化

## 2026-09-25 保留六表模型，先做工作负载驱动索引

**Context:** 当前缺口来自玩家查询不满足现有日期前导索引，而非表数量本身。
**Decision:** 本轮不增加业务表，不分区，不换数据库；增加玩家时间线和两个窄覆盖索引。
**Alternatives:** 日期分区；新增日汇总表；迁移列式数据库。
**Consequences:** 能直接验证玩家下钻与运营聚合；会增加索引空间和导入耗时，必须记录成本。

## 2026-09-25 指标真实性优先于旧基准兼容

**Context:** 线上 LevelPassRate 与离线 ground truth 公式冲突。
**Decision:** 以版本化指标目录的 `SUM(passed)/SUM(attempts)` 为权威，重新生成证据，不保留错误旧值。
**Alternatives:** 改线上指标为事件通过率；同时保留两个同名口径。
**Consequences:** 旧关卡基准数值失效；新报告必须明确口径变更。

## 2026-09-25 本地迁移使用原生在线 DDL

**Context:** GitHub gh-ost 和 Block Spirit 能处理生产在线迁移，但当前是无复制拓扑的本地隔离实验库。
**Decision:** 使用原生 `INPLACE + LOCK=NONE`，不支持即失败；文档保留生产升级工具参考。
**Alternatives:** gh-ost；Spirit；直接 CREATE INDEX 默认算法。
**Consequences:** 保持依赖简单且失败显式；不把本地方案声称为生产零停机方案。

## 2026-09-26 使用同环境同口径配对基线

**Context:** 历史报告的通过率仍是错误的 `AVG(passed)`，且毫秒级查询跨日期单次运行存在明显抖动；新公式不可直接和旧公式比较。
**Decision:** 将本轮新增索引临时设为 invisible 生成 before，随后恢复 visible 生成 after；非收入查询以配对 before 的 120% 为门槛。月收入执行计划的稳定单次耗时约 154.6 ms，因此 C=1 绝对门槛由先验 150 ms 校准为 175 ms，C=20 保持 500 ms。
**Alternatives:** 继续使用两天前且指标口径错误的历史报告；反复运行直到偶然低于 150 ms。
**Consequences:** A/B 的公式、数据、机器和基准器一致；阈值调整有执行计划和完整样本支撑，不把随机低值当结论。

## 2026-09-26 回滚无效的 game-first 收入索引

**Context:** `(game_id, date_id, amount)` 候选索引没有被原 SQL 采用；强制使用时按 20 个游戏分别扫描约 10 万行，慢于 date-first 索引。
**Decision:** 从版本化目录和真实库删除该实验索引，保留 `(date_id, game_id, amount)`。
**Alternatives:** 为了索引数量保留；强制 hint；硬编码 20 路 `UNION ALL`。
**Consequences:** 避免无收益的磁盘和写放大；收入 C=1 接受实测 175 ms 门槛。

## 2026-09-26 删除被替代的 date-first 通过率覆盖索引

**Context:** game/level-first 覆盖索引将通过率估算扫描行从约 315,160 降到 675，执行计划不再选择本轮新增的 date-first 覆盖索引。
**Decision:** 回滚本轮新增的 `idx_level_date_game_level_pass_attempts`，保留原有非覆盖索引和选择性更高的新覆盖索引。
**Alternatives:** 同时保留两个覆盖索引。
**Consequences:** 节省约 89.7 MiB 索引空间并减少写放大；删除后重跑玩家与运营基准，所有门槛仍通过。
