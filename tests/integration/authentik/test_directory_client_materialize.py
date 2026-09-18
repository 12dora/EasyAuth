from __future__ import annotations

from email.message import Message
from http import HTTPStatus
from io import BytesIO
from json import dumps, loads
from typing import TYPE_CHECKING, Self
from urllib.error import HTTPError, URLError

import pytest

from easyauth.integrations.authentik.directory_client import (
    AuthentikDirectoryClient,
    AuthentikDirectoryConflictError,
    AuthentikDirectoryUnavailableError,
)

if TYPE_CHECKING:
    from types import TracebackType
    from urllib.request import Request

TEST_API_TOKEN = "token-value"
TIMEOUT_SECONDS = 3
MATERIALIZE_URL = (
    "https://authentik.test/api/v3/sources/oauth/"
    "dingtalk-directory/dingtalk/users/corp-1/user-1/materialize/"
)
MATERIALIZE_BODY = dumps(
    {
        "created": True,
        "user": {
            "pk": 12,
            "uuid": "fdac7e94-a7ab-4311-9b57-436f3a35f3cb",
            "username": "user-1",
            "name": "张甜",
            "is_active": True,
        },
    }
).encode()


class _Response:
    def __init__(self, body: bytes, *, content_length: str | None = None) -> None:
        self._body: bytes = body
        self._content_length: str | None = content_length
        self._consumed: bool = False

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    def read(self, _amount: int = -1) -> bytes:
        if self._consumed:
            return b""
        self._consumed = True
        return self._body

    def getheader(self, name: str) -> str | None:
        if name == "Content-Length":
            return self._content_length
        return None


def _client() -> AuthentikDirectoryClient:
    return AuthentikDirectoryClient(
        base_url="https://authentik.test",
        api_token=TEST_API_TOKEN,
        source_slug="dingtalk",
        timeout_seconds=TIMEOUT_SECONDS,
    )


def test_directory_client_materialize_user_posts_empty_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    def fake_urlopen(request: Request, *, timeout: float) -> _Response:
        assert timeout == TIMEOUT_SECONDS
        seen["url"] = request.full_url
        seen["method"] = request.get_method()
        seen["headers"] = dict(request.header_items())
        seen["body"] = request.data
        return _Response(MATERIALIZE_BODY)

    monkeypatch.setattr("easyauth.integrations.authentik.directory_client.urlopen", fake_urlopen)

    result = _client().materialize_user("corp-1", "user-1")

    assert seen["url"] == MATERIALIZE_URL
    assert seen["method"] == "POST"
    assert seen["body"] == b"{}"
    headers = seen["headers"]
    assert isinstance(headers, dict)
    assert headers["Authorization"] == f"Bearer {TEST_API_TOKEN}"
    assert result.created is True
    assert result.uuid == "fdac7e94-a7ab-4311-9b57-436f3a35f3cb"
    assert result.username == "user-1"
    assert result.name == "张甜"
    assert result.is_active is True


def test_directory_client_materialize_user_idempotent_existing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(_request: Request, *, timeout: float) -> _Response:
        _ = timeout
        payload = loads(MATERIALIZE_BODY.decode())
        payload["created"] = False
        return _Response(dumps(payload).encode())

    monkeypatch.setattr("easyauth.integrations.authentik.directory_client.urlopen", fake_urlopen)

    result = _client().materialize_user("corp-1", "user-1")

    assert result.created is False
    assert result.uuid == "fdac7e94-a7ab-4311-9b57-436f3a35f3cb"


@pytest.mark.parametrize(
    "code",
    ["union_id_missing", "username_conflict", "binding_conflict", "directory_user_inactive"],
)
def test_directory_client_materialize_maps_409_code(
    monkeypatch: pytest.MonkeyPatch,
    code: str,
) -> None:
    def fake_urlopen(request: Request, *, timeout: float) -> _Response:
        _ = timeout
        raise HTTPError(
            request.full_url,
            HTTPStatus.CONFLICT,
            "conflict",
            Message(),
            BytesIO(dumps({"code": code}).encode()),
        )

    monkeypatch.setattr("easyauth.integrations.authentik.directory_client.urlopen", fake_urlopen)

    with pytest.raises(AuthentikDirectoryConflictError) as error:
        _ = _client().materialize_user("corp-1", "user-1")
    assert error.value.code == code


def test_directory_client_materialize_maps_transport_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(_request: Request, *, timeout: float) -> _Response:
        _ = timeout
        reason = "network down"
        raise URLError(reason)

    monkeypatch.setattr("easyauth.integrations.authentik.directory_client.urlopen", fake_urlopen)

    with pytest.raises(AuthentikDirectoryUnavailableError):
        _ = _client().materialize_user("corp-1", "user-1")


def test_directory_client_materialize_rejects_invalid_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(_request: Request, *, timeout: float) -> _Response:
        _ = timeout
        return _Response(b'{"created": true}')

    monkeypatch.setattr("easyauth.integrations.authentik.directory_client.urlopen", fake_urlopen)

    with pytest.raises(AuthentikDirectoryUnavailableError):
        _ = _client().materialize_user("corp-1", "user-1")
