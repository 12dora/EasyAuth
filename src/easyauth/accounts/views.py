from __future__ import annotations

from contextlib import suppress
from dataclasses import replace
from http import HTTPStatus
from secrets import token_urlsafe
from time import time
from typing import Final, TypedDict, cast
from urllib.parse import SplitResult, urlsplit, urlunsplit

from django.conf import settings as django_settings
from django.core.cache import cache
from django.db import transaction
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from easyauth.accounts.auth import (
    AUTHENTIK_SESSION_KEY,
    DEFAULT_AUTH_SUCCESS_NEXT,
    LOCAL_ADMIN_SESSION_FLAG,
    OIDC_ID_TOKEN_SESSION_KEY,
    OIDC_NEXT_SESSION_KEY,
    OIDC_NONCE_SESSION_KEY,
    OIDC_SILENT_ATTEMPTS_SESSION_KEY,
    OIDC_STATE_SESSION_KEY,
    OidcClientConfig,
    OidcSessionError,
    OidcUserInactiveError,
    _update_existing_user_profile,  # pyright: ignore[reportPrivateUsage]
    bind_oidc_session,
    build_authorization_url,
    clear_auth_session,
    clear_oidc_login_attempt,
    revoke_authentik_sessions,
    verify_callback_state,
    verify_oidc_claims,
)
from easyauth.accounts.logout_state import (
    LOGGED_OUT_LOCATION,
    PENDING_AUTHENTIK_LOGOUT_SESSION_KEY,
    clear_browser_logged_out,
    logged_out_response,
    mark_browser_logged_out,
)
from easyauth.accounts.models import USER_STATUS_ACTIVE, OidcSessionBinding, UserMirror
from easyauth.accounts.next_path import safe_next_path
from easyauth.accounts.oidc_exchange import (
    exchange_authorization_code_for_claims,
    verify_logout_token,
)
from easyauth.accounts.org_context import apply_dingtalk_org_context
from easyauth.audit.services import AuditRecord, AuditService

FIELD_BACKCHANNEL = "logout_token"
FIELD_AUTHORIZATION_CODE = "code"
LOCAL_LOOPBACK_HOSTS: Final = frozenset({"127.0.0.1", "::1", "localhost"})
REASON_CODE_REQUIRED = "is required"
SETTING_CLIENT_ID = "EASYAUTH_AUTHENTIK_OIDC_CLIENT_ID"
SETTING_CLIENT_SECRET = "EASYAUTH_AUTHENTIK_OIDC_CLIENT_SECRET"  # noqa: S105 - 配置键名, 不是密钥值.
SETTING_AUTHORIZATION_ENDPOINT = "EASYAUTH_AUTHENTIK_OIDC_AUTHORIZATION_ENDPOINT"
SETTING_AUTHENTIK_LOGOUT_URL = "EASYAUTH_AUTHENTIK_LOGOUT_URL"
SETTING_HTTP_TIMEOUT_SECONDS = "EASYAUTH_AUTHENTIK_OIDC_HTTP_TIMEOUT_SECONDS"
SETTING_ISSUER = "EASYAUTH_AUTHENTIK_OIDC_ISSUER"
SETTING_JWKS_URL = "EASYAUTH_AUTHENTIK_OIDC_JWKS_URL"
SETTING_REDIRECT_URI = "EASYAUTH_AUTHENTIK_OIDC_REDIRECT_URI"
SETTING_SIGNING_ALGORITHMS = "EASYAUTH_AUTHENTIK_OIDC_SIGNING_ALGORITHMS"
SETTING_SCOPES = "EASYAUTH_AUTHENTIK_OIDC_SCOPES"
SETTING_TOKEN_ENDPOINT = "EASYAUTH_AUTHENTIK_OIDC_TOKEN_ENDPOINT"  # noqa: S105 - 配置键名, 不是密钥值.
OIDC_ISSUER_PROVIDER_SLUG_SEGMENT_COUNT: Final = 3


def oidc_login(request: HttpRequest) -> HttpResponse:
    silent = request.GET.get("silent") == "1"
    if silent and request.session.get(LOCAL_ADMIN_SESSION_FLAG) is True:
        return _silent_result(request, "unchanged", _session_string(request, AUTHENTIK_SESSION_KEY))
    config = _oidc_config_from_settings()
    redirect_uri = _effective_redirect_uri(request, config.redirect_uri)
    canonical_login_url = _canonical_request_url(request, redirect_uri)
    if canonical_login_url != "":
        response = HttpResponseRedirect(canonical_login_url)
        clear_browser_logged_out(response)
        return response
    config = replace(config, redirect_uri=redirect_uri)
    state = token_urlsafe(32)
    nonce = token_urlsafe(32)
    if silent:
        attempts = _silent_attempts(request)
        attempts[state] = {"nonce": nonce, "created_at": time()}
        _save_silent_attempts(request, attempts)
    else:
        request.session[OIDC_STATE_SESSION_KEY] = state
        request.session[OIDC_NONCE_SESSION_KEY] = nonce
        request.session[OIDC_NEXT_SESSION_KEY] = _safe_auth_success_next(request)
    response = HttpResponseRedirect(
        build_authorization_url(
            config,
            state=state,
            nonce=nonce,
            prompt="none" if silent else "",
        ),
    )
    clear_browser_logged_out(response)
    return response


def oidc_callback(request: HttpRequest) -> HttpResponse:
    attempts = _silent_attempts(request)
    attempt = attempts.pop(request.GET.get("state", ""), None)
    if attempt is not None:
        _save_silent_attempts(request, attempts)
        return _silent_callback(request, attempt)
    config = _oidc_config_from_settings()
    config = replace(config, redirect_uri=_effective_redirect_uri(request, config.redirect_uri))
    code = request.GET.get("code", "")
    state = request.GET.get("state", "")
    try:
        _require_authorization_code(code)
        verify_callback_state(
            received_state=state,
            expected_state=_session_string(request, OIDC_STATE_SESSION_KEY),
        )
        claims = exchange_authorization_code_for_claims(request, code, config)
        verified = verify_oidc_claims(
            claims,
            config,
            expected_nonce=_session_string(request, OIDC_NONCE_SESSION_KEY),
        )
        _ = bind_oidc_session(request, verified)
    except OidcUserInactiveError as error:
        clear_oidc_login_attempt(request)
        return HttpResponse(str(error), status=HTTPStatus.FORBIDDEN, content_type="text/plain")
    except OidcSessionError as error:
        # 只清理本次登录尝试的 state/nonce; 不清已有登录会话,
        # 否则跨站 GET /auth/callback/ 可以把受害者强制登出。
        clear_oidc_login_attempt(request)
        return HttpResponse(str(error), status=HTTPStatus.BAD_REQUEST, content_type="text/plain")

    next_path = _session_string(request, OIDC_NEXT_SESSION_KEY) or DEFAULT_AUTH_SUCCESS_NEXT
    clear_oidc_login_attempt(request)
    return HttpResponseRedirect(next_path)


@require_POST
def logout(request: HttpRequest) -> HttpResponseRedirect:
    id_token_hint = _session_string(request, OIDC_ID_TOKEN_SESSION_KEY)
    authentik_endpoint = _authentik_logout_endpoint()
    clear_auth_session(request)
    request.session.flush()
    if authentik_endpoint != "":
        request.session[PENDING_AUTHENTIK_LOGOUT_SESSION_KEY] = id_token_hint
    response = HttpResponseRedirect(LOGGED_OUT_LOCATION)
    mark_browser_logged_out(response)
    return response


def logged_out(request: HttpRequest) -> HttpResponse:
    return logged_out_response(request)


@require_GET
@xframe_options_sameorigin
def authentik_logout_frame(request: HttpRequest) -> HttpResponse:
    if PENDING_AUTHENTIK_LOGOUT_SESSION_KEY not in request.session:
        return HttpResponse(status=HTTPStatus.NO_CONTENT)
    id_token_hint = _session_string(request, PENDING_AUTHENTIK_LOGOUT_SESSION_KEY)
    del request.session[PENDING_AUTHENTIK_LOGOUT_SESSION_KEY]
    endpoint = _authentik_logout_endpoint()
    if endpoint == "":
        return HttpResponse(status=HTTPStatus.NO_CONTENT)
    return render(
        request,
        "easyauth/authentik_logout_frame.html",
        {"endpoint": endpoint, "id_token_hint": id_token_hint},
    )


def _oidc_config_from_settings() -> OidcClientConfig:
    return OidcClientConfig(
        issuer=_required_setting(SETTING_ISSUER),
        authorization_endpoint=_string_setting(SETTING_AUTHORIZATION_ENDPOINT),
        client_id=_required_setting(SETTING_CLIENT_ID),
        client_secret=_string_setting(SETTING_CLIENT_SECRET),
        redirect_uri=_required_setting(SETTING_REDIRECT_URI),
        scopes=_scopes_from_settings(),
        token_endpoint=_required_setting(SETTING_TOKEN_ENDPOINT),
        jwks_url=_required_setting(SETTING_JWKS_URL),
        signing_algorithms=_string_tuple_setting(SETTING_SIGNING_ALGORITHMS),
        http_timeout_seconds=_float_setting(SETTING_HTTP_TIMEOUT_SECONDS),
    )


def _canonical_request_url(request: HttpRequest, canonical_absolute_url: str) -> str:
    current = urlsplit(request.build_absolute_uri())
    canonical = urlsplit(canonical_absolute_url)
    if current.scheme == canonical.scheme and current.netloc == canonical.netloc:
        return ""
    return urlunsplit(
        (
            canonical.scheme,
            canonical.netloc,
            request.path,
            request.META.get("QUERY_STRING", ""),
            "",
        ),
    )


def _effective_redirect_uri(request: HttpRequest, configured_redirect_uri: str) -> str:
    configured = urlsplit(configured_redirect_uri)
    current = urlsplit(request.build_absolute_uri())
    if not _is_loopback_host(configured.hostname) or not _is_loopback_host(current.hostname):
        return configured_redirect_uri

    hostname = configured.hostname or current.hostname or "localhost"
    netloc = _netloc_with_current_port(hostname, current)
    return urlunsplit((current.scheme, netloc, "/auth/callback/", "", ""))


def _is_loopback_host(hostname: str | None) -> bool:
    return hostname in LOCAL_LOOPBACK_HOSTS


def _netloc_with_current_port(hostname: str, current: SplitResult) -> str:
    if current.port is None:
        return hostname
    return f"{hostname}:{current.port}"


def _authentik_logout_endpoint() -> str:
    configured_url = _optional_string_setting(SETTING_AUTHENTIK_LOGOUT_URL)
    if configured_url != "":
        return _logout_endpoint_origin(configured_url)
    return _authentik_logout_url_from_issuer(_optional_string_setting(SETTING_ISSUER))


def _logout_endpoint_origin(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme == "" or parsed.netloc == "":
        return ""
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _authentik_logout_url_from_issuer(issuer: str) -> str:
    parsed = urlsplit(issuer)
    if parsed.scheme == "" or parsed.netloc == "":
        return ""
    issuer_path = parsed.path.strip("/")
    issuer_segments = issuer_path.split("/")
    if len(issuer_segments) < OIDC_ISSUER_PROVIDER_SLUG_SEGMENT_COUNT or issuer_segments[:2] != [
        "application",
        "o",
    ]:
        return ""
    provider_slug = issuer_segments[2]
    if provider_slug == "":
        return ""
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            f"/application/o/{provider_slug}/end-session/",
            "",
            "",
        ),
    )


def _required_setting(name: str) -> str:
    value = _string_setting(name)
    if value == "":
        raise OidcSessionError(name, "is not configured")
    return value


def _optional_string_setting(name: str) -> str:
    value = getattr(django_settings, name, "")
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    raise OidcSessionError(name, "must be a string")


def _string_setting(name: str) -> str:
    value: str | None = getattr(django_settings, name, None)
    match value:
        case str() as setting_value:
            return setting_value
        case _:
            raise OidcSessionError(name, "must be a string")


def _scopes_from_settings() -> tuple[str, ...]:
    return _string_tuple_setting(SETTING_SCOPES)


def _string_tuple_setting(name: str) -> tuple[str, ...]:
    value: tuple[str, ...] | list[str] | str | None = getattr(
        django_settings,
        name,
        None,
    )
    match value:
        case tuple() as scopes:
            return scopes
        case list() as scopes:
            return tuple(scopes)
        case str() as scopes_text:
            return tuple(scope for scope in scopes_text.split() if scope)
        case _:
            raise OidcSessionError(name, "must be a string sequence")


def _float_setting(name: str) -> float:
    value: float | int | str | None = getattr(django_settings, name, None)
    match value:
        case float() as float_value:
            return float_value
        case int() as int_value:
            return float(int_value)
        case str() as string_value:
            return float(string_value)
        case _:
            raise OidcSessionError(name, "must be a number")


def _require_authorization_code(code: str) -> None:
    if code == "":
        raise OidcSessionError(FIELD_AUTHORIZATION_CODE, REASON_CODE_REQUIRED)


def _safe_auth_success_next(request: HttpRequest) -> str:
    return safe_next_path(request.GET.get("next"), default=DEFAULT_AUTH_SUCCESS_NEXT)


def _session_string(request: HttpRequest, key: str) -> str:
    match request.session.get(key):
        case str() as value:
            return value
        case _:
            return ""


@csrf_exempt
@require_POST
def backchannel_logout(request: HttpRequest) -> JsonResponse:
    try:
        claims = verify_logout_token(
            request.POST.get("logout_token", ""),
            _oidc_config_from_settings(),
        )
        _remember_logout_jti(claims.jti, claims.replay_timeout)
    except OidcSessionError as error:
        response = JsonResponse(
            {"error": "invalid_request", "error_description": str(error)},
            status=HTTPStatus.BAD_REQUEST,
        )
    else:
        try:
            count = revoke_authentik_sessions(sid=claims.sid, subject=claims.subject)
            _ = AuditService.record(
                AuditRecord(
                    actor_type="authentik",
                    actor_id=claims.subject,
                    action="oidc_backchannel_logout",
                    target_type="user",
                    target_id=claims.subject,
                    metadata={
                        "sid": claims.sid,
                        "subject": claims.subject,
                        "revoked_sessions": count,
                    },
                )
            )
        except Exception:
            # 缓存清理失败不能替换撤销或审计的原始异常。
            with suppress(Exception):
                _ = cache.delete(f"easyauth:oidc:logout-jti:{claims.jti}")
            raise
        response = JsonResponse({})
    response.headers["Cache-Control"] = "no-store"
    return response


def _remember_logout_jti(jti: str, timeout: int) -> None:
    if not cache.add(f"easyauth:oidc:logout-jti:{jti}", value=True, timeout=timeout):
        raise OidcSessionError(FIELD_BACKCHANNEL, "logout token was already used")


SILENT_LOGOUT_ERRORS: Final = frozenset(
    {
        "login_required",
        "access_denied",
    }
)


class SilentAttempt(TypedDict):
    nonce: str
    created_at: float


SILENT_ATTEMPT_TTL: Final = 600
SILENT_ATTEMPT_LIMIT: Final = 10


def _silent_attempts(request: HttpRequest) -> dict[str, SilentAttempt]:
    return cast(
        "dict[str, SilentAttempt]", request.session.get(OIDC_SILENT_ATTEMPTS_SESSION_KEY, {})
    )


def _save_silent_attempts(request: HttpRequest, attempts: dict[str, SilentAttempt]) -> None:
    cutoff = time() - SILENT_ATTEMPT_TTL
    valid = sorted(
        (
            (state, attempt)
            for state, attempt in attempts.items()
            if attempt["created_at"] >= cutoff
        ),
        key=lambda item: item[1]["created_at"],
    )
    request.session[OIDC_SILENT_ATTEMPTS_SESSION_KEY] = dict(valid[-SILENT_ATTEMPT_LIMIT:])


def _silent_callback(request: HttpRequest, attempt: SilentAttempt) -> HttpResponse:
    previous_subject = _session_string(request, AUTHENTIK_SESSION_KEY)
    if time() - attempt["created_at"] > SILENT_ATTEMPT_TTL:
        return _silent_result(request, "error", "")
    try:
        upstream_error = request.GET.get("error", "")
        if upstream_error in SILENT_LOGOUT_ERRORS:
            clear_auth_session(request)
            outcome = "logged_out"
        elif upstream_error:
            outcome = "error"
        else:
            outcome = _silent_bind(request, previous_subject, attempt["nonce"])
    except OidcUserInactiveError:
        clear_auth_session(request)
        outcome = "logged_out"
    except OidcSessionError:
        outcome = "error"
    user_id = (
        _session_string(request, AUTHENTIK_SESSION_KEY)
        if outcome in {"unchanged", "changed"}
        else ""
    )
    return _silent_result(request, outcome, user_id)


def _silent_bind(request: HttpRequest, previous_subject: str, nonce: str) -> str:
    config = _oidc_config_from_settings()
    config = replace(config, redirect_uri=_effective_redirect_uri(request, config.redirect_uri))
    code = request.GET.get("code", "")
    _require_authorization_code(code)
    claims = exchange_authorization_code_for_claims(request, code, config)
    verified = verify_oidc_claims(
        claims,
        config,
        expected_nonce=nonce,
    )
    if previous_subject == verified.subject:
        with transaction.atomic():
            user = UserMirror.objects.select_for_update().get(authentik_user_id=previous_subject)
            if user.status != USER_STATUS_ACTIVE:
                raise OidcUserInactiveError
            _update_existing_user_profile(user, verified)
            changed_fields = apply_dingtalk_org_context(user, verified.dingtalk_org)
            if changed_fields:
                changed_fields.append("updated_at")
                user.full_clean()
                user.save(update_fields=changed_fields)
            binding = OidcSessionBinding.objects.select_for_update().get(
                session_key=request.session.session_key,
                authentik_user_id=previous_subject,
            )
            binding.sid = verified.sid
            binding.full_clean()
            binding.save(update_fields=["sid"])
        return "unchanged"
    _ = bind_oidc_session(request, verified)
    return "changed"


@xframe_options_sameorigin
def _silent_result(request: HttpRequest, outcome: str, user_id: str) -> HttpResponse:
    response = render(
        request, "easyauth/oidc_silent_result.html", {"outcome": outcome, "user_id": user_id}
    )
    response.headers["Cache-Control"] = "no-store"
    return response
