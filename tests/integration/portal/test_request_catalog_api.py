from __future__ import annotations

from http import HTTPStatus
from typing import Final

import pytest
from django.test import Client

from easyauth.accounts.auth import AUTHENTIK_SESSION_KEY
from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.applications.models import App, ApprovalRule, Permission, PermissionGroup, Role
from tests.integration.portal.json_helpers import json_object

pytestmark = pytest.mark.django_db

REQUEST_CATALOG_URL: Final = "/portal/api/v1/request-catalog"


def test_portal_request_catalog_lists_only_requestable_roles_with_approval_rules() -> None:
    # Given: active 员工和多种可申请/不可申请角色。
    client, _user = _logged_in_client("portal-catalog-user")
    crm = App.objects.create(app_key="catalog-crm", name="CRM", description="客户系统")
    inactive_app = App.objects.create(app_key="catalog-inactive", name="停用系统", is_active=False)
    requestable_role = Role.objects.create(
        app=crm,
        key="auditor",
        name="审计员",
        requestable=True,
    )
    inactive_role = Role.objects.create(
        app=crm,
        key="inactive",
        name="停用角色",
        is_active=False,
        requestable=True,
    )
    no_rule_role = Role.objects.create(app=crm, key="no-rule", name="缺少审批", requestable=True)
    not_requestable_role = Role.objects.create(
        app=crm,
        key="not-requestable",
        name="不可申请",
        requestable=False,
    )
    inactive_app_role = Role.objects.create(
        app=inactive_app,
        key="inactive-app-role",
        name="停用应用角色",
        requestable=True,
    )
    _ = ApprovalRule.objects.create(
        app=crm,
        role=requestable_role,
        approver_userids=["manager-001"],
    )
    _ = ApprovalRule.objects.create(
        app=crm,
        role=inactive_role,
        approver_userids=["manager-001"],
    )
    _ = ApprovalRule.objects.create(
        app=crm,
        role=not_requestable_role,
        approver_userids=["manager-001"],
    )
    _ = ApprovalRule.objects.create(
        app=inactive_app,
        role=inactive_app_role,
        approver_userids=["manager-001"],
    )

    # When: 读取申请目录。
    response = client.get(REQUEST_CATALOG_URL)

    # Then: 只返回 active App 下 active/requestable/有 active 审批规则的角色。
    payload = json_object(response)
    assert response.status_code == HTTPStatus.OK
    assert payload["apps"] == [
        {
            "id": crm.id,
            "app_key": crm.app_key,
            "name": crm.name,
            "description": crm.description,
        },
    ]
    assert payload["roles"] == [
        {
            "id": requestable_role.id,
            "app_key": crm.app_key,
            "key": requestable_role.key,
            "name": requestable_role.name,
            "description": requestable_role.description,
            "requestable": True,
            "requires_approval": True,
        },
    ]
    assert no_rule_role.key not in response.content.decode()


def test_portal_request_catalog_lists_requestable_permissions_as_group_tree() -> None:
    # Given: active 员工和一个包含多层权限组的可申请 App。
    client, _user = _logged_in_client("portal-catalog-permission-user")
    crm = App.objects.create(app_key="catalog-permission-crm", name="CRM")
    billing = PermissionGroup.objects.create(app=crm, key="billing", name="账务", depth=1)
    invoice = PermissionGroup.objects.create(
        app=crm,
        key="invoice",
        name="发票",
        parent=billing,
        depth=2,
    )
    requestable_permission = Permission.objects.create(
        app=crm,
        group=invoice,
        key="invoice.read",
        name="查看发票",
    )
    no_rule_permission = Permission.objects.create(
        app=crm,
        group=invoice,
        key="invoice.secret",
        name="隐藏发票",
    )
    inactive_permission = Permission.objects.create(
        app=crm,
        key="invoice.inactive",
        name="停用权限",
        is_active=False,
    )
    _ = ApprovalRule.objects.create(
        app=crm,
        permission=requestable_permission,
        approver_userids=["manager-001"],
    )

    # When: 读取申请目录。
    response = client.get(REQUEST_CATALOG_URL)

    # Then: 响应返回可申请 direct Permission 的多层权限树, 并过滤不可申请权限。
    payload = json_object(response)
    body = response.content.decode()
    groups = payload["permission_groups"]
    assert response.status_code == HTTPStatus.OK
    assert payload["apps"] == [
        {
            "id": crm.id,
            "app_key": crm.app_key,
            "name": crm.name,
            "description": crm.description,
        },
    ]
    assert isinstance(groups, list)
    root = groups[0]
    assert isinstance(root, dict)
    child = root["children"][0]
    assert isinstance(child, dict)
    permission = child["children"][0]
    assert isinstance(permission, dict)
    assert root["app_key"] == crm.app_key
    assert root["key"] == billing.key
    assert child["key"] == invoice.key
    assert permission["type"] == "permission"
    assert permission["app_key"] == crm.app_key
    assert permission["key"] == requestable_permission.key
    assert no_rule_permission.key not in body
    assert inactive_permission.key not in body


def test_portal_request_catalog_rejects_missing_session() -> None:
    # Given: 未登录 client。
    client = Client()

    # When: 读取申请目录。
    response = client.get(REQUEST_CATALOG_URL)

    # Then: 仍使用员工门户 session 边界。
    assert response.status_code == HTTPStatus.UNAUTHORIZED


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
