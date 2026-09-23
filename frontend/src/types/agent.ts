/** 后端 SSE 事件的公共可追踪字段。 */
export type EventEnvelope = {
  request_id: string;
  sequence: number;
};

export type ProgressStatus = "running" | "success" | "error";

export type ProgressEvent = EventEnvelope & {
  type: "progress";
  step: string;
  status: ProgressStatus;
};

export type SqlEvent = EventEnvelope & {
  type: "sql";
  version: number;
  sql: string;
};

export type ResultEvent = EventEnvelope & {
  type: "result";
  data: unknown;
};

export type ClarificationEvent = EventEnvelope & {
  type: "clarification";
  code: string;
  missing_slots: string[];
  message: string;
};

export type ErrorEvent = EventEnvelope & {
  type: "error";
  code: string;
  message: string;
};

export type DoneEvent = EventEnvelope & {
  type: "done";
  status: "completed" | "clarification";
};

export type AgentEvent =
  | ProgressEvent
  | SqlEvent
  | ResultEvent
  | ClarificationEvent
  | ErrorEvent
  | DoneEvent;

export type StepState = {
  step: string;
  status: ProgressStatus;
  updatedAt: number;
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  createdAt: number;
  status?: "streaming" | "done" | "error";
  steps?: StepState[];
  result?: unknown;
  error?: string;
};
