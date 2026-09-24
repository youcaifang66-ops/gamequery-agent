# Performance Requirements Checklist

Spec: `specs/synthetic-business-scale/spec.md` @ v1.0 · Generated: 2026-09-24

## Primary

- [x] 目标规模是精确数值而非“海量”——AC-01。
- [x] 生成阶段声明了峰值内存和环境元数据——AC-03。
- [x] 数据库工作负载声明了预热、重复次数和分位数——AC-10。
- [x] 并发阶梯及每档独立报告已定义——AC-11。

## Alternate

- [x] CI 使用 smoke 而非冒充正式容量——AC-13。
- [x] 当前环境无法运行某阶段时有 `not_run` 契约——AC-12。

## Exception and Recovery

- [x] 数据损坏必须在数据库变更前失败——AC-E2。
- [x] 非法输出路径在写事实文件前失败——AC-E1。
- [x] 未完成实验不得留下可外推指标——AC-12。

## Non-functional

- [x] 禁止跨规模和跨机器外推——AC-11、AC-12。
- [x] 生成器有明确内存上限——AC-03。
- [x] 数据库性能报告包含索引和计划证据——AC-10。

Intentionally excluded: 真实企业 SLA、真实用户提效和真实 LLM 指标——AC-W1~W3。

**12 items, 0 findings.**
