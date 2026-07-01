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
    assert PermissionTemplateVersion.objects.get(app=app).import_summary[
        "manifest_schema_version"
    ] == 1


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
    assert payload["items"] == [
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
    assert _json_object(versions)["items"] == []
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
