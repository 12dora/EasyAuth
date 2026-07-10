from __future__ import annotations

from http import HTTPStatus
from json import dumps
from re import search
from typing import Final, Protocol

import pytest
from django.test import Client, override_settings

from easyauth.accounts.auth import AUTHENTIK_GROUPS_SESSION_KEY, AUTHENTIK_SESSION_KEY
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
)
from easyauth.audit.models import AuditLog

pytestmark = pytest.mark.django_db

LOGIN_VALUE: Final = "console-login"


class HttpResponseLike(Protocol):
    content: bytes


def test_ops1_console_app_detail_shows_readiness_catalog_and_approval_prompt() -> None:
    # Given: 应用负责人拥有 CRM App, 且存在分组、权限和授权组, 但授权组缺少审批规则。
    client = _logged_in_client("owner-ops1-detail")
    app = App.objects.create(app_key="ops1-console-crm", name="CRM Console")
    _ = AppMembership.objects.create(app=app, user_id="owner-ops1-detail", role="owner")
    _ = AppScope.objects.create(app=app, key="GLOBAL", name="全局")
    group = PermissionGroup.objects.create(app=app, key="PIPELINE_GROUP", name="Pipeline")
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
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=authorization_group,
        permission=permission,
        scope_key="GLOBAL",
    )

    # When: 应用负责人通过 React shell 使用的 private API 读取配置和权限树。
    configuration = client.get(_api_url(app.app_key, "configuration-status"))
    tree = client.get(_api_url(app.app_key, "permission-tree"))

    # Then: API 返回配置完整性、权限目录和 ApprovalRule 缺失提示。
    body = configuration.content.decode() + tree.content.decode()
    assert configuration.status_code == HTTPStatus.OK
    assert tree.status_code == HTTPStatus.OK
    assert "requestable_authorization_group_approval_rule_missing" in body
    assert "PIPELINE_GROUP" in body
    assert "operator" in body
    assert "ALLOW_PIPELINE_CREATE" in body


def test_ops1_console_owner_can_read_unowned_app_detail() -> None:
    # Given: 用户只拥有 CRM App, 不拥有 ERP App。
    client = _logged_in_client("owner-ops1-scope")
    crm = App.objects.create(app_key="ops1-owned-crm", name="Owned CRM")
    erp = App.objects.create(app_key="ops1-unowned-erp", name="Unowned ERP")
    _ = AppMembership.objects.create(app=crm, user_id="owner-ops1-scope", role="owner")

    # When: 用户直连未负责 App 的详情页。
    response = client.get(f"/console/apps/{erp.app_key}/")

    # Then: 控制台不再按成员关系隐藏 App 详情页。
    assert response.status_code == HTTPStatus.OK


def test_ops1_console_entry_redirects_unauthenticated_user_to_authentik_login() -> None:
    # Given: 未建立 Authentik 控制台会话。
    client = Client(HTTP_HOST="localhost")

    # When: 用户访问控制台入口。
    response = client.get("/console/?tab=roles")

    # Then: 控制台跳转到 OIDC 登录并携带当前本地路径。
    assert response.status_code == HTTPStatus.FOUND
    assert response.headers["Location"] == "/auth/login/?next=/console/%3Ftab%3Droles"


@override_settings(DEBUG=True)
def test_ops1_console_entry_requires_login_even_in_debug_mode() -> None:
    # Given: 未登录浏览器; 本地开发免登已移除, DEBUG 模式也不再自动绑定会话。
    client = Client(HTTP_HOST="localhost")

    # When: 直接打开控制台首页。
    response = client.get("/console/")

    # Then: 匿名访问一律跳转统一登录入口, 不产生任何会话。
    assert response.status_code == HTTPStatus.FOUND
    assert response.headers["Location"] == "/auth/login/?next=/console/"
    assert AUTHENTIK_SESSION_KEY not in client.session
    assert AUTHENTIK_GROUPS_SESSION_KEY not in client.session


def test_ops1_console_entry_serves_shell_for_non_admin_console_user() -> None:
    # Given: 已登录但没有超管组的普通用户。
    client = _non_admin_client("developer-no-console")

    # When: 打开控制台首页。
    response = client.get("/console/")

    # Then: 控制台壳对登录用户可用, App 级权限由成员角色控制。
    assert response.status_code == HTTPStatus.OK
    assert 'data-easyauth-react-shell="console"' in response.content.decode()


def test_ops1_console_app_detail_hides_app_from_non_member_user() -> None:
    # Given: 已登录但与该 App 无成员关系的用户。
    client = _non_admin_client("developer-no-console-detail")
    app = App.objects.create(app_key="ops1-no-console", name="No Console")

    # When: 直接访问该 App 的控制台详情页。
    response = client.get(f"/console/apps/{app.app_key}/")

    # Then: 按不存在处理, 不暴露未授权 App。
    assert response.status_code == HTTPStatus.NOT_FOUND


def test_ops1_console_app_detail_legacy_form_post_is_closed() -> None:
    # Given: owner 管理一个 App。
    client = _logged_in_client("owner-ops1-legacy-post")
    app = App.objects.create(app_key="ops1-console-legacy-post", name="Legacy Post")
    _ = AppMembership.objects.create(app=app, user_id="owner-ops1-legacy-post", role="owner")

    # When: owner 直连旧 Django 表单 POST 入口。
    response = client.post(
        f"/console/apps/{app.app_key}/",
        data={
            "action": "create_role",
            "role_key": "legacy_operator",
            "role_name": "Legacy Operator",
        },
    )

    # Then: 旧表单入口已关闭, 不再渲染旧 HTML UI, 也不执行 legacy action。
    body = response.content.decode()
    assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED
    assert "旧控制台表单入口已关闭" in body
    assert "联调测试台" not in body


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


def test_ops1_console_permission_template_apply_imports_catalog() -> None:
    # Given: owner 准备从空 App 导入权限模板。
    client = _logged_in_client("owner-ops1-template-apply")
    app = App.objects.create(app_key="ops1-console-template-apply", name="Template Apply")
    _ = AppMembership.objects.create(app=app, user_id="owner-ops1-template-apply", role="owner")

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

    # Then: 模板创建分组和叶子权限, 权限树展示新目录。
    tree = client.get(_api_url(app.app_key, "permission-tree"))
    body = tree.content.decode()
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


def _logged_in_client(username: str, *, enforce_csrf_checks: bool = False) -> Client:
    return _login_client(username=username, enforce_csrf_checks=enforce_csrf_checks)


def _login_client(*, username: str, enforce_csrf_checks: bool) -> Client:
    user, _created = UserMirror.objects.get_or_create(authentik_user_id=username)
    client = Client(HTTP_HOST="localhost", enforce_csrf_checks=enforce_csrf_checks)
    session = client.session
    session[AUTHENTIK_SESSION_KEY] = user.authentik_user_id
    session[AUTHENTIK_GROUPS_SESSION_KEY] = ["EasyAuth Admins"]
    session.save()
    return client


def _non_admin_client(username: str) -> Client:
    user, _created = UserMirror.objects.get_or_create(authentik_user_id=username)
    client = Client(HTTP_HOST="localhost")
    session = client.session
    session[AUTHENTIK_SESSION_KEY] = user.authentik_user_id
    session.save()
    return client


def _api_url(app_key: str, endpoint: str) -> str:
    return f"/console/api/v1/apps/{app_key}/{endpoint}"


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
