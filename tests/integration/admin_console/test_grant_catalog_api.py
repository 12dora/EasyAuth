from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, Final, cast

import pytest
from django.test import Client

from easyauth.accounts.models import UserMirror
from easyauth.applications.models import (
    App,
    ApprovalRule,
    AppScope,
    AuthorizationGroup,
    AuthorizationGroupGrant,
    Permission,
)
from tests.integration.admin_console.auth_helpers import (
    authenticate_console_admin,
    authenticate_console_user,
)

if TYPE_CHECKING:
    from easyauth.api.errors import JsonValue

pytestmark = pytest.mark.django_db

GRANT_CATALOG_API_URL: Final = "/console/api/v1/grant-catalog"


def test_grant_catalog_requires_authentication() -> None:
    client = Client(HTTP_HOST="localhost")

    response = client.get(GRANT_CATALOG_API_URL)

    assert response.status_code == HTTPStatus.UNAUTHORIZED


def test_grant_catalog_requires_superuser() -> None:
    client = _logged_in_user("grant-catalog-ordinary")

    response = client.get(GRANT_CATALOG_API_URL)

    assert response.status_code == HTTPStatus.FORBIDDEN


def test_grant_catalog_rejects_non_get() -> None:
    client = _logged_in_superuser("grant-catalog-method-admin")

    response = client.post(GRANT_CATALOG_API_URL, data={}, content_type="application/json")

    assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED


def test_grant_catalog_includes_active_groups_without_requestable_or_approval_rules() -> None:
    client = _logged_in_superuser("grant-catalog-admin")
    app = App.objects.create(app_key="grant-catalog-crm", name="CRM", alias="客户系统")
    inactive_app = App.objects.create(
        app_key="grant-catalog-inactive",
        name="停用系统",
        is_active=False,
    )
    _ = AppScope.objects.create(app=app, key="GLOBAL", name="全局")
    requestable_group = AuthorizationGroup.objects.create(
        app=app,
        key="sales",
        kind="role",
        name="销售",
        requestable=True,
    )
    _ = ApprovalRule.objects.create(
        app=app,
        authorization_group=requestable_group,
        approver_userids=["manager-001"],
    )
    admin_only_group = AuthorizationGroup.objects.create(
        app=app,
        key="finance",
        kind="role",
        name="财务",
        requestable=False,
    )
    inactive_group = AuthorizationGroup.objects.create(
        app=app,
        key="inactive",
        kind="role",
        name="停用角色",
        is_active=False,
        requestable=True,
    )
    _ = AuthorizationGroup.objects.create(
        app=inactive_app,
        key="inactive-app-role",
        kind="role",
        name="停用应用角色",
        requestable=True,
    )
    permission = Permission.objects.create(
        app=app,
        key="order.order.view",
        name="查看订单",
        supported_scopes=["GLOBAL"],
    )
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=admin_only_group,
        permission=permission,
        scope_key="GLOBAL",
        is_active=True,
    )

    response = client.get(GRANT_CATALOG_API_URL)

    payload = cast("dict[str, JsonValue]", response.json())
    groups = cast("list[dict[str, JsonValue]]", payload["authorization_groups"])
    group_keys = [item["key"] for item in groups]
    apps = cast("list[dict[str, JsonValue]]", payload["apps"])
    finance = next(item for item in groups if item["key"] == "finance")
    assert response.status_code == HTTPStatus.OK
    assert [item["app_key"] for item in apps] == [app.app_key]
    assert set(group_keys) == {requestable_group.key, admin_only_group.key}
    assert inactive_group.key not in group_keys
    assert payload["approver_options"] == []
    assert apps[0]["default_approver_user_ids"] == []
    assert apps[0]["approver_resolution_status"] == "not_required"
    assert finance["requires_approval"] is True
    assert finance["default_approver_user_ids"] == []
    assert finance["approver_resolution_status"] == "not_required"
    assert finance["grants"] == [{"permission_key": permission.key, "scope_key": "GLOBAL"}]
    ungrouped = cast("list[dict[str, JsonValue]]", payload["ungrouped_permissions"])
    assert ungrouped[0]["key"] == permission.key
    assert ungrouped[0]["approver_resolution_status"] == "not_required"
    body = response.content.decode()
    assert "inactive-app-role" not in body


def _logged_in_user(username: str) -> Client:
    client = Client(HTTP_HOST="localhost")
    authenticate_console_user(client, username)
    return client


def _logged_in_superuser(username: str) -> Client:
    _ = UserMirror.objects.get_or_create(authentik_user_id=username)
    client = Client(HTTP_HOST="localhost")
    authenticate_console_admin(client, username)
    return client
