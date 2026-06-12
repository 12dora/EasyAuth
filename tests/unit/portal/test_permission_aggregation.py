from __future__ import annotations

import pytest
from django.utils import timezone

from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App, Permission, Role, RolePermission
from easyauth.grants.models import AccessGrant, AccessGrantPermission, AccessGrantRole
from easyauth.portal.api_data import current_grant_items_for_user
from easyauth.portal.grant_rows import current_grant_rows_for_user
from easyauth.portal.permission_aggregation import (
    direct_permission_keys_by_grant_id,
    permission_keys,
)

pytestmark = pytest.mark.django_db


def test_direct_permission_keys_by_grant_id_prefills_empty_sets_for_each_input_grant_id() -> None:
    # Given: 调用方传入没有 direct Permission 关联的 grant id。
    grant_ids = (101, 202, 303)

    # When: 聚合 direct Permission。
    keys_by_grant_id = direct_permission_keys_by_grant_id(grant_ids)

    # Then: 每个输入 grant id 都有稳定的空 set 结果。
    assert keys_by_grant_id == {101: set(), 202: set(), 303: set()}


def test_current_permission_api_excludes_inactive_and_deprecated_permissions() -> None:
    # Given: 当前授权包含 active、inactive 和 deprecated direct Permission。
    user, app, grant = _create_current_grant("portal-active-only-api")
    active_permission = Permission.objects.create(
        app=app,
        key="invoice.active",
        name="有效权限",
    )
    inactive_permission = Permission.objects.create(
        app=app,
        key="invoice.inactive",
        name="停用权限",
        is_active=False,
    )
    deprecated_permission = Permission.objects.create(
        app=app,
        key="invoice.deprecated",
        name="废弃权限",
        deprecated_at=timezone.now(),
    )
    _ = AccessGrantPermission.objects.create(grant=grant, permission=active_permission)
    _ = AccessGrantPermission.objects.create(grant=grant, permission=inactive_permission)
    _ = AccessGrantPermission.objects.create(grant=grant, permission=deprecated_permission)

    # When: 当前权限 API 聚合授权项。
    item = current_grant_items_for_user(user)[0]

    # Then: API 只返回当前有效权限。
    assert item["permissions"] == [active_permission.key]


def test_current_grant_rows_keep_inactive_and_deprecated_permissions_for_history_display() -> None:
    # Given: 历史展示行需要保留当前授权上已经停用或废弃的 direct Permission。
    user, app, grant = _create_current_grant("portal-history-rows")
    inactive_permission = Permission.objects.create(
        app=app,
        key="invoice.inactive",
        name="停用权限",
        is_active=False,
    )
    deprecated_permission = Permission.objects.create(
        app=app,
        key="invoice.deprecated",
        name="废弃权限",
        deprecated_at=timezone.now(),
    )
    _ = AccessGrantPermission.objects.create(grant=grant, permission=inactive_permission)
    _ = AccessGrantPermission.objects.create(grant=grant, permission=deprecated_permission)

    # When: 门户授权行聚合展示权限。
    row = current_grant_rows_for_user(user)[0]

    # Then: row 展示保留历史权限 key。
    assert row.permission_keys == "invoice.deprecated、invoice.inactive"


def test_permission_keys_deduplicates_role_and_direct_permissions_and_sorts_by_key() -> None:
    # Given: role 派生权限和 direct Permission 存在重复, 且输入顺序不是字典序。
    role_ids = (30, 20)
    direct_keys = {"billing.write", "billing.read"}
    role_keys_by_role_id = {
        20: {"billing.approve", "billing.write"},
        30: {"billing.read", "billing.export"},
    }

    # When: 聚合最终权限 key。
    keys = permission_keys(
        direct_permission_keys=direct_keys,
        role_ids=role_ids,
        role_permission_keys_by_role_id=role_keys_by_role_id,
    )

    # Then: 重复 key 只出现一次, 且输出按 permission key 排序。
    assert keys == (
        "billing.approve",
        "billing.export",
        "billing.read",
        "billing.write",
    )


def test_current_grant_rows_keep_inactive_role_permissions_for_history_display() -> None:
    # Given: 历史展示行需要保留 inactive Role 派生的历史权限。
    user, app, grant = _create_current_grant("portal-history-role-rows")
    inactive_role = Role.objects.create(
        app=app,
        key="inactive-role",
        name="停用角色",
        is_active=False,
    )
    inactive_role_permission = Permission.objects.create(
        app=app,
        key="role.inactive",
        name="停用角色权限",
        is_active=False,
    )
    _ = RolePermission.objects.create(role=inactive_role, permission=inactive_role_permission)
    _ = AccessGrantRole.objects.create(grant=grant, role=inactive_role)

    # When: 门户授权行聚合展示权限。
    row = current_grant_rows_for_user(user)[0]

    # Then: row 展示保留 inactive Role 的历史权限 key。
    assert row.permission_keys == inactive_role_permission.key


def _create_current_grant(key_suffix: str) -> tuple[UserMirror, App, AccessGrant]:
    user = UserMirror.objects.create(authentik_user_id=f"{key_suffix}-user", name="门户用户")
    app = App.objects.create(app_key=f"{key_suffix}-app", name="门户应用")
    grant = AccessGrant.objects.create(user=user, app=app)
    return user, app, grant
