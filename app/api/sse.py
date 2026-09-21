import json


ALLOWED_EVENT_TYPES = {"progress", "sql", "result", "error", "done"}


def encode_sse(event_type: str, payload: dict) -> str:
    if event_type not in ALLOWED_EVENT_TYPES:
        raise ValueError(f"unsupported SSE event type: {event_type}")
    return (
        f"event: {event_type}\n"
        f"data: {json.dumps(payload, ensure_ascii=False, default=str, separators=(',', ':'))}\n\n"
    )
