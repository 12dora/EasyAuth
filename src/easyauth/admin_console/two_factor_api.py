# 控制台设置页的「两步验证」JSON API: 复用本地超管 2FA 领域逻辑, 仅对本地管理员会话开放。
# 与 accounts/local_admin_views.py 的表单端点(/auth/local/security/...)行为一致,
# 但返回 JSON, 供 React 控制台设置页内联管理 TOTP 与通行密钥。
from __future__ import annotations

import json
from http import HTTPStatus
from typing import TYPE_CHECKING

from django.http import Http404, HttpRequest, JsonResponse
from django.views.decorators.http import require_http_methods

from easyauth.accounts.local_admin import (
    PasskeyVerificationError,
    clear_totp_setup_secret,
    current_local_admin,
    generate_totp_secret,
    passkey_registration_options,
    record_passkey_registered,
    record_passkey_removed,
    record_totp_disabled,
    record_totp_enabled,
    register_passkey,
    store_totp_setup_secret,
    totp_provisioning_uri,
    totp_qr_data_uri,
    totp_setup_secret,
    verify_totp_code,
)
from easyauth.admin_console.api_responses import error_response, json_response
from easyauth.api.datetime_json import datetime_value
from easyauth.api.errors import ErrorCode

if TYPE_CHECKING:
    from easyauth.accounts.models import LocalAdminAccount, LocalAdminPasskey
    from easyauth.api.errors import JsonValue

FORBIDDEN_MESSAGE = "两步验证仅适用于本地管理员账号。"
INVALID_PAYLOAD_MESSAGE = "请求参数无效。"
TOTP_ALREADY_ENABLED_MESSAGE = "验证器已启用。"
TOTP_CONFIRM_INVALID_MESSAGE = "验证码不正确, 未能启用验证器。"
TOTP_DISABLE_INVALID_MESSAGE = "验证码不正确, 未能停用验证器。"


@require_http_methods(["GET"])
def two_factor_status(request: HttpRequest) -> JsonResponse:
    account = current_local_admin(request)
    if account is None:
        # 非本地管理员(如 OIDC 管理员)的两步验证由上游 Authentik 管理。
        return json_response({"supported": False})
    return json_response(_status_payload(account))


@require_http_methods(["POST"])
def totp_begin(request: HttpRequest) -> JsonResponse:
    account = current_local_admin(request)
    if account is None:
        return _forbidden()
    if account.totp_enabled:
        return error_response(
            ErrorCode.CONFLICT, TOTP_ALREADY_ENABLED_MESSAGE, status=HTTPStatus.CONFLICT
        )
    secret = totp_setup_secret(request) or generate_totp_secret()
    store_totp_setup_secret(request, secret)
    provisioning_uri = totp_provisioning_uri(secret, account.username)
    return json_response(
        {
            "secret": secret,
            "otpauth_uri": provisioning_uri,
            "qr_svg": totp_qr_data_uri(provisioning_uri),
        },
    )


@require_http_methods(["POST"])
def totp_confirm(request: HttpRequest) -> JsonResponse:
    account = current_local_admin(request)
    if account is None:
        return _forbidden()
    secret = totp_setup_secret(request)
    code = _body_string(request, "code")
    if secret == "" or not verify_totp_code(secret, code):
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            TOTP_CONFIRM_INVALID_MESSAGE,
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    account.totp_secret = secret
    account.totp_enabled = True
    account.save(update_fields=["totp_secret", "totp_enabled", "updated_at"])
    clear_totp_setup_secret(request)
    record_totp_enabled(account.username)
    return json_response(_status_payload(account))


@require_http_methods(["POST"])
def totp_disable(request: HttpRequest) -> JsonResponse:
    account = current_local_admin(request)
    if account is None:
        return _forbidden()
    code = _body_string(request, "code")
    if not account.totp_enabled or not verify_totp_code(account.totp_secret, code):
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            TOTP_DISABLE_INVALID_MESSAGE,
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    account.totp_secret = ""
    account.totp_enabled = False
    account.save(update_fields=["totp_secret", "totp_enabled", "updated_at"])
    record_totp_disabled(account.username)
    return json_response(_status_payload(account))


@require_http_methods(["POST"])
def passkey_register_begin(request: HttpRequest) -> JsonResponse:
    account = current_local_admin(request)
    if account is None:
        return _forbidden()
    options_json, state_token = passkey_registration_options(request, account)
    return json_response({"options": json.loads(options_json), "state_token": state_token})


@require_http_methods(["POST"])
def passkey_register_complete(request: HttpRequest) -> JsonResponse:
    account = current_local_admin(request)
    if account is None:
        return _forbidden()
    payload = _json_body(request)
    credential = payload.get("credential") if payload else None
    state_token = payload.get("state_token") if payload else None
    name = payload.get("name") if payload else ""
    if not isinstance(credential, dict) or not isinstance(state_token, str):
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            INVALID_PAYLOAD_MESSAGE,
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    if not isinstance(name, str):
        name = ""
    try:
        passkey = register_passkey(
            request,
            account,
            credential,
            state_token=state_token,
            name=name.strip(),
        )
    except PasskeyVerificationError as error:
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            str(error),
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    record_passkey_registered(account.username, name=passkey.name)
    return json_response(_status_payload(account))


@require_http_methods(["DELETE"])
def passkey_delete(request: HttpRequest, passkey_id: int) -> JsonResponse:
    account = current_local_admin(request)
    if account is None:
        return _forbidden()
    passkey = account.passkeys.filter(pk=passkey_id).first()
    if passkey is None:
        raise Http404
    name = passkey.name
    _ = passkey.delete()
    record_passkey_removed(account.username, name=name)
    return json_response(_status_payload(account))


def _status_payload(account: LocalAdminAccount) -> dict[str, JsonValue]:
    return {
        "supported": True,
        "totp": {"enabled": account.totp_enabled},
        "passkeys": [_passkey_payload(passkey) for passkey in account.passkeys.all()],
    }


def _passkey_payload(passkey: LocalAdminPasskey) -> dict[str, JsonValue]:
    return {
        "id": passkey.pk,
        "name": passkey.name,
        "created_at": datetime_value(passkey.created_at),
        "last_used_at": datetime_value(passkey.last_used_at),
    }


def _forbidden() -> JsonResponse:
    return error_response(
        ErrorCode.PERMISSION_DENIED, FORBIDDEN_MESSAGE, status=HTTPStatus.FORBIDDEN
    )


def _json_body(request: HttpRequest) -> dict[str, object] | None:
    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _body_string(request: HttpRequest, key: str) -> str:
    payload = _json_body(request)
    if payload is None:
        return ""
    value = payload.get(key)
    return value if isinstance(value, str) else ""
