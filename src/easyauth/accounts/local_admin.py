# 本地超级管理员登录域逻辑: 密码 + 二次验证(TOTP / 通行密钥)。
# 不经 Authentik, 验证通过后复用 bind_oidc_session 以 local-admin: 前缀 subject
# 绑定会话, groups 取 EASYAUTH_CONSOLE_SUPERUSER_GROUPS, 因此天然是 console 超管。
from __future__ import annotations

import base64
import io
import time
from secrets import compare_digest, token_urlsafe
from typing import TYPE_CHECKING, Final

import pyotp
import qrcode
import qrcode.image.svg
import webauthn
from django.conf import settings as django_settings
from django.core.cache import cache
from django.utils import timezone
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.exceptions import (
    InvalidAuthenticationResponse,
    InvalidRegistrationResponse,
)
from webauthn.helpers.structs import PublicKeyCredentialDescriptor

from easyauth.accounts.auth import AUTHENTIK_SESSION_KEY, VerifiedOidcClaims, bind_oidc_session
from easyauth.accounts.models import LocalAdminAccount, LocalAdminPasskey
from easyauth.audit.services import AuditRecord, AuditService

if TYPE_CHECKING:
    from collections.abc import Mapping

    from django.http import HttpRequest

    from easyauth.accounts.models import UserMirror
    from easyauth.audit.models import JsonValue

LOCAL_ADMIN_SUBJECT_PREFIX: Final = "local-admin:"
LOCAL_ADMIN_ACTOR_TYPE: Final = "local_admin"
LOCAL_ADMIN_TARGET_TYPE: Final = "local_admin_account"
PENDING_SESSION_KEY: Final = "easyauth_local_admin_pending"
PENDING_TTL_SECONDS: Final = 600
CHALLENGE_SESSION_KEY: Final = "easyauth_local_admin_webauthn_challenge"
CHALLENGE_TTL_SECONDS: Final = 300
TOTP_SETUP_SESSION_KEY: Final = "easyauth_local_admin_totp_setup"
TOTP_SETUP_TTL_SECONDS: Final = 600
TOTP_CODE_LENGTH: Final = 6
LOGIN_FAILURE_LIMIT: Final = 5
LOGIN_FAILURE_WINDOW_SECONDS: Final = 300
SECOND_FACTOR_NONE: Final = "none"
SECOND_FACTOR_TOTP: Final = "totp"
SECOND_FACTOR_PASSKEY: Final = "passkey"
EVENT_LOGIN_SUCCEEDED: Final = "admin_local_login_succeeded"
EVENT_LOGIN_FAILED: Final = "admin_local_login_failed"
EVENT_SECOND_FACTOR_FAILED: Final = "admin_local_second_factor_failed"
EVENT_PASSWORD_CHANGED: Final = "admin_local_password_changed"  # noqa: S105 - 审计事件名, 不是密码值.
EVENT_PASSWORD_CHANGE_FAILED: Final = "admin_local_password_change_failed"  # noqa: S105 - 审计事件名, 不是密码值.
EVENT_TOTP_ENABLED: Final = "admin_local_totp_enabled"
EVENT_TOTP_DISABLED: Final = "admin_local_totp_disabled"
EVENT_PASSKEY_REGISTERED: Final = "admin_local_passkey_registered"
EVENT_PASSKEY_REMOVED: Final = "admin_local_passkey_removed"
SETTING_CONSOLE_SUPERUSER_GROUPS: Final = "EASYAUTH_CONSOLE_SUPERUSER_GROUPS"
SETTING_WEBAUTHN_RP_ID: Final = "EASYAUTH_WEBAUTHN_RP_ID"
SETTING_WEBAUTHN_RP_NAME: Final = "EASYAUTH_WEBAUTHN_RP_NAME"
SETTING_WEBAUTHN_ORIGINS: Final = "EASYAUTH_WEBAUTHN_ORIGINS"
REASON_CHALLENGE_MISSING: Final = "挑战已过期, 请重试。"
REASON_CREDENTIAL_MALFORMED: Final = "凭据格式不正确。"
REASON_CREDENTIAL_UNKNOWN: Final = "未找到匹配的通行密钥。"
REASON_CREDENTIAL_DUPLICATE: Final = "该通行密钥已注册过。"
REASON_VERIFICATION_FAILED: Final = "通行密钥验证失败。"


class LocalAdminConfigurationError(RuntimeError):
    pass


class PasskeyVerificationError(ValueError):
    pass


def local_admin_subject(username: str) -> str:
    return f"{LOCAL_ADMIN_SUBJECT_PREFIX}{username}"


def current_local_admin(request: HttpRequest) -> LocalAdminAccount | None:
    subject = request.session.get(AUTHENTIK_SESSION_KEY)
    if not isinstance(subject, str) or not subject.startswith(LOCAL_ADMIN_SUBJECT_PREFIX):
        return None
    username = subject[len(LOCAL_ADMIN_SUBJECT_PREFIX) :]
    return LocalAdminAccount.objects.filter(username=username, is_active=True).first()


def bind_local_admin_session(
    request: HttpRequest,
    account: LocalAdminAccount,
    *,
    second_factor: str,
) -> UserMirror:
    groups = _console_superuser_groups()
    if not groups:
        message = f"{SETTING_CONSOLE_SUPERUSER_GROUPS} is required for local admin login"
        raise LocalAdminConfigurationError(message)
    user = bind_oidc_session(
        request,
        VerifiedOidcClaims(
            subject=local_admin_subject(account.username),
            name=f"本地管理员 {account.username}",
            email=f"{account.username}@local.admin",
            groups=groups,
        ),
    )
    clear_pending_verification(request)
    reset_login_failures(account.username)
    _record_event(
        EVENT_LOGIN_SUCCEEDED,
        account.username,
        metadata={"second_factor": second_factor},
    )
    return user


def start_pending_verification(request: HttpRequest, account: LocalAdminAccount) -> None:
    request.session[PENDING_SESSION_KEY] = {
        "account_id": account.pk,
        "issued_at": time.time(),
    }


def pending_account(request: HttpRequest) -> LocalAdminAccount | None:
    payload = request.session.get(PENDING_SESSION_KEY)
    if not isinstance(payload, dict):
        return None
    account_id = payload.get("account_id")
    issued_at = payload.get("issued_at")
    if not isinstance(account_id, int) or not isinstance(issued_at, (int, float)):
        clear_pending_verification(request)
        return None
    if time.time() - float(issued_at) > PENDING_TTL_SECONDS:
        clear_pending_verification(request)
        return None
    account = LocalAdminAccount.objects.filter(pk=account_id, is_active=True).first()
    if account is None:
        clear_pending_verification(request)
        return None
    return account


def clear_pending_verification(request: HttpRequest) -> None:
    request.session.pop(PENDING_SESSION_KEY, None)
    request.session.pop(CHALLENGE_SESSION_KEY, None)


def login_is_throttled(username: str) -> bool:
    count = cache.get(_throttle_cache_key(username), 0)
    return isinstance(count, int) and count >= LOGIN_FAILURE_LIMIT


def record_login_failure(username: str) -> None:
    key = _throttle_cache_key(username)
    if cache.add(key, 1, LOGIN_FAILURE_WINDOW_SECONDS):
        return
    try:
        _ = cache.incr(key)
    except ValueError:
        cache.set(key, 1, LOGIN_FAILURE_WINDOW_SECONDS)


def reset_login_failures(username: str) -> None:
    cache.delete(_throttle_cache_key(username))


def record_login_failed(username: str, *, reason: str) -> None:
    _record_event(EVENT_LOGIN_FAILED, username, metadata={"reason": reason})


def record_second_factor_failed(username: str, *, method: str) -> None:
    _record_event(EVENT_SECOND_FACTOR_FAILED, username, metadata={"method": method})


def record_password_changed(username: str) -> None:
    _record_event(EVENT_PASSWORD_CHANGED, username)


def record_password_change_failed(username: str, *, reason: str) -> None:
    _record_event(EVENT_PASSWORD_CHANGE_FAILED, username, metadata={"reason": reason})


def record_totp_enabled(username: str) -> None:
    _record_event(EVENT_TOTP_ENABLED, username)


def record_totp_disabled(username: str) -> None:
    _record_event(EVENT_TOTP_DISABLED, username)


def record_passkey_registered(username: str, *, name: str) -> None:
    _record_event(EVENT_PASSKEY_REGISTERED, username, metadata={"name": name})


def record_passkey_removed(username: str, *, name: str) -> None:
    _record_event(EVENT_PASSKEY_REMOVED, username, metadata={"name": name})


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def verify_totp_code(secret: str, code: str) -> bool:
    normalized = code.strip().replace(" ", "")
    if secret == "" or len(normalized) != TOTP_CODE_LENGTH or not normalized.isdigit():
        return False
    return pyotp.TOTP(secret).verify(normalized, valid_window=1)


def totp_provisioning_uri(secret: str, username: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name=_webauthn_rp_name())


def totp_qr_data_uri(provisioning_uri: str) -> str:
    image = qrcode.make(provisioning_uri, image_factory=qrcode.image.svg.SvgPathImage)
    buffer = io.BytesIO()
    image.save(buffer)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def store_totp_setup_secret(request: HttpRequest, secret: str) -> None:
    request.session[TOTP_SETUP_SESSION_KEY] = {"secret": secret, "issued_at": time.time()}


def totp_setup_secret(request: HttpRequest) -> str:
    payload = request.session.get(TOTP_SETUP_SESSION_KEY)
    if not isinstance(payload, dict):
        return ""
    secret = payload.get("secret")
    issued_at = payload.get("issued_at")
    if not isinstance(secret, str) or not isinstance(issued_at, (int, float)):
        clear_totp_setup_secret(request)
        return ""
    if time.time() - float(issued_at) > TOTP_SETUP_TTL_SECONDS:
        clear_totp_setup_secret(request)
        return ""
    return secret


def clear_totp_setup_secret(request: HttpRequest) -> None:
    request.session.pop(TOTP_SETUP_SESSION_KEY, None)


def passkey_authentication_options(
    request: HttpRequest,
    account: LocalAdminAccount,
) -> tuple[str, str]:
    # 生成 WebAuthn 认证 options; 返回 (options JSON, state_token)。
    allow_credentials = [
        PublicKeyCredentialDescriptor(id=base64url_to_bytes(passkey.credential_id))
        for passkey in account.passkeys.all()
    ]
    options = webauthn.generate_authentication_options(
        rp_id=_webauthn_rp_id(),
        allow_credentials=allow_credentials,
    )
    state_token = _store_challenge(request, options.challenge)
    return webauthn.options_to_json(options), state_token


def verify_passkey_authentication(
    request: HttpRequest,
    account: LocalAdminAccount,
    credential: Mapping[str, object],
    *,
    state_token: str,
) -> None:
    challenge = _pop_challenge(request, state_token)
    if challenge is None:
        raise PasskeyVerificationError(REASON_CHALLENGE_MISSING)
    credential_id = _credential_id_from_payload(credential)
    passkey = account.passkeys.filter(credential_id=credential_id).first()
    if passkey is None:
        raise PasskeyVerificationError(REASON_CREDENTIAL_UNKNOWN)
    try:
        verified = webauthn.verify_authentication_response(
            credential=dict(credential),
            expected_challenge=challenge,
            expected_rp_id=_webauthn_rp_id(),
            expected_origin=list(_webauthn_origins()),
            credential_public_key=base64url_to_bytes(passkey.public_key),
            credential_current_sign_count=passkey.sign_count,
        )
    except InvalidAuthenticationResponse as error:
        raise PasskeyVerificationError(REASON_VERIFICATION_FAILED) from error
    passkey.sign_count = verified.new_sign_count
    passkey.last_used_at = timezone.now()
    passkey.save(update_fields=["sign_count", "last_used_at"])


def passkey_registration_options(
    request: HttpRequest,
    account: LocalAdminAccount,
) -> tuple[str, str]:
    # 生成 WebAuthn 注册 options; 返回 (options JSON, state_token)。
    exclude_credentials = [
        PublicKeyCredentialDescriptor(id=base64url_to_bytes(passkey.credential_id))
        for passkey in account.passkeys.all()
    ]
    options = webauthn.generate_registration_options(
        rp_id=_webauthn_rp_id(),
        rp_name=_webauthn_rp_name(),
        user_name=account.username,
        user_id=local_admin_subject(account.username).encode("utf-8"),
        user_display_name=f"本地管理员 {account.username}",
        exclude_credentials=exclude_credentials,
    )
    state_token = _store_challenge(request, options.challenge)
    return webauthn.options_to_json(options), state_token


def register_passkey(
    request: HttpRequest,
    account: LocalAdminAccount,
    credential: Mapping[str, object],
    *,
    state_token: str,
    name: str,
) -> LocalAdminPasskey:
    challenge = _pop_challenge(request, state_token)
    if challenge is None:
        raise PasskeyVerificationError(REASON_CHALLENGE_MISSING)
    try:
        verified = webauthn.verify_registration_response(
            credential=dict(credential),
            expected_challenge=challenge,
            expected_rp_id=_webauthn_rp_id(),
            expected_origin=list(_webauthn_origins()),
        )
    except InvalidRegistrationResponse as error:
        raise PasskeyVerificationError(REASON_VERIFICATION_FAILED) from error
    credential_id = bytes_to_base64url(verified.credential_id)
    if LocalAdminPasskey.objects.filter(credential_id=credential_id).exists():
        raise PasskeyVerificationError(REASON_CREDENTIAL_DUPLICATE)
    return LocalAdminPasskey.objects.create(
        account=account,
        credential_id=credential_id,
        public_key=bytes_to_base64url(verified.credential_public_key),
        sign_count=verified.sign_count,
        transports=_transports_from_payload(credential),
        name=name[:100],
    )


def _credential_id_from_payload(credential: Mapping[str, object]) -> str:
    raw_id = credential.get("rawId") or credential.get("id")
    if not isinstance(raw_id, str) or raw_id == "":
        raise PasskeyVerificationError(REASON_CREDENTIAL_MALFORMED)
    return raw_id


def _transports_from_payload(credential: Mapping[str, object]) -> list[str]:
    response = credential.get("response")
    if not isinstance(response, dict):
        return []
    transports = response.get("transports")
    if not isinstance(transports, list):
        return []
    return [item for item in transports if isinstance(item, str)]


def _store_challenge(request: HttpRequest, challenge: bytes) -> str:
    state_token = token_urlsafe(16)
    request.session[CHALLENGE_SESSION_KEY] = {
        "challenge": bytes_to_base64url(challenge),
        "state_token": state_token,
        "issued_at": time.time(),
    }
    return state_token


def _pop_challenge(request: HttpRequest, state_token: str) -> bytes | None:
    payload = request.session.pop(CHALLENGE_SESSION_KEY, None)
    if not isinstance(payload, dict):
        return None
    challenge = payload.get("challenge")
    stored_token = payload.get("state_token")
    issued_at = payload.get("issued_at")
    if (
        not isinstance(challenge, str)
        or not isinstance(stored_token, str)
        or not isinstance(issued_at, (int, float))
    ):
        return None
    if time.time() - float(issued_at) > CHALLENGE_TTL_SECONDS:
        return None
    if state_token == "" or not compare_digest(stored_token, state_token):
        return None
    return base64url_to_bytes(challenge)


def _record_event(
    action: str,
    username: str,
    *,
    metadata: Mapping[str, JsonValue] | None = None,
) -> None:
    _ = AuditService.record(
        AuditRecord(
            actor_type=LOCAL_ADMIN_ACTOR_TYPE,
            actor_id=username,
            action=action,
            target_type=LOCAL_ADMIN_TARGET_TYPE,
            target_id=username,
            metadata=metadata,
        ),
    )


def _throttle_cache_key(username: str) -> str:
    return f"easyauth-local-admin-login-failures:{username}"


def _console_superuser_groups() -> tuple[str, ...]:
    value: object = getattr(django_settings, SETTING_CONSOLE_SUPERUSER_GROUPS, ())
    match value:
        case str() as text:
            return tuple(item.strip() for item in text.split(",") if item.strip())
        case tuple() | list():
            return tuple(item for item in value if isinstance(item, str) and item)
        case _:
            return ()


def _webauthn_rp_id() -> str:
    value: object = getattr(django_settings, SETTING_WEBAUTHN_RP_ID, "localhost")
    return value if isinstance(value, str) and value else "localhost"


def _webauthn_rp_name() -> str:
    value: object = getattr(django_settings, SETTING_WEBAUTHN_RP_NAME, "EasyAuth")
    return value if isinstance(value, str) and value else "EasyAuth"


def _webauthn_origins() -> tuple[str, ...]:
    value: object = getattr(django_settings, SETTING_WEBAUTHN_ORIGINS, ())
    match value:
        case str() as text:
            origins = tuple(item.strip() for item in text.split(",") if item.strip())
        case tuple() | list():
            origins = tuple(item for item in value if isinstance(item, str) and item)
        case _:
            origins = ()
    return origins if origins else ("http://localhost:8001",)
