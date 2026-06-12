from __future__ import annotations

from email.message import Message
from http import HTTPStatus
from typing import TYPE_CHECKING, Self
from urllib.error import HTTPError, URLError

import pytest

from easyauth.integrations.authentik.directory_client import (
    AuthentikDirectoryClient,
    AuthentikDirectoryPermissionError,
    AuthentikDirectoryUnavailableError,
)

if TYPE_CHECKING:
    from types import TracebackType
    from urllib.request import Request

TEST_API_TOKEN = "token-value"  # noqa: S105 - 测试用假 token.
TIMEOUT_SECONDS = 3


class _Response:
    _body: bytes

    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def test_directory_client_fetches_user_org_context(monkeypatch: pytest.MonkeyPatch) -> None:
    seen_headers: dict[str, str] = {}

    def fake_urlopen(request: Request, *, timeout: float) -> _Response:
        assert timeout == TIMEOUT_SECONDS
        assert request.full_url == (
            "http://authentik.test/api/v3/sources/oauth/"
            "dingtalk-directory/dingtalk/users/corp-1/user-1/org/"
        )
        seen_headers.update(dict(request.header_items()))
        body = """
            {
              "corp_id": "corp-1",
              "user_id": "user-1",
              "source_slug": "dingtalk",
              "departments": [{"dept_id": "1", "name": "销售部", "parent_id": ""}],
              "manager": {"user_id": "manager-1", "name": "主管"},
              "manager_chain": [{"user_id": "manager-1", "name": "主管"}],
              "mobile": "13800000000",
              "raw": {"ignored": true},
              "stale": false,
              "last_synced_at": "2026-06-12T01:00:00+00:00"
            }
            """.encode()
        return _Response(body)

    monkeypatch.setattr("easyauth.integrations.authentik.directory_client.urlopen", fake_urlopen)

    context = AuthentikDirectoryClient(
        base_url="http://authentik.test",
        api_token=TEST_API_TOKEN,
        source_slug="dingtalk",
        timeout_seconds=TIMEOUT_SECONDS,
    ).get_user_org("corp-1", "user-1")

    assert seen_headers["Authorization"] == f"Bearer {TEST_API_TOKEN}"
    assert context.manager["user_id"] == "manager-1"
    assert context.departments[0]["name"] == "销售部"
    assert not hasattr(context, "mobile")


def test_directory_client_iterates_paginated_users(monkeypatch: pytest.MonkeyPatch) -> None:
    seen_urls: list[str] = []

    def fake_urlopen(request: Request, *, timeout: float) -> _Response:
        _ = timeout
        seen_urls.append(request.full_url)
        if request.full_url.endswith("page=1"):
            return _Response(
                b"""
                {
                  "pagination": {"next": 2},
                  "results": [
                    {
                      "corp_id": "corp-1",
                      "user_id": "user-1",
                      "dept_id_list": ["dept-1"],
                      "manager_user_id": "manager-1",
                      "active": true,
                      "is_deleted": false
                    }
                  ]
                }
                """,
            )
        return _Response(
            b"""
            {
              "pagination": {"next": 0},
              "results": [
                {
                  "corp_id": "corp-1",
                  "user_id": "user-2",
                  "dept_id_list": ["dept-2"],
                  "active": false,
                  "is_deleted": false
                }
              ]
            }
            """,
        )

    monkeypatch.setattr("easyauth.integrations.authentik.directory_client.urlopen", fake_urlopen)

    users = tuple(
        AuthentikDirectoryClient(
            base_url="http://authentik.test",
            api_token=TEST_API_TOKEN,
            source_slug="dingtalk",
            timeout_seconds=TIMEOUT_SECONDS,
        ).iter_users(),
    )

    assert [user.user_id for user in users] == ["user-1", "user-2"]
    assert users[0].department_ids == ("dept-1",)
    assert users[0].manager_userid == "manager-1"
    assert users[0].status == "active"
    assert users[1].status == "inactive"
    assert seen_urls == [
        "http://authentik.test/api/v3/sources/oauth/dingtalk-directory/dingtalk/users/?page=1",
        "http://authentik.test/api/v3/sources/oauth/dingtalk-directory/dingtalk/users/?page=2",
    ]


def test_directory_client_maps_403_to_permission_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: Request, *, timeout: float) -> _Response:
        _ = timeout
        raise HTTPError(request.full_url, HTTPStatus.FORBIDDEN, "forbidden", Message(), None)

    monkeypatch.setattr("easyauth.integrations.authentik.directory_client.urlopen", fake_urlopen)

    with pytest.raises(AuthentikDirectoryPermissionError):
        _ = AuthentikDirectoryClient(
            base_url="http://authentik.test",
            api_token=TEST_API_TOKEN,
            source_slug="dingtalk",
            timeout_seconds=TIMEOUT_SECONDS,
        ).get_status()


def test_directory_client_maps_network_error_without_leaking_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(_request: Request, *, timeout: float) -> _Response:
        _ = timeout
        reason = "network token-value failed"
        raise URLError(reason)

    monkeypatch.setattr("easyauth.integrations.authentik.directory_client.urlopen", fake_urlopen)

    with pytest.raises(AuthentikDirectoryUnavailableError) as error:
        _ = AuthentikDirectoryClient(
            base_url="http://authentik.test",
            api_token=TEST_API_TOKEN,
            source_slug="dingtalk",
            timeout_seconds=TIMEOUT_SECONDS,
        ).get_status()

    assert TEST_API_TOKEN not in str(error.value)
