/**
 * 智能体接口客户端
 * 封装后端 /api/query SSE 流式接口请求与事件解析逻辑
 */
import type { AgentEvent } from "../types/agent";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") ?? "";

type QueryOptions = {
  signal?: AbortSignal;
  onEvent: (event: AgentEvent) => void;
};

export async function streamQuery(query: string, options: QueryOptions) {
  const response = await fetch(`${API_BASE_URL}/api/query`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify({ query }),
    signal: options.signal,
  });

  if (!response.ok) {
    throw new Error(`接口请求失败：HTTP ${response.status}`);
  }

  if (!response.body) {
    throw new Error("浏览器未返回可读取的流式响应。");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  let requestId: string | null = null;
  let lastSequence = 0;
  let terminal = false;

  const emit = (event: AgentEvent) => {
    if (terminal) return;
    if (requestId !== null && event.request_id !== requestId) {
      throw new Error("后端事件 request_id 在同一条流中发生变化。");
    }
    if (event.sequence !== lastSequence + 1) {
      throw new Error("后端事件 sequence 不连续。");
    }
    requestId = event.request_id;
    lastSequence = event.sequence;
    options.onEvent(event);
    terminal = event.type === "done" || event.type === "error";
  };

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split(/\n\n/);
    buffer = chunks.pop() ?? "";

    for (const chunk of chunks) {
      const event = parseSseChunk(chunk);
      if (event) {
        emit(event);
      }
    }
    if (terminal) {
      await reader.cancel();
      return;
    }
  }

  buffer += decoder.decode();
  const tail = parseSseChunk(buffer);
  if (tail) {
    emit(tail);
  }
}

function parseSseChunk(chunk: string): AgentEvent | null {
  const payload = chunk
    .split("\n")
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.replace(/^data:\s?/, ""))
    .join("\n")
    .trim();

  if (!payload) return null;

  try {
    const event = JSON.parse(payload) as AgentEvent;
    if (
      !event ||
      typeof event !== "object" ||
      typeof event.type !== "string" ||
      typeof event.request_id !== "string" ||
      !Number.isInteger(event.sequence)
    ) {
      throw new Error("后端事件缺少 type、request_id 或 sequence。");
    }
    return event;
  } catch {
    throw new Error("无法解析后端 SSE 事件。");
  }
}
