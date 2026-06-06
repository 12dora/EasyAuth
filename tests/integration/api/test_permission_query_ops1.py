from __future__ import annotations

from http import HTTPStatus
from re import escape, findall, search
from typing import TYPE_CHECKING, Protocol

import pytest
from django.test import Client

from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App, Permission, PermissionGroup, Role, RolePermission
from easyauth.applications.services import StaticTokenService
from easyauth.grants.models import (
    GRANT_TYPE_PERMANENT,
    AccessGrant,
    AccessGrantPermission,
    AccessGrantRole,
)

if TYPE_CHECKING:
    from easyauth.api.serializers import PermissionQueryResponsePayload

pytestmark = pytest.mark.django_db


class HttpResponseLike(Protocol):
    status_code: int
    content: bytes


def test_permission_query_excludes_deprecated_permissions_and_group_keys() -> None:
    # Given: 用户授权同时引用 active permission 和已废弃 permission。
    user = UserMirror.objects.create(authentik_user_id="user-api-deprecated-permission")
    app = App.objects.create(app_key="deprecated-api-app", name="Deprecated API App")
    issue = StaticTokenService.create_token(app=app, name="integration")
    group = PermissionGroup.objects.create(app=app, key="PIPELINE_GROUP", name="Pipeline")
    active_permission = Permission.objects.create(
        app=app,
        group=group,
        key="pipeline.active",
        name="Active",
    )
    deprecated_direct = Permission.objects.create(
        app=app,
        group=group,
        key="pipeline.deprecated.direct",
        name="Deprecated Direct",
        is_active=False,
    )
    deprecated_role = Permission.objects.create(
        app=app,
        group=group,
        key="pipeline.deprecated.role",
        name="Deprecated Role",
        is_active=False,
    )
    role = Role.objects.create(app=app, key="operator", name="Operator")
    _ = RolePermission.objects.create(role=role, permission=active_permission)
    _ = RolePermission.objects.create(role=role, permission=deprecated_role)
    grant = AccessGrant.objects.create(user=user, app=app, grant_type=GRANT_TYPE_PERMANENT)
    _ = AccessGrantRole.objects.create(grant=grant, role=role)
    _ = AccessGrantPermission.objects.create(grant=grant, permission=deprecated_direct)

    # When: 应用查询该用户权限。
    response = Client().get(
        _permission_url(app.app_key, user.authentik_user_id),
        HTTP_AUTHORIZATION=_bearer(issue.plaintext_token),
    )

    # Then: 响应只包含 active 叶子权限, 不暴露废弃 permission 或 group key。
    assert response.status_code == HTTPStatus.OK
    payload = _permission_payload(response)
    body = response.content.decode()
    assert payload["permissions"] == ["pipeline.active"]
    assert "pipeline.deprecated.direct" not in body
    assert "pipeline.deprecated.role" not in body
    assert "PIPELINE_GROUP" not in body


def test_permission_query_excludes_inactive_grant_roles_and_their_permissions() -> None:
    # Given: 当前授权绑定 inactive role, 同时包含 direct active permission。
    user = UserMirror.objects.create(authentik_user_id="user-api-inactive-role")
    app = App.objects.create(app_key="inactive-role-api-app", name="Inactive Role API App")
    issue = StaticTokenService.create_token(app=app, name="integration")
    inactive_role = Role.objects.create(
        app=app,
        key="disabled-operator",
        name="Disabled Operator",
        is_active=False,
    )
    direct_permission = Permission.objects.create(
        app=app,
        key="invoice.direct",
        name="Direct invoice permission",
    )
    inactive_role_permission = Permission.objects.create(
        app=app,
        key="invoice.inactive-role",
        name="Inactive role invoice permission",
    )
    _ = RolePermission.objects.create(role=inactive_role, permission=inactive_role_permission)
    grant = AccessGrant.objects.create(user=user, app=app, grant_type=GRANT_TYPE_PERMANENT)
    _ = AccessGrantRole.objects.create(grant=grant, role=inactive_role)
    _ = AccessGrantPermission.objects.create(grant=grant, permission=direct_permission)

    # When: 应用查询该用户权限。
    response = Client().get(
        _permission_url(app.app_key, user.authentik_user_id),
        HTTP_AUTHORIZATION=_bearer(issue.plaintext_token),
    )

    # Then: 响应不暴露 inactive role, 也不通过该 role 展开权限。
    assert response.status_code == HTTPStatus.OK
    payload = _permission_payload(response)
    body = response.content.decode()
    assert payload["roles"] == []
    assert payload["permissions"] == ["invoice.direct"]
    assert "disabled-operator" not in body
    assert "invoice.inactive-role" not in body


def _permission_url(app_key: str, user_id: str) -> str:
    return f"/api/v1/apps/{app_key}/users/{user_id}/permissions"


def _bearer(token: str) -> str:
    return f"Bearer {token}"


def _permission_payload(response: HttpResponseLike) -> PermissionQueryResponsePayload:
    return {
        "user_id": _json_string(response, "user_id"),
        "app_key": _json_string(response, "app_key"),
        "roles": _json_string_array(response, "roles"),
        "permissions": _json_string_array(response, "permissions"),
        "version": _json_int(response, "version"),
        "expires_at": _json_string(response, "expires_at"),
    }


def _json_string(response: HttpResponseLike, key: str) -> str:
    return _json_field_match(response, key, r'"{key}"\s*:\s*"([^"]*)"')


def _json_string_array(response: HttpResponseLike, key: str) -> list[str]:
    array_content = _json_field_match(response, key, r'"{key}"\s*:\s*\[(.*?)\]')
    return findall(r'"([^"]*)"', array_content)


def _json_int(response: HttpResponseLike, key: str) -> int:
    return int(_json_field_match(response, key, r'"{key}"\s*:\s*(\d+)'))


def _json_field_match(response: HttpResponseLike, key: str, pattern: str) -> str:
    match = search(pattern.format(key=escape(key)), response.content.decode())
    if match is None:
        raise AssertionError(response.content.decode())
    return match.group(1)
