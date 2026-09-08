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
    AuthorizationGroup,
    AuthorizationGroupGrant,
    ManagedScopePolicy,
    Permission,
)
from easyauth.applications.models.constants import BUILTIN_SUPER_ADMIN_GROUP_KEY
from easyauth.grants.models import AccessGrant, AccessGrantGroup
from easyauth.grants.query import ExpandedGrant, GroupSnapshot, resolve_user_permissions
from tests.integration.admin_console.auth_helpers import (
    authenticate_console_admin,
    authenticate_console_user,
)
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


def test_console_allows_builtin_managed_scope_policy_override() -> None:
    client = _logged_in_owner("builtin-sa-policy-owner")
    app = _member_app("builtin-sa-policy", "builtin-sa-policy-owner")
    _ = AppScope.objects.create(app=app, key="MANAGED_USERS", name="被管理人员")
    permission = Permission.objects.create(
        app=app,
        key="invoice.delegate",
        name="代开发票",
        supported_scopes=["MANAGED_USERS"],
    )
    group = ensure_builtin_super_admin(app)
    app.refresh_from_db()
    version = app.catalog_version

    patched = client.patch(
        _authorization_group_detail_url(app.app_key, group.key),
        data=dumps(
            _locked_group_body(
                group,
                [
                    {
                        "permission": permission.key,
                        "scope": "MANAGED_USERS",
                        "is_active": True,
                        "managed_scope_policy": {
                            "mode": "override",
                            "resolver": "dingtalk_manager_chain",
                            "enabled": True,
                        },
                    },
                ],
            ),
        ),
        content_type="application/json",
    )

    grant = AuthorizationGroupGrant.objects.get(
        authorization_group=group,
        permission=permission,
        scope_key="MANAGED_USERS",
    )
    policy = ManagedScopePolicy.objects.get(
        app=app,
        target_type="authorization_group_grant",
        authorization_group_grant=grant,
        scope="MANAGED_USERS",
    )
    group.refresh_from_db()
    app.refresh_from_db()
    assert patched.status_code == HTTPStatus.OK
    assert policy.resolver == "dingtalk_manager_chain"
    assert policy.enabled is True
    assert group.name == "超级管理员"
    assert group.requestable is False
    assert app.catalog_version == version + 1

    extra = client.post(
        f"/console/api/v1/apps/{app.app_key}/permissions",
        data=dumps(
            {
                "key": "invoice.read",
                "name": "查看发票",
                "supported_scopes": ["MANAGED_USERS"],
            },
        ),
        content_type="application/json",
    )
    policy.refresh_from_db()
    grant.refresh_from_db()
    app.refresh_from_db()
    assert extra.status_code == HTTPStatus.CREATED
    assert policy.resolver == "dingtalk_manager_chain"
    assert grant.is_active is True
    assert app.catalog_version == version + 2


def test_console_rejects_builtin_grant_membership_change() -> None:
    client = _logged_in_owner("builtin-sa-membership-owner")
    app = _member_app("builtin-sa-membership", "builtin-sa-membership-owner")
    _ = AppScope.objects.create(app=app, key="GLOBAL", name="全局")
    permission = Permission.objects.create(
        app=app,
        key="invoice.read",
        name="查看发票",
        supported_scopes=["GLOBAL"],
    )
    group = ensure_builtin_super_admin(app)
    extra = Permission.objects.create(
        app=app,
        key="invoice.write",
        name="开具发票",
        supported_scopes=["GLOBAL"],
    )

    added = client.patch(
        _authorization_group_detail_url(app.app_key, group.key),
        data=dumps(
            _locked_group_body(
                group,
                [
                    {
                        "permission": permission.key,
                        "scope": "GLOBAL",
                        "is_active": True,
                    },
                    {
                        "permission": extra.key,
                        "scope": "GLOBAL",
                        "is_active": True,
                    },
                ],
            ),
        ),
        content_type="application/json",
    )
    deactivated = client.patch(
        _authorization_group_detail_url(app.app_key, group.key),
        data=dumps(
            _locked_group_body(
                group,
                [
                    {
                        "permission": permission.key,
                        "scope": "GLOBAL",
                        "is_active": False,
                    },
                ],
            ),
        ),
        content_type="application/json",
    )

    group.refresh_from_db()
    assert added.status_code == HTTPStatus.BAD_REQUEST
    assert added.json()["error"]["details"]["reason"] == RESERVED_AUTHORIZATION_GROUP_REASON
    assert deactivated.status_code == HTTPStatus.BAD_REQUEST
    assert deactivated.json()["error"]["details"]["reason"] == RESERVED_AUTHORIZATION_GROUP_REASON
    assert not AuthorizationGroupGrant.objects.filter(
        authorization_group=group,
        permission=extra,
    ).exists()
    assert AuthorizationGroupGrant.objects.get(
        authorization_group=group,
        permission=permission,
        scope_key="GLOBAL",
    ).is_active is True


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
    app.refresh_from_db()
    assert created.status_code == HTTPStatus.CREATED
    assert app.catalog_version == 2
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
    client = Client(HTTP_HOST="localhost")
    return authenticate_console_user(client, username)


def _locked_group_body(
    group: AuthorizationGroup,
    grants: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "key": group.key,
        "kind": group.kind,
        "name": group.name,
        "name_en": group.name_en,
        "description": group.description,
        "description_en": group.description_en,
        "requestable": group.requestable,
        "is_active": group.is_active,
        "grants": grants,
    }
