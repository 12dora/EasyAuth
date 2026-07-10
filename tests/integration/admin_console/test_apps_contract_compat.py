from __future__ import annotations

from datetime import datetime
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
    AppCredential,
    AppMembership,
    ApprovalRule,
    AppScope,
    AuthorizationGroup,
    AuthorizationGroupGrant,
    Permission,
    PermissionTemplateVersion,
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
    items = _json_list(body["data"])
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
    items = _json_list(body["data"])
    assert response.status_code == HTTPStatus.OK
    assert [_json_object(item)["app_key"] for item in items] == [crm.app_key]
    assert body["pagination"] == {
        "page": 1,
        "page_size": 1,
        "total_items": 1,
        "total_pages": 1,
    }


def test_app_detail_includes_documented_summary_fields() -> None:
    # Given: owner 可见一个含成员、Permission、授权组、active 凭据和模板版本的 App。
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
    _ = AppScope.objects.create(app=app, key="GLOBAL", name="全局")
    read_permission = Permission.objects.create(
        app=app,
        key="deal.read",
        name="Read deals",
        supported_scopes=["GLOBAL"],
    )
    write_permission = Permission.objects.create(
        app=app,
        key="deal.write",
        name="Write deals",
        supported_scopes=["GLOBAL"],
    )
    sales_group = _authorization_group_with_rule(app=app, key="sales", name="Sales")
    finance_group = _authorization_group_with_rule(app=app, key="finance", name="Finance")
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=sales_group,
        permission=read_permission,
        scope_key="GLOBAL",
    )
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=finance_group,
        permission=write_permission,
        scope_key="GLOBAL",
    )
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
    assert item["authorization_group_count"] == EXPECTED_DETAIL_COUNT
    assert item["permission_count"] == EXPECTED_DETAIL_COUNT
    assert item["active_credential_count"] == 1
    assert item["latest_template_version"] == {
        "version": 2,
        "status": "imported",
        "imported_by": "apps-contract-detail-owner",
        "action_count": 1,
    }
    assert item["configuration_summary"] == {
        "status": "ready",
        "issue_count": 0,
        "blocking_count": 0,
        "warning_count": 0,
    }


def test_apps_create_success_response_uses_detail_contract() -> None:
    # Given: 系统管理员提交 App 创建请求。
    client = _logged_in_superuser("apps-contract-create-admin")

    # When: 创建 App。
    response = client.post(
        APPS_API_URL,
        data=dumps(
            {
                "app_key": "apps-contract-create-crm",
                "name": "CRM",
                "description": "客户管理",
                "owner_user_ids": ["apps-contract-create-owner"],
                "developer_user_ids": ["apps-contract-create-dev"],
            },
        ),
        content_type="application/json",
    )

    # Then: 成功响应使用完整 detail 契约。
    body = _response_json_object(response)
    item = _json_object(body["app"])
    assert response.status_code == HTTPStatus.CREATED
    assert set(item) == _expected_detail_fields()
    assert item["app_key"] == "apps-contract-create-crm"
    assert item["description"] == "客户管理"
    assert item["owners"] == ["apps-contract-create-owner"]
    assert item["developers"] == ["apps-contract-create-dev"]


def test_apps_patch_success_response_uses_detail_contract() -> None:
    # Given: owner 可见 CRM App。
    client = _logged_in_user("apps-contract-patch-owner")
    app = App.objects.create(app_key="apps-contract-patch-crm", name="CRM")
    _ = AppMembership.objects.create(app=app, user_id="apps-contract-patch-owner", role="owner")

    # When: owner 修改 name。
    response = client.patch(
        f"{APPS_API_URL}/{app.app_key}",
        data=dumps({"name": "CRM 新版"}),
        content_type="application/json",
    )

    # Then: 成功响应仍使用完整 detail 契约。
    body = _response_json_object(response)
    item = _json_object(body["app"])
    assert response.status_code == HTTPStatus.OK
    assert set(item) == _expected_detail_fields()
    assert item["app_key"] == app.app_key
    assert item["name"] == "CRM 新版"


def test_apps_create_and_patch_errors_use_documented_error_codes() -> None:
    # Given: 系统管理员和 developer 面对 App 写入错误场景。
    admin = _logged_in_superuser("apps-contract-errors-admin")
    developer = _logged_in_user("apps-contract-errors-dev")
    app = App.objects.create(app_key="apps-contract-errors-crm", name="CRM")
    _ = AppMembership.objects.create(app=app, user_id="apps-contract-errors-dev", role="developer")

    # When: 创建 payload 校验失败、重复创建、developer 修改 App。
    invalid_create = admin.post(
        APPS_API_URL,
        data=dumps({"app_key": "Invalid Key", "name": "CRM"}),
        content_type="application/json",
    )
    duplicate_create = admin.post(
        APPS_API_URL,
        data=dumps({"app_key": app.app_key, "name": "CRM"}),
        content_type="application/json",
    )
    forbidden_patch = developer.patch(
        f"{APPS_API_URL}/{app.app_key}",
        data=dumps({"name": "CRM 新版"}),
        content_type="application/json",
    )
    missing_patch = admin.patch(
        f"{APPS_API_URL}/apps-contract-errors-missing",
        data=dumps({"name": "CRM 新版"}),
        content_type="application/json",
    )

    # Then: 错误响应固定使用统一 error.code。
    assert invalid_create.status_code == HTTPStatus.BAD_REQUEST
    assert _error_code(invalid_create) == ErrorCode.VALIDATION_ERROR
    assert duplicate_create.status_code == HTTPStatus.CONFLICT
    assert _error_code(duplicate_create) == ErrorCode.CONFLICT
    assert forbidden_patch.status_code == HTTPStatus.FORBIDDEN
    assert _error_code(forbidden_patch) == ErrorCode.PERMISSION_DENIED
    assert missing_patch.status_code == HTTPStatus.NOT_FOUND
    assert _error_code(missing_patch) == ErrorCode.NOT_FOUND


def test_configuration_status_reports_documented_target_fields() -> None:
    # Given: owner 可见一个 requestable AuthorizationGroup 缺少 active ApprovalRule 的 App。
    client = _logged_in_user("apps-contract-config-owner")
    app = App.objects.create(app_key="apps-contract-config-crm", name="CRM")
    _ = AppMembership.objects.create(app=app, user_id="apps-contract-config-owner", role="owner")
    _ = AppScope.objects.create(app=app, key="GLOBAL", name="全局")
    role = AuthorizationGroup.objects.create(
        app=app,
        key="sales_manager",
        kind="role",
        name="Sales Manager",
        requestable=True,
    )
    permission = Permission.objects.create(
        app=app,
        key="deal.read",
        name="Read deals",
        supported_scopes=["GLOBAL"],
    )
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=role,
        permission=permission,
        scope_key="GLOBAL",
    )
    _ = StaticTokenService.create_token(app=app, name="token")

    # When: owner 查询配置完整性。
    response = client.get(f"{APPS_API_URL}/{app.app_key}/configuration-status")

    # Then: 响应以文档契约 items 字段返回配置问题及目标信息。
    body = _response_json_object(response)
    items = _json_list(body["data"])
    item = _json_object(items[0])
    assert response.status_code == HTTPStatus.OK
    assert body["status"] == "blocking"
    assert item["level"] == "blocking"
    assert item["code"] == "requestable_authorization_group_approval_rule_missing"
    assert item["message"] == "requestable AuthorizationGroup 必须存在 active ApprovalRule。"
    assert item["target_type"] == "authorization_group"
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


def _error_code(response: HttpResponseLike) -> JsonValue:
    body = _response_json_object(response)
    error = _json_object(body["error"])
    return error["code"]


def _authorization_group_with_rule(*, app: App, key: str, name: str) -> AuthorizationGroup:
    group = AuthorizationGroup.objects.create(
        app=app,
        key=key,
        kind="role",
        name=name,
        requestable=True,
    )
    _ = ApprovalRule.objects.create(
        app=app,
        authorization_group=group,
        approver_userids=["manager-001"],
    )
    return group


def _expected_detail_fields() -> set[str]:
    return {
        "id",
        "app_key",
        "name",
        "description",
        "is_active",
        "owners",
        "configuration_status",
        "updated_at",
        "can_manage",
        "developers",
        "authorization_group_count",
        "permission_count",
        "active_credential_count",
        "latest_template_version",
        "configuration_summary",
    }
