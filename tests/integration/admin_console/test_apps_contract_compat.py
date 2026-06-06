from __future__ import annotations

from datetime import datetime
from http import HTTPStatus
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
    PermissionTemplateVersion,
    Role,
    RolePermission,
)
from easyauth.applications.services import StaticTokenService

pytestmark = pytest.mark.django_db

LOGIN_VALUE: Final = "console-app-contract"
APPS_API_URL: Final = "/console/api/v1/apps"
EXPECTED_DETAIL_COUNT: Final = 2
JSON_VALUE_ADAPTER: Final[TypeAdapter[JsonValue]] = TypeAdapter(JsonValue)


class HttpResponseLike(Protocol):
    content: bytes


def test_apps_list_includes_documented_contract_fields() -> None:
    # Given: 系统管理员面对一个存在 active owner 的 App。
    client = _logged_in_superuser("apps-contract-list-admin")
    app = App.objects.create(app_key="apps-contract-list-crm", name="CRM")
    _ = AppMembership.objects.create(app=app, user_id="apps-contract-owner", role="owner")
    _ = AppMembership.objects.create(
        app=app,
        user_id="apps-contract-inactive-owner",
        role="owner",
        is_active=False,
    )

    # When: 系统管理员查询 App 列表。
    response = client.get(APPS_API_URL)

    # Then: 列表项同时保留旧字段并包含文档要求的兼容字段。
    body = _response_json_object(response)
    items = _json_list(body["items"])
    item = _json_object(items[0])
    assert response.status_code == HTTPStatus.OK
    assert item["app_key"] == app.app_key
    assert item["description"] == ""
    assert item["id"] == app.id
    assert item["owners"] == ["apps-contract-owner"]
    assert item["configuration_status"] == "blocking"
    assert isinstance(item["updated_at"], str)
    assert datetime.fromisoformat(item["updated_at"])


def test_apps_list_supports_documented_filters_and_pagination() -> None:
    # Given: 系统管理员面对 active/inactive App 和不同 owner。
    client = _logged_in_superuser("apps-contract-list-filter-admin")
    crm = App.objects.create(app_key="apps-contract-filter-crm", name="CRM")
    erp = App.objects.create(app_key="apps-contract-filter-erp", name="ERP", is_active=False)
    scm = App.objects.create(app_key="apps-contract-filter-scm", name="SCM")
    _ = AppMembership.objects.create(app=crm, user_id="apps-contract-filter-owner", role="owner")
    _ = AppMembership.objects.create(app=erp, user_id="apps-contract-filter-owner", role="owner")
    _ = AppMembership.objects.create(app=scm, user_id="apps-contract-filter-other", role="owner")

    # When: 按 active status、owner_user_id 和分页参数查询 App 列表。
    response = client.get(
        APPS_API_URL,
        {
            "page": "1",
            "page_size": "1",
            "status": "active",
            "owner_user_id": "apps-contract-filter-owner",
        },
    )

    # Then: API 只返回匹配 App, 且包含文档约定 pagination。
    body = _response_json_object(response)
    items = _json_list(body["items"])
    assert response.status_code == HTTPStatus.OK
    assert [_json_object(item)["app_key"] for item in items] == [crm.app_key]
    assert body["pagination"] == {
        "page": 1,
        "page_size": 1,
        "total_items": 1,
        "total_pages": 1,
    }


def test_app_detail_includes_documented_summary_fields() -> None:
    # Given: owner 可见一个含成员、Role、Permission、active 凭据和模板版本的 App。
    client = _logged_in_user("apps-contract-detail-owner")
    app = App.objects.create(app_key="apps-contract-detail-crm", name="CRM")
    _ = AppMembership.objects.create(app=app, user_id="apps-contract-detail-owner", role="owner")
    _ = AppMembership.objects.create(
        app=app,
        user_id="apps-contract-detail-developer",
        role="developer",
    )
    _ = AppMembership.objects.create(
        app=app,
        user_id="apps-contract-detail-inactive-developer",
        role="developer",
        is_active=False,
    )
    _ = Role.objects.create(app=app, key="sales", name="Sales")
    _ = Role.objects.create(app=app, key="finance", name="Finance")
    _ = Permission.objects.create(app=app, key="deal.read", name="Read deals")
    _ = Permission.objects.create(app=app, key="deal.write", name="Write deals")
    active_token = StaticTokenService.create_token(app=app, name="active")
    inactive_token = StaticTokenService.create_token(app=app, name="inactive")
    _ = AppCredential.objects.filter(id=inactive_token.credential_id).update(is_active=False)
    _ = PermissionTemplateVersion.objects.create(
        app=app,
        version=2,
        source="manual",
        content_hash="b" * 64,
        raw_template="version: 2",
        import_summary={"actions": ["create_permission"]},
        imported_by="apps-contract-detail-owner",
    )

    # When: owner 查询 App 详情。
    response = client.get(f"{APPS_API_URL}/{app.app_key}")

    # Then: 详情包含文档约定的成员、数量、凭据、模板和配置摘要字段。
    body = _response_json_object(response)
    item = _json_object(body["app"])
    assert response.status_code == HTTPStatus.OK
    assert active_token.credential_id != inactive_token.credential_id
    assert item["owners"] == ["apps-contract-detail-owner"]
    assert item["developers"] == ["apps-contract-detail-developer"]
    assert item["role_count"] == EXPECTED_DETAIL_COUNT
    assert item["permission_count"] == EXPECTED_DETAIL_COUNT
    assert item["active_credential_count"] == 1
    assert item["latest_template_version"] == {
        "version": 2,
        "status": "imported",
        "imported_by": "apps-contract-detail-owner",
        "action_count": 1,
    }
    assert item["configuration_summary"] == {
        "status": "blocking",
        "issue_count": 4,
        "blocking_count": 4,
        "warning_count": 0,
    }


def test_configuration_status_includes_items_alias_with_documented_target_fields() -> None:
    # Given: owner 可见一个 requestable Role 缺少 active ApprovalRule 的 App。
    client = _logged_in_user("apps-contract-config-owner")
    app = App.objects.create(app_key="apps-contract-config-crm", name="CRM")
    _ = AppMembership.objects.create(app=app, user_id="apps-contract-config-owner", role="owner")
    role = Role.objects.create(app=app, key="sales_manager", name="Sales Manager")
    permission = Permission.objects.create(app=app, key="deal.read", name="Read deals")
    _ = RolePermission.objects.create(role=role, permission=permission)
    _ = StaticTokenService.create_token(app=app, name="token")

    # When: owner 查询配置完整性。
    response = client.get(f"{APPS_API_URL}/{app.app_key}/configuration-status")

    # Then: 响应保留旧 issues, 并新增文档契约 items 目标字段。
    body = _response_json_object(response)
    issues = _json_list(body["issues"])
    items = _json_list(body["items"])
    item = _json_object(items[0])
    assert response.status_code == HTTPStatus.OK
    assert body["status"] == "blocking"
    assert items == issues
    assert item["level"] == "blocking"
    assert item["code"] == "requestable_role_approval_rule_missing"
    assert item["message"] == "requestable Role 必须存在 active ApprovalRule。"
    assert item["target_type"] == "role"
    assert item["target_id"] == "sales_manager"


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


def _json_list(value: JsonValue) -> list[JsonValue]:
    assert isinstance(value, list), value
    return value
