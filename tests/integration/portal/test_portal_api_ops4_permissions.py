from __future__ import annotations

from datetime import timedelta
from http import HTTPStatus
from json import dumps
from typing import Final

import pytest
from django.test import Client
from django.utils import timezone

from easyauth.accounts.auth import AUTHENTIK_SESSION_KEY
from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.applications.models import App, ApprovalRule, Permission, Role, RolePermission
from easyauth.grants.models import (
    GRANT_TYPE_TIMED,
    AccessGrant,
    AccessGrantPermission,
    AccessGrantRole,
)
from tests.integration.portal.json_helpers import json_object

pytestmark = pytest.mark.django_db

GRANTS_API_URL: Final = "/portal/api/v1/me/grants"
REQUESTS_API_URL: Final = "/portal/api/v1/me/access-requests"


def test_ops4_portal_api_lists_access_request_direct_permissions() -> None:
    # Given: 当前员工提交了只包含 direct Permission 目标的 change 申请。
    client, user = _logged_in_client("ops4-list-request-permission-user")
    app = App.objects.create(app_key="ops4-list-request-permission", name="OPS4 List Permission")
    old_permission = _requestable_permission(app=app, key="invoice.read")
    new_permission = _requestable_permission(app=app, key="invoice.write")
    current_grant = AccessGrant.objects.create(user=user, app=app)
    _ = AccessGrantPermission.objects.create(grant=current_grant, permission=old_permission)
    post_response = client.post(
        REQUESTS_API_URL,
        data=dumps(
            {
                "app_key": app.app_key,
                "request_type": "change",
                "role_keys": [],
                "permission_keys": [new_permission.key],
                "grant_type": GRANT_TYPE_TIMED,
                "grant_expires_at": (timezone.now() + timedelta(days=30)).isoformat(),
                "reason": "提交 direct permission 申请",
            },
        ),
        content_type="application/json",
    )

    # When: 员工查询自己的申请列表。
    response = client.get(REQUESTS_API_URL)

    # Then: 列表项保留 direct Permission key 与名称。
    items = json_object(response)["items"]
    assert isinstance(items, list), response.content.decode()
    item = items[0]
    assert isinstance(item, dict), response.content.decode()
    assert post_response.status_code == HTTPStatus.CREATED
    assert response.status_code == HTTPStatus.OK
    assert item["permissions"] == [new_permission.key]
    assert item["permission_names"] == [new_permission.name]
    assert item["roles"] == []


def test_ops4_portal_api_hides_inactive_role_and_derived_permissions() -> None:
    # Given: 当前员工授权同时绑定 active Role、inactive Role 和 direct Permission。
    client, user = _logged_in_client("ops4-grants-inactive-role-user")
    app = App.objects.create(app_key="ops4-grants-inactive-role", name="OPS4 Inactive Role")
    active_role = Role.objects.create(app=app, key="active-role", name="有效角色")
    inactive_role = Role.objects.create(
        app=app,
        key="inactive-role",
        name="停用角色",
        is_active=False,
    )
    active_permission = Permission.objects.create(app=app, key="active.read", name="有效权限")
    inactive_role_permission = Permission.objects.create(
        app=app,
        key="inactive-role.read",
        name="停用角色派生权限",
    )
    direct_permission = Permission.objects.create(app=app, key="direct.read", name="直接权限")
    _ = RolePermission.objects.create(role=active_role, permission=active_permission)
    _ = RolePermission.objects.create(role=inactive_role, permission=inactive_role_permission)
    grant = AccessGrant.objects.create(user=user, app=app)
    _ = AccessGrantRole.objects.create(grant=grant, role=active_role)
    _ = AccessGrantRole.objects.create(grant=grant, role=inactive_role)
    _ = AccessGrantPermission.objects.create(grant=grant, permission=direct_permission)

    # When: 员工读取自己的当前授权 API。
    response = client.get(GRANTS_API_URL)

    # Then: 响应不返回 inactive Role, 也不返回 inactive Role 派生权限。
    items = json_object(response)["items"]
    assert isinstance(items, list), response.content.decode()
    item = items[0]
    assert isinstance(item, dict), response.content.decode()
    assert response.status_code == HTTPStatus.OK
    assert item["roles"] == [active_role.key]
    assert item["role_names"] == [active_role.name]
    assert item["permissions"] == [active_permission.key, direct_permission.key]


def _logged_in_client(authentik_user_id: str) -> tuple[Client, UserMirror]:
    client = Client()
    user = UserMirror.objects.create(
        authentik_user_id=authentik_user_id,
        name="门户用户",
        status=USER_STATUS_ACTIVE,
    )
    session = client.session
    session[AUTHENTIK_SESSION_KEY] = user.authentik_user_id
    session.save()
    return client, user


def _requestable_permission(*, app: App, key: str) -> Permission:
    permission = Permission.objects.create(app=app, key=key, name=key)
    _ = ApprovalRule.objects.create(
        app=app,
        permission=permission,
        approver_userids=["manager-001"],
    )
    return permission
