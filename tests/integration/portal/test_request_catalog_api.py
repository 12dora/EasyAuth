from __future__ import annotations

from http import HTTPStatus
from typing import Final

import pytest
from django.test import Client

from easyauth.accounts.models import USER_STATUS_DISABLED, UserMirror
from easyauth.applications.models import (
    App,
    AppMembership,
    ApprovalRule,
    AppScope,
    AuthorizationGroup,
    Permission,
    PermissionGroup,
)
from tests.integration.portal.helpers import logged_in_client
from tests.integration.portal.json_helpers import json_object

pytestmark = pytest.mark.django_db

REQUEST_CATALOG_URL: Final = "/portal/api/v1/request-catalog"


def test_portal_request_catalog_lists_only_requestable_authorization_groups() -> None:
    # Given: active 员工和多种可提交/不可提交授权组。
    client, user = logged_in_client("portal-catalog-user")
    crm = App.objects.create(app_key="catalog-crm", name="CRM", description="客户系统")
    inactive_app = App.objects.create(app_key="catalog-inactive", name="停用系统", is_active=False)
    requestable_group = AuthorizationGroup.objects.create(
        app=crm,
        key="auditor",
        kind="role",
        name="审计员",
        requestable=True,
    )
    inactive_group = AuthorizationGroup.objects.create(
        app=crm,
        key="inactive",
        kind="role",
        name="停用角色",
        is_active=False,
        requestable=True,
    )
    not_requestable_group = AuthorizationGroup.objects.create(
        app=crm,
        key="not-requestable",
        kind="bundle",
        name="不可申请",
        requestable=False,
    )
    inactive_app_group = AuthorizationGroup.objects.create(
        app=inactive_app,
        key="inactive-app-role",
        kind="role",
        name="停用应用角色",
        requestable=True,
    )
    _ = ApprovalRule.objects.create(
        app=crm,
        authorization_group=requestable_group,
        approver_userids=["manager-001"],
    )

    # When: 读取申请目录。
    response = client.get(REQUEST_CATALOG_URL)

    # Then: 只返回 active App 下 active/requestable 且有 active 审批规则的授权组。
    payload = json_object(response)
    assert response.status_code == HTTPStatus.OK
    assert payload["apps"] == [
        {
            "id": crm.id,
            "app_key": crm.app_key,
            "name": crm.name,
            "description": crm.description,
            "catalog_version": crm.catalog_version,
            "default_approver_user_ids": [],
        },
    ]
    assert payload["authorization_groups"] == [
        {
            "id": requestable_group.id,
            "app_key": crm.app_key,
            "key": requestable_group.key,
            "kind": requestable_group.kind,
            "name": requestable_group.name,
            "description": requestable_group.description,
            "requestable": True,
            "requires_approval": True,
            "default_approver_user_ids": [],
        },
    ]
    assert payload["approver_options"] == [
        {
            "user_id": user.authentik_user_id,
            "name": user.name,
            "email": user.email,
            "department": user.department,
        },
    ]
    body = response.content.decode()
    assert inactive_group.key not in body
    assert not_requestable_group.key not in body
    assert inactive_app_group.key not in body


def test_portal_request_catalog_lists_requestable_permissions_as_group_tree() -> None:
    # Given: active 员工和一个包含多层权限组的可申请 App。
    client, _user = logged_in_client("portal-catalog-permission-user")
    crm = App.objects.create(app_key="catalog-permission-crm", name="CRM")
    _ = AppScope.objects.create(app=crm, key="GLOBAL", name="全局")
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
        supported_scopes=["GLOBAL"],
    )
    no_rule_permission = Permission.objects.create(
        app=crm,
        group=invoice,
        key="invoice.secret",
        name="隐藏发票",
        supported_scopes=["GLOBAL"],
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
            "catalog_version": crm.catalog_version,
            "default_approver_user_ids": [],
        },
    ]
    assert isinstance(groups, list)
    root = groups[0]
    assert isinstance(root, dict)
    children = root["children"]
    assert isinstance(children, list)
    child = children[0]
    assert isinstance(child, dict)
    child_children = child["children"]
    assert isinstance(child_children, list)
    permission = child_children[0]
    assert isinstance(permission, dict)
    assert root["app_key"] == crm.app_key
    assert root["key"] == billing.key
    assert child["key"] == invoice.key
    assert permission["type"] == "permission"
    assert permission["app_key"] == crm.app_key
    assert permission["key"] == requestable_permission.key
    assert no_rule_permission.key in body
    assert inactive_permission.key not in body


def test_portal_request_catalog_excludes_requestable_group_without_active_approval_rule() -> None:
    client, _user = logged_in_client("request-catalog-no-rule-user")
    app_without_rule = App.objects.create(app_key="catalog-no-rule", name="No Rule")
    app_with_rule = App.objects.create(app_key="catalog-with-rule", name="With Rule")
    group_without_rule = AuthorizationGroup.objects.create(
        app=app_without_rule,
        key="reader",
        kind="role",
        name="无审批规则角色",
        requestable=True,
    )
    group_with_rule = AuthorizationGroup.objects.create(
        app=app_with_rule,
        key="auditor",
        kind="role",
        name="有审批规则角色",
        requestable=True,
    )
    _ = ApprovalRule.objects.create(
        app=app_with_rule,
        authorization_group=group_with_rule,
        approver_userids=["manager-001"],
    )

    response = client.get(REQUEST_CATALOG_URL)

    body = response.content.decode()
    payload = json_object(response)
    assert response.status_code == HTTPStatus.OK
    assert group_with_rule.key in body
    assert group_without_rule.key not in body
    assert payload["apps"] == [
        {
            "id": app_without_rule.id,
            "app_key": app_without_rule.app_key,
            "name": app_without_rule.name,
            "description": app_without_rule.description,
            "catalog_version": app_without_rule.catalog_version,
            "default_approver_user_ids": [],
        },
        {
            "id": app_with_rule.id,
            "app_key": app_with_rule.app_key,
            "name": app_with_rule.name,
            "description": app_with_rule.description,
            "catalog_version": app_with_rule.catalog_version,
            "default_approver_user_ids": [],
        },
    ]


def test_portal_request_catalog_rejects_missing_session() -> None:
    # Given: 未登录 client。
    client = Client()

    # When: 读取申请目录。
    response = client.get(REQUEST_CATALOG_URL)

    # Then: 仍使用员工门户 session 边界。
    assert response.status_code == HTTPStatus.UNAUTHORIZED


def test_portal_request_catalog_returns_authorization_groups_and_catalog_version() -> None:
    # Given: active 员工和新授权组目录。
    client, _user = logged_in_client("portal-catalog-authorization-group-user")
    crm = App.objects.create(app_key="catalog-authz-crm", name="CRM", catalog_version=7)
    active_group = AuthorizationGroup.objects.create(
        app=crm,
        key="sales",
        kind="role",
        name="销售",
        requestable=True,
    )
    _ = AuthorizationGroup.objects.create(
        app=crm,
        key="internal",
        kind="bundle",
        name="内部",
        requestable=False,
    )
    _ = ApprovalRule.objects.create(
        app=crm,
        authorization_group=active_group,
        approver_userids=["manager-001"],
    )

    # When: 读取申请目录。
    response = client.get(REQUEST_CATALOG_URL)

    # Then: 目录返回 authorization_groups 和 catalog_version, 不再返回 roles。
    payload = json_object(response)
    assert response.status_code == HTTPStatus.OK
    assert payload["authorization_groups"] == [
        {
            "id": active_group.id,
            "app_key": crm.app_key,
            "key": active_group.key,
            "kind": active_group.kind,
            "name": active_group.name,
            "description": active_group.description,
            "requestable": True,
            "requires_approval": True,
            "default_approver_user_ids": [],
        },
    ]
    assert payload["apps"][0]["catalog_version"] == crm.catalog_version
    assert "roles" not in payload


def test_portal_request_catalog_includes_direct_grant_scope_options() -> None:
    # Given: active direct Permission 支持多个 scope。
    client, _user = logged_in_client("portal-catalog-direct-grant-scope-user")
    crm = App.objects.create(app_key="catalog-direct-scope-crm", name="CRM")
    _ = AppScope.objects.create(app=crm, key="SELF", name="本人")
    _ = AppScope.objects.create(app=crm, key="TEAM", name="团队")
    _ = AppScope.objects.create(app=crm, key="DISABLED", name="停用", is_active=False)
    permission = Permission.objects.create(
        app=crm,
        key="invoice.export",
        name="导出发票",
        supported_scopes=["SELF", "TEAM", "DISABLED"],
    )
    _ = ApprovalRule.objects.create(
        app=crm,
        permission=permission,
        approver_userids=["manager-001"],
    )

    # When: 读取申请目录。
    response = client.get(REQUEST_CATALOG_URL)

    # Then: direct grant 目标只暴露 active 且 permission 支持的 scopes。
    payload = json_object(response)
    direct_grants = payload["ungrouped_permissions"]
    assert response.status_code == HTTPStatus.OK
    assert direct_grants[0]["key"] == permission.key
    assert direct_grants[0]["scopes"] == [
        {"key": "SELF", "name": "本人", "description": ""},
        {"key": "TEAM", "name": "团队", "description": ""},
    ]


def test_portal_request_catalog_returns_active_approver_options_and_defaults() -> None:
    # Given: 当前员工有直属主管, App 有 owner, 目标也可有审批规则审批人。
    client, user = logged_in_client("portal-catalog-approver-user")
    user.manager_userid = "manager-dt"
    user.save(update_fields=["manager_userid"])
    manager = UserMirror.objects.create(
        authentik_user_id="portal-catalog-manager",
        name="主管",
        dingtalk_userid="manager-dt",
    )
    owner = UserMirror.objects.create(authentik_user_id="portal-catalog-owner", name="Owner")
    rule_approver = UserMirror.objects.create(
        authentik_user_id="portal-catalog-rule-approver",
        name="规则审批人",
        dingtalk_userid="rule-dt",
    )
    _ = UserMirror.objects.create(
        authentik_user_id="portal-catalog-disabled-approver",
        name="停用审批人",
        status=USER_STATUS_DISABLED,
    )
    app = App.objects.create(app_key="catalog-approver-app", name="审批 App")
    orphan_app = App.objects.create(app_key="catalog-approver-orphan", name="无目标 App")
    _ = AppMembership.objects.create(app=app, user_id=owner.authentik_user_id, role="owner")
    _ = AppScope.objects.create(app=app, key="GLOBAL", name="全局")
    group = AuthorizationGroup.objects.create(
        app=app,
        key="finance",
        kind="role",
        name="财务",
        requestable=True,
    )
    permission = Permission.objects.create(
        app=app,
        key="invoice.read",
        name="查看发票",
        supported_scopes=["GLOBAL"],
    )
    _ = ApprovalRule.objects.create(
        app=app,
        authorization_group=group,
        approver_userids=["rule-dt"],
    )

    # When: 读取申请目录。
    response = client.get(REQUEST_CATALOG_URL)

    # Then: 目录返回 active 系统用户审批人选项, 默认值按目标规则优先, 否则直属主管。
    payload = json_object(response)
    assert response.status_code == HTTPStatus.OK
    option_ids = {option["user_id"] for option in payload["approver_options"]}
    app_defaults = {
        app_item["app_key"]: app_item["default_approver_user_ids"]
        for app_item in payload["apps"]
    }
    group_defaults = {
        group_item["key"]: group_item["default_approver_user_ids"]
        for group_item in payload["authorization_groups"]
    }
    permission_defaults = {
        permission_item["key"]: permission_item["default_approver_user_ids"]
        for permission_item in payload["ungrouped_permissions"]
    }
    assert option_ids == {
        user.authentik_user_id,
        manager.authentik_user_id,
        owner.authentik_user_id,
        rule_approver.authentik_user_id,
    }
    assert app_defaults[app.app_key] == [manager.authentik_user_id]
    assert app_defaults[orphan_app.app_key] == [manager.authentik_user_id]
    assert group_defaults[group.key] == [rule_approver.authentik_user_id]
    assert permission_defaults[permission.key] == [manager.authentik_user_id]
