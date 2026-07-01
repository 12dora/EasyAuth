from __future__ import annotations

from datetime import datetime, timedelta
from http import HTTPStatus
from json import dumps
from re import escape, findall, search
from typing import Final, Protocol

import pytest
from django.contrib.auth.models import User
from django.test import Client, override_settings
from django.utils import timezone

from easyauth.accounts.models import UserMirror
from easyauth.api.errors import ErrorCode
from easyauth.applications.models import (
    App,
    AppMembership,
    AppStaticToken,
    Permission,
    Role,
    RolePermission,
)
from easyauth.applications.services import StaticTokenService
from easyauth.audit.models import AuditLog
from easyauth.grants.models import AccessGrant, AccessGrantRole

pytestmark = pytest.mark.django_db

LOGIN_VALUE: Final = "console-login"
QUERY_TEST_API_URL: Final = "/console/api/v1/apps/{app_key}/permission-query-tests"


class HttpResponseLike(Protocol):
    content: bytes


def test_ops1_console_query_tester_runs_real_permission_query_without_storing_token() -> None:
    # Given: App 有静态 token, 测试用户有 active grant 和角色权限。
    client = _logged_in_client("owner-ops1-query-success")
    app = _owned_app("ops1-query-success", "owner-ops1-query-success")
    issue = StaticTokenService.create_token(app=app, name="query tester")
    user = UserMirror.objects.create(authentik_user_id="query-user")
    role = Role.objects.create(app=app, key="auditor", name="Auditor")
    permission = Permission.objects.create(app=app, key="invoice.read", name="Read invoices")
    _ = RolePermission.objects.create(role=role, permission=permission)
    grant = AccessGrant.objects.create(user=user, app=app)
    _ = AccessGrantRole.objects.create(grant=grant, role=role)

    # When: owner 通过 private API 粘贴 token 并查询测试用户。
    response = client.post(
        _query_test_api_url(app.app_key),
        data=dumps({"user_id": user.authentik_user_id, "token": issue.plaintext_token}),
        content_type="application/json",
    )

    # Then: API 返回真实权限结果, 审计 metadata 不保存明文 token。
    assert response.status_code == HTTPStatus.OK
    assert _json_bool(response, "allowed") is True
    assert _json_string_array(response, "roles") == ["auditor"]
    assert _json_string_array(response, "permissions") == ["invoice.read"]
    assert '"status_code": 200' in response.content.decode()
    audit_log = AuditLog.objects.get(event_type="permission_query_test_executed")
    assert issue.plaintext_token not in str(audit_log.metadata)


def test_ops1_console_query_tester_explains_401_403_and_422_errors() -> None:
    # Given: owner 有目标 App, 另一个 App 有不同 token。
    client = _logged_in_client("owner-ops1-query-errors")
    app = _owned_app("ops1-query-errors", "owner-ops1-query-errors")
    other_app = App.objects.create(app_key="ops1-query-other", name="Other")
    other_issue = StaticTokenService.create_token(app=other_app, name="other token")

    # When: 分别通过 private API 提交空用户、无效 token、跨 App token。
    missing_user = client.post(
        _query_test_api_url(app.app_key),
        data=dumps({"user_id": "", "token": "eat_bad"}),
        content_type="application/json",
    )
    invalid_token = client.post(
        _query_test_api_url(app.app_key),
        data=dumps({"user_id": "query-user", "token": "eat_bad"}),
        content_type="application/json",
    )
    mismatched_app = client.post(
        _query_test_api_url(app.app_key),
        data=dumps({"user_id": "query-user", "token": other_issue.plaintext_token}),
        content_type="application/json",
    )

    # Then: API 给出 422、401、403 的结构化解释。
    assert missing_user.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert _json_string(missing_user, "code") == ErrorCode.VALIDATION_ERROR
    assert invalid_token.status_code == HTTPStatus.UNAUTHORIZED
    assert "缺失或无效凭据" in invalid_token.content.decode()
    assert mismatched_app.status_code == HTTPStatus.FORBIDDEN
    assert "凭据绑定 App 与路径 app_key 不一致" in mismatched_app.content.decode()


def test_ops1_console_query_tester_rejects_disabled_token_and_disabled_app() -> None:
    # Given: owner 有目标 App, 同时存在禁用 token 和禁用 App 的 token。
    client = _logged_in_client("owner-ops1-query-disabled")
    app = _owned_app("ops1-query-disabled", "owner-ops1-query-disabled")
    disabled_token_issue = StaticTokenService.create_token(app=app, name="disabled token")
    _ = AppStaticToken.objects.filter(id=disabled_token_issue.credential_id).update(
        is_active=False,
    )
    disabled_app = App.objects.create(
        app_key="ops1-query-disabled-app",
        name="Disabled App",
        is_active=False,
    )
    disabled_app_issue = StaticTokenService.create_token(app=disabled_app, name="disabled app")

    # When: 联调 API 分别提交禁用 token 和禁用 App token。
    disabled_token = client.post(
        _query_test_api_url(app.app_key),
        data=dumps({"user_id": "query-user", "token": disabled_token_issue.plaintext_token}),
        content_type="application/json",
    )
    disabled_app_response = client.post(
        _query_test_api_url(disabled_app.app_key),
        data=dumps({"user_id": "query-user", "token": disabled_app_issue.plaintext_token}),
        content_type="application/json",
    )

    # Then: 禁用 token 为 401, 禁用 App 为 403, 与正式权限查询认证口径一致。
    assert disabled_token.status_code == HTTPStatus.UNAUTHORIZED
    assert _json_string(disabled_token, "code") == ErrorCode.AUTHENTICATION_FAILED
    assert disabled_app_response.status_code == HTTPStatus.FORBIDDEN
    assert _json_string(disabled_app_response, "code") == ErrorCode.PERMISSION_DENIED


def test_ops1_console_query_tester_preserves_submitted_token_bytes() -> None:
    # Given: owner 有目标 App 和有效 token。
    client = _logged_in_client("owner-ops1-query-token-bytes")
    app = _owned_app("ops1-query-token-bytes", "owner-ops1-query-token-bytes")
    issue = StaticTokenService.create_token(app=app, name="query tester")

    # When: 联调 API 提交末尾带空格的 token。
    response = client.post(
        _query_test_api_url(app.app_key),
        data=dumps({"user_id": "query-user", "token": f"{issue.plaintext_token} "}),
        content_type="application/json",
    )

    # Then: token 原样认证, 不通过额外 strip() 放宽正式 API 的 Bearer 行为。
    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert _json_string(response, "code") == ErrorCode.AUTHENTICATION_FAILED


@override_settings(EASYAUTH_PERMISSION_QUERY_CACHE_TTL_SECONDS="60")
def test_ops1_console_query_tester_uses_default_ttl_for_invalid_configuration() -> None:
    # Given: 联调 API 命中非法 TTL 配置。
    client = _logged_in_client("owner-ops1-query-invalid-ttl")
    app = _owned_app("ops1-query-invalid-ttl", "owner-ops1-query-invalid-ttl")
    issue = StaticTokenService.create_token(app=app, name="query tester")
    user = UserMirror.objects.create(authentik_user_id="query-invalid-ttl-user")
    grant = AccessGrant.objects.create(user=user, app=app)
    role = Role.objects.create(app=app, key="auditor", name="Auditor")
    _ = AccessGrantRole.objects.create(grant=grant, role=role)

    # When: owner 通过 private API 查询该用户。
    before = timezone.now()
    response = client.post(
        _query_test_api_url(app.app_key),
        data=dumps({"user_id": user.authentik_user_id, "token": issue.plaintext_token}),
        content_type="application/json",
    )
    after = timezone.now()

    # Then: 非法 TTL 退回默认 300 秒。
    assert response.status_code == HTTPStatus.OK
    expires_at = datetime.fromisoformat(_json_string(response, "expires_at"))
    assert before + timedelta(seconds=300) <= expires_at
    assert expires_at <= after + timedelta(seconds=300)


def test_ops1_console_query_tester_explains_internal_permission_query_error() -> None:
    # Given: App token 有效, 但测试用户数据状态异常会触发权限查询内部校验失败。
    client = _logged_in_client("owner-ops1-query-internal-error")
    app = _owned_app("ops1-query-internal-error", "owner-ops1-query-internal-error")
    issue = StaticTokenService.create_token(app=app, name="query tester")
    user = UserMirror.objects.create(authentik_user_id="query-broken-user", status="unsupported")
    grant = AccessGrant.objects.create(user=user, app=app)
    role = Role.objects.create(app=app, key="auditor", name="Auditor")
    _ = AccessGrantRole.objects.create(grant=grant, role=role)

    # When: owner 通过 private API 查询该用户。
    response = client.post(
        _query_test_api_url(app.app_key),
        data=dumps({"user_id": user.authentik_user_id, "token": issue.plaintext_token}),
        content_type="application/json",
    )

    # Then: API 返回 500 错误解释, 且审计 metadata 不保存明文 token。
    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    assert _json_string(response, "code") == ErrorCode.INTERNAL_ERROR
    assert "权限查询内部错误" in response.content.decode()
    audit_log = AuditLog.objects.get(event_type="permission_query_test_executed")
    assert issue.plaintext_token not in str(audit_log.metadata)


def test_ops1_console_integration_guide_contains_current_app_examples() -> None:
    # Given: 应用负责人需要读取 App 接入说明。
    client = _logged_in_client("owner-ops1-guide")
    app = _owned_app("ops1-guide", "owner-ops1-guide")
    _ = Role.objects.create(app=app, key="operator", name="Operator")
    _ = Permission.objects.create(app=app, key="invoice.read", name="Read invoices")

    # When: React shell 使用 private API 读取接入说明和权限目录。
    guide = client.get(_api_url(app.app_key, "integration-guide"))
    permissions = client.get(_api_url(app.app_key, "permissions"))

    # Then: API 包含 app_key、公共权限查询端点和当前权限目录。
    body = guide.content.decode() + permissions.content.decode()
    assert guide.status_code == HTTPStatus.OK
    assert permissions.status_code == HTTPStatus.OK
    assert app.app_key in body
    assert f"/api/v1/apps/{app.app_key}/users/{{user_id}}/permissions" in body
    assert "invoice.read" in body


def _api_url(app_key: str, endpoint: str) -> str:
    return f"/console/api/v1/apps/{app_key}/{endpoint}"


@pytest.mark.parametrize("membership_role", ["owner", "developer"])
def test_ops1_console_query_test_api_allows_owner_and_developer(
    membership_role: str,
) -> None:
    # Given: App 成员有 owner/developer 角色, 且测试用户有有效角色权限。
    username = f"ops1-query-api-{membership_role}"
    client = _logged_in_client(username)
    app = _member_app(f"ops1-query-api-{membership_role}", username, membership_role)
    issue = StaticTokenService.create_token(app=app, name="query api")
    user = UserMirror.objects.create(authentik_user_id=f"query-api-user-{membership_role}")
    role = Role.objects.create(app=app, key=f"auditor-{membership_role}", name="Auditor")
    permission = Permission.objects.create(
        app=app,
        key=f"invoice.{membership_role}.read",
        name="Read invoices",
    )
    _ = RolePermission.objects.create(role=role, permission=permission)
    grant = AccessGrant.objects.create(user=user, app=app)
    _ = AccessGrantRole.objects.create(grant=grant, role=role)

    # When: 成员通过 private console API 发起联调。
    response = client.post(
        _query_test_api_url(app.app_key),
        data=dumps(
            {
                "user_id": user.authentik_user_id,
                "token": issue.plaintext_token,
            },
        ),
        content_type="application/json",
    )

    # Then: API 返回真实权限结果, 并只记录一次不含明文 token 的审计。
    assert response.status_code == HTTPStatus.OK
    assert _json_bool(response, "allowed") is True
    assert _json_string_array(response, "roles") == [role.key]
    assert _json_string_array(response, "permissions") == [permission.key]
    audit_log = AuditLog.objects.get(event_type="permission_query_test_executed")
    assert audit_log.actor_id == username
    assert issue.plaintext_token not in str(audit_log.metadata)


def test_ops1_console_query_test_api_rejects_non_member() -> None:
    # Given: 登录用户不是目标 App 成员。
    client = _logged_in_client("ops1-query-api-outsider")
    app = App.objects.create(app_key="ops1-query-api-denied", name="Denied")

    # When: 非成员调用 App 的联调 API。
    response = client.post(
        _query_test_api_url(app.app_key),
        data=dumps({"user_id": "query-user", "token": "eat_bad"}),
        content_type="application/json",
    )

    # Then: API 返回统一权限错误, 且不写入联调审计。
    assert response.status_code == HTTPStatus.FORBIDDEN
    assert _json_string(response, "code") == ErrorCode.PERMISSION_DENIED
    assert AuditLog.objects.count() == 0


def test_ops1_console_query_test_api_returns_structured_validation_errors() -> None:
    # Given: owner 可访问目标 App。
    client = _logged_in_client("ops1-query-api-validation")
    app = _owned_app("ops1-query-api-validation", "ops1-query-api-validation")

    # When: 分别提交空 user_id 和非法 JSON 请求体。
    empty_user = client.post(
        _query_test_api_url(app.app_key),
        data=dumps({"user_id": " ", "token": "eat_bad"}),
        content_type="application/json",
    )
    invalid_payload = client.post(
        _query_test_api_url(app.app_key),
        data="{",
        content_type="application/json",
    )

    # Then: API 使用统一错误结构返回 422。
    assert empty_user.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert _json_string(empty_user, "code") == ErrorCode.VALIDATION_ERROR
    assert invalid_payload.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert _json_string(invalid_payload, "code") == ErrorCode.VALIDATION_ERROR


def _query_test_api_url(app_key: str) -> str:
    return QUERY_TEST_API_URL.format(app_key=app_key)


def _member_app(app_key: str, user_id: str, role: str) -> App:
    app = App.objects.create(app_key=app_key, name=app_key)
    _ = AppMembership.objects.create(app=app, user_id=user_id, role=role)
    return app


def _json_string(response: HttpResponseLike, key: str) -> str:
    return _json_field_match(response, key, r'"{key}"\s*:\s*"([^"]*)"')


def _json_string_array(response: HttpResponseLike, key: str) -> list[str]:
    array_content = _json_field_match(response, key, r'"{key}"\s*:\s*\[(.*?)\]')
    return findall(r'"([^"]*)"', array_content)


def _json_bool(response: HttpResponseLike, key: str) -> bool:
    return _json_field_match(response, key, r'"{key}"\s*:\s*(true|false)') == "true"


def _json_field_match(response: HttpResponseLike, key: str, pattern: str) -> str:
    match = search(pattern.format(key=escape(key)), response.content.decode())
    if match is None:
        raise AssertionError(response.content.decode())
    return match.group(1)


def _owned_app(app_key: str, owner_user_id: str) -> App:
    app = App.objects.create(app_key=app_key, name=app_key)
    _ = AppMembership.objects.create(app=app, user_id=owner_user_id, role="owner")
    return app


def _logged_in_client(username: str) -> Client:
    _ = User.objects.create_user(username=username, password=LOGIN_VALUE)
    client = Client(HTTP_HOST="localhost")
    assert client.login(username=username, password=LOGIN_VALUE) is True
    return client
