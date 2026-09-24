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
