from __future__ import annotations

from json import dumps
from typing import TYPE_CHECKING, Self, final

import pytest

from easyauth.integrations.authentik import admin_client as admin_client_module
from easyauth.integrations.authentik.admin_client import (
    OPERATION_TIMEOUT_MESSAGE,
    RESPONSE_TOO_LARGE_MESSAGE,
    AuthentikAdminClient,
    AuthentikAdminError,
    AuthentikAdminPaginationLimitError,
    AuthentikAdminUserNotFoundError,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import TracebackType
    from urllib.request import Request

_OVERSIZED_BODY_BYTES = 1024 * 1024 + 1
_EXPECTED_SESSION_COUNT = 3


@final
class _Response:
    def __init__(
        self,
        body: bytes,
        *,
        content_length: str | None = None,
        omit_content_length: bool = False,
    ) -> None:
        self._body: bytes = body
        self._offset: int = 0
        self._content_length: str | None = (
            None
            if omit_content_length
            else (str(len(body)) if content_length is None else content_length)
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    def read(self, amount: int = -1) -> bytes:
        if amount < 0:
            amount = len(self._body) - self._offset
        chunk = self._body[self._offset : self._offset + amount]
        self._offset += len(chunk)
        return chunk

    def getheader(self, name: str) -> str | None:
        return self._content_length if name == "Content-Length" else None


def _json_response(payload: object) -> _Response:
    return _Response(dumps(payload).encode())


def _client(*, monotonic: Callable[[], float] | None = None) -> AuthentikAdminClient:
    if monotonic is None:
        return AuthentikAdminClient(
            base_url="https://authentik.test",
            api_token="test-token",
            timeout_seconds=5,
        )
    return AuthentikAdminClient(
        base_url="https://authentik.test",
        api_token="test-token",
        timeout_seconds=5,
        monotonic=monotonic,
    )


_USER_UUID = "fdac7e94-a7ab-4311-9b57-436f3a35f3cb"
_USER_LOOKUP_URL = f"https://authentik.test/api/v3/core/users/?uuid={_USER_UUID}&page_size=2"


def _user_page(
    *,
    uuid: str = _USER_UUID,
    pk: int = 7,
    count: int | None = 1,
    extra_results: tuple[dict[str, object], ...] = (),
) -> dict[str, object]:
    results: list[dict[str, object]] = [{"uuid": uuid, "pk": pk, "uid": "hash-not-sub"}]
    results.extend(extra_results)
    pagination: dict[str, object] = {"total_pages": 1, "current": 1, "next": 0}
    if count is not None:
        pagination["count"] = count
    return {"results": results, "pagination": pagination}


def _active_user_page(
    *entries: dict[str, object],
    current: int,
    total_pages: int,
) -> dict[str, object]:
    return {
        "results": list(entries),
        "pagination": {"current": current, "total_pages": total_pages, "next": 0},
    }


def _session_page(*uuids: str, current: int, next_page: int) -> dict[str, object]:
    return {
        "results": [{"uuid": value} for value in uuids],
        "pagination": {"current": current, "next": next_page},
    }


def _urlopen_response(response: _Response) -> Callable[..., _Response]:
    def fake_urlopen(_request: Request, *, timeout: float) -> _Response:
        _ = timeout
        return response

    return fake_urlopen


def test_disable_user_revokes_every_session_page(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = iter(
        [
            _json_response(_user_page()),
            _json_response({}),
            _json_response(_session_page("session-1", "session-2", current=1, next_page=2)),
            _json_response(_session_page("session-3", current=2, next_page=0)),
            _Response(b""),
            _Response(b""),
            _Response(b""),
        ],
    )
    seen_urls: list[str] = []

    def fake_urlopen(request: Request, *, timeout: float) -> _Response:
        assert timeout > 0
        seen_urls.append(request.full_url)
        return next(responses)

    monkeypatch.setattr("easyauth.integrations.authentik.admin_client.urlopen", fake_urlopen)

    result = _client().disable_user_and_revoke_sessions(_USER_UUID)

    assert result.revoked_session_count == _EXPECTED_SESSION_COUNT
    assert seen_urls[0] == _USER_LOOKUP_URL
    session_list_urls = [url for url in seen_urls if "authenticated_sessions/?" in url]
    assert session_list_urls == [
        "https://authentik.test/api/v3/core/authenticated_sessions/?user=7&page=1&page_size=500",
        "https://authentik.test/api/v3/core/authenticated_sessions/?user=7&page=2&page_size=500",
    ]
    assert (
        sum("authenticated_sessions/session-" in url for url in seen_urls)
        == _EXPECTED_SESSION_COUNT
    )


def test_user_group_names_by_uuid_reads_current_user_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = iter(
        [
            _json_response(_user_page()),
            _json_response(
                {
                    "groups": [
                        {"name": "EasyAuth Admins"},
                        {"name": "Developers"},
                        "EasyAuth Admins",
                    ],
                },
            ),
        ],
    )
    seen_urls: list[str] = []

    def fake_urlopen(request: Request, *, timeout: float) -> _Response:
        assert timeout > 0
        seen_urls.append(request.full_url)
        return next(responses)

    monkeypatch.setattr("easyauth.integrations.authentik.admin_client.urlopen", fake_urlopen)

    groups = _client().user_group_names_by_uuid(_USER_UUID)

    assert groups == ("Developers", "EasyAuth Admins")
    assert seen_urls == [
        _USER_LOOKUP_URL,
        "https://authentik.test/api/v3/core/users/7/",
    ]


def test_user_group_names_by_uuid_rejects_missing_groups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = iter([_json_response(_user_page()), _json_response({})])

    def fake_urlopen(_request: Request, *, timeout: float) -> _Response:
        _ = timeout
        return next(responses)

    monkeypatch.setattr("easyauth.integrations.authentik.admin_client.urlopen", fake_urlopen)

    with pytest.raises(AuthentikAdminError, match="响应格式"):
        _ = _client().user_group_names_by_uuid(_USER_UUID)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"results": None, "pagination": {"current": 1, "next": 0}},
        {"results": ["bad-item"], "pagination": {"current": 1, "next": 0}},
        {"results": [{"uuid": 123}], "pagination": {"current": 1, "next": 0}},
        {"results": [], "pagination": {"current": 2, "next": 0}},
    ],
)
def test_session_revoke_rejects_malformed_envelope(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, object],
) -> None:
    responses = iter(
        [
            _json_response(_user_page()),
            _json_response({}),
            _json_response(payload),
        ],
    )

    def fake_urlopen(_request: Request, *, timeout: float) -> _Response:
        _ = timeout
        return next(responses)

    monkeypatch.setattr("easyauth.integrations.authentik.admin_client.urlopen", fake_urlopen)

    with pytest.raises(AuthentikAdminError, match="响应格式"):
        _ = _client().disable_user_and_revoke_sessions(_USER_UUID)


def test_get_user_by_uuid_returns_the_core_user_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    entry = {"uuid": _USER_UUID, "pk": 7, "name": "陈柠", "is_active": True}

    def fake_urlopen(request: Request, *, timeout: float) -> _Response:
        _ = timeout
        assert request.full_url == _USER_LOOKUP_URL
        return _json_response(_user_page())

    monkeypatch.setattr("easyauth.integrations.authentik.admin_client.urlopen", fake_urlopen)

    found = _client().get_user_by_uuid(_USER_UUID)

    assert found["uuid"] == entry["uuid"]
    assert found["pk"] == entry["pk"]


def test_get_user_by_uuid_raises_not_found_for_empty_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(_request: Request, *, timeout: float) -> _Response:
        _ = timeout
        return _json_response({"results": [], "pagination": {"count": 0, "total_pages": 1}})

    monkeypatch.setattr("easyauth.integrations.authentik.admin_client.urlopen", fake_urlopen)

    with pytest.raises(AuthentikAdminUserNotFoundError, match="找不到"):
        _ = _client().get_user_by_uuid(_USER_UUID)


def test_get_user_by_uuid_rejects_ambiguous_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    duplicate = {"uuid": _USER_UUID, "pk": 8, "uid": "other-hash"}

    def fake_urlopen(_request: Request, *, timeout: float) -> _Response:
        _ = timeout
        return _json_response(_user_page(count=2, extra_results=(duplicate,)))

    monkeypatch.setattr("easyauth.integrations.authentik.admin_client.urlopen", fake_urlopen)

    with pytest.raises(AuthentikAdminError, match="多个用户"):
        _ = _client().get_user_by_uuid(_USER_UUID)


def test_iter_active_users_walks_bounded_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    first = {"uuid": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "pk": 1, "is_active": True}
    second = {"uuid": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", "pk": 2, "is_active": True}
    responses = iter(
        [
            _json_response(_active_user_page(first, current=1, total_pages=2)),
            _json_response(_active_user_page(second, current=2, total_pages=2)),
        ],
    )
    seen_urls: list[str] = []

    def fake_urlopen(request: Request, *, timeout: float) -> _Response:
        _ = timeout
        seen_urls.append(request.full_url)
        return next(responses)

    monkeypatch.setattr("easyauth.integrations.authentik.admin_client.urlopen", fake_urlopen)

    users = list(_client().iter_active_users())

    assert [entry["pk"] for entry in users] == [1, 2]
    assert seen_urls == [
        "https://authentik.test/api/v3/core/users/?is_active=true&page=1&page_size=100&ordering=pk",
        "https://authentik.test/api/v3/core/users/?is_active=true&page=2&page_size=100&ordering=pk",
    ]


def test_iter_active_users_shares_one_deadline_across_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = {"uuid": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "pk": 1, "is_active": True}
    second = {"uuid": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", "pk": 2, "is_active": True}
    clock = {"now": 0.0}

    @final
    class _DeadlineResponse(_Response):
        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc_value: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            del exc_type, exc_value, traceback
            clock["now"] = 61.0

    responses = iter(
        [
            _DeadlineResponse(dumps(_active_user_page(first, current=1, total_pages=2)).encode()),
            _DeadlineResponse(dumps(_active_user_page(second, current=2, total_pages=2)).encode()),
        ],
    )

    def fake_urlopen(_request: Request, *, timeout: float) -> _Response:
        _ = timeout
        return next(responses)

    monkeypatch.setattr("easyauth.integrations.authentik.admin_client.urlopen", fake_urlopen)

    def monotonic() -> float:
        return clock["now"]

    with pytest.raises(AuthentikAdminError, match=OPERATION_TIMEOUT_MESSAGE):
        _ = list(_client(monotonic=monotonic).iter_active_users())


def test_iter_active_users_rejects_missing_uuid(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(_request: Request, *, timeout: float) -> _Response:
        _ = timeout
        return _json_response(
            _active_user_page({"pk": 1, "is_active": True}, current=1, total_pages=1),
        )

    monkeypatch.setattr("easyauth.integrations.authentik.admin_client.urlopen", fake_urlopen)

    with pytest.raises(AuthentikAdminError, match="响应格式"):
        _ = list(_client().iter_active_users())


def test_iter_active_users_raises_when_page_bound_exceeded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(_request: Request, *, timeout: float) -> _Response:
        _ = timeout
        return _json_response(_active_user_page(current=1, total_pages=201))

    monkeypatch.setattr("easyauth.integrations.authentik.admin_client.urlopen", fake_urlopen)

    with pytest.raises(AuthentikAdminPaginationLimitError, match="分页超过上限"):
        _ = list(_client().iter_active_users())


def test_request_rejects_declared_oversized_response(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _Response(b"{}", content_length=str(_OVERSIZED_BODY_BYTES))
    monkeypatch.setattr(
        "easyauth.integrations.authentik.admin_client.urlopen",
        _urlopen_response(response),
    )

    with pytest.raises(AuthentikAdminError, match=RESPONSE_TOO_LARGE_MESSAGE):
        _ = _client()._request_json(  # pyright: ignore[reportPrivateUsage]  # noqa: SLF001
            "GET",
            "/api/v3/test/",
        )


def test_request_rejects_streamed_oversized_response(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _Response(b"x" * _OVERSIZED_BODY_BYTES, omit_content_length=True)
    monkeypatch.setattr(
        "easyauth.integrations.authentik.admin_client.urlopen",
        _urlopen_response(response),
    )

    with pytest.raises(AuthentikAdminError, match=RESPONSE_TOO_LARGE_MESSAGE):
        _ = _client()._request_json(  # pyright: ignore[reportPrivateUsage]  # noqa: SLF001
            "GET",
            "/api/v3/test/",
        )


def test_probe_core_users_counts_internal_authentik_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    keys: list[str] = []
    monkeypatch.setattr(
        admin_client_module,
        "record_usage",
        lambda key, *_args, **_kwargs: keys.append(str(key)),
        raising=False,
    )
    monkeypatch.setattr(
        admin_client_module,
        "urlopen",
        _urlopen_response(_json_response({"results": []})),
    )
    _client().probe_core_users()
    assert keys == ["internal_authentik_admin"]


def test_request_enforces_total_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = iter([0.0, 0.0, 61.0]).__next__
    monkeypatch.setattr(
        "easyauth.integrations.authentik.admin_client.urlopen",
        _urlopen_response(_json_response({})),
    )

    with pytest.raises(AuthentikAdminError, match=OPERATION_TIMEOUT_MESSAGE):
        _ = _client(monotonic=clock)._request_json(  # pyright: ignore[reportPrivateUsage]  # noqa: SLF001
            "GET",
            "/api/v3/test/",
        )
