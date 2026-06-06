from __future__ import annotations

from http import HTTPStatus
from json import dumps
from re import escape, search
from typing import Final

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.utils import timezone

from easyauth.api.errors import ErrorCode
from easyauth.applications.models import (
    App,
    AppMembership,
    Permission,
    PermissionGroup,
    Role,
    RolePermission,
)
from easyauth.audit.models import AuditLog

pytestmark = pytest.mark.django_db

LOGIN_VALUE: Final = "console-matrix-contract"


def test_matrix_get_keeps_legacy_fields_and_adds_tree_assignments_contract() -> None:
    # Given: owner 管理一个带权限分组和 RolePermission 的 App。
    client = _logged_in_user("matrix-contract-read")
    app = _member_app("matrix-contract-read", "matrix-contract-read")
    role = Role.objects.create(app=app, key="sales_manager", name="销售经理")
    group = PermissionGroup.objects.create(app=app, key="CUSTOMER_GROUP", name="客户")
    permission = Permission.objects.create(
        app=app,
        group=group,
        key="customer:view:department",
        name="查看部门客户",
    )
    _ = RolePermission.objects.create(role=role, permission=permission)

    # When: owner 读取矩阵。
    response = client.get(_api_url(app.app_key))

    # Then: 响应保留旧字段, 并补齐 permission_tree 和 key-based assignments。
    body = response.content.decode()
    assert response.status_code == HTTPStatus.OK
    assert _json_string(body, "version") != ""
    assert '"permissions": [' in body
    assert '"cells": [' in body
    assert '"enabled": true' in body
    assert '"permission_tree": [' in body
    assert f'"key": "{group.key}"' in body
    assert '"assignments": [' in body
    assert f'"role_key": "{role.key}"' in body
    assert f'"permission_key": "{permission.key}"' in body


def test_matrix_patch_accepts_key_based_diff_and_rejects_stale_base_version() -> None:
    # Given: owner 打开当前矩阵版本, App 已有一个旧授权并准备新增一个授权。
    client = _logged_in_user("matrix-contract-patch")
    app = _member_app("matrix-contract-patch", "matrix-contract-patch")
    role = Role.objects.create(app=app, key="sales_manager", name="销售经理")
    old_permission = Permission.objects.create(
        app=app,
        key="customer:delete:any",
        name="删除任意客户",
    )
    new_permission = Permission.objects.create(
        app=app,
        key="customer:edit:own",
        name="编辑自己的客户",
    )
    _ = RolePermission.objects.create(role=role, permission=old_permission)
    initial = client.get(_api_url(app.app_key))
    initial_version = _json_string(initial.content.decode(), "version")

    # When: owner 使用 key-based diff 新增/删除 RolePermission, 随后用旧 base_version 再次提交。
    accepted = client.patch(
        _api_url(app.app_key),
        data=dumps(
            {
                "base_version": initial_version,
                "add": [{"role_key": role.key, "permission_key": new_permission.key}],
                "remove": [{"role_key": role.key, "permission_key": old_permission.key}],
            },
        ),
        content_type="application/json",
    )
    stale = client.patch(
        _api_url(app.app_key),
        data=dumps(
            {
                "base_version": initial_version,
                "remove": [{"role_key": role.key, "permission_key": new_permission.key}],
            },
        ),
        content_type="application/json",
    )

    # Then: 首次提交按 key 差异更新矩阵, 旧 base_version 保持现有 409 冲突语义。
    assert accepted.status_code == HTTPStatus.OK
    assert RolePermission.objects.filter(role=role, permission=new_permission).exists() is True
    assert RolePermission.objects.filter(role=role, permission=old_permission).exists() is False
    assert AuditLog.objects.filter(event_type="role_permission_matrix_changed").exists() is True
    assert stale.status_code == HTTPStatus.CONFLICT
    assert "CONFLICT" in stale.content.decode()


@pytest.mark.parametrize("payload_mode", ["assignments", "add"])
def test_matrix_patch_rejects_deprecated_permission_even_when_active(
    payload_mode: str,
) -> None:
    # Given: owner 面对一个历史异常状态的 active deprecated Permission。
    client = _logged_in_user(f"matrix-contract-deprecated-{payload_mode}")
    app_key = f"matrix-contract-deprecated-{payload_mode}"
    app = _member_app(app_key, app_key)
    role = Role.objects.create(app=app, key="sales_manager", name="销售经理")
    permission = Permission.objects.create(
        app=app,
        key="legacy:read",
        name="旧权限",
        is_active=True,
        deprecated_at=timezone.now(),
        deprecated_reason="改用 report.read",
    )
    initial = client.get(_api_url(app.app_key))
    initial_version = _json_string(initial.content.decode(), "version")

    # When: owner 尝试通过 id 或 key matrix diff 重新加入已废弃权限。
    response = client.patch(
        _api_url(app.app_key),
        data=dumps(
            _deprecated_permission_payload(payload_mode, initial_version, role, permission),
        ),
        content_type="application/json",
    )

    # Then: API 拒绝该权限, 不创建 RolePermission 或审计。
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert ErrorCode.VALIDATION_ERROR in response.content.decode()
    assert RolePermission.objects.filter(role=role, permission=permission).exists() is False
    assert AuditLog.objects.count() == 0


def _member_app(app_key: str, username: str) -> App:
    app = App.objects.create(app_key=app_key, name=app_key)
    _ = AppMembership.objects.create(app=app, user_id=username, role="owner")
    return app


def _api_url(app_key: str) -> str:
    return f"/console/api/v1/apps/{app_key}/role-permission-matrix"


def _json_string(body: str, key: str) -> str:
    match = search(rf'"{escape(key)}"\s*:\s*"([^"]*)"', body)
    if match is None:
        raise AssertionError(body)
    return match.group(1)


def _deprecated_permission_payload(
    payload_mode: str,
    initial_version: str,
    role: Role,
    permission: Permission,
) -> dict[str, str | list[dict[str, str | int | bool]]]:
    match payload_mode:
        case "assignments":
            return {
                "base_version": initial_version,
                "assignments": [
                    {"role_id": role.id, "permission_id": permission.id, "enabled": True},
                ],
            }
        case "add":
            return {
                "base_version": initial_version,
                "add": [{"role_key": role.key, "permission_key": permission.key}],
            }
        case unreachable:
            raise AssertionError(unreachable)


def _logged_in_user(username: str) -> Client:
    _ = User.objects.create_user(username=username, password=LOGIN_VALUE)
    client = Client(HTTP_HOST="localhost")
    assert client.login(username=username, password=LOGIN_VALUE) is True
    return client
