from __future__ import annotations

import pytest
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.test import RequestFactory
from django.test.utils import override_settings
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied

from easyauth.api.authentication import AppBearerAuthentication, AppPrincipal
from easyauth.api.permission_query_auth import permission_query_ttl_seconds
from easyauth.applications.models import App, AppStaticToken
from easyauth.applications.oauth import (
    APP_CREDENTIAL_TYPE_OAUTH_CLIENT,
    OAuthClientAppDisabledError,
    OAuthClientAuthenticationError,
    OAuthClientService,
)
from easyauth.applications.services import StaticTokenAuthenticationError, StaticTokenService

pytestmark = pytest.mark.django_db

DEFAULT_PERMISSION_QUERY_TTL_SECONDS = 300


def test_app_bearer_authentication_returns_app_principal_for_valid_static_token() -> None:
    # Given
    app = App.objects.create(app_key="crm", name="CRM")
    issue = StaticTokenService.create_token(app=app, name="CRM integration")
    request = RequestFactory().get(
        "/api/v1/auth-probe",
        HTTP_AUTHORIZATION=f"Bearer {issue.plaintext_token}",
    )

    # When
    result = AppBearerAuthentication().authenticate(request)

    # Then
    assert result is not None
    principal, auth = result
    assert isinstance(principal, AppPrincipal)
    assert auth is None
    assert principal.app_id == app.id
    assert principal.app_key == "crm"
    assert principal.credential_type == "static_token"
    assert principal.credential_id == issue.credential_id


def test_app_bearer_authentication_returns_none_when_authorization_is_missing() -> None:
    # Given
    request = RequestFactory().get("/api/v1/auth-probe")

    # When
    result = AppBearerAuthentication().authenticate(request)

    # Then
    assert result is None


def test_app_bearer_authentication_returns_oauth_principal_when_static_token_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    expected = AppPrincipal(
        app_id=123,
        app_key="crm-oauth",
        credential_type=APP_CREDENTIAL_TYPE_OAUTH_CLIENT,
        credential_id=456,
    )

    def reject_static_token(_token: str) -> AppPrincipal:
        raise StaticTokenAuthenticationError

    def accept_oauth_token(credential: str) -> AppPrincipal:
        assert credential == "oauth-access-token"
        return expected

    monkeypatch.setattr(StaticTokenService, "authenticate_for_api", reject_static_token)
    monkeypatch.setattr(OAuthClientService, "authenticate_access_token_for_api", accept_oauth_token)
    request = RequestFactory().get(
        "/api/v1/auth-probe",
        HTTP_AUTHORIZATION="Bearer oauth-access-token",
    )

    # When
    result = AppBearerAuthentication().authenticate(request)

    # Then
    assert result == (expected, None)


def test_app_bearer_authentication_raises_permission_denied_when_oauth_app_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    def reject_static_token(_token: str) -> AppPrincipal:
        raise StaticTokenAuthenticationError

    def reject_disabled_oauth_app(_token: str) -> AppPrincipal:
        raise OAuthClientAppDisabledError(app_id=1)

    monkeypatch.setattr(StaticTokenService, "authenticate_for_api", reject_static_token)
    monkeypatch.setattr(
        OAuthClientService,
        "authenticate_access_token_for_api",
        reject_disabled_oauth_app,
    )
    request = RequestFactory().get(
        "/api/v1/auth-probe",
        HTTP_AUTHORIZATION="Bearer oauth-disabled-token",
    )

    # When / Then
    with pytest.raises(PermissionDenied):
        _ = AppBearerAuthentication().authenticate(request)


def test_app_bearer_authentication_rejects_malformed_or_invalid_bearer_token() -> None:
    # Given
    malformed_request = RequestFactory().get(
        "/api/v1/auth-probe",
        HTTP_AUTHORIZATION="Token not-bearer",
    )
    invalid_request = RequestFactory().get(
        "/api/v1/auth-probe",
        HTTP_AUTHORIZATION="Bearer eat_invalid",
    )

    # When / Then
    with pytest.raises(AuthenticationFailed):
        _ = AppBearerAuthentication().authenticate(malformed_request)
    with pytest.raises(AuthenticationFailed):
        _ = AppBearerAuthentication().authenticate(invalid_request)


@pytest.mark.parametrize(
    "authorization",
    [
        "Bearer ",
        "Bearer",
        "Token abc",
    ],
)
def test_app_bearer_authentication_rejects_malformed_bearer_headers(
    monkeypatch: pytest.MonkeyPatch,
    authorization: str,
) -> None:
    # Given
    def fail_if_called(_token: str) -> AppPrincipal:
        raise AssertionError

    monkeypatch.setattr(StaticTokenService, "authenticate_for_api", fail_if_called)
    monkeypatch.setattr(OAuthClientService, "authenticate_access_token_for_api", fail_if_called)
    request = RequestFactory().get(
        "/api/v1/auth-probe",
        HTTP_AUTHORIZATION=authorization,
    )

    # When / Then
    with pytest.raises(AuthenticationFailed):
        _ = AppBearerAuthentication().authenticate(request)


def test_app_bearer_authentication_preserves_extra_bearer_whitespace_as_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    observed_tokens: list[str] = []

    def reject_static_token(token: str) -> AppPrincipal:
        observed_tokens.append(token)
        raise StaticTokenAuthenticationError

    def reject_oauth_token(token: str) -> AppPrincipal:
        observed_tokens.append(token)
        raise OAuthClientAuthenticationError

    monkeypatch.setattr(StaticTokenService, "authenticate_for_api", reject_static_token)
    monkeypatch.setattr(OAuthClientService, "authenticate_access_token_for_api", reject_oauth_token)
    request = RequestFactory().get(
        "/api/v1/auth-probe",
        HTTP_AUTHORIZATION="Bearer  token",
    )

    # When / Then
    with pytest.raises(AuthenticationFailed):
        _ = AppBearerAuthentication().authenticate(request)
    assert observed_tokens == [" token", " token"]


def test_app_bearer_authentication_rejects_disabled_token_and_disabled_app() -> None:
    # Given
    active_app = App.objects.create(app_key="crm", name="CRM")
    disabled_token_issue = StaticTokenService.create_token(app=active_app, name="Disabled token")
    _ = AppStaticToken.objects.filter(id=disabled_token_issue.credential_id).update(
        is_active=False,
    )
    disabled_app = App.objects.create(app_key="erp", name="ERP", is_active=False)
    disabled_app_issue = StaticTokenService.create_token(app=disabled_app, name="Disabled app")

    disabled_token_request = RequestFactory().get(
        "/api/v1/auth-probe",
        HTTP_AUTHORIZATION=f"Bearer {disabled_token_issue.plaintext_token}",
    )
    disabled_app_request = RequestFactory().get(
        "/api/v1/auth-probe",
        HTTP_AUTHORIZATION=f"Bearer {disabled_app_issue.plaintext_token}",
    )

    # When / Then
    with pytest.raises(AuthenticationFailed):
        _ = AppBearerAuthentication().authenticate(disabled_token_request)
    with pytest.raises(PermissionDenied):
        _ = AppBearerAuthentication().authenticate(disabled_app_request)


@pytest.mark.parametrize("invalid_ttl", [False, True, "60", None, 0, -1])
def test_permission_query_ttl_seconds_fails_fast_for_invalid_values(
    invalid_ttl: object,
) -> None:
    # 配错 TTL 必须启动失败; 静默回退默认值会悄悄延长撤销窗口。
    with (
        override_settings(EASYAUTH_PERMISSION_QUERY_CACHE_TTL_SECONDS=invalid_ttl),
        pytest.raises(ImproperlyConfigured),
    ):
        _ = permission_query_ttl_seconds()


def test_app_bearer_authentication_accepts_case_insensitive_scheme(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: RFC 7235 认证方案不区分大小写。
    observed_tokens: list[str] = []

    def record_token(token: str) -> AppPrincipal:
        observed_tokens.append(token)
        return AppPrincipal(
            app_id=1,
            app_key="case-app",
            credential_type="static_token",
            credential_id=1,
        )

    monkeypatch.setattr(StaticTokenService, "authenticate_for_api", record_token)
    request = RequestFactory().get(
        "/api/v1/auth-probe",
        HTTP_AUTHORIZATION="bearer eat_lower-case-scheme",
    )

    # When
    result = AppBearerAuthentication().authenticate(request)

    # Then
    assert result is not None
    assert observed_tokens == ["eat_lower-case-scheme"]


def test_permission_query_ttl_seconds_uses_default_when_setting_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delattr(settings, "EASYAUTH_PERMISSION_QUERY_CACHE_TTL_SECONDS", raising=False)

    assert permission_query_ttl_seconds() == DEFAULT_PERMISSION_QUERY_TTL_SECONDS
