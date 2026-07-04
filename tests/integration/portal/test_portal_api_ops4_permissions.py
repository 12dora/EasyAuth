from __future__ import annotations

from datetime import timedelta
from http import HTTPStatus
from json import dumps
from typing import Final

import pytest
from django.utils import timezone

from easyauth.access_requests.models import AccessRequest, AccessRequestPermission
from easyauth.applications.models import (
    App,
    AppScope,
    AuthorizationGroup,
    AuthorizationGroupGrant,
    Permission,
)
from easyauth.grants.models import (
    GRANT_TYPE_TIMED,
    AccessGrant,
    AccessGrantGroup,
    AccessGrantPermission,
)
from tests.integration.portal.helpers import logged_in_client
from tests.integration.portal.json_helpers import json_object

pytestmark = pytest.mark.django_db

GRANTS_API_URL: Final = "/portal/api/v1/me/grants"
REQUESTS_API_URL: Final = "/portal/api/v1/me/access-requests"
DEFAULT_SCOPE_KEY: Final = "GLOBAL"


def test_ops4_portal_api_submits_grant_request_with_direct_permission_without_rule() -> None:
    # Given: 当前员工还没有授权, 目标 direct Permission 没有配置审批规则。
    client, user = logged_in_client("ops4-grant-direct-permission-user")
    app = App.objects.create(app_key="ops4-grant-direct-permission", name="OPS4 Grant Permission")
    permission = _requestable_permission(app=app, key="invoice.read")

    # When: 员工提交 direct Permission 授权申请。
    response = client.post(
        REQUESTS_API_URL,
        data=dumps(
            {
                "app_key": app.app_key,
                "request_type": "grant",
                "authorization_group_keys": [],
                "direct_grants": [{"permission": permission.key, "scope": DEFAULT_SCOPE_KEY}],
                "approver_user_ids": [user.authentik_user_id],
                "grant_type": "permanent",
                "grant_expires_at": None,
                "reason": "申请 direct permission",
            },
        ),
        content_type="application/json",
    )

    # Then: API 创建 grant 申请并保留 permission 目标。
    access_request = AccessRequest.objects.get(user=user, app=app)
    permission_keys = tuple(
        AccessRequestPermission.objects.filter(access_request=access_request).values_list(
            "permission__key",
            flat=True,
        ),
    )
    scope_keys = tuple(
        AccessRequestPermission.objects.filter(access_request=access_request).values_list(
            "scope_key",
            flat=True,
        ),
    )
    assert response.status_code == HTTPStatus.CREATED
    assert access_request.request_type == "grant"
    assert access_request.approver_user_ids == [user.authentik_user_id]
    assert permission_keys == (permission.key,)
    assert scope_keys == (DEFAULT_SCOPE_KEY,)


def test_ops4_portal_api_rejects_access_request_without_approver() -> None:
    # Given: direct Permission 本身可申请。
    client, user = logged_in_client("ops4-grant-missing-approver-user")
    app = App.objects.create(app_key="ops4-grant-missing-approver", name="OPS4 Missing Approver")
    permission = _requestable_permission(app=app, key="invoice.read")

    # When: 员工提交时没有提供审批人。
    response = client.post(
        REQUESTS_API_URL,
        data=dumps(
            {
                "app_key": app.app_key,
                "request_type": "grant",
                "authorization_group_keys": [],
                "direct_grants": [{"permission": permission.key, "scope": DEFAULT_SCOPE_KEY}],
                "approver_user_ids": [],
                "grant_type": "permanent",
                "grant_expires_at": None,
                "reason": "申请 direct permission",
            },
        ),
        content_type="application/json",
    )

    # Then: API 拒绝提交, 不创建申请。
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert AccessRequest.objects.filter(user=user, app=app).exists() is False


def test_ops4_portal_api_lists_access_request_direct_permissions() -> None:
    # Given: 当前员工提交了只包含 direct Permission 目标的 change 申请。
    client, user = logged_in_client("ops4-list-request-permission-user")
    app = App.objects.create(app_key="ops4-list-request-permission", name="OPS4 List Permission")
    old_permission = _requestable_permission(app=app, key="invoice.read")
    new_permission = _requestable_permission(app=app, key="invoice.write")
    current_grant = AccessGrant.objects.create(user=user, app=app)
    _ = AccessGrantPermission.objects.create(
        grant=current_grant,
        permission=old_permission,
        scope_key=DEFAULT_SCOPE_KEY,
    )
    post_response = client.post(
        REQUESTS_API_URL,
        data=dumps(
            {
                "app_key": app.app_key,
                "request_type": "change",
                "authorization_group_keys": [],
                "direct_grants": [{"permission": new_permission.key, "scope": DEFAULT_SCOPE_KEY}],
                "approver_user_ids": [user.authentik_user_id],
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
    assert item["direct_grants"] == [
        {
            "permission": new_permission.key,
            "permission_name": new_permission.name,
            "scope": DEFAULT_SCOPE_KEY,
        },
    ]
    assert item["authorization_groups"] == []


def test_ops4_portal_api_hides_inactive_group_and_derived_grants() -> None:
    # Given: 当前员工授权同时绑定 active group、inactive group 和 direct grant。
    client, user = logged_in_client("ops4-grants-inactive-role-user")
    app = App.objects.create(app_key="ops4-grants-inactive-role", name="OPS4 Inactive Role")
    _ = AppScope.objects.create(app=app, key=DEFAULT_SCOPE_KEY, name="Global")
    active_group = AuthorizationGroup.objects.create(
        app=app,
        key="active-role",
        kind="role",
        name="有效角色",
    )
    inactive_group = AuthorizationGroup.objects.create(
        app=app,
        key="inactive-role",
        kind="role",
        name="停用角色",
        is_active=False,
    )
    active_permission = Permission.objects.create(
        app=app,
        key="active.read",
        name="有效权限",
        supported_scopes=[DEFAULT_SCOPE_KEY],
    )
    inactive_role_permission = Permission.objects.create(
        app=app,
        key="inactive-role.read",
        name="停用角色派生权限",
        supported_scopes=[DEFAULT_SCOPE_KEY],
    )
    direct_permission = Permission.objects.create(
        app=app,
        key="direct.read",
        name="直接权限",
        supported_scopes=[DEFAULT_SCOPE_KEY],
    )
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=active_group,
        permission=active_permission,
        scope_key=DEFAULT_SCOPE_KEY,
    )
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=inactive_group,
        permission=inactive_role_permission,
        scope_key=DEFAULT_SCOPE_KEY,
    )
    grant = AccessGrant.objects.create(user=user, app=app)
    _ = AccessGrantGroup.objects.create(grant=grant, authorization_group=active_group)
    _ = AccessGrantGroup.objects.create(grant=grant, authorization_group=inactive_group)
    _ = AccessGrantPermission.objects.create(
        grant=grant,
        permission=direct_permission,
        scope_key=DEFAULT_SCOPE_KEY,
    )

    # When: 员工读取自己的当前授权 API。
    response = client.get(GRANTS_API_URL)

    # Then: 响应不返回 inactive group, 也不返回 inactive group 派生 grant。
    items = json_object(response)["items"]
    assert isinstance(items, list), response.content.decode()
    item = items[0]
    assert isinstance(item, dict), response.content.decode()
    assert response.status_code == HTTPStatus.OK
    assert item["groups"] == [
        {"key": active_group.key, "kind": active_group.kind, "name": active_group.name},
    ]
    assert item["grants"] == [
        {
            "permission": active_permission.key,
            "scope": DEFAULT_SCOPE_KEY,
            "source_type": "group",
            "source_key": active_group.key,
        },
        {
            "permission": direct_permission.key,
            "scope": DEFAULT_SCOPE_KEY,
            "source_type": "direct",
            "source_key": "",
        },
    ]


def _requestable_permission(*, app: App, key: str) -> Permission:
    _ = AppScope.objects.get_or_create(app=app, key=DEFAULT_SCOPE_KEY, defaults={"name": "Global"})
    return Permission.objects.create(
        app=app,
        key=key,
        name=key,
        supported_scopes=[DEFAULT_SCOPE_KEY],
    )
