# 本地超级管理员登录/二次验证/安全设置视图。
# 页面为自包含 Django 模板(设计 token 与 config/templates/404.html 一致);
# WebAuthn 走 JSON 端点 + 页面内联原生 JS, 无前端构建步骤。
from __future__ import annotations

import json
from http import HTTPStatus
from typing import TYPE_CHECKING, Final
from urllib.parse import urlsplit

from django.http import Http404, HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from easyauth.accounts.local_admin import (
    SECOND_FACTOR_NONE,
    SECOND_FACTOR_PASSKEY,
    SECOND_FACTOR_TOTP,
    LocalAdminConfigurationError,
    PasskeyVerificationError,
    bind_local_admin_session,
    clear_totp_setup_secret,
    current_local_admin,
    generate_totp_secret,
    login_is_throttled,
    passkey_authentication_options,
    passkey_registration_options,
    pending_account,
    record_login_failed,
    record_login_failure,
    record_passkey_registered,
    record_passkey_removed,
    record_password_change_failed,
    record_password_changed,
    record_second_factor_failed,
    record_totp_disabled,
    record_totp_enabled,
    register_passkey,
    reset_login_failures,
    start_pending_verification,
    store_totp_setup_secret,
    totp_provisioning_uri,
    totp_qr_data_uri,
    totp_setup_secret,
    verify_passkey_authentication,
    verify_totp_code,
)
from easyauth.accounts.models import LocalAdminAccount

if TYPE_CHECKING:
    from django.http import HttpRequest

LOGIN_TEMPLATE: Final = "accounts/local_admin/login.html"
VERIFY_TEMPLATE: Final = "accounts/local_admin/verify.html"
SECURITY_TEMPLATE: Final = "accounts/local_admin/security.html"
CHANGE_PASSWORD_TEMPLATE: Final = "accounts/local_admin/change_password.html"  # noqa: S105 - 模板路径, 不是密码值.
LOGIN_PATH: Final = "/auth/local/"
VERIFY_PATH: Final = "/auth/local/verify/"
SECURITY_PATH: Final = "/auth/local/security/"
CHANGE_PASSWORD_PATH: Final = "/auth/local/change-password/"  # noqa: S105 - URL 路径, 不是密码值.
CONSOLE_PATH: Final = "/console/"
DEFAULT_CHANGE_PASSWORD_NEXT: Final = "/portal/"  # noqa: S105 - URL 路径, 不是密码值.
PASSWORD_MIN_LENGTH: Final = 8
ERROR_INVALID_CREDENTIALS: Final = "用户名或密码错误。"
ERROR_THROTTLED: Final = "尝试次数过多, 请稍后再试。"
ERROR_INVALID_TOTP: Final = "验证码不正确, 请重试。"
ERROR_TOTP_NOT_ENABLED: Final = "该账号未启用验证器验证。"
ERROR_CURRENT_PASSWORD_WRONG: Final = "当前密码不正确。"  # noqa: S105 - 错误提示文案, 不是密码值.
ERROR_NEW_PASSWORD_TOO_SHORT: Final = "新密码长度至少 8 位。"  # noqa: S105 - 错误提示文案, 不是密码值.
ERROR_NEW_PASSWORD_SAME_AS_CURRENT: Final = "新密码不能与当前密码相同。"  # noqa: S105 - 错误提示文案, 不是密码值.
ERROR_NEW_PASSWORD_MISMATCH: Final = "两次输入的新密码不一致。"  # noqa: S105 - 错误提示文案, 不是密码值.
SECURITY_NOTICES: Final[dict[str, str]] = {
    "totp_enabled": "验证器验证已启用。",
    "totp_disabled": "验证器验证已停用。",
    "passkey_removed": "通行密钥已删除。",
    "passkey_registered": "通行密钥已注册。",
    "password_changed": "密码已修改。",
}
SECURITY_ERRORS: Final[dict[str, str]] = {
    "totp_confirm": "验证码不正确, 未能启用验证器。",
    "totp_disable": "验证码不正确, 未能停用验证器。",
}
JSON_ERROR_LOGIN_REQUIRED: Final = "login_required"
JSON_ERROR_BAD_REQUEST: Final = "bad_request"


@require_http_methods(["GET", "POST"])
def login_page(request: HttpRequest) -> HttpResponse:
    if request.method == "GET":
        return render(request, LOGIN_TEMPLATE, {"error": ""})
    username = _post_value(request, "username").strip()
    password = _post_value(request, "password")
    if username == "" or password == "":
        return _login_error(request, ERROR_INVALID_CREDENTIALS)
    if login_is_throttled(username):
        record_login_failed(username, reason="throttled")
        return _login_error(request, ERROR_THROTTLED)
    account = LocalAdminAccount.objects.filter(username=username).first()
    if account is None or not account.is_active or not account.check_password(password):
        record_login_failure(username)
        record_login_failed(username, reason="invalid_credentials")
        return _login_error(request, ERROR_INVALID_CREDENTIALS)
    reset_login_failures(username)
    if not account.has_second_factor():
        return _bind_and_redirect(request, account, second_factor=SECOND_FACTOR_NONE)
    start_pending_verification(request, account)
    return HttpResponseRedirect(VERIFY_PATH)


@require_GET
def verify_page(request: HttpRequest) -> HttpResponse:
    account = pending_account(request)
    if account is None:
        return HttpResponseRedirect(LOGIN_PATH)
    return _render_verify(request, account, error="")


@require_POST
def verify_totp(request: HttpRequest) -> HttpResponse:
    account = pending_account(request)
    if account is None:
        return HttpResponseRedirect(LOGIN_PATH)
    if not account.totp_enabled:
        return _render_verify(request, account, error=ERROR_TOTP_NOT_ENABLED)
    if login_is_throttled(account.username):
        return _render_verify(request, account, error=ERROR_THROTTLED)
    code = _post_value(request, "code")
    if not verify_totp_code(account.totp_secret, code):
        record_login_failure(account.username)
        record_second_factor_failed(account.username, method=SECOND_FACTOR_TOTP)
        return _render_verify(request, account, error=ERROR_INVALID_TOTP)
    return _bind_and_redirect(request, account, second_factor=SECOND_FACTOR_TOTP)


@require_POST
def passkey_begin(request: HttpRequest) -> HttpResponse:
    account = pending_account(request)
    if account is None:
        return _json_error(JSON_ERROR_LOGIN_REQUIRED, status=HTTPStatus.UNAUTHORIZED)
    options_json, state_token = passkey_authentication_options(request, account)
    return JsonResponse({"options": json.loads(options_json), "state_token": state_token})


@require_POST
def passkey_complete(request: HttpRequest) -> HttpResponse:
    account = pending_account(request)
    if account is None:
        return _json_error(JSON_ERROR_LOGIN_REQUIRED, status=HTTPStatus.UNAUTHORIZED)
    payload = _json_body(request)
    credential = payload.get("credential") if payload else None
    state_token = payload.get("state_token") if payload else None
    if not isinstance(credential, dict) or not isinstance(state_token, str):
        return _json_error(JSON_ERROR_BAD_REQUEST, status=HTTPStatus.BAD_REQUEST)
    try:
        verify_passkey_authentication(request, account, credential, state_token=state_token)
    except PasskeyVerificationError as error:
        record_login_failure(account.username)
        record_second_factor_failed(account.username, method=SECOND_FACTOR_PASSKEY)
        return _json_error(str(error), status=HTTPStatus.BAD_REQUEST)
    try:
        _ = bind_local_admin_session(request, account, second_factor=SECOND_FACTOR_PASSKEY)
    except LocalAdminConfigurationError as error:
        return _json_error(str(error), status=HTTPStatus.BAD_REQUEST)
    return JsonResponse({"redirect": CONSOLE_PATH})


@require_http_methods(["GET", "POST"])
def change_password_page(request: HttpRequest) -> HttpResponse:
    # 修改本地管理员密码: 首次登录/被重置后强制走这里, 平时也可从安全设置进入。
    account = current_local_admin(request)
    if account is None:
        return HttpResponseRedirect(LOGIN_PATH)
    next_path = _safe_change_password_next(request)
    if request.method == "GET":
        return _render_change_password(request, account, next_path=next_path, error="")
    if login_is_throttled(account.username):
        return _render_change_password(request, account, next_path=next_path, error=ERROR_THROTTLED)
    current_password = _post_value(request, "current_password")
    new_password = _post_value(request, "new_password")
    confirm_password = _post_value(request, "confirm_password")
    if not account.check_password(current_password):
        # 当前密码校验失败与登录失败共用同一节流计数, 防止已登录会话暴力试探密码。
        record_login_failure(account.username)
        record_password_change_failed(account.username, reason="invalid_current_password")
        return _render_change_password(
            request,
            account,
            next_path=next_path,
            error=ERROR_CURRENT_PASSWORD_WRONG,
        )
    error = _new_password_error(
        current_password=current_password,
        new_password=new_password,
        confirm_password=confirm_password,
    )
    if error != "":
        record_password_change_failed(account.username, reason="invalid_new_password")
        return _render_change_password(request, account, next_path=next_path, error=error)
    account.set_password(new_password)
    account.must_change_password = False
    account.save(update_fields=["password_hash", "must_change_password", "updated_at"])
    reset_login_failures(account.username)
    record_password_changed(account.username)
    return HttpResponseRedirect(next_path)


@require_GET
def security_page(request: HttpRequest) -> HttpResponse:
    account = _require_local_admin(request)
    setup_secret = totp_setup_secret(request)
    setup_qr = ""
    setup_uri = ""
    if setup_secret and not account.totp_enabled:
        setup_uri = totp_provisioning_uri(setup_secret, account.username)
        setup_qr = totp_qr_data_uri(setup_uri)
    return render(
        request,
        SECURITY_TEMPLATE,
        {
            "account": account,
            "passkeys": list(account.passkeys.all()),
            "setup_secret": setup_secret if not account.totp_enabled else "",
            "setup_qr": setup_qr,
            "setup_uri": setup_uri,
            "notice": SECURITY_NOTICES.get(request.GET.get("notice", ""), ""),
            "error": SECURITY_ERRORS.get(request.GET.get("error", ""), ""),
        },
    )


@require_POST
def totp_begin(request: HttpRequest) -> HttpResponse:
    account = _require_local_admin(request)
    if not account.totp_enabled:
        store_totp_setup_secret(request, generate_totp_secret())
    return HttpResponseRedirect(SECURITY_PATH)


@require_POST
def totp_confirm(request: HttpRequest) -> HttpResponse:
    account = _require_local_admin(request)
    secret = totp_setup_secret(request)
    code = _post_value(request, "code")
    if secret == "" or not verify_totp_code(secret, code):
        return HttpResponseRedirect(f"{SECURITY_PATH}?error=totp_confirm")
    account.totp_secret = secret
    account.totp_enabled = True
    account.save(update_fields=["totp_secret", "totp_enabled", "updated_at"])
    clear_totp_setup_secret(request)
    record_totp_enabled(account.username)
    return HttpResponseRedirect(f"{SECURITY_PATH}?notice=totp_enabled")


@require_POST
def totp_disable(request: HttpRequest) -> HttpResponse:
    account = _require_local_admin(request)
    code = _post_value(request, "code")
    if not account.totp_enabled or not verify_totp_code(account.totp_secret, code):
        return HttpResponseRedirect(f"{SECURITY_PATH}?error=totp_disable")
    account.totp_secret = ""
    account.totp_enabled = False
    account.save(update_fields=["totp_secret", "totp_enabled", "updated_at"])
    record_totp_disabled(account.username)
    return HttpResponseRedirect(f"{SECURITY_PATH}?notice=totp_disabled")


@require_POST
def passkey_register_begin(request: HttpRequest) -> HttpResponse:
    account = _require_local_admin(request)
    options_json, state_token = passkey_registration_options(request, account)
    return JsonResponse({"options": json.loads(options_json), "state_token": state_token})


@require_POST
def passkey_register_complete(request: HttpRequest) -> HttpResponse:
    account = _require_local_admin(request)
    payload = _json_body(request)
    credential = payload.get("credential") if payload else None
    state_token = payload.get("state_token") if payload else None
    name = payload.get("name") if payload else ""
    if not isinstance(credential, dict) or not isinstance(state_token, str):
        return _json_error(JSON_ERROR_BAD_REQUEST, status=HTTPStatus.BAD_REQUEST)
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
        return _json_error(str(error), status=HTTPStatus.BAD_REQUEST)
    record_passkey_registered(account.username, name=passkey.name)
    return JsonResponse({"redirect": f"{SECURITY_PATH}?notice=passkey_registered"})


@require_POST
def passkey_delete(request: HttpRequest, passkey_id: int) -> HttpResponse:
    account = _require_local_admin(request)
    passkey = account.passkeys.filter(pk=passkey_id).first()
    if passkey is None:
        raise Http404
    name = passkey.name
    _ = passkey.delete()
    record_passkey_removed(account.username, name=name)
    return HttpResponseRedirect(f"{SECURITY_PATH}?notice=passkey_removed")


def _require_local_admin(request: HttpRequest) -> LocalAdminAccount:
    account = current_local_admin(request)
    if account is None:
        raise Http404
    return account


def _bind_and_redirect(
    request: HttpRequest,
    account: LocalAdminAccount,
    *,
    second_factor: str,
) -> HttpResponse:
    try:
        _ = bind_local_admin_session(request, account, second_factor=second_factor)
    except LocalAdminConfigurationError as error:
        return HttpResponse(
            str(error),
            status=HTTPStatus.BAD_REQUEST,
            content_type="text/plain",
        )
    return HttpResponseRedirect(CONSOLE_PATH)


def _render_verify(request: HttpRequest, account: LocalAdminAccount, *, error: str) -> HttpResponse:
    has_passkeys = account.passkeys.exists()
    return render(
        request,
        VERIFY_TEMPLATE,
        {
            "error": error,
            "has_passkeys": has_passkeys,
            "totp_enabled": account.totp_enabled,
            "show_switcher": account.totp_enabled and has_passkeys,
        },
    )


def _render_change_password(
    request: HttpRequest,
    account: LocalAdminAccount,
    *,
    next_path: str,
    error: str,
) -> HttpResponse:
    return render(
        request,
        CHANGE_PASSWORD_TEMPLATE,
        {
            "account": account,
            "next_path": next_path,
            "forced": account.must_change_password,
            "error": error,
        },
    )


def _new_password_error(
    *,
    current_password: str,
    new_password: str,
    confirm_password: str,
) -> str:
    if len(new_password) < PASSWORD_MIN_LENGTH:
        return ERROR_NEW_PASSWORD_TOO_SHORT
    if new_password == current_password:
        return ERROR_NEW_PASSWORD_SAME_AS_CURRENT
    if new_password != confirm_password:
        return ERROR_NEW_PASSWORD_MISMATCH
    return ""


def _safe_change_password_next(request: HttpRequest) -> str:
    # next 只接受站内绝对路径, 防开放重定向; POST 时取表单隐藏字段。
    if request.method == "POST":
        next_path = _post_value(request, "next")
    else:
        next_path = request.GET.get("next", "")
    if _is_local_absolute_path(next_path):
        return next_path
    return DEFAULT_CHANGE_PASSWORD_NEXT


def _is_local_absolute_path(value: str) -> bool:
    if not value.startswith("/") or value.startswith("//") or "\\" in value:
        return False
    parsed = urlsplit(value)
    return parsed.scheme == "" and parsed.netloc == ""


def _login_error(request: HttpRequest, message: str) -> HttpResponse:
    return render(request, LOGIN_TEMPLATE, {"error": message})


def _post_value(request: HttpRequest, key: str) -> str:
    value = request.POST.get(key, "")
    return value if isinstance(value, str) else ""


def _json_body(request: HttpRequest) -> dict[str, object] | None:
    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _json_error(code: str, *, status: HTTPStatus) -> JsonResponse:
    return JsonResponse({"error": code}, status=status)
