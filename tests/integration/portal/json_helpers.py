from __future__ import annotations

from typing import Final, Protocol

from pydantic import TypeAdapter

from easyauth.api.errors import JsonValue

JSON_VALUE_ADAPTER: Final[TypeAdapter[JsonValue]] = TypeAdapter(JsonValue)


class HttpResponseLike(Protocol):
    content: bytes


def json_object(response: HttpResponseLike) -> dict[str, JsonValue]:
    payload = JSON_VALUE_ADAPTER.validate_json(response.content)
    assert isinstance(payload, dict), response.content.decode()
    return payload
