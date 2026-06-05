from __future__ import annotations

import pytest

from easyauth.applications.models import App, AppCredential
from easyauth.applications.services import (
    APP_CREDENTIAL_STATIC_KIND,
    STATIC_APP_CREDENTIAL_PREFIX,
    STATIC_APP_TOKEN_ENTROPY_BYTES,
    AppCredentialService,
)

pytestmark = pytest.mark.django_db
MINIMUM_STATIC_TOKEN_ENTROPY_BYTES = 32


def test_create_static_token_hashes_plaintext_when_credential_is_created() -> None:
    # Given
    app = App.objects.create(app_key="crm-token-create", name="CRM Token Create")

    # When
    issued_token = AppCredentialService.create_static_token(app)

    # Then
    assert issued_token.plaintext_token.startswith(STATIC_APP_CREDENTIAL_PREFIX)
    assert STATIC_APP_TOKEN_ENTROPY_BYTES >= MINIMUM_STATIC_TOKEN_ENTROPY_BYTES
    credential = AppCredential.objects.get(id=issued_token.credential.id)
    assert credential.credential_type == APP_CREDENTIAL_STATIC_KIND
    assert credential.is_active is True
    assert credential.token_hash != issued_token.plaintext_token
    assert issued_token.plaintext_token not in {
        str(credential.id),
        str(credential.app.id),
        credential.credential_type,
        credential.token_hash,
    }


def test_authenticate_static_token_returns_app_principal_when_token_is_valid() -> None:
    # Given
    app = App.objects.create(app_key="crm-token-auth", name="CRM Token Auth")
    issued_token = AppCredentialService.create_static_token(app)

    # When
    principal = AppCredentialService.authenticate_static_token(issued_token.plaintext_token)

    # Then
    assert principal is not None
    assert principal.app_id == app.id
    assert principal.app_key == "crm-token-auth"
    assert principal.credential_type == APP_CREDENTIAL_STATIC_KIND
    assert principal.credential_id == issued_token.credential.id


def test_authenticate_static_token_returns_none_when_credential_is_disabled() -> None:
    # Given
    app = App.objects.create(app_key="crm-token-disabled", name="CRM Token Disabled")
    issued_token = AppCredentialService.create_static_token(app)
    credential = issued_token.credential
    credential.is_active = False
    credential.save(update_fields=["is_active", "updated_at"])

    # When
    principal = AppCredentialService.authenticate_static_token(issued_token.plaintext_token)

    # Then
    assert principal is None


def test_authenticate_static_token_returns_none_when_app_is_disabled() -> None:
    # Given
    app = App.objects.create(
        app_key="crm-token-disabled-app",
        name="CRM Token Disabled App",
        is_active=False,
    )
    issued_token = AppCredentialService.create_static_token(app)

    # When
    principal = AppCredentialService.authenticate_static_token(issued_token.plaintext_token)

    # Then
    assert principal is None


def test_rotate_static_token_keeps_old_credential_active_until_explicit_disable() -> None:
    # Given
    app = App.objects.create(app_key="crm-token-rotate", name="CRM Token Rotate")
    old_token = AppCredentialService.create_static_token(app)

    # When
    new_token = AppCredentialService.rotate_static_token(app)

    old_credential = AppCredential.objects.get(id=old_token.credential.id)
    new_credential = AppCredential.objects.get(id=new_token.credential.id)
    assert old_credential.is_active is True
    assert old_credential.disabled_at is None
    assert new_credential.is_active is True
    assert old_credential.token_hash != new_credential.token_hash
    assert old_token.plaintext_token != new_token.plaintext_token
    assert AppCredentialService.authenticate_static_token(old_token.plaintext_token) is not None
    assert AppCredentialService.authenticate_static_token(new_token.plaintext_token) is not None
