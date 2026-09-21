import json

import pytest
from pydantic import ValidationError

from app.api.schemas.query_schema import QuerySchema
from app.api.sse import encode_sse


def test_query_length_is_bounded():
    with pytest.raises(ValidationError):
        QuerySchema(query="x")
    with pytest.raises(ValidationError):
        QuerySchema(query="x" * 1001)


def test_sse_contract_contains_named_event_and_utf8_json():
    message = encode_sse("progress", {"step": "校验SQL", "status": "success"})
    assert message.startswith("event: progress\n")
    assert json.loads(message.split("data: ", 1)[1]) == {"step": "校验SQL", "status": "success"}


def test_unknown_sse_event_is_rejected():
    with pytest.raises(ValueError):
        encode_sse("debug", {})
