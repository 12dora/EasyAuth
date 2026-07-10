from __future__ import annotations

from http import HTTPStatus
from typing import Protocol

import pytest
from django.test import Client
from django.utils import timezone

from easyauth.accounts.models import UserMirror
from easyauth.applications.models import (
    App,
    AppScope,
    AuthorizationGroup,
    AuthorizationGroupGrant,
    Permission,
    PermissionGroup,
)
from easyauth.applications.services import StaticTokenService
from easyauth.grants.models import (
    AccessGrant,
    AccessGrantGroup,
    AccessGrantPermission,
)

pytestmark = pytest.mark.django_db


class HttpResponseLike(Protocol):
    status_code: int
    content: bytes

    def json(self) -> dict[str, object]: ...


def test_permission_query_excludes_deprecated_permissions_and_permission_group_keys() -> None:
    # Given: 用户授权同时引用 active permission 和已废弃 permission。
    user = UserMirror.objects.create(authentik_user_id="user-api-deprecated-permission")
    app = App.objects.create(app_key="deprecated-api-app", name="Deprecated API App")
    _scope(app, "SELF")
    issue = StaticTokenService.create_token(app=app, name="integration")
    permission_group = PermissionGroup.objects.create(
        app=app,
        key="PIPELINE_GROUP",
        name="Pipeline",
    )
    group = AuthorizationGroup.objects.create(app=app, key="operator", kind="role", name="Operator")
    active_permission = Permission.objects.create(
        app=app,
        group=permission_group,
        key="pipeline.active",
        name="Active",
        supported_scopes=["SELF"],
    )
    deprecated_direct = Permission.objects.create(
        app=app,
        group=permission_group,
        key="pipeline.deprecated.direct",
        name="Deprecated Direct",
        supported_scopes=["SELF"],
        deprecated_at=timezone.now(),
    )
    deprecated_group = Permission.objects.create(
        app=app,
        group=permission_group,
        key="pipeline.deprecated.group",
        name="Deprecated Group",
        supported_scopes=["SELF"],
        deprecated_at=timezone.now(),
    )
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=group,
        permission=active_permission,
        scope_key="SELF",
    )
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=group,
        permission=deprecated_group,
        scope_key="SELF",
    )
    grant = AccessGrant.objects.create(user=user, app=app)
    _ = AccessGrantGroup.objects.create(
        grant=grant,
        authorization_group=group,
        expires_at=None,
    )
    _ = AccessGrantPermission.objects.create(
        grant=grant,
        permission=deprecated_direct,
        scope_key="SELF",
        expires_at=None,
    )

    # When: 应用查询该用户权限。
    response = Client().get(
        _permission_url(app.app_key, user.authentik_user_id),
        HTTP_AUTHORIZATION=_bearer(issue.plaintext_token),
    )

    # Then: 响应只包含 active 叶子授权, 不暴露废弃 permission 或 PermissionGroup key。
    assert response.status_code == HTTPStatus.OK
    payload = response.json()
    assert payload["grants"] == [
        {
            "permission": "pipeline.active",
            "scope": "SELF",
            "source_type": "group",
            "source_key": "operator",
        },
    ]
    body = response.content.decode()
    assert "pipeline.deprecated.direct" not in body
    assert "pipeline.deprecated.group" not in body
    assert "PIPELINE_GROUP" not in body


def test_permission_query_excludes_inactive_groups_group_grants_permissions_and_scopes() -> None:
    # Given: 当前授权绑定 inactive group 与 inactive 目录项, 同时包含 direct active grant。
    user = UserMirror.objects.create(authentik_user_id="user-api-inactive-catalog")
    app = App.objects.create(app_key="inactive-catalog-api-app", name="Inactive Catalog API App")
    _scope(app, "SELF")
    _scope(app, "INACTIVE", is_active=False)
    issue = StaticTokenService.create_token(app=app, name="integration")
    active_group = AuthorizationGroup.objects.create(
        app=app,
        key="operator",
        kind="role",
        name="Operator",
    )
    inactive_group = AuthorizationGroup.objects.create(
        app=app,
        key="disabled-operator",
        kind="role",
        name="Disabled Operator",
        is_active=False,
    )
    direct_permission = _permission(app, "invoice.direct", scopes=["SELF"])
    inactive_group_permission = _permission(app, "invoice.inactive-group", scopes=["SELF"])
    inactive_group_grant_permission = _permission(
        app,
        "invoice.inactive-group-grant",
        scopes=["SELF"],
    )
    inactive_permission = _permission(
        app,
        "invoice.inactive-permission",
        scopes=["SELF"],
        is_active=False,
    )
    inactive_scope_permission = _permission(app, "invoice.inactive-scope", scopes=["INACTIVE"])
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=inactive_group,
        permission=inactive_group_permission,
        scope_key="SELF",
    )
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=active_group,
        permission=inactive_group_grant_permission,
        scope_key="SELF",
        is_active=False,
    )
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=active_group,
        permission=inactive_permission,
        scope_key="SELF",
    )
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=active_group,
        permission=inactive_scope_permission,
        scope_key="INACTIVE",
    )
    grant = AccessGrant.objects.create(user=user, app=app)
    _ = AccessGrantGroup.objects.create(
        grant=grant,
        authorization_group=active_group,
        expires_at=None,
    )
    _ = AccessGrantGroup.objects.create(
        grant=grant,
        authorization_group=inactive_group,
        expires_at=None,
    )
    _ = AccessGrantPermission.objects.create(
        grant=grant,
        permission=direct_permission,
        scope_key="SELF",
        expires_at=None,
    )
    _ = AccessGrantPermission.objects.create(
        grant=grant,
        permission=inactive_permission,
        scope_key="SELF",
        expires_at=None,
    )
    _ = AccessGrantPermission.objects.create(
        grant=grant,
        permission=inactive_scope_permission,
        scope_key="INACTIVE",
        expires_at=None,
    )

    # When: 应用查询该用户权限。
    response = Client().get(
        _permission_url(app.app_key, user.authentik_user_id),
        HTTP_AUTHORIZATION=_bearer(issue.plaintext_token),
    )

    # Then: 响应不暴露 inactive 目录项, 也不通过它们展开权限。
    assert response.status_code == HTTPStatus.OK
    payload = response.json()
    assert payload["groups"] == [{"key": "operator", "kind": "role", "name": "Operator"}]
    assert payload["grants"] == [
        {
            "permission": "invoice.direct",
            "scope": "SELF",
            "source_type": "direct",
            "source_key": "",
        },
    ]
    body = response.content.decode()
    assert "disabled-operator" not in body
    assert "invoice.inactive-group" not in body
    assert "invoice.inactive-group-grant" not in body
    assert "invoice.inactive-permission" not in body
    assert "invoice.inactive-scope" not in body


def test_permission_query_returns_empty_snake_case_snapshot_without_envelope() -> None:
    # Given: 用户有 App 级授权快照, 但没有任何授权组或直授权限。
    user = UserMirror.objects.create(authentik_user_id="user-api-empty-grants")
    app = App.objects.create(app_key="empty-grants-api-app", name="Empty Grants API App")
    issue = StaticTokenService.create_token(app=app, name="integration")
    _ = AccessGrant.objects.create(user=user, app=app)

    # When: 应用查询该用户权限。
    response = Client().get(
        _permission_url(app.app_key, user.authentik_user_id),
        HTTP_AUTHORIZATION=_bearer(issue.plaintext_token),
    )

    # Then: 公共 API 保持统一 snake_case 契约, 空授权不包专用 envelope。
    assert response.status_code == HTTPStatus.OK
    payload = response.json()
    assert set(payload) == {
        "user_id",
        "app_key",
        "groups",
        "grants",
        "grant_version",
        "catalog_version",
        "snapshot_version",
        "expires_at",
    }
    assert payload["user_id"] == user.authentik_user_id
    assert payload["app_key"] == app.app_key
    assert payload["groups"] == []
    assert payload["grants"] == []
    assert payload["grant_version"] == 1
    assert payload["catalog_version"] == 1
    assert payload["snapshot_version"] == "1.1.0"
    assert isinstance(payload["expires_at"], str)
    assert "userId" not in payload
    assert "appKey" not in payload
    assert "expiresAt" not in payload
    assert "version" not in payload
    assert "data" not in payload
    assert "result" not in payload


def _permission_url(app_key: str, user_id: str) -> str:
    return f"/api/v1/apps/{app_key}/users/{user_id}/permissions"


def _bearer(token: str) -> str:
    return f"Bearer {token}"


def _scope(app: App, key: str, *, is_active: bool = True) -> AppScope:
    return AppScope.objects.create(app=app, key=key, name=key.title(), is_active=is_active)


def _permission(
    app: App,
    key: str,
    *,
    scopes: list[str],
    is_active: bool = True,
) -> Permission:
    return Permission.objects.create(
        app=app,
        key=key,
        name=key,
        supported_scopes=scopes,
        is_active=is_active,
    )
