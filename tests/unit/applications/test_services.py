from __future__ import annotations

import pytest
from django.contrib.auth.hashers import PBKDF2PasswordHasher

from easyauth.applications.models import App, AppStaticToken
from easyauth.applications.services import (
    StaticTokenAuthenticationFailed,
    StaticTokenIssue,
    StaticTokenService,
)
from easyauth.audit.models import AuditLog

pytestmark = pytest.mark.django_db
MINIMUM_STATIC_TOKEN_LENGTH = 40


def test_create_static_token_returns_prefixed_plaintext_and_stores_only_hash() -> None:
    # Given
    app = App.objects.create(app_key="crm", name="CRM")

    # When
    issue = StaticTokenService.create_token(app=app, name="CRM integration")

    # Then
    assert isinstance(issue, StaticTokenIssue)
    assert issue.plaintext_token.startswith("eat_")
    assert len(issue.plaintext_token) >= MINIMUM_STATIC_TOKEN_LENGTH
    credential = AppStaticToken.objects.get(id=issue.credential_id)
    assert credential.app == app
    assert credential.name == "CRM integration"
    assert credential.token_hash
    assert issue.plaintext_token not in credential.token_hash


def test_create_static_token_uses_django_password_hasher_when_stored() -> None:
    # Given
    app = App.objects.create(app_key="crm", name="CRM")

    # When
    issue = StaticTokenService.create_token(app=app, name="CRM integration")

    # Then
    credential = AppStaticToken.objects.get(id=issue.credential_id)
    hasher = PBKDF2PasswordHasher()
    assert credential.token_hash.startswith(f"{hasher.algorithm}$")
    assert hasher.verify(issue.plaintext_token, credential.token_hash) is True


def test_create_static_token_records_audit_event_without_plaintext() -> None:
    # Given
    app = App.objects.create(app_key="crm", name="CRM")

    # When
    issue = StaticTokenService.create_token(app=app, name="CRM integration")

    # Then
    audit_log = AuditLog.objects.get(event_type="app_credential_created")
    assert audit_log.actor_type == "system"
    assert audit_log.target_type == "app_credential"
    assert audit_log.target_id == str(issue.credential_id)
    assert audit_log.metadata["app_key"] == "crm"
    assert issue.plaintext_token not in str(audit_log.metadata)


def test_authenticate_static_token_resolves_bound_active_app() -> None:
    # Given
    app = App.objects.create(app_key="crm", name="CRM")
    issue = StaticTokenService.create_token(app=app, name="CRM integration")

    # When
    principal = StaticTokenService.authenticate(issue.plaintext_token)

    # Then
    assert principal.app_id == app.id
    assert principal.app_key == "crm"
    assert principal.credential_type == "static_token"
    assert principal.credential_id == issue.credential_id


def test_authenticate_static_token_rejects_invalid_or_disabled_token() -> None:
    # Given
    app = App.objects.create(app_key="crm", name="CRM")
    issue = StaticTokenService.create_token(app=app, name="CRM integration")
    _ = AppStaticToken.objects.filter(id=issue.credential_id).update(is_active=False)

    # When / Then
    with pytest.raises(StaticTokenAuthenticationFailed):
        _ = StaticTokenService.authenticate("eat_invalid-token")
    with pytest.raises(StaticTokenAuthenticationFailed):
        _ = StaticTokenService.authenticate(issue.plaintext_token)


def test_authenticate_static_token_skips_unparseable_stored_hash_when_resolving() -> None:
    # Given
    app = App.objects.create(app_key="crm", name="CRM")
    _ = AppStaticToken.objects.create(
        app=app,
        credential_type="static_token",
        name="legacy bad hash",
        token_hash=_unparseable_token_hash(),
    )
    issue = StaticTokenService.create_token(app=app, name="CRM integration")

    # When
    principal = StaticTokenService.authenticate(issue.plaintext_token)

    # Then
    assert principal.app_id == app.id
    assert principal.credential_id == issue.credential_id


def test_authenticate_static_token_rejects_disabled_app() -> None:
    # Given
    app = App.objects.create(app_key="crm", name="CRM", is_active=False)
    issue = StaticTokenService.create_token(app=app, name="CRM integration")

    # When / Then
    with pytest.raises(StaticTokenAuthenticationFailed):
        _ = StaticTokenService.authenticate(issue.plaintext_token)


def test_rotate_static_token_keeps_old_token_active_until_explicit_disable() -> None:
    # Given
    app = App.objects.create(app_key="crm", name="CRM")
    old_issue = StaticTokenService.create_token(app=app, name="CRM integration")

    # When
    new_issue = StaticTokenService.rotate_token(credential_id=old_issue.credential_id)

    # Then
    assert new_issue.plaintext_token.startswith("eat_")
    assert new_issue.plaintext_token != old_issue.plaintext_token
    old_principal = StaticTokenService.authenticate(old_issue.plaintext_token)
    new_principal = StaticTokenService.authenticate(new_issue.plaintext_token)
    old_credential = AppStaticToken.objects.get(id=old_issue.credential_id)
    assert old_credential.is_active is True
    assert old_principal.app_id == app.id
    assert old_principal.credential_id == old_issue.credential_id
    assert new_principal.app_id == app.id
    assert new_principal.credential_id == new_issue.credential_id


def test_rotate_static_token_records_audit_event_without_plaintext() -> None:
    # Given
    app = App.objects.create(app_key="crm", name="CRM")
    old_issue = StaticTokenService.create_token(app=app, name="CRM integration")

    # When
    new_issue = StaticTokenService.rotate_token(credential_id=old_issue.credential_id)

    # Then
    audit_log = AuditLog.objects.get(event_type="app_credential_rotated")
    assert audit_log.actor_type == "system"
    assert audit_log.target_type == "app_credential"
    assert audit_log.target_id == str(new_issue.credential_id)
    assert audit_log.metadata["previous_credential_id"] == old_issue.credential_id
    assert old_issue.plaintext_token not in str(audit_log.metadata)
    assert new_issue.plaintext_token not in str(audit_log.metadata)


def _unparseable_token_hash() -> str:
    return "not-a-django-password-hash"
