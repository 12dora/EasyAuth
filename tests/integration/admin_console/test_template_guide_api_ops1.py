from __future__ import annotations

from http import HTTPStatus
from json import dumps
from typing import Final, Protocol

import pytest
from django.contrib.auth.models import User
from django.test import Client
from pydantic import TypeAdapter

from easyauth.api.errors import JsonValue
from easyauth.applications.models import (
    App,
    AppCredential,
    AppMembership,
    Permission,
    PermissionGroup,
    PermissionTemplateVersion,
    Role,
)
from easyauth.applications.oauth import OAuthClientService
from easyauth.applications.services import StaticTokenService

pytestmark = pytest.mark.django_db

LOGIN_VALUE: Final = "console-login"
JSON_VALUE_ADAPTER: Final[TypeAdapter[JsonValue]] = TypeAdapter(JsonValue)
TEMPLATE_YAML: Final = """
version: 1
groups:
  - key: BILLING
    name: 账务
    children:
      - key: BILLING_READ
        name: 查看账务
        type: permission
"""


class HttpResponseLike(Protocol):
    content: bytes


def test_ops1_template_preview_api_returns_diff_without_writing_database() -> None:
    # Given: developer 对目标 App 有 active membership, 并提交 YAML 权限模板。
    client = _logged_in_client("ops1-template-api-developer")
    app = _member_app("ops1-template-api-preview", "ops1-template-api-developer", "developer")

    # When: developer 调用控制台模板预览 API。
    response = client.post(
        f"/console/api/v1/apps/{app.app_key}/permission-template-imports/preview",
        data=dumps({"template_format": "yaml", "template": TEMPLATE_YAML}),
        content_type="application/json",
    )

    # Then: API 返回摘要和差异, 且不写入模板版本、分组或 Permission。
    payload = _json_object(response)
    assert response.status_code == HTTPStatus.OK
    assert payload["app_key"] == app.app_key
    assert isinstance(payload["preview_id"], str)
    assert payload["preview_id"]
    assert payload["summary"] == {
        "version": 1,
        "action_count": 2,
        "create_group_count": 1,
        "create_permission_count": 1,
        "update_group_count": 0,
        "update_permission_count": 0,
        "move_permission_count": 0,
        "deprecate_permission_count": 0,
    }
    assert payload["changes"] == [
        {"action": "create_group", "key": "BILLING", "parent_key": ""},
        {"action": "create_permission", "key": "BILLING_READ", "parent_key": "BILLING"},
    ]
    assert PermissionTemplateVersion.objects.filter(app=app).count() == 0
    assert PermissionGroup.objects.filter(app=app).count() == 0
    assert Permission.objects.filter(app=app).count() == 0


def test_ops1_template_confirm_api_imports_previewed_template() -> None:
    # Given: owner 预览一个包含分组和叶子权限的模板, 预览阶段不写入业务表。
    client = _logged_in_client("ops1-template-api-confirm-owner")
    app = _member_app("ops1-template-api-confirm", "ops1-template-api-confirm-owner", "owner")
    _ = Role.objects.create(app=app, key="operator", name="Operator")
    preview = client.post(
        f"/console/api/v1/apps/{app.app_key}/permission-template-imports/preview",
        data=dumps({"template_format": "yaml", "template": TEMPLATE_YAML}),
        content_type="application/json",
    )
    preview_id = _required_str(_json_object(preview), "preview_id")

    # When: owner 使用 preview_id 确认导入。
    response = client.post(
        f"/console/api/v1/apps/{app.app_key}/permission-template-imports/{preview_id}/confirm",
    )

    # Then: API 创建模板版本、权限组和 Permission, 但不改写已有角色。
    payload = _json_object(response)
    assert response.status_code == HTTPStatus.OK
    assert payload["app_key"] == app.app_key
    assert payload["summary"] == {
        "version": 1,
        "action_count": 2,
        "create_group_count": 1,
        "create_permission_count": 1,
        "update_group_count": 0,
        "update_permission_count": 0,
        "move_permission_count": 0,
        "deprecate_permission_count": 0,
    }
    assert payload["template_version"] == 1
    assert payload["template_version_detail"] == {
        "version": 1,
        "status": "imported",
        "imported_by": "ops1-template-api-confirm-owner",
        "action_count": 2,
    }
    assert PermissionTemplateVersion.objects.get(app=app).version == 1
    assert PermissionGroup.objects.get(app=app, key="BILLING").name == "账务"
    assert Permission.objects.get(app=app, key="BILLING_READ").group is not None
    assert Role.objects.get(app=app, key="operator").name == "Operator"


def test_ops1_template_confirm_api_rejects_duplicate_or_old_version() -> None:
    # Given: App 已通过确认 API 导入 v1, 随后又预览同版本模板。
    client = _logged_in_client("ops1-template-api-conflict-owner")
    app = _member_app("ops1-template-api-conflict", "ops1-template-api-conflict-owner", "owner")
    first_preview = client.post(
        f"/console/api/v1/apps/{app.app_key}/permission-template-imports/preview",
        data=dumps({"template_format": "yaml", "template": TEMPLATE_YAML}),
        content_type="application/json",
    )
    first_preview_id = _required_str(_json_object(first_preview), "preview_id")
    first_confirm = client.post(
        f"/console/api/v1/apps/{app.app_key}/permission-template-imports/{first_preview_id}/confirm",
    )
    duplicate_preview = client.post(
        f"/console/api/v1/apps/{app.app_key}/permission-template-imports/preview",
        data=dumps({"template_format": "yaml", "template": TEMPLATE_YAML}),
        content_type="application/json",
    )
    duplicate_preview_id = _required_str(_json_object(duplicate_preview), "preview_id")

    # When: owner 再次确认同版本模板。
    import_base_url = f"/console/api/v1/apps/{app.app_key}/permission-template-imports"
    duplicate_confirm = client.post(f"{import_base_url}/{duplicate_preview_id}/confirm")

    # Then: 第一次确认成功, 重复版本返回 409 且不产生第二个版本。
    assert first_confirm.status_code == HTTPStatus.OK
    assert duplicate_confirm.status_code == HTTPStatus.CONFLICT
    assert PermissionTemplateVersion.objects.filter(app=app).count() == 1
    old_app = _member_app("ops1-template-api-old", "ops1-template-api-conflict-owner", "owner")
    _confirm_template(client, old_app, TEMPLATE_YAML.replace("version: 1", "version: 2"))
    old_preview = client.post(
        f"/console/api/v1/apps/{old_app.app_key}/permission-template-imports/preview",
        data=dumps({"template_format": "yaml", "template": TEMPLATE_YAML}),
        content_type="application/json",
    )
    old_preview_id = _required_str(_json_object(old_preview), "preview_id")
    old_import_base_url = f"/console/api/v1/apps/{old_app.app_key}/permission-template-imports"
    old_confirm = client.post(f"{old_import_base_url}/{old_preview_id}/confirm")
    assert old_confirm.status_code == HTTPStatus.CONFLICT
    assert PermissionTemplateVersion.objects.filter(app=old_app).count() == 1


def test_ops1_template_versions_api_returns_latest_first_with_pagination() -> None:
    # Given: owner 已导入两个模板版本, developer 是同一 App 的 active 成员。
    latest_version: Final = 2
    owner_client = _logged_in_client("ops1-template-api-versions-owner")
    developer_client = _logged_in_client("ops1-template-api-versions-developer")
    app = _member_app("ops1-template-api-versions", "ops1-template-api-versions-owner", "owner")
    _ = AppMembership.objects.create(
        app=app,
        user_id="ops1-template-api-versions-developer",
        role="developer",
    )
    _confirm_template(owner_client, app, TEMPLATE_YAML)
    _confirm_template(owner_client, app, TEMPLATE_YAML.replace("version: 1", "version: 2"))

    # When: developer 分页读取模板版本列表。
    response = developer_client.get(
        f"/console/api/v1/apps/{app.app_key}/permission-template-versions",
        {"page": "1", "page_size": "1"},
    )

    # Then: API 允许只读访问, 按最新版本优先返回分页结果。
    payload = _json_object(response)
    assert response.status_code == HTTPStatus.OK
    assert payload["app_key"] == app.app_key
    assert payload["latest_version"] == latest_version
    assert payload["items"] == [
        {
            "version": 2,
            "status": "imported",
            "imported_by": "ops1-template-api-versions-owner",
            "action_count": 0,
        },
    ]
    assert payload["pagination"] == {
        "page": 1,
        "page_size": 1,
        "total_items": 2,
        "total_pages": 2,
    }


def test_ops1_template_confirm_api_rejects_developer_but_versions_are_readable() -> None:
    # Given: developer 可以查看 App 并预览模板。
    client = _logged_in_client("ops1-template-api-developer-readonly")
    app = _member_app(
        "ops1-template-api-readonly",
        "ops1-template-api-developer-readonly",
        "developer",
    )
    preview = client.post(
        f"/console/api/v1/apps/{app.app_key}/permission-template-imports/preview",
        data=dumps({"template_format": "yaml", "template": TEMPLATE_YAML}),
        content_type="application/json",
    )
    preview_id = _required_str(_json_object(preview), "preview_id")

    # When: developer 确认导入并读取版本列表。
    confirm = client.post(
        f"/console/api/v1/apps/{app.app_key}/permission-template-imports/{preview_id}/confirm",
    )
    versions = client.get(f"/console/api/v1/apps/{app.app_key}/permission-template-versions")

    # Then: 写操作被拒绝, 读操作允许, 且没有部分写入。
    assert confirm.status_code == HTTPStatus.FORBIDDEN
    assert versions.status_code == HTTPStatus.OK
    assert _json_object(versions)["items"] == []
    assert PermissionTemplateVersion.objects.filter(app=app).count() == 0
    assert PermissionGroup.objects.filter(app=app).count() == 0
    assert Permission.objects.filter(app=app).count() == 0


def test_ops1_integration_guide_api_returns_credential_summary_without_secrets() -> None:
    # Given: owner 的 App 同时存在静态 token 与 OAuth client credentials。
    client = _logged_in_client("ops1-guide-api-owner")
    app = _member_app("ops1-guide-api", "ops1-guide-api-owner", "owner")
    static_issue = StaticTokenService.create_token(app=app, name="static integration")
    oauth_issue = OAuthClientService.create_client(app=app, name="oauth integration")

    # When: owner 查询控制台接入指南 API。
    response = client.get(f"/console/api/v1/apps/{app.app_key}/integration-guide")

    # Then: API 返回 app_key、权限查询端点和凭据模式摘要, 不泄漏 token/secret/hash。
    body = response.content.decode()
    payload = _json_object(response)
    assert response.status_code == HTTPStatus.OK
    assert payload["app_key"] == app.app_key
    assert payload["permission_query_endpoint"] == (
        f"/api/v1/apps/{app.app_key}/users/{{user_id}}/permissions"
    )
    assert payload["credential_modes"] == [
        {"mode": "static_token", "active_count": 1},
        {"mode": "oauth_client_credentials", "active_count": 1},
    ]
    assert static_issue.plaintext_token not in body
    assert AppCredential.objects.get(app=app).token_hash not in body
    assert oauth_issue.client_secret not in body


def test_ops1_console_app_api_rejects_users_without_active_membership() -> None:
    # Given: 普通用户没有目标 App 的 active membership。
    client = _logged_in_client("ops1-guide-api-outsider")
    app = App.objects.create(app_key="ops1-guide-api-private", name="Private")

    # When: 用户查询控制台 App API。
    response = client.get(f"/console/api/v1/apps/{app.app_key}/integration-guide")

    # Then: API 不暴露该 App。
    assert response.status_code == HTTPStatus.NOT_FOUND


def _member_app(app_key: str, user_id: str, role: str) -> App:
    app = App.objects.create(app_key=app_key, name=app_key)
    _ = AppMembership.objects.create(app=app, user_id=user_id, role=role)
    return app


def _logged_in_client(username: str) -> Client:
    _ = User.objects.create_user(username=username, password=LOGIN_VALUE)
    client = Client(HTTP_HOST="localhost")
    assert client.login(username=username, password=LOGIN_VALUE) is True
    return client


def _confirm_template(client: Client, app: App, template: str) -> None:
    preview = client.post(
        f"/console/api/v1/apps/{app.app_key}/permission-template-imports/preview",
        data=dumps({"template_format": "yaml", "template": template}),
        content_type="application/json",
    )
    preview_id = _required_str(_json_object(preview), "preview_id")
    response = client.post(
        f"/console/api/v1/apps/{app.app_key}/permission-template-imports/{preview_id}/confirm",
    )
    assert response.status_code == HTTPStatus.OK


def _json_object(response: HttpResponseLike) -> dict[str, JsonValue]:
    payload = JSON_VALUE_ADAPTER.validate_json(response.content)
    assert isinstance(payload, dict), response.content.decode()
    return payload


def _required_str(payload: dict[str, JsonValue], key: str) -> str:
    value = payload.get(key)
    assert isinstance(value, str), payload
    return value
