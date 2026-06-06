from __future__ import annotations

from http import HTTPStatus
from re import search
from typing import Final

import pytest
from django.contrib.auth.models import User
from django.test import Client

from easyauth.applications.models import (
    App,
    AppMembership,
    Permission,
    PermissionGroup,
    PermissionTemplateVersion,
    Role,
    RolePermission,
)
from easyauth.audit.models import AuditLog
from easyauth.grants.models import AccessGrant

pytestmark = pytest.mark.django_db

LOGIN_VALUE: Final = "console-login"
PIPELINE_TEMPLATE_YAML: Final = """
version: 1
groups:
  - key: PIPELINE_GROUP
    name: 流水线
    children:
      - key: ALLOW_PIPELINE_CREATE
        name: 创建流水线
        type: permission
"""


def test_ops1_console_app_detail_shows_readiness_matrix_and_approval_prompt() -> None:
    # Given: 应用负责人拥有 CRM App, 且存在分组、角色和权限, 但缺少审批规则。
    client = _logged_in_client("owner-ops1-detail")
    app = App.objects.create(app_key="ops1-console-crm", name="CRM Console")
    _ = AppMembership.objects.create(app=app, user_id="owner-ops1-detail", role="owner")
    group = PermissionGroup.objects.create(app=app, key="PIPELINE_GROUP", name="Pipeline")
    role = Role.objects.create(app=app, key="operator", name="Operator", requestable=True)
    permission = Permission.objects.create(
        app=app,
        group=group,
        key="ALLOW_PIPELINE_CREATE",
        name="Create pipeline",
    )
    _ = RolePermission.objects.create(role=role, permission=permission)

    # When: 应用负责人打开 App 详情页。
    response = client.get(f"/console/apps/{app.app_key}/")

    # Then: 页面展示配置完整性、分组矩阵和 ApprovalRule 缺失提示。
    html = response.content.decode()
    assert response.status_code == HTTPStatus.OK
    assert 'data-ops1-console="app-detail"' in html
    assert "配置完整性" in html
    assert "requestable_role_approval_rule_missing" in html
    assert "PIPELINE_GROUP" in html
    assert "Operator" in html
    assert "ALLOW_PIPELINE_CREATE" in html


def test_ops1_console_owner_cannot_access_unowned_app_detail() -> None:
    # Given: 用户只拥有 CRM App, 不拥有 ERP App。
    client = _logged_in_client("owner-ops1-scope")
    crm = App.objects.create(app_key="ops1-owned-crm", name="Owned CRM")
    erp = App.objects.create(app_key="ops1-unowned-erp", name="Unowned ERP")
    _ = AppMembership.objects.create(app=crm, user_id="owner-ops1-scope", role="owner")

    # When: 用户直连未负责 App 的详情页。
    response = client.get(f"/console/apps/{erp.app_key}/")

    # Then: 控制台拒绝暴露未授权 App。
    assert response.status_code == HTTPStatus.NOT_FOUND


def test_ops1_console_matrix_save_writes_role_permission_and_audit_without_grants() -> None:
    # Given: owner 管理一个 App, 角色和权限尚未建立矩阵关系。
    client = _logged_in_client("owner-ops1-matrix")
    app = App.objects.create(app_key="ops1-console-matrix", name="Console Matrix")
    _ = AppMembership.objects.create(app=app, user_id="owner-ops1-matrix", role="owner")
    role = Role.objects.create(app=app, key="auditor", name="Auditor", requestable=True)
    permission = Permission.objects.create(app=app, key="invoice.read", name="Read invoices")

    # When: owner 在矩阵中勾选 RolePermission。
    response = client.post(
        f"/console/apps/{app.app_key}/",
        {
            "action": "set_role_permission",
            "role_id": str(role.id),
            "permission_id": str(permission.id),
            "enabled": "on",
        },
        follow=True,
    )

    # Then: 保存只写 RolePermission 和审计, 不直接创建 AccessGrant。
    assert response.status_code == HTTPStatus.OK
    assert RolePermission.objects.filter(role=role, permission=permission).exists() is True
    audit_log = AuditLog.objects.get(event_type="role_permission_matrix_updated")
    assert audit_log.actor_id == "owner-ops1-matrix"
    assert audit_log.metadata["app_key"] == app.app_key
    assert AccessGrant.objects.count() == 0


@pytest.mark.parametrize("invalid_field", ["role_id", "permission_id"])
def test_ops1_console_invalid_matrix_post_returns_controlled_bad_request(
    invalid_field: str,
) -> None:
    # Given: owner 管理一个 App, 但 POST 中的矩阵 ID 被篡改为非数字。
    client = _logged_in_client("owner-ops1-invalid-matrix")
    app = App.objects.create(app_key="ops1-console-invalid-matrix", name="Invalid Matrix")
    _ = AppMembership.objects.create(app=app, user_id="owner-ops1-invalid-matrix", role="owner")
    role = Role.objects.create(app=app, key="auditor", name="Auditor")
    permission = Permission.objects.create(app=app, key="invoice.read", name="Read invoices")
    form_data = {
        "action": "set_role_permission",
        "role_id": str(role.id),
        "permission_id": str(permission.id),
        "enabled": "on",
    }
    form_data[invalid_field] = "not-a-number"

    # When: owner 提交非法矩阵表单。
    response = client.post(
        f"/console/apps/{app.app_key}/",
        form_data,
    )

    # Then: 控制台返回受控 400, 不产生 RolePermission 或审计写入。
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert "表单参数无效" in response.content.decode()
    assert RolePermission.objects.count() == 0
    assert AuditLog.objects.count() == 0


def test_ops1_console_config_post_requires_csrf_token_when_enforced() -> None:
    # Given: 强制 CSRF 的 owner client 打开控制台详情页。
    client = _logged_in_client("owner-ops1-csrf", enforce_csrf_checks=True)
    app = App.objects.create(app_key="ops1-console-csrf", name="CSRF Console")
    _ = AppMembership.objects.create(app=app, user_id="owner-ops1-csrf", role="owner")
    get_response = client.get(f"/console/apps/{app.app_key}/")
    csrf_token = _extract_csrf_token(get_response.content.decode())

    # When: 分别提交无 CSRF token 和带 CSRF token 的新增 Role 表单。
    missing_token = client.post(
        f"/console/apps/{app.app_key}/",
        {"action": "create_role", "role_key": "operator", "role_name": "Operator"},
    )
    accepted = client.post(
        f"/console/apps/{app.app_key}/",
        {
            "action": "create_role",
            "role_key": "operator",
            "role_name": "Operator",
            "csrfmiddlewaretoken": csrf_token,
        },
        follow=True,
    )

    # Then: 无 CSRF token 被拒绝, 合法表单可写入。
    assert missing_token.status_code == HTTPStatus.FORBIDDEN
    assert accepted.status_code == HTTPStatus.OK
    assert Role.objects.filter(app=app, key="operator").exists() is True


def test_ops1_console_permission_template_preview_shows_diff_without_writes() -> None:
    # Given: owner 打开空 App 的权限模板导入入口。
    client = _logged_in_client("owner-ops1-template-preview")
    app = App.objects.create(app_key="ops1-console-template-preview", name="Template Preview")
    _ = AppMembership.objects.create(app=app, user_id="owner-ops1-template-preview", role="owner")

    # When: owner 粘贴 YAML 模板并点击预览。
    response = client.post(
        f"/console/apps/{app.app_key}/",
        {
            "action": "preview_permission_template",
            "template_format": "yaml",
            "template_content": PIPELINE_TEMPLATE_YAML,
        },
    )

    # Then: 页面展示差异确认, 但不创建 group、permission 或模板版本。
    html = response.content.decode()
    assert response.status_code == HTTPStatus.OK
    assert 'data-ops1-template-result="preview"' in html
    assert "create_group" in html
    assert "PIPELINE_GROUP" in html
    assert "create_permission" in html
    assert "ALLOW_PIPELINE_CREATE" in html
    assert PermissionGroup.objects.count() == 0
    assert Permission.objects.count() == 0
    assert PermissionTemplateVersion.objects.count() == 0


def test_ops1_console_permission_template_apply_imports_and_updates_matrix() -> None:
    # Given: owner 准备从空 App 导入权限模板。
    client = _logged_in_client("owner-ops1-template-apply")
    app = App.objects.create(app_key="ops1-console-template-apply", name="Template Apply")
    _ = AppMembership.objects.create(app=app, user_id="owner-ops1-template-apply", role="owner")
    _ = Role.objects.create(app=app, key="operator", name="Operator")

    # When: owner 确认导入 YAML 模板。
    response = client.post(
        f"/console/apps/{app.app_key}/",
        {
            "action": "apply_permission_template",
            "template_format": "yaml",
            "template_content": PIPELINE_TEMPLATE_YAML,
        },
    )

    # Then: 模板创建分组和叶子权限, 矩阵展示叶子权限, 且不直接创建授权事实。
    html = response.content.decode()
    assert response.status_code == HTTPStatus.OK
    assert 'data-ops1-template-result="applied"' in html
    assert PermissionGroup.objects.get(app=app, key="PIPELINE_GROUP").name == "流水线"
    assert Permission.objects.get(app=app, key="ALLOW_PIPELINE_CREATE").group is not None
    assert PermissionTemplateVersion.objects.get(app=app).version == 1
    assert AuditLog.objects.get(event_type="permission_template_imported").actor_id == (
        "owner-ops1-template-apply"
    )
    assert "PIPELINE_GROUP" in html
    assert "ALLOW_PIPELINE_CREATE" in html
    assert 'data-ops1-permission-tree="groups"' in html
    assert "流水线" in html
    assert AccessGrant.objects.count() == 0


def _logged_in_client(username: str, *, enforce_csrf_checks: bool = False) -> Client:
    return _login_client(username=username, enforce_csrf_checks=enforce_csrf_checks)


def _login_client(*, username: str, enforce_csrf_checks: bool) -> Client:
    _ = User.objects.create_user(username=username, password=LOGIN_VALUE)
    client = Client(HTTP_HOST="localhost", enforce_csrf_checks=enforce_csrf_checks)
    assert client.login(username=username, password=LOGIN_VALUE) is True
    return client


def _extract_csrf_token(html: str) -> str:
    match = search(r'name="csrfmiddlewaretoken" value="([^"]+)"', html)
    if match is None:
        raise AssertionError(html)
    return match.group(1)
