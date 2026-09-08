from __future__ import annotations

from http import HTTPStatus
from json import dumps
from typing import Final, cast

import pytest
from django.test import Client

from easyauth.accounts.models import UserMirror
from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.applications.builtin_authorization_groups import (
    RESERVED_AUTHORIZATION_GROUP_REASON,
    ensure_builtin_super_admin,
)
from easyauth.applications.models import (
    App,
    AppMembership,
    AppScope,
    AuthorizationGroupGrant,
    Permission,
)
from easyauth.applications.models.constants import BUILTIN_SUPER_ADMIN_GROUP_KEY
from easyauth.grants.models import AccessGrant, AccessGrantGroup
from easyauth.grants.query import ExpandedGrant, GroupSnapshot, resolve_user_permissions
from tests.integration.admin_console.auth_helpers import authenticate_console_admin
from tests.integration.portal.helpers import logged_in_client
from tests.integration.portal.json_helpers import json_object

pytestmark = pytest.mark.django_db

GRANT_CATALOG_API_URL: Final = "/console/api/v1/grant-catalog"
REQUEST_CATALOG_URL: Final = "/portal/api/v1/request-catalog"


def test_console_grant_catalog_lists_super_admin_and_portal_catalog_hides_it() -> None:
    console = _logged_in_superuser("builtin-sa-catalog-admin")
    portal, _user = logged_in_client("builtin-sa-catalog-portal")
    app = _catalog_app("builtin-sa-catalog")
    group = ensure_builtin_super_admin(app)
    permission = Permission.objects.get(app=app, key="invoice.read")

    console_response = console.get(GRANT_CATALOG_API_URL)
    portal_response = portal.get(REQUEST_CATALOG_URL)

    console_payload = cast("dict[str, JsonValue]", console_response.json())
    console_groups = cast("list[dict[str, JsonValue]]", console_payload["authorization_groups"])
    super_admin = next(item for item in console_groups if item["key"] == group.key)
    portal_payload = json_object(portal_response)
    portal_groups = cast("list[dict[str, JsonValue]]", portal_payload["authorization_groups"])
    assert console_response.status_code == HTTPStatus.OK
    assert super_admin["requestable"] is False
    assert super_admin["name"] == group.name
    assert super_admin["grants"] == [
        {"permission_key": permission.key, "scope_key": "GLOBAL"},
        {"permission_key": permission.key, "scope_key": "TEAM"},
        {"permission_key": "invoice.write", "scope_key": "GLOBAL"},
    ]
    assert portal_response.status_code == HTTPStatus.OK
    assert all(item["key"] != BUILTIN_SUPER_ADMIN_GROUP_KEY for item in portal_groups)
    assert BUILTIN_SUPER_ADMIN_GROUP_KEY not in portal_response.content.decode()


def test_resolve_user_permissions_expands_every_super_admin_grant() -> None:
    user = UserMirror.objects.create(authentik_user_id="builtin-sa-holder")
    app = _catalog_app("builtin-sa-resolve")
    group = ensure_builtin_super_admin(app)
    grant = AccessGrant.objects.create(user=user, app=app)
    _ = AccessGrantGroup.objects.create(grant=grant, authorization_group=group, expires_at=None)

    snapshot = resolve_user_permissions(user=user, app=app)

    assert snapshot.groups == (
        GroupSnapshot(
            key=BUILTIN_SUPER_ADMIN_GROUP_KEY,
            kind="role",
            name="超级管理员",
            expires_at=None,
        ),
    )
    assert snapshot.grants == (
        ExpandedGrant("invoice.read", "GLOBAL", "group", BUILTIN_SUPER_ADMIN_GROUP_KEY, None),
        ExpandedGrant("invoice.read", "TEAM", "group", BUILTIN_SUPER_ADMIN_GROUP_KEY, None),
        ExpandedGrant("invoice.write", "GLOBAL", "group", BUILTIN_SUPER_ADMIN_GROUP_KEY, None),
    )


def test_console_rejects_reserved_authorization_group_mutations() -> None:
    client = _logged_in_owner("builtin-sa-write-owner")
    app = _member_app("builtin-sa-write", "builtin-sa-write-owner")
    group = ensure_builtin_super_admin(app)
    _ = AppScope.objects.create(app=app, key="GLOBAL", name="全局")
    permission = Permission.objects.create(
        app=app,
        key="invoice.read",
        name="查看发票",
        supported_scopes=["GLOBAL"],
    )
    create = client.post(
        _authorization_groups_url(app.app_key),
        data=dumps(
            {
                "key": BUILTIN_SUPER_ADMIN_GROUP_KEY,
                "kind": "role",
                "name": "伪造超管",
                "grants": [{"permission": permission.key, "scope": "GLOBAL"}],
            },
        ),
        content_type="application/json",
    )
    deactivate = client.patch(
        _authorization_group_detail_url(app.app_key, group.key),
        data=dumps(
            {
                "key": group.key,
                "kind": "role",
                "name": group.name,
                "is_active": False,
                "grants": [],
            },
        ),
        content_type="application/json",
    )
    rename = client.patch(
        _authorization_group_detail_url(app.app_key, group.key),
        data=dumps(
            {
                "key": "not-super-admin",
                "kind": "role",
                "name": group.name,
                "grants": [],
            },
        ),
        content_type="application/json",
    )

    group.refresh_from_db()
    assert create.status_code == HTTPStatus.BAD_REQUEST
    assert create.json()["error"]["code"] == ErrorCode.VALIDATION_ERROR
    assert create.json()["error"]["details"]["reason"] == RESERVED_AUTHORIZATION_GROUP_REASON
    assert deactivate.status_code == HTTPStatus.BAD_REQUEST
    assert deactivate.json()["error"]["details"]["reason"] == RESERVED_AUTHORIZATION_GROUP_REASON
    assert rename.status_code == HTTPStatus.BAD_REQUEST
    assert rename.json()["error"]["details"]["reason"] == RESERVED_AUTHORIZATION_GROUP_REASON
    assert group.key == BUILTIN_SUPER_ADMIN_GROUP_KEY
    assert group.is_active is True


def test_console_permission_write_resyncs_super_admin_grants() -> None:
    client = _logged_in_owner("builtin-sa-perm-owner")
    app = _member_app("builtin-sa-perm", "builtin-sa-perm-owner")
    group = ensure_builtin_super_admin(app)
    _ = AppScope.objects.create(app=app, key="GLOBAL", name="全局")

    created = client.post(
        f"/console/api/v1/apps/{app.app_key}/permissions",
        data=dumps(
            {
                "key": "invoice.read",
                "name": "查看发票",
                "supported_scopes": ["GLOBAL"],
            },
        ),
        content_type="application/json",
    )

    permission = Permission.objects.get(app=app, key="invoice.read")
    assert created.status_code == HTTPStatus.CREATED
    assert AuthorizationGroupGrant.objects.filter(
        authorization_group=group,
        permission=permission,
        scope_key="GLOBAL",
        is_active=True,
    ).exists()


def _catalog_app(app_key: str) -> App:
    app = App.objects.create(app_key=app_key, name=app_key)
    _ = AppScope.objects.create(app=app, key="GLOBAL", name="全局")
    _ = AppScope.objects.create(app=app, key="TEAM", name="团队")
    _ = Permission.objects.create(
        app=app,
        key="invoice.read",
        name="查看发票",
        supported_scopes=["GLOBAL", "TEAM"],
    )
    _ = Permission.objects.create(
        app=app,
        key="invoice.write",
        name="开具发票",
        supported_scopes=["GLOBAL"],
    )
    return app


def _member_app(app_key: str, username: str) -> App:
    app = App.objects.create(app_key=app_key, name=app_key)
    _ = AppMembership.objects.create(app=app, user_id=username, role="owner")
    return app


def _authorization_groups_url(app_key: str) -> str:
    return f"/console/api/v1/apps/{app_key}/authorization-groups"


def _authorization_group_detail_url(app_key: str, authorization_group_key: str) -> str:
    return f"{_authorization_groups_url(app_key)}/{authorization_group_key}"


def _logged_in_superuser(username: str) -> Client:
    client = Client(HTTP_HOST="localhost")
    return authenticate_console_admin(client, username)


def _logged_in_owner(username: str) -> Client:
    _ = UserMirror.objects.get_or_create(authentik_user_id=username)
    client = Client(HTTP_HOST="localhost")
    return authenticate_console_admin(client, username)
