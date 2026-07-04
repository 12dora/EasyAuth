from __future__ import annotations

from http import HTTPStatus
from json import dumps
from typing import Any, Final, Protocol

import pytest
from django.contrib.auth.models import User
from django.test import Client
from pydantic import TypeAdapter

from easyauth.api.errors import JsonValue
from easyauth.applications.models import (
    App,
    AppCredential,
    AppMembership,
    AppScope,
    AuthorizationGroup,
    AuthorizationGroupGrant,
    Permission,
    PermissionGroup,
    PermissionTemplateVersion,
)
from easyauth.applications.oauth import OAuthClientService
from easyauth.applications.services import StaticTokenService

pytestmark = pytest.mark.django_db

LOGIN_VALUE: Final = "console-login"
MAX_CONFIRM_URL_PREVIEW_ID_LENGTH: Final = 256
ROOT_PERMISSION_GROUP_DEPTH: Final = 1
CHILD_PERMISSION_GROUP_DEPTH: Final = 2
GRANDCHILD_PERMISSION_GROUP_DEPTH: Final = 3
DETACHED_MISSING_LEAF_DEPTH: Final = 4
JSON_VALUE_ADAPTER: Final[TypeAdapter[JsonValue]] = TypeAdapter(JsonValue)


class HttpResponseLike(Protocol):
    content: bytes


def test_ops1_template_preview_api_returns_manifest_diff_without_writing_database() -> None:
    client = _logged_in_client("ops1-manifest-api-developer")
    app = _member_app("ops1-manifest-api-preview", "ops1-manifest-api-developer", "developer")

    response = client.post(
        f"/console/api/v1/apps/{app.app_key}/permission-template-imports/preview",
        data=dumps({"template_format": "json", "template": dumps(_manifest_payload(app.app_key))}),
        content_type="application/json",
    )

    payload = _json_object(response)
    assert response.status_code == HTTPStatus.OK
    assert payload["app_key"] == app.app_key
    assert isinstance(payload["preview_id"], str)
    assert payload["summary"] == {
        "version": 1,
        "action_count": 6,
        "create_scope_count": 1,
        "update_scope_count": 0,
        "deactivate_scope_count": 0,
        "create_permission_group_count": 1,
        "update_permission_group_count": 0,
        "deactivate_permission_group_count": 0,
        "create_permission_count": 1,
        "update_permission_count": 0,
        "deactivate_permission_count": 0,
        "create_authorization_group_count": 1,
        "update_authorization_group_count": 0,
        "deactivate_authorization_group_count": 0,
        "create_approval_rule_count": 1,
        "update_approval_rule_count": 0,
        "deactivate_approval_rule_count": 0,
        "update_app_count": 1,
    }
    assert payload["changes"] == [
        {"action": "update_app", "key": app.app_key, "parent_key": ""},
        {"action": "create_scope", "key": "SELF", "parent_key": ""},
        {"action": "create_permission_group", "key": "billing", "parent_key": ""},
        {"action": "create_permission", "key": "billing.read", "parent_key": "billing"},
        {"action": "create_authorization_group", "key": "accountant", "parent_key": ""},
        {
            "action": "create_approval_rule",
            "key": "authorization_group:accountant",
            "parent_key": "",
        },
    ]
    assert PermissionTemplateVersion.objects.filter(app=app).count() == 0
    assert AppScope.objects.filter(app=app).count() == 0
    assert PermissionGroup.objects.filter(app=app).count() == 0
    assert Permission.objects.filter(app=app).count() == 0
    assert AuthorizationGroup.objects.filter(app=app).count() == 0


def test_ops1_template_confirm_api_imports_previewed_manifest() -> None:
    client = _logged_in_client("ops1-manifest-api-confirm-owner")
    app = _member_app("ops1-manifest-api-confirm", "ops1-manifest-api-confirm-owner", "owner")
    before_version = app.catalog_version
    preview_id = _preview_manifest(client, app)

    response = client.post(
        f"/console/api/v1/apps/{app.app_key}/permission-template-imports/{preview_id}/confirm",
    )

    payload = _json_object(response)
    app.refresh_from_db()
    auth_group = AuthorizationGroup.objects.get(app=app, key="accountant")
    assert response.status_code == HTTPStatus.OK
    assert payload["app_key"] == app.app_key
    assert payload["template_version"] == 1
    assert payload["template_version_detail"] == {
        "version": 1,
        "status": "imported",
        "imported_by": "ops1-manifest-api-confirm-owner",
        "action_count": 6,
    }
    assert app.name == "Manifest App"
    assert app.catalog_version == before_version + 1
    assert AppScope.objects.get(app=app, key="SELF").name == "本人"
    assert PermissionGroup.objects.get(app=app, key="billing").name == "账务"
    assert Permission.objects.get(app=app, key="billing.read").supported_scopes == ["SELF"]
    assert AuthorizationGroupGrant.objects.get(authorization_group=auth_group).scope_key == "SELF"
    assert (
        PermissionTemplateVersion.objects.get(app=app).import_summary["manifest_schema_version"]
        == 1
    )


def test_ops1_template_preview_uses_short_confirm_id_for_large_manifest() -> None:
    # Given: EasyTrade 这类真实 manifest 体积可能很大, preview_id 不能携带整份内容进 URL。
    client = _logged_in_client("ops1-manifest-api-large-owner")
    app = _member_app("ops1-manifest-api-large", "ops1-manifest-api-large-owner", "owner")
    manifest = _manifest_payload(app.app_key)
    manifest["app"]["description"] = "大型权限目录" * 1000

    preview = client.post(
        f"/console/api/v1/apps/{app.app_key}/permission-template-imports/preview",
        data=dumps({"template_format": "json", "template": dumps(manifest)}),
        content_type="application/json",
    )
    preview_id = _required_str(_json_object(preview), "preview_id")
    confirm = client.post(
        f"/console/api/v1/apps/{app.app_key}/permission-template-imports/{preview_id}/confirm",
    )

    assert preview.status_code == HTTPStatus.OK
    assert len(preview_id) < MAX_CONFIRM_URL_PREVIEW_ID_LENGTH
    assert confirm.status_code == HTTPStatus.OK, confirm.content.decode()
    assert PermissionTemplateVersion.objects.filter(app=app, version=1).exists()


def test_ops1_template_confirm_imports_nested_permission_groups() -> None:
    # Given: EasyTrade manifest 使用 domain.resource 形式的多层权限目录。
    client = _logged_in_client("ops1-manifest-api-nested-owner")
    app = _member_app("ops1-manifest-api-nested", "ops1-manifest-api-nested-owner", "owner")
    manifest = _manifest_payload(app.app_key)
    manifest["permission_groups"] = [
        {"key": "customer", "name": "客户", "display_order": 10},
        {
            "key": "customer.profile",
            "name": "客户资料",
            "parent_key": "customer",
            "display_order": 20,
        },
    ]
    manifest["permissions"][0]["group_key"] = "customer.profile"

    preview = client.post(
        f"/console/api/v1/apps/{app.app_key}/permission-template-imports/preview",
        data=dumps({"template_format": "json", "template": dumps(manifest)}),
        content_type="application/json",
    )
    preview_id = _required_str(_json_object(preview), "preview_id")
    confirm = client.post(
        f"/console/api/v1/apps/{app.app_key}/permission-template-imports/{preview_id}/confirm",
    )

    assert confirm.status_code == HTTPStatus.OK, confirm.content.decode()
    parent = PermissionGroup.objects.get(app=app, key="customer")
    child = PermissionGroup.objects.get(app=app, key="customer.profile")
    permission = Permission.objects.get(app=app, key="billing.read")
    assert parent.depth == ROOT_PERMISSION_GROUP_DEPTH
    assert child.parent == parent
    assert child.depth == CHILD_PERMISSION_GROUP_DEPTH
    assert permission.group == child


def test_ops1_template_confirm_reparents_existing_permission_groups() -> None:
    # Given: 已有目录树为 customer -> customer.profile。
    client = _logged_in_client("ops1-manifest-api-reparent-owner")
    app = _member_app("ops1-manifest-api-reparent", "ops1-manifest-api-reparent-owner", "owner")
    initial_manifest = _manifest_payload(app.app_key)
    initial_manifest["permission_groups"] = [
        {"key": "customer", "name": "客户", "display_order": 10},
        {
            "key": "customer.profile",
            "name": "客户资料",
            "parent_key": "customer",
            "display_order": 20,
        },
    ]
    initial_manifest["permissions"][0]["group_key"] = "customer.profile"
    _confirm_payload_manifest(client, app, initial_manifest)

    # When: 新版本合法地把目录重排为 customer.profile -> customer。
    reparent_manifest = _manifest_payload(app.app_key, version=2)
    reparent_manifest["permission_groups"] = [
        {
            "key": "customer",
            "name": "客户",
            "parent_key": "customer.profile",
            "display_order": 20,
        },
        {"key": "customer.profile", "name": "客户资料", "display_order": 10},
    ]
    reparent_manifest["permissions"][0]["group_key"] = "customer"
    confirm = _confirm_payload_manifest(client, app, reparent_manifest)

    # Then: 导入不应被旧 parent 关系误判成环, 最终树按 manifest 落库。
    assert confirm.status_code == HTTPStatus.OK, confirm.content.decode()
    parent = PermissionGroup.objects.get(app=app, key="customer.profile")
    child = PermissionGroup.objects.get(app=app, key="customer")
    permission = Permission.objects.get(app=app, key="billing.read")
    assert parent.parent is None
    assert parent.depth == ROOT_PERMISSION_GROUP_DEPTH
    assert child.parent == parent
    assert child.depth == CHILD_PERMISSION_GROUP_DEPTH
    assert permission.group == child


def test_ops1_template_confirm_reparents_group_before_deactivating_missing_child() -> None:
    # Given: 旧目录树里 b 是 a 的子目录, c 是独立目录。
    client = _logged_in_client("ops1-manifest-api-reparent-missing-owner")
    app = _member_app(
        "ops1-manifest-api-reparent-missing",
        "ops1-manifest-api-reparent-missing-owner",
        "owner",
    )
    initial_manifest = _manifest_payload(app.app_key)
    initial_manifest["permission_groups"] = [
        {"key": "a", "name": "A", "display_order": 10},
        {"key": "b", "name": "B", "parent_key": "a", "display_order": 20},
        {"key": "c", "name": "C", "display_order": 30},
    ]
    initial_manifest["permissions"][0]["group_key"] = "b"
    _confirm_payload_manifest(client, app, initial_manifest)

    # When: 新 manifest 把 a 挂到 c 下, 并遗漏旧子目录 b。
    reparent_manifest = _manifest_payload(app.app_key, version=2)
    reparent_manifest["permission_groups"] = [
        {"key": "c", "name": "C", "display_order": 10},
        {"key": "a", "name": "A", "parent_key": "c", "display_order": 20},
    ]
    reparent_manifest["permissions"][0]["group_key"] = "a"
    confirm = _confirm_payload_manifest(client, app, reparent_manifest)

    # Then: 缺失子目录 b 作为 missing 子树根被 detach 后停用, 保持历史目录树不变量。
    assert confirm.status_code == HTTPStatus.OK, confirm.content.decode()
    root = PermissionGroup.objects.get(app=app, key="c")
    retained = PermissionGroup.objects.get(app=app, key="a")
    missing_child = PermissionGroup.objects.get(app=app, key="b")
    assert root.depth == ROOT_PERMISSION_GROUP_DEPTH
    assert retained.parent == root
    assert retained.depth == CHILD_PERMISSION_GROUP_DEPTH
    assert missing_child.parent is None
    assert missing_child.depth == ROOT_PERMISSION_GROUP_DEPTH
    assert missing_child.is_active is False


def test_ops1_template_confirm_detaches_deep_missing_subtree_before_deactivate() -> None:
    # Given: 旧目录树里 a 的 missing 子树已达到最大深度。
    client = _logged_in_client("ops1-manifest-api-deep-missing-owner")
    app = _member_app(
        "ops1-manifest-api-deep-missing",
        "ops1-manifest-api-deep-missing-owner",
        "owner",
    )
    initial_manifest = _manifest_payload(app.app_key)
    initial_manifest["permission_groups"] = [
        {"key": "a", "name": "A", "display_order": 10},
        {"key": "b", "name": "B", "parent_key": "a", "display_order": 20},
        {"key": "d", "name": "D", "parent_key": "b", "display_order": 30},
        {"key": "e", "name": "E", "parent_key": "d", "display_order": 40},
        {"key": "f", "name": "F", "parent_key": "e", "display_order": 50},
        {"key": "c", "name": "C", "display_order": 60},
    ]
    initial_manifest["permissions"][0]["group_key"] = "f"
    _confirm_payload_manifest(client, app, initial_manifest)

    # When: 新 manifest 只保留 c 与 a, 并把 a 挂到 c 下。
    reparent_manifest = _manifest_payload(app.app_key, version=2)
    reparent_manifest["permission_groups"] = [
        {"key": "c", "name": "C", "display_order": 10},
        {"key": "a", "name": "A", "parent_key": "c", "display_order": 20},
    ]
    reparent_manifest["permissions"][0]["group_key"] = "a"
    confirm = _confirm_payload_manifest(client, app, reparent_manifest)

    # Then: missing 子树从保留父节点 detach 后停用, 不会被新活跃树挤到非法深度。
    assert confirm.status_code == HTTPStatus.OK, confirm.content.decode()
    retained = PermissionGroup.objects.get(app=app, key="a")
    missing_root = PermissionGroup.objects.get(app=app, key="b")
    missing_leaf = PermissionGroup.objects.get(app=app, key="f")
    assert retained.parent == PermissionGroup.objects.get(app=app, key="c")
    assert retained.depth == CHILD_PERMISSION_GROUP_DEPTH
    assert missing_root.parent is None
    assert missing_root.depth == ROOT_PERMISSION_GROUP_DEPTH
    assert missing_leaf.depth == DETACHED_MISSING_LEAF_DEPTH
    assert missing_leaf.is_active is False


def test_ops1_template_confirm_api_rejects_duplicate_or_old_version() -> None:
    client = _logged_in_client("ops1-manifest-api-conflict-owner")
    app = _member_app("ops1-manifest-api-conflict", "ops1-manifest-api-conflict-owner", "owner")
    first_preview_id = _preview_manifest(client, app)
    first_confirm = client.post(
        f"/console/api/v1/apps/{app.app_key}/permission-template-imports/{first_preview_id}/confirm",
    )
    duplicate_preview_id = _preview_manifest(client, app)

    duplicate_confirm = client.post(
        f"/console/api/v1/apps/{app.app_key}/permission-template-imports/{duplicate_preview_id}/confirm",
    )

    assert first_confirm.status_code == HTTPStatus.OK
    assert duplicate_confirm.status_code == HTTPStatus.CONFLICT
    assert PermissionTemplateVersion.objects.filter(app=app).count() == 1


def test_ops1_template_versions_api_returns_latest_first_with_pagination() -> None:
    latest_version: Final = 2
    owner_client = _logged_in_client("ops1-manifest-api-versions-owner")
    developer_client = _logged_in_client("ops1-manifest-api-versions-developer")
    app = _member_app("ops1-manifest-api-versions", "ops1-manifest-api-versions-owner", "owner")
    _ = AppMembership.objects.create(
        app=app,
        user_id="ops1-manifest-api-versions-developer",
        role="developer",
    )
    _confirm_manifest(owner_client, app)
    _confirm_manifest(owner_client, app, version=2)

    response = developer_client.get(
        f"/console/api/v1/apps/{app.app_key}/permission-template-versions",
        {"page": "1", "page_size": "1"},
    )

    payload = _json_object(response)
    assert response.status_code == HTTPStatus.OK
    assert payload["latest_version"] == latest_version
    assert payload["data"] == [
        {
            "version": 2,
            "status": "imported",
            "imported_by": "ops1-manifest-api-versions-owner",
            "action_count": 0,
        },
    ]


def test_ops1_template_confirm_api_rejects_developer_but_versions_are_readable() -> None:
    client = _logged_in_client("ops1-manifest-api-developer-readonly")
    app = _member_app(
        "ops1-manifest-api-readonly",
        "ops1-manifest-api-developer-readonly",
        "developer",
    )
    preview_id = _preview_manifest(client, app)

    confirm = client.post(
        f"/console/api/v1/apps/{app.app_key}/permission-template-imports/{preview_id}/confirm",
    )
    versions = client.get(f"/console/api/v1/apps/{app.app_key}/permission-template-versions")

    assert confirm.status_code == HTTPStatus.FORBIDDEN
    assert versions.status_code == HTTPStatus.OK
    assert _json_object(versions)["data"] == []
    assert PermissionTemplateVersion.objects.filter(app=app).count() == 0
    assert PermissionGroup.objects.filter(app=app).count() == 0
    assert Permission.objects.filter(app=app).count() == 0


def test_ops1_manifest_export_api_returns_replayable_current_state_without_secrets() -> None:
    client = _logged_in_client("ops1-manifest-api-export-owner")
    app = _member_app("ops1-manifest-api-export", "ops1-manifest-api-export-owner", "owner")
    static_issue = StaticTokenService.create_token(app=app, name="static integration")
    oauth_issue = OAuthClientService.create_client(app=app, name="oauth integration")
    _confirm_manifest(client, app)

    response = client.get(f"/console/api/v1/apps/{app.app_key}/manifest")
    body = response.content.decode()
    exported = _json_object(response)
    replay = client.post(
        f"/console/api/v1/apps/{app.app_key}/permission-template-imports/preview",
        data=dumps({"template_format": "json", "template": dumps(exported)}),
        content_type="application/json",
    )

    assert response.status_code == HTTPStatus.OK
    assert exported["app"]["app_key"] == app.app_key
    assert exported["scopes"] == [
        {
            "key": "SELF",
            "name": "本人",
            "description": "",
            "is_active": True,
            "display_order": 10,
        },
    ]
    assert _json_object(replay)["summary"]["action_count"] == 0
    assert static_issue.plaintext_token not in body
    assert AppCredential.objects.filter(app=app).first().token_hash not in body
    assert oauth_issue.client_secret not in body
    assert "secret" not in body.lower()
    assert "token" not in body.lower()


def test_ops1_manifest_import_export_roundtrips_bilingual_fields() -> None:
    # Given: owner 导入一个携带双语字段的 manifest。
    client = _logged_in_client("ops1-manifest-api-bilingual-owner")
    app = _member_app("ops1-manifest-api-bilingual", "ops1-manifest-api-bilingual-owner", "owner")
    manifest = _manifest_payload(app.app_key)
    manifest["scopes"] = [
        {
            "key": "SELF",
            "name": "本人",
            "name_en": "Self",
            "description": "",
            "description_en": "Only the requester",
            "display_order": 10,
        },
    ]
    preview = client.post(
        f"/console/api/v1/apps/{app.app_key}/permission-template-imports/preview",
        data=dumps({"template_format": "json", "template": dumps(manifest)}),
        content_type="application/json",
    )
    assert preview.status_code == HTTPStatus.OK, preview.content.decode()
    preview_id = _required_str(_json_object(preview), "preview_id")
    confirm = client.post(
        f"/console/api/v1/apps/{app.app_key}/permission-template-imports/{preview_id}/confirm",
    )
    assert confirm.status_code == HTTPStatus.OK, confirm.content.decode()

    # When: owner 导出 manifest 并回放导入 preview。
    response = client.get(f"/console/api/v1/apps/{app.app_key}/manifest")
    exported = _json_object(response)
    replay = client.post(
        f"/console/api/v1/apps/{app.app_key}/permission-template-imports/preview",
        data=dumps({"template_format": "json", "template": dumps(exported)}),
        content_type="application/json",
    )

    # Then: 双语字段仅在非空时输出, 且导出内容可无差异回放。
    assert response.status_code == HTTPStatus.OK
    assert exported["scopes"] == [
        {
            "key": "SELF",
            "name": "本人",
            "name_en": "Self",
            "description": "",
            "description_en": "Only the requester",
            "is_active": True,
            "display_order": 10,
        },
    ]
    permission_groups = exported["permission_groups"]
    assert isinstance(permission_groups, list)
    first_group = permission_groups[0]
    assert isinstance(first_group, dict)
    assert "name_en" not in first_group
    assert "description_en" not in first_group
    replay_summary = _json_object(replay)["summary"]
    assert isinstance(replay_summary, dict)
    assert replay_summary["action_count"] == 0


def test_ops1_integration_guide_api_returns_credential_summary_without_secrets() -> None:
    client = _logged_in_client("ops1-guide-api-owner")
    app = _member_app("ops1-guide-api", "ops1-guide-api-owner", "owner")
    static_issue = StaticTokenService.create_token(app=app, name="static integration")
    oauth_issue = OAuthClientService.create_client(app=app, name="oauth integration")

    response = client.get(f"/console/api/v1/apps/{app.app_key}/integration-guide")

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
    client = _logged_in_client("ops1-guide-api-outsider")
    app = App.objects.create(app_key="ops1-guide-api-private", name="Private")

    response = client.get(f"/console/api/v1/apps/{app.app_key}/integration-guide")

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


def _preview_manifest(client: Client, app: App, *, version: int = 1) -> str:
    response = client.post(
        f"/console/api/v1/apps/{app.app_key}/permission-template-imports/preview",
        data=dumps(
            {
                "template_format": "json",
                "template": dumps(_manifest_payload(app.app_key, version=version)),
            },
        ),
        content_type="application/json",
    )
    assert response.status_code == HTTPStatus.OK, response.content.decode()
    return _required_str(_json_object(response), "preview_id")


def _confirm_manifest(client: Client, app: App, *, version: int = 1) -> None:
    preview_id = _preview_manifest(client, app, version=version)
    response = client.post(
        f"/console/api/v1/apps/{app.app_key}/permission-template-imports/{preview_id}/confirm",
    )
    assert response.status_code == HTTPStatus.OK, response.content.decode()


def _confirm_payload_manifest(
    client: Client,
    app: App,
    manifest: dict[str, Any],
) -> HttpResponseLike:
    preview = client.post(
        f"/console/api/v1/apps/{app.app_key}/permission-template-imports/preview",
        data=dumps({"template_format": "json", "template": dumps(manifest)}),
        content_type="application/json",
    )
    assert preview.status_code == HTTPStatus.OK, preview.content.decode()
    preview_id = _required_str(_json_object(preview), "preview_id")
    return client.post(
        f"/console/api/v1/apps/{app.app_key}/permission-template-imports/{preview_id}/confirm",
    )


def _json_object(response: HttpResponseLike) -> dict[str, JsonValue]:
    payload = JSON_VALUE_ADAPTER.validate_json(response.content)
    assert isinstance(payload, dict), response.content.decode()
    return payload


def _required_str(payload: dict[str, JsonValue], key: str) -> str:
    value = payload.get(key)
    assert isinstance(value, str), payload
    return value


def _manifest_payload(app_key: str, *, version: int = 1) -> dict[str, Any]:
    return {
        "schema_version": version,
        "app": {
            "app_key": app_key,
            "name": "Manifest App",
            "description": "控制台导入测试",
        },
        "scopes": [
            {"key": "SELF", "name": "本人", "description": "", "display_order": 10},
        ],
        "permission_groups": [
            {"key": "billing", "name": "账务", "display_order": 10},
        ],
        "permissions": [
            {
                "key": "billing.read",
                "name": "查看账务",
                "description": "",
                "group_key": "billing",
                "supported_scopes": ["SELF"],
                "risk_level": "standard",
            },
        ],
        "authorization_groups": [
            {
                "key": "accountant",
                "kind": "role",
                "name": "会计",
                "description": "",
                "requestable": True,
                "is_active": True,
                "grants": [{"permission": "billing.read", "scope": "SELF"}],
            },
        ],
        "approval_rules": [
            {
                "target_type": "authorization_group",
                "target_key": "accountant",
                "approver_userids": ["manager-001"],
                "is_active": True,
            },
        ],
    }
