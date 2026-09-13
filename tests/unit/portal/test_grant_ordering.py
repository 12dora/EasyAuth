from __future__ import annotations

from datetime import datetime, timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING, Final, Protocol, cast

import pytest
from django.utils import timezone

from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.applications.models import App, AppScope, AuthorizationGroup, Permission
from easyauth.grants.models import AccessGrant, AccessGrantGroup, AccessGrantPermission
from tests.integration.portal.helpers import logged_in_client

if TYPE_CHECKING:
    from django.test import Client

    from easyauth.accounts.models import UserMirror

pytestmark = pytest.mark.django_db


class _JsonResponse(Protocol):
    status_code: int
    content: bytes

    def json(self) -> dict[str, JsonValue]: ...


GRANTS_URL: Final = "/portal/api/v1/me/grants"
EXPIRING_URL: Final = "/portal/api/v1/me/grants/expiring"


def test_portal_grants_order_by_app_key_and_created_at() -> None:
    client, user = logged_in_client("portal-grant-order-basic")
    now = timezone.now()
    later = _grant(user, "portal-grant-z", created_at=now)
    middle = _grant(user, "portal-grant-m", created_at=now - timedelta(hours=1))
    earlier = _grant(user, "portal-grant-a", created_at=now - timedelta(hours=2))

    assert _app_keys(client, GRANTS_URL, "app_key") == [
        earlier.app.app_key,
        middle.app.app_key,
        later.app.app_key,
    ]
    assert _app_keys(client, GRANTS_URL, "-app_key") == [
        later.app.app_key,
        middle.app.app_key,
        earlier.app.app_key,
    ]
    assert _app_keys(client, GRANTS_URL, "created_at") == [
        earlier.app.app_key,
        middle.app.app_key,
        later.app.app_key,
    ]
    assert _app_keys(client, GRANTS_URL, "-created_at") == [
        later.app.app_key,
        middle.app.app_key,
        earlier.app.app_key,
    ]


def test_portal_grants_order_by_expires_at_places_permanent_last() -> None:
    client, user = logged_in_client("portal-grant-order-expires")
    soon = _grant(user, "portal-grant-soon", expires_in_days=2)
    later = _grant(user, "portal-grant-later", expires_in_days=9)
    permanent = _grant(user, "portal-grant-perm")

    assert _app_keys(client, GRANTS_URL, "expires_at") == [
        soon.app.app_key,
        later.app.app_key,
        permanent.app.app_key,
    ]
    assert _app_keys(client, GRANTS_URL, "-expires_at") == [
        later.app.app_key,
        soon.app.app_key,
        permanent.app.app_key,
    ]


def test_portal_grants_order_by_groups_uses_first_name_and_places_empty_last() -> None:
    client, user = logged_in_client("portal-grant-order-groups")
    alpha = _grant(user, "portal-grant-group-a", group_name="Alpha")
    zeta = _grant(user, "portal-grant-group-z", group_name="Zeta")
    empty = _grant(user, "portal-grant-group-none")
    _ = _grant(
        user,
        "portal-grant-group-second",
        group_name="Mu",
        extra_group_name="Zulu",
    )

    assert _app_keys(client, GRANTS_URL, "groups") == [
        alpha.app.app_key,
        "portal-grant-group-second",
        zeta.app.app_key,
        empty.app.app_key,
    ]
    assert _app_keys(client, GRANTS_URL, "-groups") == [
        zeta.app.app_key,
        "portal-grant-group-second",
        alpha.app.app_key,
        empty.app.app_key,
    ]


def test_portal_grants_order_by_permission_details_counts_direct_rows() -> None:
    client, user = logged_in_client("portal-grant-order-perms")
    none = _grant(user, "portal-grant-perm-0", permission_count=0, group_name="KeepVisible")
    one = _grant(user, "portal-grant-perm-1", permission_count=1)
    two = _grant(user, "portal-grant-perm-2", permission_count=2)

    assert _app_keys(client, GRANTS_URL, "permission_details") == [
        none.app.app_key,
        one.app.app_key,
        two.app.app_key,
    ]
    assert _app_keys(client, GRANTS_URL, "-permission_details") == [
        two.app.app_key,
        one.app.app_key,
        none.app.app_key,
    ]


def test_portal_expiring_grants_honor_new_ordering_fields() -> None:
    client, user = logged_in_client("portal-expiring-order")
    soon = _grant(
        user,
        "portal-exp-a",
        expires_in_days=2,
        group_name="Alpha",
        permission_count=2,
    )
    mid = _grant(
        user,
        "portal-exp-m",
        expires_in_days=5,
        group_name="Mu",
        permission_count=0,
    )
    later = _grant(
        user,
        "portal-exp-z",
        expires_in_days=9,
        permission_count=1,
    )
    _ = _grant(user, "portal-exp-far", expires_in_days=30)

    assert _app_keys(client, EXPIRING_URL, "app_key") == [
        soon.app.app_key,
        mid.app.app_key,
        later.app.app_key,
    ]
    assert _app_keys(client, EXPIRING_URL, "-app_key") == [
        later.app.app_key,
        mid.app.app_key,
        soon.app.app_key,
    ]
    assert _app_keys(client, EXPIRING_URL, "expires_at") == [
        soon.app.app_key,
        mid.app.app_key,
        later.app.app_key,
    ]
    assert _app_keys(client, EXPIRING_URL, "-expires_at") == [
        later.app.app_key,
        mid.app.app_key,
        soon.app.app_key,
    ]
    assert _app_keys(client, EXPIRING_URL, "groups") == [
        soon.app.app_key,
        mid.app.app_key,
        later.app.app_key,
    ]
    assert _app_keys(client, EXPIRING_URL, "permission_details") == [
        mid.app.app_key,
        later.app.app_key,
        soon.app.app_key,
    ]


def test_portal_grant_lists_reject_unknown_ordering() -> None:
    client, _user = logged_in_client("portal-grant-order-unknown")
    for url in (GRANTS_URL, EXPIRING_URL):
        response = client.get(url, {"ordering": "not-a-field"})
        _assert_unknown_ordering(response, "not-a-field")


def _grant(  # noqa: PLR0913 - 测试夹具按授权排序字段铺开。
    user: UserMirror,
    app_key: str,
    *,
    expires_in_days: int | None = None,
    group_name: str | None = None,
    extra_group_name: str | None = None,
    permission_count: int = 1,
    created_at: datetime | None = None,
) -> AccessGrant:
    app = App.objects.create(app_key=app_key, name=app_key)
    grant = AccessGrant.objects.create(user=user, app=app)
    expires_at = (
        timezone.now() + timedelta(days=expires_in_days) if expires_in_days is not None else None
    )
    if group_name is not None:
        group = AuthorizationGroup.objects.create(
            app=app,
            key="primary",
            kind="role",
            name=group_name,
            requestable=False,
        )
        _ = AccessGrantGroup.objects.create(
            grant=grant,
            authorization_group=group,
            expires_at=expires_at,
        )
    if extra_group_name is not None:
        extra = AuthorizationGroup.objects.create(
            app=app,
            key="secondary",
            kind="role",
            name=extra_group_name,
            requestable=False,
        )
        _ = AccessGrantGroup.objects.create(grant=grant, authorization_group=extra)
    if permission_count > 0:
        scope = AppScope.objects.create(app=app, key="GLOBAL", name="全局")
        for index in range(permission_count):
            permission = Permission.objects.create(
                app=app,
                key=f"perm.{index}",
                name=f"权限 {index}",
                supported_scopes=[scope.key],
            )
            _ = AccessGrantPermission.objects.create(
                grant=grant,
                permission=permission,
                scope_key=scope.key,
                expires_at=expires_at,
            )
    if created_at is not None:
        _ = AccessGrant.objects.filter(pk=grant.pk).update(created_at=created_at)
        grant.refresh_from_db()
    return grant


def _app_keys(client: Client, url: str, ordering: str) -> list[str]:
    return [str(item["app_key"]) for item in _items(client, url, ordering)]


def _items(client: Client, url: str, ordering: str) -> list[dict[str, JsonValue]]:
    response = client.get(url, {"ordering": ordering, "page_size": "20"})
    assert response.status_code == HTTPStatus.OK, response.content
    payload = cast("dict[str, JsonValue]", response.json())
    data = payload["data"]
    assert isinstance(data, list), payload
    items: list[dict[str, JsonValue]] = []
    for item in data:
        assert isinstance(item, dict), payload
        items.append(item)
    return items


def _assert_unknown_ordering(response: _JsonResponse, value: str) -> None:
    assert response.status_code == HTTPStatus.BAD_REQUEST
    payload = cast("dict[str, JsonValue]", response.json())
    error = payload["error"]
    assert isinstance(error, dict)
    assert error["code"] == ErrorCode.VALIDATION_ERROR
    assert error["details"] == {"field": "ordering", "value": value}
