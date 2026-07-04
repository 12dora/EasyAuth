from __future__ import annotations

from http import HTTPStatus
from json import dumps
from typing import Final, Protocol

import pytest
from django.contrib.auth.models import User
from django.test import Client
from pydantic import TypeAdapter

from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.applications.models import (
    App,
    AppMembership,
    AppScope,
    OAuthClientBinding,
    Permission,
    PermissionGroup,
    Role,
)
from easyauth.audit.models import AuditLog

pytestmark = pytest.mark.django_db

LOGIN_VALUE: Final = "console-contract"
APPS_API_URL: Final = "/console/api/v1/apps"
JSON_VALUE_ADAPTER: Final[TypeAdapter[JsonValue]] = TypeAdapter(JsonValue)


class HttpResponseLike(Protocol):
    content: bytes


def test_ops_contract_list_responses_use_canonical_data_key() -> None:
    # Given: 系统管理员面对 App、成员、角色、权限、分组和凭据列表。
    client = _logged_in_superuser("ops-contract-list-admin")
    app = App.objects.create(app_key="ops-contract-list-app", name="Contract App")
    _ = AppMembership.objects.create(app=app, user_id="ops-contract-member", role="owner")
    _ = PermissionGroup.objects.create(app=app, key="ROOT", name="Root")
    _ = Role.objects.create(app=app, key="auditor", name="Auditor")
    _ = Permission.objects.create(app=app, key="reports.read", name="Read reports")

    # When: 调用文档定义为列表响应的 admin_console API。
    responses = [
        client.get(APPS_API_URL),
        client.get(f"{APPS_API_URL}/{app.app_key}/memberships"),
        client.get(f"{APPS_API_URL}/{app.app_key}/permission-groups"),
        client.get(f"{APPS_API_URL}/{app.app_key}/roles"),
        client.get(f"{APPS_API_URL}/{app.app_key}/permissions"),
        client.get(f"{APPS_API_URL}/{app.app_key}/credentials"),
    ]

    # Then: 每个列表响应只使用文档契约 `data`, 不再输出 legacy `items`。
    for response in responses:
        body = _response_json_object(response)
        assert response.status_code == HTTPStatus.OK
        assert isinstance(body["data"], list)
        assert "items" not in body


def test_ops_contract_owner_cannot_write_memberships() -> None:
    # Given: owner 可见并管理普通 App, 但成员写入契约限定 sysadmin。
    client = _logged_in_user("ops-contract-membership-owner")
    app = App.objects.create(app_key="ops-contract-membership-app", name="Membership App")
    membership = AppMembership.objects.create(
        app=app,
        user_id="ops-contract-membership-owner",
        role="owner",
    )

    # When: owner 尝试新增和停用 AppMembership。
    created = client.post(
        f"{APPS_API_URL}/{app.app_key}/memberships",
        data=dumps({"user_id": "ops-contract-new-member", "role": "developer"}),
        content_type="application/json",
    )
    patched = client.patch(
        f"{APPS_API_URL}/{app.app_key}/memberships/{membership.id}",
        data=dumps({"is_active": False}),
        content_type="application/json",
    )

    # Then: API 拒绝 owner 写入且数据未变更。
    membership.refresh_from_db()
    assert created.status_code == HTTPStatus.FORBIDDEN
    assert patched.status_code == HTTPStatus.FORBIDDEN
    error = _json_object(_response_json_object(created)["error"])
    assert error["code"] == ErrorCode.PERMISSION_DENIED
    assert AppMembership.objects.filter(user_id="ops-contract-new-member").exists() is False
    assert membership.is_active is True


def test_ops_contract_oauth_client_can_be_disabled_by_generic_route() -> None:
    # Given: owner 已创建 OAuth client credential。
    client = _logged_in_user("ops-contract-oauth-owner")
    app = _owned_app("ops-contract-oauth-app", "ops-contract-oauth-owner")
    created = client.post(
        f"{APPS_API_URL}/{app.app_key}/credentials/oauth-clients",
        data=dumps({"name": "oauth"}),
        content_type="application/json",
    )
    created_body = _response_json_object(created)
    credential_id = _json_int(_json_object(created_body["credential"])["id"])

    # When: 使用文档通用 disable route 禁用 OAuth client credential。
    disabled = client.post(
        f"{APPS_API_URL}/{app.app_key}/credentials/oauth-clients/{credential_id}/disable",
        data=dumps({"reason": "rotation"}),
        content_type="application/json",
    )

    # Then: API 返回 inactive OAuth credential, 数据库同步停用。
    binding = OAuthClientBinding.objects.get(id=credential_id)
    audit_log = AuditLog.objects.get(event_type="console_oauth_client_disabled")
    disabled_body = _response_json_object(disabled)
    assert disabled.status_code == HTTPStatus.OK
    assert _json_object(disabled_body["credential"])["kind"] == "oauth_client"
    assert _json_object(disabled_body["credential"])["is_active"] is False
    assert binding.is_active is False
    assert audit_log.metadata["reason"] == "rotation"


@pytest.mark.parametrize(
    ("endpoint", "lookup_key", "payload", "model"),
    [
        ("permission-groups", "ROOT", {"name": "Root Updated"}, PermissionGroup),
        ("roles", "auditor", {"description": "Updated"}, Role),
        ("permissions", "reports.read", {"name": "Read Reports Updated"}, Permission),
    ],
)
def test_ops_contract_catalog_patch_accepts_key_route(
    endpoint: str,
    lookup_key: str,
    payload: dict[str, str],
    model: type[PermissionGroup | Role | Permission],
) -> None:
    # Given: owner 管理已有 catalog 资源。
    client = _logged_in_user(f"ops-contract-{endpoint}-owner")
    app = _owned_app(f"ops-contract-{endpoint}-app", f"ops-contract-{endpoint}-owner")
    _seed_catalog_resource(app=app, endpoint=endpoint, key=lookup_key)

    # When: 按文档 key-based PATCH route 更新资源。
    response = client.patch(
        f"{APPS_API_URL}/{app.app_key}/{endpoint}/{lookup_key}",
        data=dumps(payload),
        content_type="application/json",
    )

    # Then: API 兼容 key route 并更新对应资源。
    instance = model.objects.get(app=app, key=lookup_key)
    assert response.status_code == HTTPStatus.OK
    for field_name, expected_value in payload.items():
        assert getattr(instance, field_name) == expected_value


def _seed_catalog_resource(*, app: App, endpoint: str, key: str) -> None:
    match endpoint:
        case "permission-groups":
            _ = PermissionGroup.objects.create(app=app, key=key, name=key)
        case "roles":
            _ = Role.objects.create(app=app, key=key, name=key)
        case "permissions":
            scope = AppScope.objects.create(app=app, key="GLOBAL", name="Global")
            _ = Permission.objects.create(
                app=app,
                key=key,
                name=key,
                supported_scopes=[scope.key],
            )
        case unreachable:
            raise AssertionError(unreachable)


def _owned_app(app_key: str, username: str) -> App:
    app = App.objects.create(app_key=app_key, name=app_key)
    _ = AppMembership.objects.create(app=app, user_id=username, role="owner")
    return app


def _logged_in_superuser(username: str) -> Client:
    _ = User.objects.create_superuser(username=username, password=LOGIN_VALUE)
    client = Client(HTTP_HOST="localhost")
    assert client.login(username=username, password=LOGIN_VALUE) is True
    return client


def _logged_in_user(username: str) -> Client:
    _ = User.objects.create_user(username=username, password=LOGIN_VALUE)
    client = Client(HTTP_HOST="localhost")
    assert client.login(username=username, password=LOGIN_VALUE) is True
    return client


def _response_json_object(response: HttpResponseLike) -> dict[str, JsonValue]:
    parsed = JSON_VALUE_ADAPTER.validate_json(response.content)
    assert isinstance(parsed, dict), response.content.decode()
    return parsed


def _json_object(value: JsonValue) -> dict[str, JsonValue]:
    assert isinstance(value, dict), value
    return value


def _json_int(value: JsonValue) -> int:
    assert isinstance(value, int), value
    return value
