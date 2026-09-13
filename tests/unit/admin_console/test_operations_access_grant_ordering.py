from __future__ import annotations

from datetime import timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING, Final, Protocol, cast

import pytest
from django.test import Client
from django.utils import timezone

from easyauth.accounts.models import UserMirror
from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.applications.models import App, AppScope, AuthorizationGroup, Permission
from easyauth.grants.models import (
    GRANT_STATUS_ACTIVE,
    GRANT_STATUS_EXPIRED,
    GRANT_STATUS_REVOKED,
    AccessGrant,
    AccessGrantGroup,
    AccessGrantPermission,
)
from tests.integration.admin_console.auth_helpers import (
    authenticate_console_admin,
    install_authentik_authority,
    reset_authentik_authority,
)

if TYPE_CHECKING:
    from datetime import datetime

    from pytest_django.fixtures import SettingsWrapper

pytestmark = pytest.mark.django_db

GRANTS_URL: Final = "/console/api/v1/operations/access-grants"


class _JsonResponse(Protocol):
    status_code: int

    def json(self) -> dict[str, JsonValue]: ...


@pytest.fixture(autouse=True)
def _console_auth(monkeypatch: pytest.MonkeyPatch, settings: SettingsWrapper) -> None:
    settings.EASYAUTH_CONSOLE_SUPERUSER_GROUPS = ("easyauth-admins",)
    reset_authentik_authority()
    install_authentik_authority(monkeypatch)


def test_operations_access_grants_order_by_user_app_and_status() -> None:
    client = _admin("ord-ops-grant-basic-admin")
    ada = UserMirror.objects.create(authentik_user_id="ord-ops-grant-ada", name="Ada")
    cara = UserMirror.objects.create(authentik_user_id="ord-ops-grant-cara", name="Cara")
    ben = UserMirror.objects.create(authentik_user_id="ord-ops-grant-ben", name="Ben")
    active = _grant(ada, "ord-ops-grant-z", status=GRANT_STATUS_ACTIVE)
    expired = _grant(
        ben,
        "ord-ops-grant-m",
        status=GRANT_STATUS_EXPIRED,
        is_current=False,
    )
    revoked = _grant(
        cara,
        "ord-ops-grant-a",
        status=GRANT_STATUS_REVOKED,
        is_current=False,
    )

    assert _ids(client, "user", current_only="false") == [active.id, expired.id, revoked.id]
    assert _ids(client, "-user", current_only="false") == [revoked.id, expired.id, active.id]
    assert _ids(client, "app_key", current_only="false") == [revoked.id, expired.id, active.id]
    assert _ids(client, "status", current_only="false") == [active.id, expired.id, revoked.id]
    assert _ids(client, "-status", current_only="false") == [revoked.id, expired.id, active.id]


def test_operations_access_grants_order_by_groups_permissions_and_expiry() -> None:
    client = _admin("ord-ops-grant-ann-admin")
    user = UserMirror.objects.create(authentik_user_id="ord-ops-grant-ann-user")
    alpha = _grant(user, "ord-ops-grant-alpha", group_name="Alpha", permission_count=2, days=2)
    empty = _grant(user, "ord-ops-grant-empty", permission_count=0)
    zeta = _grant(user, "ord-ops-grant-zeta", group_name="Zeta", permission_count=1, days=9)
    permanent = _grant(user, "ord-ops-grant-perm", permission_count=3)

    assert _ids(client, "groups") == [alpha.id, zeta.id, empty.id, permanent.id]
    assert _ids(client, "-groups") == [zeta.id, alpha.id, empty.id, permanent.id]
    assert _ids(client, "permission_details") == [empty.id, zeta.id, alpha.id, permanent.id]
    assert _ids(client, "-permission_details") == [permanent.id, alpha.id, zeta.id, empty.id]
    assert _ids(client, "grant_expires_at") == [alpha.id, zeta.id, empty.id, permanent.id]
    assert _ids(client, "-grant_expires_at") == [zeta.id, alpha.id, empty.id, permanent.id]


def test_operations_access_grants_default_order_is_user_name_app_key_then_version() -> None:
    client = _admin("ord-ops-grant-default-admin")
    cara = UserMirror.objects.create(authentik_user_id="ord-ops-grant-default-cara", name="Cara")
    ada = UserMirror.objects.create(authentik_user_id="ord-ops-grant-default-ada", name="Ada")
    ada_zeta = _grant(ada, "ord-ops-grant-default-z")
    cara_mu = _grant(cara, "ord-ops-grant-default-m")
    ada_alpha_v1 = _grant(ada, "ord-ops-grant-default-a", is_current=False)
    ada_alpha_v2 = AccessGrant.objects.create(
        user=ada,
        app=ada_alpha_v1.app,
        status=GRANT_STATUS_ACTIVE,
        is_current=True,
        version=2,
    )

    response = client.get(GRANTS_URL, {"current_only": "false", "page_size": "20"})
    assert response.status_code == HTTPStatus.OK, response.content
    payload = cast("dict[str, JsonValue]", response.json())
    data = payload["data"]
    assert isinstance(data, list), payload
    ids = [item["id"] for item in data if isinstance(item, dict)]
    assert ids == [ada_alpha_v2.id, ada_alpha_v1.id, ada_zeta.id, cara_mu.id]


def test_operations_access_grants_reject_unknown_ordering() -> None:
    client = _admin("ord-ops-grant-unknown-admin")
    response = client.get(GRANTS_URL, {"ordering": "does_not_exist"})
    _assert_unknown(response, "does_not_exist")


def _grant(  # noqa: PLR0913 - 运营授权夹具按排序字段铺开。
    user: UserMirror,
    app_key: str,
    *,
    status: str = GRANT_STATUS_ACTIVE,
    is_current: bool = True,
    group_name: str | None = None,
    permission_count: int = 1,
    days: int | None = None,
) -> AccessGrant:
    app = App.objects.create(app_key=app_key, name=app_key)
    grant = AccessGrant.objects.create(
        user=user,
        app=app,
        status=status,
        is_current=is_current,
    )
    expires_at: datetime | None = (
        timezone.now() + timedelta(days=days) if days is not None else None
    )
    if group_name is not None:
        group = AuthorizationGroup.objects.create(
            app=app,
            key="role",
            kind="role",
            name=group_name,
            requestable=False,
        )
        _ = AccessGrantGroup.objects.create(
            grant=grant,
            authorization_group=group,
            expires_at=expires_at,
        )
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
    return grant


def _admin(username: str) -> Client:
    return authenticate_console_admin(Client(HTTP_HOST="localhost"), username)


def _ids(client: Client, ordering: str, *, current_only: str = "true") -> list[int]:
    response = client.get(
        GRANTS_URL,
        {"ordering": ordering, "current_only": current_only, "page_size": "20"},
    )
    assert response.status_code == HTTPStatus.OK, response.content
    payload = cast("dict[str, JsonValue]", response.json())
    data = payload["data"]
    assert isinstance(data, list), payload
    ids: list[int] = []
    for item in data:
        assert isinstance(item, dict), payload
        grant_id = item["id"]
        assert isinstance(grant_id, int)
        ids.append(grant_id)
    return ids


def _assert_unknown(response: _JsonResponse, value: str) -> None:
    assert response.status_code == HTTPStatus.BAD_REQUEST
    payload = cast("dict[str, JsonValue]", response.json())
    error = payload["error"]
    assert isinstance(error, dict)
    assert error["code"] == ErrorCode.VALIDATION_ERROR
    assert error["details"] == {"field": "ordering", "value": value}
