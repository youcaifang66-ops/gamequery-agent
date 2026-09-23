import type { AgentEvent } from "./agent";

// 编译期合同样例：后端新增/删除必填字段时，前端构建会立即失败。
export const agentContractExamples = [
  {
    type: "progress",
    request_id: "00000000-0000-0000-0000-000000000001",
    sequence: 1,
    step: "校验SQL",
    status: "running",
  },
  {
    type: "sql",
    request_id: "00000000-0000-0000-0000-000000000001",
    sequence: 2,
    version: 1,
    sql: "SELECT amount FROM fact_payment LIMIT 500",
  },
  {
    type: "result",
    request_id: "00000000-0000-0000-0000-000000000001",
    sequence: 3,
    data: [{ amount: 42 }],
  },
  {
    type: "clarification",
    request_id: "00000000-0000-0000-0000-000000000002",
    sequence: 1,
    code: "MISSING_DATE",
    missing_slots: ["date"],
    message: "请提供要查询的日期。",
  },
  {
    type: "error",
    request_id: "00000000-0000-0000-0000-000000000003",
    sequence: 1,
    code: "QUERY_TIMEOUT",
    message: "查询超时，请缩小范围后重试。",
  },
  {
    type: "done",
    request_id: "00000000-0000-0000-0000-000000000001",
    sequence: 4,
    status: "completed",
  },
] satisfies AgentEvent[];
