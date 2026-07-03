from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from secrets import token_urlsafe
from typing import TYPE_CHECKING, Final, override

from django.contrib.auth.hashers import PBKDF2PasswordHasher
from django.db import transaction
from django.utils import timezone

from easyauth.applications.models import App, AppCredential
from easyauth.audit.services import AuditRecord, AuditService

if TYPE_CHECKING:
    from easyauth.audit.models import JsonValue

APP_CREDENTIAL_STATIC_KIND: Final = "static_token"
STATIC_APP_TOKEN_ENTROPY_BYTES: Final = 32
STATIC_APP_CREDENTIAL_PREFIX: Final = "eat_"
APP_CREDENTIAL_CREATED_EVENT: Final = "app_credential_created"
APP_CREDENTIAL_ROTATED_EVENT: Final = "app_credential_rotated"


@dataclass(frozen=True, slots=True)
class AppPrincipal:
    app_id: int
    app_key: str
    credential_type: str
    credential_id: int


@dataclass(frozen=True, slots=True)
class IssuedStaticToken:
    credential: AppCredential
    plaintext_token: str


@dataclass(frozen=True, slots=True)
class StaticTokenIssue:
    credential_id: int
    plaintext_token: str


@dataclass(frozen=True, slots=True)
class StaticTokenAuthenticationError(Exception):
    @override
    def __str__(self) -> str:
        return "static app token authentication failed"


@dataclass(frozen=True, slots=True)
class StaticTokenAppDisabledError(Exception):
    app_id: int

    @override
    def __str__(self) -> str:
        return "static app token app is disabled"


@dataclass(frozen=True, slots=True)
class _StaticTokenAuditContext:
    event_type: str
    previous_credential_id: int | None = None


class AppCredentialService:
    @staticmethod
    @transaction.atomic
    def create_static_token(app: App, name: str = "") -> IssuedStaticToken:
        return _issue_static_token(
            app=app,
            name=name,
            audit_context=_StaticTokenAuditContext(APP_CREDENTIAL_CREATED_EVENT),
        )

    @staticmethod
    @transaction.atomic
    def rotate_static_token(
        app: App,
        name: str = "",
        previous_credential_id: int | None = None,
    ) -> IssuedStaticToken:
        credential_name = name if name else "rotated static token"
        return _issue_static_token(
            app=app,
            name=credential_name,
            audit_context=_StaticTokenAuditContext(
                APP_CREDENTIAL_ROTATED_EVENT,
                previous_credential_id,
            ),
        )

    @staticmethod
    @transaction.atomic
    def disable_static_token(credential: AppCredential) -> AppCredential:
        credential.is_active = False
        credential.disabled_at = timezone.now()
        credential.save(update_fields=["is_active", "disabled_at", "updated_at"])
        return credential

    @staticmethod
    def authenticate_static_token(plaintext_token: str) -> AppPrincipal | None:
        try:
            return _authenticate_static_token(plaintext_token)
        except (StaticTokenAuthenticationError, StaticTokenAppDisabledError):
            return None


class StaticTokenService:
    @staticmethod
    def create_token(*, app: App, name: str) -> StaticTokenIssue:
        issued_token = AppCredentialService.create_static_token(app=app, name=name)
        return StaticTokenIssue(
            credential_id=_model_id(issued_token.credential),
            plaintext_token=issued_token.plaintext_token,
        )

    @staticmethod
    def rotate_token(*, credential_id: int) -> StaticTokenIssue:
        credential = AppCredential.objects.select_related("app").get(id=credential_id)
        issued_token = AppCredentialService.rotate_static_token(
            app=credential.app,
            name=credential.name,
            previous_credential_id=credential_id,
        )
        return StaticTokenIssue(
            credential_id=_model_id(issued_token.credential),
            plaintext_token=issued_token.plaintext_token,
        )

    @staticmethod
    def authenticate(plaintext_token: str) -> AppPrincipal:
        try:
            return _authenticate_static_token(plaintext_token)
        except StaticTokenAppDisabledError as error:
            raise StaticTokenAuthenticationError from error

    @staticmethod
    def authenticate_for_api(plaintext_token: str) -> AppPrincipal:
        return _authenticate_static_token(plaintext_token)


def _generate_static_token() -> str:
    return f"{STATIC_APP_CREDENTIAL_PREFIX}{token_urlsafe(STATIC_APP_TOKEN_ENTROPY_BYTES)}"


def _authenticate_static_token(plaintext_token: str) -> AppPrincipal:
    if not plaintext_token.startswith(STATIC_APP_CREDENTIAL_PREFIX):
        raise StaticTokenAuthenticationError

    # 先用确定性查找键索引到唯一候选行, 再对单行跑 PBKDF2;
    # 垃圾令牌只花一次 SHA-256, 不会诱发全表慢哈希扫描。
    credentials = AppCredential.objects.select_related("app").filter(
        credential_type=APP_CREDENTIAL_STATIC_KIND,
        is_active=True,
        token_lookup=_static_token_lookup(plaintext_token),
    )
    for credential in credentials:
        if _verify_static_token(plaintext_token, credential.token_hash):
            if not credential.app.is_active:
                raise StaticTokenAppDisabledError(app_id=_model_id(credential.app))
            return AppPrincipal(
                app_id=_model_id(credential.app),
                app_key=credential.app.app_key,
                credential_type=credential.credential_type,
                credential_id=_model_id(credential),
            )

    raise StaticTokenAuthenticationError


APP_CREDENTIAL_TYPE_STATIC_TOKEN: Final = APP_CREDENTIAL_STATIC_KIND
STATIC_APP_TOKEN_PREFIX: Final = STATIC_APP_CREDENTIAL_PREFIX
StaticTokenAuthenticationFailed = StaticTokenAuthenticationError
StaticTokenAppDisabled = StaticTokenAppDisabledError


def _hash_static_token(plaintext_token: str) -> str:
    hasher = PBKDF2PasswordHasher()
    return hasher.encode(plaintext_token, hasher.salt())


def _static_token_lookup(plaintext_token: str) -> str:
    return sha256(plaintext_token.encode("utf-8")).hexdigest()


def _verify_static_token(plaintext_token: str, token_hash: str) -> bool:
    try:
        return PBKDF2PasswordHasher().verify(plaintext_token, token_hash)
    except ValueError:
        return False


def _issue_static_token(
    *,
    app: App,
    name: str,
    audit_context: _StaticTokenAuditContext,
) -> IssuedStaticToken:
    plaintext_token = _generate_static_token()
    credential = AppCredential.objects.create(
        app=app,
        credential_type=APP_CREDENTIAL_STATIC_KIND,
        name=name,
        token_hash=_hash_static_token(plaintext_token),
        token_lookup=_static_token_lookup(plaintext_token),
    )
    _record_app_credential_event(credential, audit_context)
    return IssuedStaticToken(credential=credential, plaintext_token=plaintext_token)


def _record_app_credential_event(
    credential: AppCredential,
    audit_context: _StaticTokenAuditContext,
) -> None:
    metadata: dict[str, JsonValue] = {
        "app_id": _model_id(credential.app),
        "app_key": credential.app.app_key,
        "credential_type": credential.credential_type,
    }
    previous_credential_id = audit_context.previous_credential_id
    if previous_credential_id is not None:
        metadata["previous_credential_id"] = previous_credential_id

    _ = AuditService.record(
        AuditRecord(
            actor_type="system",
            actor_id="easyauth",
            action=audit_context.event_type,
            target_type="app_credential",
            target_id=str(_model_id(credential)),
            metadata=metadata,
        ),
    )


def _model_id(model: App | AppCredential) -> int:
    return model.id
