from __future__ import annotations

from hashlib import sha256

import pytest
from django.contrib.auth.hashers import PBKDF2PasswordHasher
from django.db import DatabaseError
from django.db.models.query import QuerySet
from django.test.utils import override_settings

from easyauth.applications.models import App, AppCredential
from easyauth.applications.services import (
    APP_CREDENTIAL_STATIC_KIND,
    LEGACY_STATIC_TOKEN_HASH_PREFIX,
    STATIC_APP_CREDENTIAL_PREFIX,
    STATIC_APP_TOKEN_ENTROPY_BYTES,
    STATIC_TOKEN_HASH_PREFIX,
    AppCredentialService,
    _maybe_upgrade_legacy_static_token_hash,
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
    assert credential.token_hash == _fast_token_hash(issued_token.plaintext_token)
    assert credential.token_hash.startswith(STATIC_TOKEN_HASH_PREFIX)
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
    )
    issued_token = AppCredentialService.create_static_token(app)
    _ = App.objects.filter(id=app.id).update(is_active=False)

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
    assert new_credential.token_hash.startswith(STATIC_TOKEN_HASH_PREFIX)
    assert new_credential.token_hash == _fast_token_hash(new_token.plaintext_token)


def test_fast_format_verify_does_not_invoke_pbkdf2(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: 新签发的凭据已是 sha256$ 格式。
    app = App.objects.create(app_key="crm-token-fast", name="CRM Token Fast")
    issued_token = AppCredentialService.create_static_token(app)
    monkeypatch.setattr(PBKDF2PasswordHasher, "verify", _fail_if_pbkdf2_called)

    # When / Then: 快路径不得调用 PBKDF2。
    principal = AppCredentialService.authenticate_static_token(issued_token.plaintext_token)
    assert principal is not None
    assert principal.credential_id == issued_token.credential.id


def test_legacy_pbkdf2_hash_is_upgraded_once_on_successful_verify(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: 库中仍是历史 PBKDF2 哈希。
    app = App.objects.create(app_key="crm-token-upgrade", name="CRM Token Upgrade")
    issued_token = AppCredentialService.create_static_token(app)
    credential_id = issued_token.credential.id
    legacy_hash = _replace_with_legacy_pbkdf2_hash(credential_id, issued_token.plaintext_token)
    assert legacy_hash.startswith(LEGACY_STATIC_TOKEN_HASH_PREFIX)

    # When: 首次成功校验后原地改写为快格式。
    principal = AppCredentialService.authenticate_static_token(issued_token.plaintext_token)

    # Then
    assert principal is not None
    upgraded_hash = AppCredential.objects.get(id=credential_id).token_hash
    assert upgraded_hash == _fast_token_hash(issued_token.plaintext_token)
    monkeypatch.setattr(PBKDF2PasswordHasher, "verify", _fail_if_pbkdf2_called)
    assert AppCredentialService.authenticate_static_token(issued_token.plaintext_token) is not None
    assert AppCredential.objects.get(id=credential_id).token_hash == upgraded_hash


def test_wrong_token_is_rejected_without_rewriting_hash() -> None:
    app = App.objects.create(app_key="crm-token-wrong", name="CRM Token Wrong")
    issued_token = AppCredentialService.create_static_token(app)
    stored_hash = AppCredential.objects.get(id=issued_token.credential.id).token_hash

    principal = AppCredentialService.authenticate_static_token(
        f"{STATIC_APP_CREDENTIAL_PREFIX}not-the-issued-token",
    )

    assert principal is None
    assert AppCredential.objects.get(id=issued_token.credential.id).token_hash == stored_hash


def test_unknown_hash_format_is_rejected() -> None:
    unknown_hash = "md5$not-supported"
    app = App.objects.create(app_key="crm-token-unknown", name="CRM Token Unknown")
    issued_token = AppCredentialService.create_static_token(app)
    AppCredential.objects.filter(id=issued_token.credential.id).update(token_hash=unknown_hash)

    principal = AppCredentialService.authenticate_static_token(issued_token.plaintext_token)

    assert principal is None
    assert AppCredential.objects.get(id=issued_token.credential.id).token_hash == unknown_hash


def test_garbage_token_does_not_invoke_pbkdf2(monkeypatch: pytest.MonkeyPatch) -> None:
    app = App.objects.create(app_key="crm-token-garbage", name="CRM Token Garbage")
    _ = AppCredentialService.create_static_token(app)
    monkeypatch.setattr(PBKDF2PasswordHasher, "verify", _fail_if_pbkdf2_called)

    principal = AppCredentialService.authenticate_static_token(
        f"{STATIC_APP_CREDENTIAL_PREFIX}garbage-token-with-no-row",
    )

    assert principal is None


def test_concurrent_legacy_upgrade_is_noop_when_row_already_changed() -> None:
    # Given: 本请求读到的仍是 PBKDF2 哈希, 但并发胜出方已写成快格式。
    app = App.objects.create(app_key="crm-token-concurrent", name="CRM Token Concurrent")
    issued_token = AppCredentialService.create_static_token(app)
    credential_id = issued_token.credential.id
    legacy_hash = _replace_with_legacy_pbkdf2_hash(credential_id, issued_token.plaintext_token)
    fast_hash = _fast_token_hash(issued_token.plaintext_token)
    AppCredential.objects.filter(id=credential_id).update(token_hash=fast_hash)
    stale_credential = AppCredential.objects.get(id=credential_id)
    stale_credential.token_hash = legacy_hash

    # When: 条件更新匹配不到旧哈希, 必须是 no-op。
    _maybe_upgrade_legacy_static_token_hash(
        credential=stale_credential,
        plaintext_token=issued_token.plaintext_token,
    )

    # Then
    assert AppCredential.objects.get(id=credential_id).token_hash == fast_hash


def test_legacy_upgrade_failure_does_not_fail_authentication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = App.objects.create(app_key="crm-token-upgrade-fail", name="CRM Token Upgrade Fail")
    issued_token = AppCredentialService.create_static_token(app)
    _ = _replace_with_legacy_pbkdf2_hash(issued_token.credential.id, issued_token.plaintext_token)
    original_update = QuerySet.update

    def fail_token_hash_update(self: QuerySet[AppCredential], **kwargs: object) -> int:
        if "token_hash" in kwargs:
            raise DatabaseError
        return original_update(self, **kwargs)

    monkeypatch.setattr(QuerySet, "update", fail_token_hash_update)

    principal = AppCredentialService.authenticate_static_token(issued_token.plaintext_token)

    assert principal is not None
    assert principal.credential_id == issued_token.credential.id


def test_static_token_verify_does_not_depend_on_secret_key() -> None:
    app = App.objects.create(app_key="crm-token-secret", name="CRM Token Secret")
    issued_token = AppCredentialService.create_static_token(app)
    expected_hash = _fast_token_hash(issued_token.plaintext_token)
    assert AppCredential.objects.get(id=issued_token.credential.id).token_hash == expected_hash

    with override_settings(SECRET_KEY="rotated-secret-key-must-not-invalidate-tokens"):
        principal = AppCredentialService.authenticate_static_token(issued_token.plaintext_token)

    assert principal is not None
    assert principal.credential_id == issued_token.credential.id


def _fast_token_hash(plaintext_token: str) -> str:
    return f"{STATIC_TOKEN_HASH_PREFIX}{sha256(plaintext_token.encode('utf-8')).hexdigest()}"


def _replace_with_legacy_pbkdf2_hash(credential_id: int, plaintext_token: str) -> str:
    hasher = PBKDF2PasswordHasher()
    hasher.iterations = 1
    legacy_hash = hasher.encode(plaintext_token, hasher.salt())
    updated = AppCredential.objects.filter(id=credential_id).update(token_hash=legacy_hash)
    assert updated == 1
    return legacy_hash


def _fail_if_pbkdf2_called(*_args: object, **_kwargs: object) -> bool:
    pytest.fail("fast-format / garbage tokens must not invoke PBKDF2")
