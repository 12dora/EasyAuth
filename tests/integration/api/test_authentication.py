from __future__ import annotations

import pytest
from django.test import RequestFactory
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied

from easyauth.api.authentication import AppBearerAuthentication, AppPrincipal
from easyauth.applications.models import App, AppStaticToken
from easyauth.applications.services import StaticTokenService

pytestmark = pytest.mark.django_db


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
