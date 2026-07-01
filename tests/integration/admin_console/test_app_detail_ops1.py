from __future__ import annotations

from http import HTTPStatus
from json import dumps
from pathlib import Path
from re import search
from typing import Final, Protocol

import pytest
from django.test import Client

from easyauth.accounts.auth import AUTHENTIK_SESSION_KEY
from easyauth.accounts.models import UserMirror
from easyauth.applications.models import (
    App,
    AppMembership,
    AppScope,
    AuthorizationGroup,
    AuthorizationGroupGrant,
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
APP_DETAIL_TEMPLATE: Final = (
    Path(__file__).parents[3]
    / "src/easyauth/admin_console/templates/admin_console/app_detail.html"
)
MIN_CSRF_TOKEN_FIELDS: Final = 8
APP_DETAIL_PARENT_MAX_LINES: Final = 120
APP_DETAIL_PARTIALS: Final = (
    "admin_console/app_detail/_readiness.html",
    "admin_console/app_detail/_permission_template.html",
    "admin_console/app_detail/_role_permission_matrix.html",
    "admin_console/app_detail/_query_tester.html",
    "admin_console/app_detail/_integration_guide.html",
    "admin_console/app_detail/_roles_permissions.html",
    "admin_console/app_detail/_credentials.html",
    "admin_console/app_detail/_approval_rules.html",
)


class HttpResponseLike(Protocol):
    content: bytes


def test_ops1_console_app_detail_shows_readiness_matrix_and_approval_prompt() -> None:
    # Given: 应用负责人拥有 CRM App, 且存在分组、角色、权限和授权组, 但授权组缺少审批规则。
    client = _logged_in_client("owner-ops1-detail")
    app = App.objects.create(app_key="ops1-console-crm", name="CRM Console")
    _ = AppMembership.objects.create(app=app, user_id="owner-ops1-detail", role="owner")
    _ = AppScope.objects.create(app=app, key="GLOBAL", name="全局")
    group = PermissionGroup.objects.create(app=app, key="PIPELINE_GROUP", name="Pipeline")
    role = Role.objects.create(app=app, key="operator", name="Operator", requestable=True)
    authorization_group = AuthorizationGroup.objects.create(
        app=app,
        key="operator",
        kind="role",
        name="Operator",
        requestable=True,
    )
    permission = Permission.objects.create(
        app=app,
        group=group,
        key="ALLOW_PIPELINE_CREATE",
        name="Create pipeline",
        supported_scopes=["GLOBAL"],
    )
    _ = RolePermission.objects.create(role=role, permission=permission)
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=authorization_group,
        permission=permission,
        scope_key="GLOBAL",
    )

    # When: 应用负责人通过 React shell 使用的 private API 读取配置和矩阵。
    configuration = client.get(_api_url(app.app_key, "configuration-status"))
    matrix = client.get(_api_url(app.app_key, "role-permission-matrix"))
    tree = client.get(_api_url(app.app_key, "permission-tree"))

    # Then: API 返回配置完整性、分组矩阵和 ApprovalRule 缺失提示。
    body = configuration.content.decode() + matrix.content.decode() + tree.content.decode()
    assert configuration.status_code == HTTPStatus.OK
    assert matrix.status_code == HTTPStatus.OK
    assert tree.status_code == HTTPStatus.OK
    assert "requestable_authorization_group_approval_rule_missing" in body
    assert "PIPELINE_GROUP" in body
    assert "operator" in body
    assert "ALLOW_PIPELINE_CREATE" in body
    assert '"enabled": true' in body


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


def test_ops1_console_entry_redirects_unauthenticated_user_to_authentik_login() -> None:
    # Given: 未建立 Authentik 控制台会话。
    client = Client(HTTP_HOST="localhost")

    # When: 用户访问控制台入口。
    response = client.get("/console/?tab=roles")

    # Then: 控制台跳转到 OIDC 登录并携带当前本地路径。
    assert response.status_code == HTTPStatus.FOUND
    assert response.headers["Location"] == "/auth/login/?next=/console/%3Ftab%3Droles"


def test_ops1_console_app_detail_template_preserves_sections_forms_and_partials() -> None:
    # Given: owner 管理一个含角色、权限和凭据入口的 App。
    client = _logged_in_client("owner-ops1-template-sections")
    app = App.objects.create(app_key="ops1-console-template-sections", name="Template Sections")
    _ = AppMembership.objects.create(app=app, user_id="owner-ops1-template-sections", role="owner")
    group = PermissionGroup.objects.create(app=app, key="PIPELINE_GROUP", name="Pipeline")
    role = Role.objects.create(app=app, key="operator", name="Operator", requestable=True)
    permission = Permission.objects.create(
        app=app,
        group=group,
        key="ALLOW_PIPELINE_CREATE",
        name="Create pipeline",
    )
    _ = RolePermission.objects.create(role=role, permission=permission)

    # When: owner 通过联调测试 POST 触发 Django app detail 模板页。
    response = client.post(
        f"/console/apps/{app.app_key}/",
        data={"action": "run_permission_query_test", "test_user_id": "owner", "test_token": ""},
    )

    # Then: 拆分 partial 后仍保留每个区块关键文本、提交 action 和 csrf 字段。
    body = response.content.decode()
    assert response.status_code == HTTPStatus.OK
    for expected_text in (
        "配置完整性",
        "权限模板",
        "RolePermission 矩阵",
        "联调测试台",
        "接入说明",
        "Role",
        "Permission",
        "凭据",
        "ApprovalRule",
    ):
        assert expected_text in body
    rendered_actions = (
        "preview_permission_template",
        "set_role_permission",
        "run_permission_query_test",
        "create_role",
        "create_permission",
        "create_static_token",
        "create_oauth_client",
        "create_approval_rule",
    )
    for expected_action in rendered_actions:
        assert f'name="action" value="{expected_action}"' in body
    assert body.count('name="csrfmiddlewaretoken"') >= MIN_CSRF_TOKEN_FIELDS

    template_source = APP_DETAIL_TEMPLATE.read_text()
    for partial in APP_DETAIL_PARTIALS:
        assert f'{{% include "{partial}" %}}' in template_source
    assert len(template_source.splitlines()) < APP_DETAIL_PARENT_MAX_LINES

    partial_source = "\n".join(
        (APP_DETAIL_TEMPLATE.parent / "app_detail" / Path(partial).name).read_text()
        for partial in APP_DETAIL_PARTIALS
    )
    for expected_action in (
        *rendered_actions,
        "apply_permission_template",
        "rotate_static_token",
        "disable_static_token",
    ):
        assert f'name="action" value="{expected_action}"' in partial_source


def test_ops1_console_matrix_save_writes_role_permission_and_audit_without_grants() -> None:
    # Given: owner 管理一个 App, 角色和权限尚未建立矩阵关系。
    client = _logged_in_client("owner-ops1-matrix")
    app = App.objects.create(app_key="ops1-console-matrix", name="Console Matrix")
    _ = AppMembership.objects.create(app=app, user_id="owner-ops1-matrix", role="owner")
    role = Role.objects.create(app=app, key="auditor", name="Auditor", requestable=True)
    permission = Permission.objects.create(app=app, key="invoice.read", name="Read invoices")

    initial = client.get(_api_url(app.app_key, "role-permission-matrix"))
    version = _json_string(initial, "version")

    # When: owner 通过矩阵 API 勾选 RolePermission。
    response = client.post(
        _api_url(app.app_key, "role-permission-matrix"),
        data=_matrix_payload(
            version=version,
            role_id=role.id,
            permission_id=permission.id,
            enabled=True,
        ),
        content_type="application/json",
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

    initial = client.get(_api_url(app.app_key, "role-permission-matrix"))
    version = _json_string(initial, "version")

    # When: owner 提交非法矩阵 JSON。
    response = client.post(
        _api_url(app.app_key, "role-permission-matrix"),
        data=dumps(
            {
                "version": version,
                "assignments": [
                    {
                        "role_id": form_data["role_id"],
                        "permission_id": form_data["permission_id"],
                        "enabled": True,
                    },
                ],
            },
        ),
        content_type="application/json",
    )

    # Then: 控制台 API 返回受控 400, 不产生 RolePermission 或审计写入。
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert "VALIDATION_ERROR" in response.content.decode()
    assert RolePermission.objects.count() == 0
    assert AuditLog.objects.count() == 0


def test_ops1_console_config_post_requires_csrf_token_when_enforced() -> None:
    # Given: 强制 CSRF 的 owner client 打开控制台详情页。
    client = _logged_in_client("owner-ops1-csrf", enforce_csrf_checks=True)
    app = App.objects.create(app_key="ops1-console-csrf", name="CSRF Console")
    _ = AppMembership.objects.create(app=app, user_id="owner-ops1-csrf", role="owner")
    get_response = client.get(f"/console/apps/{app.app_key}/")
    csrf_token = _extract_csrf_token(get_response.content.decode())

    # When: 分别提交无 CSRF token 和带 CSRF token 的新增 Role API 请求。
    missing_token = client.post(
        _api_url(app.app_key, "roles"),
        data=dumps({"key": "operator", "name": "Operator"}),
        content_type="application/json",
    )
    accepted = client.post(
        _api_url(app.app_key, "roles"),
        data=dumps({"key": "operator", "name": "Operator"}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )

    # Then: 无 CSRF token 被拒绝, 合法 API 请求可写入。
    assert missing_token.status_code == HTTPStatus.FORBIDDEN
    assert accepted.status_code == HTTPStatus.CREATED
    assert Role.objects.filter(app=app, key="operator").exists() is True


def test_ops1_console_permission_template_preview_shows_diff_without_writes() -> None:
    # Given: owner 管理一个空 App。
    client = _logged_in_client("owner-ops1-template-preview")
    app = App.objects.create(app_key="ops1-console-template-preview", name="Template Preview")
    _ = AppMembership.objects.create(app=app, user_id="owner-ops1-template-preview", role="owner")

    # When: owner 通过模板预览 API 提交 YAML。
    response = client.post(
        _api_url(app.app_key, "permission-template-imports/preview"),
        data=dumps({"template_format": "yaml", "template": _pipeline_template_yaml(app)}),
        content_type="application/json",
    )

    # Then: API 返回差异确认, 但不创建 group、permission 或模板版本。
    body = response.content.decode()
    assert response.status_code == HTTPStatus.OK
    assert "create_permission_group" in body
    assert "PIPELINE_GROUP" in body
    assert "create_permission" in body
    assert "ALLOW_PIPELINE_CREATE" in body
    assert "create_authorization_group" in body
    assert "create_approval_rule" in body
    assert PermissionGroup.objects.count() == 0
    assert Permission.objects.count() == 0
    assert PermissionTemplateVersion.objects.count() == 0


def test_ops1_console_permission_template_apply_imports_and_updates_matrix() -> None:
    # Given: owner 准备从空 App 导入权限模板。
    client = _logged_in_client("owner-ops1-template-apply")
    app = App.objects.create(app_key="ops1-console-template-apply", name="Template Apply")
    _ = AppMembership.objects.create(app=app, user_id="owner-ops1-template-apply", role="owner")
    _ = Role.objects.create(app=app, key="operator", name="Operator")

    # When: owner 先预览再确认导入 YAML 模板。
    preview = client.post(
        _api_url(app.app_key, "permission-template-imports/preview"),
        data=dumps({"template_format": "yaml", "template": _pipeline_template_yaml(app)}),
        content_type="application/json",
    )
    preview_id = _json_string(preview, "preview_id")
    response = client.post(
        _api_url(app.app_key, f"permission-template-imports/{preview_id}/confirm"),
        content_type="application/json",
    )

    # Then: 模板创建分组和叶子权限, 矩阵 API 展示叶子权限, 且不直接创建授权事实。
    matrix = client.get(_api_url(app.app_key, "role-permission-matrix"))
    body = matrix.content.decode()
    assert response.status_code == HTTPStatus.OK
    assert PermissionGroup.objects.get(app=app, key="PIPELINE_GROUP").name == "流水线"
    assert Permission.objects.get(app=app, key="ALLOW_PIPELINE_CREATE").group is not None
    assert PermissionTemplateVersion.objects.get(app=app).version == 1
    assert AuditLog.objects.get(event_type="app_manifest_imported").actor_id == (
        "owner-ops1-template-apply"
    )
    assert "PIPELINE_GROUP" in body
    assert "ALLOW_PIPELINE_CREATE" in body
    assert "流水线" in body
    assert AccessGrant.objects.count() == 0


def _logged_in_client(username: str, *, enforce_csrf_checks: bool = False) -> Client:
    return _login_client(username=username, enforce_csrf_checks=enforce_csrf_checks)


def _login_client(*, username: str, enforce_csrf_checks: bool) -> Client:
    user, _created = UserMirror.objects.get_or_create(authentik_user_id=username)
    client = Client(HTTP_HOST="localhost", enforce_csrf_checks=enforce_csrf_checks)
    session = client.session
    session[AUTHENTIK_SESSION_KEY] = user.authentik_user_id
    session.save()
    return client


def _extract_csrf_token(html: str) -> str:
    match = search(r'name="csrfmiddlewaretoken" value="([^"]+)"', html)
    if match is None:
        raise AssertionError(html)
    return match.group(1)


def _api_url(app_key: str, endpoint: str) -> str:
    return f"/console/api/v1/apps/{app_key}/{endpoint}"


def _matrix_payload(*, version: str, role_id: int, permission_id: int, enabled: bool) -> str:
    return dumps(
        {
            "version": version,
            "assignments": [
                {"role_id": role_id, "permission_id": permission_id, "enabled": enabled},
            ],
        },
    )


def _pipeline_template_yaml(app: App) -> str:
    return f"""
schema_version: 1
app:
  app_key: {app.app_key}
  name: {app.name}
scopes:
  - key: GLOBAL
    name: 全局
permission_groups:
  - key: PIPELINE_GROUP
    name: 流水线
permissions:
  - key: ALLOW_PIPELINE_CREATE
    name: 创建流水线
    group_key: PIPELINE_GROUP
    supported_scopes:
      - GLOBAL
authorization_groups:
  - key: operator
    kind: role
    name: Operator
    grants:
      - permission: ALLOW_PIPELINE_CREATE
        scope: GLOBAL
approval_rules:
  - target_type: authorization_group
    target_key: operator
    approver_userids:
      - manager-001
"""


def _json_string(response: HttpResponseLike, key: str) -> str:
    match = search(rf'"{key}"\s*:\s*"([^"]+)"', response.content.decode())
    if match is None:
        raise AssertionError(response.content.decode())
    return match.group(1)
