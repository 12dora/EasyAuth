from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from http import HTTPStatus
from re import escape, search
from typing import Final, Protocol

import pytest
from django.test import Client, override_settings
from django.utils import timezone as django_timezone
from oauth2_provider.generators import generate_client_secret
from oauth2_provider.models import AccessToken, Application

from easyauth.accounts.models import UserMirror
from easyauth.api.errors import ErrorCode
from easyauth.applications.models import (
    App,
    AppScope,
    AuthorizationGroup,
    AuthorizationGroupGrant,
    Permission,
)
from easyauth.applications.oauth import OAuthClientIssue, OAuthClientService
from easyauth.applications.services import StaticTokenService
from easyauth.audit.models import AuditLog
from easyauth.grants.models import (
    AccessGrant,
    AccessGrantGroup,
    AccessGrantPermission,
)

pytestmark = pytest.mark.django_db

PERMISSION_QUERY_TTL_SECONDS: Final = 120
FIXED_NOW: Final = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
EXPECTED_PERMISSION_QUERY_AUDIT_LOGS: Final = 2


class HttpResponseLike(Protocol):
    status_code: int
    content: bytes


def test_oauth_token_endpoint_issues_client_credentials_access_token_for_bound_app() -> None:
    # Given: EasyAuth 应用绑定了一个 confidential client credentials OAuth client。
    app = App.objects.create(app_key="crm-oauth-token", name="CRM OAuth Token")
    issue = _create_bound_oauth_client(app=app, name="CRM OAuth client")

    # When: OAuth client 使用 client credentials grant 换取 access token。
    response = Client().post(
        "/oauth/token",
        data={
            "grant_type": "client_credentials",
            "client_id": issue.client_id,
            "client_secret": issue.client_secret,
        },
    )

    # Then: token endpoint 返回 OAuth2 标准 token JSON, 并只持久化 token 校验材料。
    assert response.status_code == HTTPStatus.OK
    assert _json_string(response, "token_type") == "Bearer"
    access_token = _json_string(response, "access_token")
    assert access_token
    assert issue.client_secret not in _response_body(response)
    assert AccessToken.objects.filter(token_checksum=_token_checksum(access_token)).exists()


def test_oauth_token_endpoint_keeps_oauth_error_shape_for_invalid_client() -> None:
    # Given: 请求没有有效 OAuth client 凭据。
    client = Client()

    # When: 调用 OAuth token endpoint。
    response = client.post(
        "/oauth/token",
        data={
            "grant_type": "client_credentials",
            "client_id": "missing-client",
            "client_secret": "wrong-secret",
        },
    )

    # Then: 错误保持 OAuth2 标准 JSON, 不使用 EasyAuth /api/v1 envelope。
    assert response.status_code in {HTTPStatus.BAD_REQUEST, HTTPStatus.UNAUTHORIZED}
    body = _response_body(response)
    assert search(r'"error"\s*:\s*"invalid_client"', body) is not None
    assert search(r'"code"\s*:', body) is None
    assert search(r'"details"\s*:', body) is None


@override_settings(EASYAUTH_PERMISSION_QUERY_CACHE_TTL_SECONDS=PERMISSION_QUERY_TTL_SECONDS)
def test_permission_query_returns_identical_json_for_static_and_oauth_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: 同一应用、同一用户同时拥有静态 token 和绑定的 OAuth client credentials token。
    monkeypatch.setattr(django_timezone, "now", _fixed_now)
    user = UserMirror.objects.create(authentik_user_id="user-oauth-equivalent")
    app = App.objects.create(app_key="crm-oauth-equivalent", name="CRM OAuth Equivalent")
    static_issue = StaticTokenService.create_token(app=app, name="static integration")
    oauth_issue = _create_bound_oauth_client(app=app, name="CRM OAuth client")
    _ = AppScope.objects.create(app=app, key="GLOBAL", name="全局")
    admin = AuthorizationGroup.objects.create(
        app=app,
        key="admin",
        kind="role",
        name="管理员",
    )
    auditor = AuthorizationGroup.objects.create(
        app=app,
        key="auditor",
        kind="role",
        name="审计员",
    )
    approve = Permission.objects.create(
        app=app,
        key="invoice.approve",
        name="Approve invoices",
        supported_scopes=["GLOBAL"],
    )
    read = Permission.objects.create(
        app=app,
        key="invoice.read",
        name="Read invoices",
        supported_scopes=["GLOBAL"],
    )
    write = Permission.objects.create(
        app=app,
        key="invoice.write",
        name="Write invoices",
        supported_scopes=["GLOBAL"],
    )
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=admin,
        permission=write,
        scope_key="GLOBAL",
    )
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=auditor,
        permission=read,
        scope_key="GLOBAL",
    )
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=auditor,
        permission=write,
        scope_key="GLOBAL",
    )
    grant = AccessGrant.objects.create(user=user, app=app)
    _ = AccessGrantGroup.objects.create(grant=grant, authorization_group=auditor)
    _ = AccessGrantGroup.objects.create(grant=grant, authorization_group=admin)
    _ = AccessGrantPermission.objects.create(grant=grant, permission=approve, expires_at=None)
    oauth_access_token = _request_oauth_access_token(oauth_issue)

    # When: 静态 token 与 OAuth access token 分别查询同一用户权限。
    static_response = Client().get(
        _permission_url(app.app_key, user.authentik_user_id),
        HTTP_AUTHORIZATION=_bearer(static_issue.plaintext_token),
    )
    oauth_response = Client().get(
        _permission_url(app.app_key, user.authentik_user_id),
        HTTP_AUTHORIZATION=_bearer(oauth_access_token),
    )

    # Then: 两种凭据的业务响应完全一致, 审计 metadata 能区分凭据类型且不含明文密钥。
    assert static_response.status_code == HTTPStatus.OK
    assert oauth_response.status_code == HTTPStatus.OK
    assert _response_body(oauth_response) == _response_body(static_response)
    payload = static_response.json()
    assert payload["groups"] == [
        {"key": "admin", "kind": "role", "name": "管理员"},
        {"key": "auditor", "kind": "role", "name": "审计员"},
    ]
    assert payload["grants"] == [
        {
            "permission": "invoice.approve",
            "scope": "GLOBAL",
            "source_type": "direct",
            "source_key": "",
        },
        {
            "permission": "invoice.read",
            "scope": "GLOBAL",
            "source_type": "group",
            "source_key": "auditor",
        },
        {
            "permission": "invoice.write",
            "scope": "GLOBAL",
            "source_type": "group",
            "source_key": "admin",
        },
        {
            "permission": "invoice.write",
            "scope": "GLOBAL",
            "source_type": "group",
            "source_key": "auditor",
        },
    ]
    audit_logs = list(AuditLog.objects.filter(event_type="app_permission_queried").order_by("id"))
    assert len(audit_logs) == EXPECTED_PERMISSION_QUERY_AUDIT_LOGS
    assert audit_logs[0].metadata["credential_type"] == "static_token"
    assert audit_logs[1].metadata["credential_type"] == "oauth_client"
    assert static_issue.plaintext_token not in str(audit_logs[0].metadata)
    assert oauth_issue.client_secret not in str(audit_logs[1].metadata)
    assert oauth_access_token not in str(audit_logs[1].metadata)


def test_permission_query_rejects_invalid_unbound_and_disabled_oauth_tokens() -> None:
    # Given: 存在无效 token、未绑定 EasyAuth App 的 OAuth token、绑定禁用 App 的 OAuth token。
    app = App.objects.create(app_key="crm-oauth-errors", name="CRM OAuth Errors")
    disabled_app = App.objects.create(
        app_key="disabled-oauth-errors",
        name="Disabled OAuth Errors",
        is_active=False,
    )
    disabled_issue = _create_bound_oauth_client(app=disabled_app, name="disabled OAuth client")
    unbound_access_token = _request_unbound_oauth_access_token()
    disabled_access_token = _request_oauth_access_token(disabled_issue)

    # When: 这些 token 调用 /api/v1 权限查询接口。
    invalid = Client().get(
        _permission_url(app.app_key, "user-oauth-errors"),
        HTTP_AUTHORIZATION=_bearer("oauth-invalid-token"),
    )
    unbound = Client().get(
        _permission_url(app.app_key, "user-oauth-errors"),
        HTTP_AUTHORIZATION=_bearer(unbound_access_token),
    )
    disabled = Client().get(
        _permission_url(disabled_app.app_key, "user-oauth-errors"),
        HTTP_AUTHORIZATION=_bearer(disabled_access_token),
    )

    # Then: /api/v1 仍返回 EasyAuth 统一错误结构。
    _assert_error(
        invalid,
        status_code=HTTPStatus.UNAUTHORIZED,
        code=ErrorCode.AUTHENTICATION_FAILED,
    )
    _assert_error(
        unbound,
        status_code=HTTPStatus.UNAUTHORIZED,
        code=ErrorCode.AUTHENTICATION_FAILED,
    )
    _assert_error(
        disabled,
        status_code=HTTPStatus.FORBIDDEN,
        code=ErrorCode.PERMISSION_DENIED,
    )


def _create_bound_oauth_client(*, app: App, name: str) -> OAuthClientIssue:
    return OAuthClientService.create_client(app=app, name=name)


def _request_oauth_access_token(issue: OAuthClientIssue) -> str:
    response = Client().post(
        "/oauth/token",
        data={
            "grant_type": "client_credentials",
            "client_id": issue.client_id,
            "client_secret": issue.client_secret,
        },
    )
    assert response.status_code == HTTPStatus.OK
    return _json_string(response, "access_token")


def _request_unbound_oauth_access_token() -> str:
    plaintext_secret = generate_client_secret()
    oauth_application = Application.objects.create(
        name="Unbound OAuth client",
        client_type=Application.CLIENT_CONFIDENTIAL,
        authorization_grant_type=Application.GRANT_CLIENT_CREDENTIALS,
        client_secret=plaintext_secret,
    )
    response = Client().post(
        "/oauth/token",
        data={
            "grant_type": "client_credentials",
            "client_id": oauth_application.client_id,
            "client_secret": plaintext_secret,
        },
    )
    assert response.status_code == HTTPStatus.OK
    return _json_string(response, "access_token")


def _permission_url(app_key: str, user_id: str) -> str:
    return f"/api/v1/apps/{app_key}/users/{user_id}/permissions"


def _bearer(token: str) -> str:
    return f"Bearer {token}"


def _fixed_now() -> datetime:
    return FIXED_NOW


def _token_checksum(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def _json_string(response: HttpResponseLike, key: str) -> str:
    return _json_field_match(response, key, r'"{key}"\s*:\s*"([^"]*)"')


def _json_field_match(response: HttpResponseLike, key: str, pattern: str) -> str:
    match search(pattern.format(key=escape(key)), _response_body(response)):
        case None:
            raise AssertionError(_response_body(response))
        case result:
            return result.group(1)


def _response_body(response: HttpResponseLike) -> str:
    return response.content.decode()


def _assert_error(response: HttpResponseLike, *, status_code: HTTPStatus, code: ErrorCode) -> None:
    assert response.status_code == status_code
    body = _response_body(response)
    assert search(r'"code"\s*:\s*"' + escape(code.value) + r'"', body) is not None
    assert search(r'"message"\s*:\s*"[^"]*"', body) is not None
    assert search(r'"details"\s*:\s*\{\}', body) is not None
