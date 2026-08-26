# 本地超级管理员登录域逻辑: 密码 + 二次验证(TOTP / 通行密钥)。
# 不经 Authentik, 验证通过后复用 bind_oidc_session 以 local-admin: 前缀 subject
# 绑定会话, groups 取 EASYAUTH_CONSOLE_SUPERUSER_GROUPS, 因此天然是 console 超管。
# TOTP / 通行密钥实现拆到 local_admin_totp.py 与 local_admin_passkeys.py; 本模块保留
# 会话、节流、审计、配置, 并显式再导出原公共符号, 使既有 import 与 monkeypatch 路径不变。
from __future__ import annotations

import time
from typing import TYPE_CHECKING, Final, cast

import webauthn
from django.conf import settings as django_settings
from django.core.cache import cache
from django.db import transaction

from easyauth.accounts import local_admin_passkeys as _passkeys
from easyauth.accounts import local_admin_totp as _totp
from easyauth.accounts.auth import (
    AUTHENTIK_SESSION_KEY,
    LOCAL_ADMIN_SESSION_FLAG,
    LOCAL_ADMIN_SESSION_VERSION_KEY,
    VerifiedOidcClaims,
    bind_oidc_session,
)
from easyauth.accounts.local_admin_common import (
    SETTING_WEBAUTHN_RP_NAME,
    session_mapping,
    webauthn_rp_name,
)
from easyauth.accounts.local_admin_passkeys import (
    CHALLENGE_SESSION_KEY,
    CHALLENGE_TTL_SECONDS,
    REASON_CHALLENGE_MISSING,
    REASON_CREDENTIAL_DUPLICATE,
    REASON_CREDENTIAL_MALFORMED,
    REASON_CREDENTIAL_UNKNOWN,
    REASON_VERIFICATION_FAILED,
    PasskeyRegistrationPayload,
    PasskeyVerificationError,
    WebAuthnLib,
    WebAuthnRuntime,
    parse_passkey_registration_payload,
)
from easyauth.accounts.local_admin_totp import (
    STEP_UP_INVALID,
    STEP_UP_OK,
    STEP_UP_THROTTLED,
    TOTP_CODE_LENGTH,
    TOTP_SETUP_SESSION_KEY,
    TOTP_SETUP_TTL_SECONDS,
    clear_totp_setup_secret,
    generate_totp_secret,
    matched_totp_timestep,
    run_dummy_password_hash,
    store_totp_setup_secret,
    totp_provisioning_uri,
    totp_qr_data_uri,
    totp_setup_nonce,
    totp_setup_secret,
    verify_and_consume_totp,
    verify_totp_code,
)
from easyauth.accounts.models import LocalAdminAccount, LocalAdminPasskey
from easyauth.audit.services import AuditRecord, AuditService

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from django.http import HttpRequest

    from easyauth.accounts.models import UserMirror
    from easyauth.audit.models import JsonValue

LOCAL_ADMIN_SUBJECT_PREFIX: Final = "local-admin:"
LOCAL_ADMIN_ACTOR_TYPE: Final = "local_admin"
LOCAL_ADMIN_TARGET_TYPE: Final = "local_admin_account"
PENDING_SESSION_KEY: Final = "easyauth_local_admin_pending"
PENDING_TTL_SECONDS: Final = 600
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
SETTING_WEBAUTHN_ORIGINS: Final = "EASYAUTH_WEBAUTHN_ORIGINS"


class LocalAdminConfigurationError(RuntimeError):
    pass


def local_admin_subject(username: str) -> str:
    return f"{LOCAL_ADMIN_SUBJECT_PREFIX}{username}"


def current_local_admin(request: HttpRequest) -> LocalAdminAccount | None:
    # 必须同时命中 local-admin: 前缀与专用会话标志: 仅凭前缀匹配会让某个 sub 恰为
    # local-admin:<username> 的普通 OIDC 会话被冒认为本地超管(BS-10)。
    if request.session.get(LOCAL_ADMIN_SESSION_FLAG) is not True:
        return None
    subject = request.session.get(AUTHENTIK_SESSION_KEY)
    if not isinstance(subject, str) or not subject.startswith(LOCAL_ADMIN_SUBJECT_PREFIX):
        return None
    username = subject[len(LOCAL_ADMIN_SUBJECT_PREFIX) :]
    account = LocalAdminAccount.objects.filter(username=username, is_active=True).first()
    if account is None:
        return None
    session_version = request.session.get(LOCAL_ADMIN_SESSION_VERSION_KEY)
    if session_version != account.session_version:
        return None
    return account


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
        local_admin=True,
    )
    request.session[LOCAL_ADMIN_SESSION_VERSION_KEY] = account.session_version
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
        "account_id": account.id,
        "issued_at": time.time(),
    }


def pending_account(request: HttpRequest) -> LocalAdminAccount | None:
    payload = session_mapping(request.session.get(PENDING_SESSION_KEY))
    if payload is None:
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
    count: object = cache.get(_throttle_cache_key(username), 0)  # pyright: ignore[reportAny]
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
    _ = cache.delete(_throttle_cache_key(username))


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


def check_step_up(account: LocalAdminAccount, password: str) -> str:
    # 调用时注入节流函数, 使测试对 local_admin.login_is_throttled 的 patch 生效。
    return _totp.check_step_up(
        account,
        password,
        login_is_throttled=login_is_throttled,
        record_login_failure=record_login_failure,
    )


def passkey_authentication_options(
    request: HttpRequest,
    account: LocalAdminAccount,
) -> tuple[str, str]:
    return _passkeys.passkey_authentication_options(request, account, runtime=_webauthn_runtime())


def verify_passkey_authentication(
    request: HttpRequest,
    account: LocalAdminAccount,
    credential: Mapping[str, object],
    *,
    state_token: str,
) -> None:
    _passkeys.verify_passkey_authentication(
        request,
        account,
        credential,
        state_token=state_token,
        runtime=_webauthn_runtime(),
    )


def passkey_registration_options(
    request: HttpRequest,
    account: LocalAdminAccount,
) -> tuple[str, str]:
    return _passkeys.passkey_registration_options(
        request,
        account,
        runtime=_webauthn_runtime(),
        user_id=local_admin_subject(account.username).encode("utf-8"),
    )


def register_passkey(
    request: HttpRequest,
    account: LocalAdminAccount,
    credential: Mapping[str, object],
    *,
    state_token: str,
    name: str,
) -> LocalAdminPasskey:
    return _passkeys.register_passkey(
        request,
        account,
        credential,
        state_token=state_token,
        name=name,
        runtime=_webauthn_runtime(),
    )


def rotate_local_admin_session(request: HttpRequest, account: LocalAdminAccount) -> None:
    """递增账号会话版本, 同时让当前已完成 step-up 的会话继续有效。"""
    with transaction.atomic():
        locked = LocalAdminAccount.objects.select_for_update().get(pk=account.id)
        locked.session_version += 1
        locked.save(update_fields=["session_version", "updated_at"])
    account.session_version = locked.session_version
    request.session.cycle_key()
    request.session[LOCAL_ADMIN_SESSION_VERSION_KEY] = locked.session_version


def finalize_passkey_registration(
    request: HttpRequest,
    account: LocalAdminAccount,
    passkey: LocalAdminPasskey,
) -> None:
    """通行密钥注册成功后清节流、写审计并轮换会话, 供表单端点与控制台 JSON API 共用。"""
    reset_login_failures(account.username)
    record_passkey_registered(account.username, name=passkey.name)
    rotate_local_admin_session(request, account)


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


def _webauthn_runtime() -> WebAuthnRuntime:
    # webauthn 在调用时从本模块全局解析, 测试 monkeypatch local_admin.webauthn 会生效。
    return WebAuthnRuntime(
        lib=_webauthn_lib(),
        rp_id=_webauthn_rp_id(),
        rp_name=_webauthn_rp_name(),
        origins=_webauthn_origins(),
    )


def _webauthn_lib() -> WebAuthnLib:
    return webauthn  # pyright: ignore[reportReturnType]


def _console_superuser_groups() -> tuple[str, ...]:
    value: object = getattr(django_settings, SETTING_CONSOLE_SUPERUSER_GROUPS, ())
    match value:
        case str() as text:
            return tuple(item.strip() for item in text.split(",") if item.strip())
        case tuple() | list():
            items = cast("Iterable[object]", value)
            return tuple(item for item in items if isinstance(item, str) and item)
        case _:
            return ()


def _webauthn_rp_id() -> str:
    value: object = getattr(django_settings, SETTING_WEBAUTHN_RP_ID, "localhost")
    return value if isinstance(value, str) and value else "localhost"


def _webauthn_rp_name() -> str:
    return webauthn_rp_name()


def _webauthn_origins() -> tuple[str, ...]:
    value: object = getattr(django_settings, SETTING_WEBAUTHN_ORIGINS, ())
    match value:
        case str() as text:
            origins = tuple(item.strip() for item in text.split(",") if item.strip())
        case tuple() | list():
            items = cast("Iterable[object]", value)
            origins = tuple(item for item in items if isinstance(item, str) and item)
        case _:
            origins = ()
    return origins if origins else ("http://localhost:8001",)


__all__ = [
    "CHALLENGE_SESSION_KEY",
    "CHALLENGE_TTL_SECONDS",
    "EVENT_LOGIN_FAILED",
    "EVENT_LOGIN_SUCCEEDED",
    "EVENT_PASSKEY_REGISTERED",
    "EVENT_PASSKEY_REMOVED",
    "EVENT_PASSWORD_CHANGED",
    "EVENT_PASSWORD_CHANGE_FAILED",
    "EVENT_SECOND_FACTOR_FAILED",
    "EVENT_TOTP_DISABLED",
    "EVENT_TOTP_ENABLED",
    "LOCAL_ADMIN_ACTOR_TYPE",
    "LOCAL_ADMIN_SUBJECT_PREFIX",
    "LOCAL_ADMIN_TARGET_TYPE",
    "LOGIN_FAILURE_LIMIT",
    "LOGIN_FAILURE_WINDOW_SECONDS",
    "PENDING_SESSION_KEY",
    "PENDING_TTL_SECONDS",
    "REASON_CHALLENGE_MISSING",
    "REASON_CREDENTIAL_DUPLICATE",
    "REASON_CREDENTIAL_MALFORMED",
    "REASON_CREDENTIAL_UNKNOWN",
    "REASON_VERIFICATION_FAILED",
    "SECOND_FACTOR_NONE",
    "SECOND_FACTOR_PASSKEY",
    "SECOND_FACTOR_TOTP",
    "SETTING_CONSOLE_SUPERUSER_GROUPS",
    "SETTING_WEBAUTHN_ORIGINS",
    "SETTING_WEBAUTHN_RP_ID",
    "SETTING_WEBAUTHN_RP_NAME",
    "STEP_UP_INVALID",
    "STEP_UP_OK",
    "STEP_UP_THROTTLED",
    "TOTP_CODE_LENGTH",
    "TOTP_SETUP_SESSION_KEY",
    "TOTP_SETUP_TTL_SECONDS",
    "LocalAdminConfigurationError",
    "PasskeyRegistrationPayload",
    "PasskeyVerificationError",
    "bind_local_admin_session",
    "check_step_up",
    "clear_pending_verification",
    "clear_totp_setup_secret",
    "current_local_admin",
    "finalize_passkey_registration",
    "generate_totp_secret",
    "local_admin_subject",
    "login_is_throttled",
    "matched_totp_timestep",
    "parse_passkey_registration_payload",
    "passkey_authentication_options",
    "passkey_registration_options",
    "pending_account",
    "record_login_failed",
    "record_login_failure",
    "record_passkey_registered",
    "record_passkey_removed",
    "record_password_change_failed",
    "record_password_changed",
    "record_second_factor_failed",
    "record_totp_disabled",
    "record_totp_enabled",
    "register_passkey",
    "reset_login_failures",
    "rotate_local_admin_session",
    "run_dummy_password_hash",
    "start_pending_verification",
    "store_totp_setup_secret",
    "totp_provisioning_uri",
    "totp_qr_data_uri",
    "totp_setup_nonce",
    "totp_setup_secret",
    "verify_and_consume_totp",
    "verify_passkey_authentication",
    "verify_totp_code",
    "webauthn",
]
