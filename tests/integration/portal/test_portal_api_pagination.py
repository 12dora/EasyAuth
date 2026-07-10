from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING, Final, Protocol

import pytest
from django.utils import timezone

from easyauth.access_requests.models import AccessRequest
from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App, AppScope, Permission
from easyauth.grants.models import AccessGrant, AccessGrantPermission
from tests.integration.portal.helpers import logged_in_client

if TYPE_CHECKING:
    from easyauth.api.errors import JsonValue

pytestmark = pytest.mark.django_db

GRANTS_API_URL: Final = "/portal/api/v1/me/grants"
EXPIRING_API_URL: Final = "/portal/api/v1/me/grants/expiring"
REQUESTS_API_URL: Final = "/portal/api/v1/me/access-requests"
EXPECTED_PAGE: Final = 2
EXPECTED_PAGE_SIZE: Final = 2
EXPECTED_TOTAL_ITEMS: Final = 3
EXPECTED_TOTAL_PAGES: Final = 2


class _JsonResponse(Protocol):
    def json(self) -> dict[str, JsonValue]: ...


@dataclass(frozen=True, slots=True)
class _PaginationPayload:
    page: int
    page_size: int
    total_items: int
    total_pages: int


@dataclass(frozen=True, slots=True)
class _ListPayload:
    data: tuple[dict[str, JsonValue], ...]
    pagination: _PaginationPayload


def test_portal_grants_returns_requested_page_for_session_user() -> None:
    # Given: 当前员工有三条授权, 另一个员工也有授权。
    client, user = logged_in_client("portal-page-grants-user")
    _ = _create_grant(user=user, app_key="portal-page-grant-1")
    _ = _create_grant(user=user, app_key="portal-page-grant-2")
    _ = _create_grant(user=user, app_key="portal-page-grant-3")
    other_user = UserMirror.objects.create(authentik_user_id="portal-page-grants-other")
    _ = _create_grant(user=other_user, app_key="portal-page-grant-other")

    # When: 员工请求第二页。
    response = client.get(
        GRANTS_API_URL,
        {"page": str(EXPECTED_PAGE), "page_size": str(EXPECTED_PAGE_SIZE)},
    )

    # Then: 响应只返回当前员工第二页数据, 并带分页元数据。
    payload = _json_payload(response)
    assert response.status_code == HTTPStatus.OK
    assert [item["app_key"] for item in payload.data] == ["portal-page-grant-3"]
    assert payload.pagination == _PaginationPayload(
        page=EXPECTED_PAGE,
        page_size=EXPECTED_PAGE_SIZE,
        total_items=EXPECTED_TOTAL_ITEMS,
        total_pages=EXPECTED_TOTAL_PAGES,
    )


def test_portal_expiring_grants_returns_requested_page_after_expiring_filter() -> None:
    # Given: 当前员工有三条即将过期授权和一条远期授权。
    client, user = logged_in_client("portal-page-expiring-user")
    _ = _create_grant(user=user, app_key="portal-page-expiring-1", expires_in_days=3)
    _ = _create_grant(user=user, app_key="portal-page-expiring-2", expires_in_days=4)
    _ = _create_grant(user=user, app_key="portal-page-expiring-3", expires_in_days=5)
    _ = _create_grant(user=user, app_key="portal-page-expiring-far", expires_in_days=30)

    # When: 员工读取默认 14 天窗口内的第二页即将过期授权。
    response = client.get(
        EXPIRING_API_URL,
        {"page": str(EXPECTED_PAGE), "page_size": str(EXPECTED_PAGE_SIZE)},
    )

    # Then: 分页发生在即将过期过滤之后, 不包含远期授权。
    payload = _json_payload(response)
    assert response.status_code == HTTPStatus.OK
    assert [item["app_key"] for item in payload.data] == ["portal-page-expiring-3"]
    assert payload.pagination.total_items == EXPECTED_TOTAL_ITEMS
    assert payload.pagination.total_pages == EXPECTED_TOTAL_PAGES


def test_portal_access_requests_returns_requested_page_for_session_user() -> None:
    # Given: 当前员工有三条申请, 另一个员工也有申请。
    client, user = logged_in_client("portal-page-requests-user")
    app = App.objects.create(app_key="portal-page-requests-app", name="Portal Requests")
    oldest = AccessRequest.objects.create(
        user=user,
        app=app,
        reason="第二页申请",
        idempotency_key="portal-page-request-oldest",
        payload_digest="a" * 64,
    )
    _ = AccessRequest.objects.create(
        user=user,
        app=app,
        reason="第一页申请 2",
        idempotency_key="portal-page-request-middle",
        payload_digest="b" * 64,
    )
    _ = AccessRequest.objects.create(
        user=user,
        app=app,
        reason="第一页申请",
        idempotency_key="portal-page-request-newest",
        payload_digest="c" * 64,
    )
    other_user = UserMirror.objects.create(authentik_user_id="portal-page-requests-other")
    _ = AccessRequest.objects.create(
        user=other_user,
        app=app,
        reason="不应泄露",
        idempotency_key="portal-page-request-other",
        payload_digest="d" * 64,
    )

    # When: 员工请求第二页申请。
    response = client.get(
        REQUESTS_API_URL,
        {"page": str(EXPECTED_PAGE), "page_size": str(EXPECTED_PAGE_SIZE)},
    )

    # Then: 响应只返回当前员工第二页申请, 并带分页元数据。
    payload = _json_payload(response)
    assert response.status_code == HTTPStatus.OK
    assert [item["id"] for item in payload.data] == [oldest.id]
    assert payload.pagination == _PaginationPayload(
        page=EXPECTED_PAGE,
        page_size=EXPECTED_PAGE_SIZE,
        total_items=EXPECTED_TOTAL_ITEMS,
        total_pages=EXPECTED_TOTAL_PAGES,
    )


def _create_grant(
    *,
    user: UserMirror,
    app_key: str,
    expires_in_days: int | None = None,
) -> AccessGrant:
    app = App.objects.create(app_key=app_key, name=app_key)
    expires_at = (
        timezone.now() + timedelta(days=expires_in_days)
        if expires_in_days is not None
        else None
    )
    grant = AccessGrant.objects.create(user=user, app=app)
    scope = AppScope.objects.create(app=app, key="GLOBAL", name="全局")
    permission = Permission.objects.create(
        app=app,
        key="portal.fixture",
        name="门户测试权限",
        supported_scopes=[scope.key],
    )
    _ = AccessGrantPermission.objects.create(
        grant=grant,
        permission=permission,
        scope_key=scope.key,
        expires_at=expires_at,
    )
    return grant


def _json_payload(response: _JsonResponse) -> _ListPayload:
    raw_payload = response.json()
    return _ListPayload(
        data=_required_data(raw_payload),
        pagination=_required_pagination(raw_payload),
    )


def _required_data(payload: dict[str, JsonValue]) -> tuple[dict[str, JsonValue], ...]:
    data = payload.get("data")
    assert isinstance(data, list), payload
    return _json_dict_items(data, payload)


def _json_dict_items(
    items: list[JsonValue],
    payload: dict[str, JsonValue],
) -> tuple[dict[str, JsonValue], ...]:
    result: list[dict[str, JsonValue]] = []
    for item in items:
        assert isinstance(item, dict), payload
        result.append(item)
    return tuple(result)


def _required_pagination(payload: dict[str, JsonValue]) -> _PaginationPayload:
    pagination = payload.get("pagination")
    assert isinstance(pagination, dict), payload
    return _PaginationPayload(
        page=_required_int(pagination, "page"),
        page_size=_required_int(pagination, "page_size"),
        total_items=_required_int(pagination, "total_items"),
        total_pages=_required_int(pagination, "total_pages"),
    )


def _required_int(payload: dict[str, JsonValue], key: str) -> int:
    value = payload.get(key)
    assert isinstance(value, int), payload
    assert not isinstance(value, bool), payload
    return value
