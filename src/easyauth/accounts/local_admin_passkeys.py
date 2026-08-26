# 本地超级管理员 WebAuthn 通行密钥: 认证、注册与挑战态。
# 本模块不导入 local_admin, 避免循环依赖; webauthn 库与 RP 配置由门面在调用时注入,
# 使测试对 local_admin.webauthn 的 monkeypatch 仍然命中真正执行路径。
from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass
from secrets import compare_digest, token_urlsafe
from typing import TYPE_CHECKING, Final, Protocol, cast

from django.db import IntegrityError, transaction
from django.utils import timezone
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.exceptions import (
    InvalidAuthenticationResponse,
    InvalidRegistrationResponse,
)
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    UserVerificationRequirement,
)

from easyauth.accounts.models import LocalAdminAccount, LocalAdminPasskey

if TYPE_CHECKING:
    from django.http import HttpRequest

CHALLENGE_SESSION_KEY: Final = "easyauth_local_admin_webauthn_challenge"
CHALLENGE_TTL_SECONDS: Final = 300
REASON_CHALLENGE_MISSING: Final = "挑战已过期, 请重试。"
REASON_CREDENTIAL_MALFORMED: Final = "凭据格式不正确。"
REASON_CREDENTIAL_UNKNOWN: Final = "未找到匹配的通行密钥。"
REASON_CREDENTIAL_DUPLICATE: Final = "该通行密钥已注册过。"
REASON_VERIFICATION_FAILED: Final = "通行密钥验证失败。"


class PasskeyVerificationError(ValueError):
    pass


class _WebAuthnOptions(Protocol):
    challenge: bytes


class _AuthenticationVerification(Protocol):
    new_sign_count: int


class _RegistrationVerification(Protocol):
    credential_id: bytes
    credential_public_key: bytes
    sign_count: int


class WebAuthnLib(Protocol):
    def generate_authentication_options(
        self,
        *,
        rp_id: str,
        allow_credentials: list[PublicKeyCredentialDescriptor],
        user_verification: UserVerificationRequirement,
    ) -> _WebAuthnOptions: ...

    def generate_registration_options(  # noqa: PLR0913
        self,
        *,
        rp_id: str,
        rp_name: str,
        user_name: str,
        user_id: bytes,
        user_display_name: str,
        exclude_credentials: list[PublicKeyCredentialDescriptor],
        authenticator_selection: AuthenticatorSelectionCriteria,
    ) -> _WebAuthnOptions: ...

    def verify_authentication_response(  # noqa: PLR0913
        self,
        *,
        credential: dict[str, object],
        expected_challenge: bytes,
        expected_rp_id: str,
        expected_origin: list[str],
        credential_public_key: bytes,
        credential_current_sign_count: int,
        require_user_verification: bool,
    ) -> _AuthenticationVerification: ...

    def verify_registration_response(
        self,
        *,
        credential: dict[str, object],
        expected_challenge: bytes,
        expected_rp_id: str,
        expected_origin: list[str],
        require_user_verification: bool,
    ) -> _RegistrationVerification: ...

    def options_to_json(self, options: _WebAuthnOptions) -> str: ...


@dataclass(frozen=True, slots=True)
class WebAuthnRuntime:
    lib: WebAuthnLib
    rp_id: str
    rp_name: str
    origins: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PasskeyRegistrationPayload:
    credential: dict[str, object]
    state_token: str
    name: str
    current_password: str


@dataclass(frozen=True, slots=True)
class _VerifiedPasskeyMaterial:
    credential_id: str
    public_key: str
    sign_count: int
    transports: list[str]
    name: str


def parse_passkey_registration_payload(
    payload: Mapping[str, object] | None,
) -> PasskeyRegistrationPayload | None:
    if payload is None:
        return None
    credential = payload.get("credential")
    state_token = payload.get("state_token")
    name = payload.get("name")
    current_password = payload.get("current_password")
    if not isinstance(credential, dict) or not isinstance(state_token, str):
        return None
    return PasskeyRegistrationPayload(
        credential=cast("dict[str, object]", credential),
        state_token=state_token,
        name=name if isinstance(name, str) else "",
        current_password=current_password if isinstance(current_password, str) else "",
    )


def passkey_authentication_options(
    request: HttpRequest,
    account: LocalAdminAccount,
    *,
    runtime: WebAuthnRuntime,
) -> tuple[str, str]:
    # 生成 WebAuthn 认证 options; 返回 (options JSON, state_token)。
    allow_credentials = [
        PublicKeyCredentialDescriptor(id=base64url_to_bytes(passkey.credential_id))
        for passkey in account.passkeys.all()
    ]
    options = runtime.lib.generate_authentication_options(
        rp_id=runtime.rp_id,
        allow_credentials=allow_credentials,
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    state_token = _store_challenge(request, options.challenge)
    return runtime.lib.options_to_json(options), state_token


def verify_passkey_authentication(
    request: HttpRequest,
    account: LocalAdminAccount,
    credential: Mapping[str, object],
    *,
    state_token: str,
    runtime: WebAuthnRuntime,
) -> None:
    challenge = _pop_challenge(request, state_token)
    if challenge is None:
        raise PasskeyVerificationError(REASON_CHALLENGE_MISSING)
    credential_id = _credential_id_from_payload(credential)
    with transaction.atomic():
        passkey = (
            LocalAdminPasskey.objects.select_for_update()
            .filter(account=account, credential_id=credential_id)
            .first()
        )
        if passkey is None:
            raise PasskeyVerificationError(REASON_CREDENTIAL_UNKNOWN)
        try:
            verified = runtime.lib.verify_authentication_response(
                credential=_plain_payload(credential),
                expected_challenge=challenge,
                expected_rp_id=runtime.rp_id,
                expected_origin=list(runtime.origins),
                credential_public_key=base64url_to_bytes(passkey.public_key),
                credential_current_sign_count=passkey.sign_count,
                require_user_verification=True,
            )
        except InvalidAuthenticationResponse as error:
            raise PasskeyVerificationError(REASON_VERIFICATION_FAILED) from error
        passkey.sign_count = verified.new_sign_count
        passkey.last_used_at = timezone.now()
        passkey.save(update_fields=["sign_count", "last_used_at"])


def passkey_registration_options(
    request: HttpRequest,
    account: LocalAdminAccount,
    *,
    runtime: WebAuthnRuntime,
    user_id: bytes,
) -> tuple[str, str]:
    # 生成 WebAuthn 注册 options; 返回 (options JSON, state_token)。
    exclude_credentials = [
        PublicKeyCredentialDescriptor(id=base64url_to_bytes(passkey.credential_id))
        for passkey in account.passkeys.all()
    ]
    options = runtime.lib.generate_registration_options(
        rp_id=runtime.rp_id,
        rp_name=runtime.rp_name,
        user_name=account.username,
        user_id=user_id,
        user_display_name=f"本地管理员 {account.username}",
        exclude_credentials=exclude_credentials,
        authenticator_selection=AuthenticatorSelectionCriteria(
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
    )
    state_token = _store_challenge(request, options.challenge)
    return runtime.lib.options_to_json(options), state_token


def register_passkey(  # noqa: PLR0913
    request: HttpRequest,
    account: LocalAdminAccount,
    credential: Mapping[str, object],
    *,
    state_token: str,
    name: str,
    runtime: WebAuthnRuntime,
) -> LocalAdminPasskey:
    challenge = _pop_challenge(request, state_token)
    if challenge is None:
        raise PasskeyVerificationError(REASON_CHALLENGE_MISSING)
    try:
        verified = runtime.lib.verify_registration_response(
            credential=_plain_payload(credential),
            expected_challenge=challenge,
            expected_rp_id=runtime.rp_id,
            expected_origin=list(runtime.origins),
            require_user_verification=True,
        )
    except InvalidRegistrationResponse as error:
        raise PasskeyVerificationError(REASON_VERIFICATION_FAILED) from error
    return _insert_registered_passkey(
        account,
        _VerifiedPasskeyMaterial(
            credential_id=bytes_to_base64url(verified.credential_id),
            public_key=bytes_to_base64url(verified.credential_public_key),
            sign_count=verified.sign_count,
            transports=_transports_from_payload(credential),
            name=name[:100],
        ),
    )


def _insert_registered_passkey(
    account: LocalAdminAccount,
    material: _VerifiedPasskeyMaterial,
) -> LocalAdminPasskey:
    # 预检查 + 插入包在同一事务里; 并发撞 unique(credential_id) 时 IntegrityError
    # 走与预检查相同的"已注册"校验错误, 避免 500。
    try:
        with transaction.atomic():
            if LocalAdminPasskey.objects.filter(credential_id=material.credential_id).exists():
                raise PasskeyVerificationError(REASON_CREDENTIAL_DUPLICATE)
            return LocalAdminPasskey.objects.create(
                account=account,
                credential_id=material.credential_id,
                public_key=material.public_key,
                sign_count=material.sign_count,
                transports=material.transports,
                name=material.name,
            )
    except IntegrityError as error:
        raise PasskeyVerificationError(REASON_CREDENTIAL_DUPLICATE) from error


def _credential_id_from_payload(credential: Mapping[str, object]) -> str:
    raw_id = credential.get("rawId") or credential.get("id")
    if not isinstance(raw_id, str) or raw_id == "":
        raise PasskeyVerificationError(REASON_CREDENTIAL_MALFORMED)
    return raw_id


def _transports_from_payload(credential: Mapping[str, object]) -> list[str]:
    response = _object_mapping(credential.get("response"))
    if response is None:
        return []
    transports = response.get("transports")
    if not isinstance(transports, list):
        return []
    items = cast("list[object]", transports)
    return [item for item in items if isinstance(item, str)]


def _store_challenge(request: HttpRequest, challenge: bytes) -> str:
    state_token = token_urlsafe(16)
    request.session[CHALLENGE_SESSION_KEY] = {
        "challenge": bytes_to_base64url(challenge),
        "state_token": state_token,
        "issued_at": time.time(),
    }
    return state_token


def _pop_challenge(request: HttpRequest, state_token: str) -> bytes | None:
    raw_payload: object = request.session.pop(CHALLENGE_SESSION_KEY, None)  # pyright: ignore[reportAny]
    payload = _session_mapping(raw_payload)
    if payload is None:
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


def _session_mapping(value: object) -> Mapping[str, object] | None:
    return _object_mapping(value)


def _object_mapping(value: object) -> Mapping[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    mapping = cast("Mapping[object, object]", value)
    if not all(isinstance(key, str) for key in mapping):
        return None
    return cast("Mapping[str, object]", mapping)


def _plain_payload(value: Mapping[str, object]) -> dict[str, object]:
    return dict(value.items())
