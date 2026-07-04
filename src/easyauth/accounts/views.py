from __future__ import annotations

from dataclasses import replace
from http import HTTPStatus
from secrets import token_urlsafe
from typing import Final
from urllib.parse import SplitResult, parse_qsl, urlencode, urlsplit, urlunsplit

from django.conf import settings as django_settings
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.views.decorators.http import require_POST

from easyauth.accounts.auth import (
    DEFAULT_AUTH_SUCCESS_NEXT,
    OIDC_ID_TOKEN_SESSION_KEY,
    OIDC_NEXT_SESSION_KEY,
    OIDC_NONCE_SESSION_KEY,
    OIDC_STATE_SESSION_KEY,
    OidcClientConfig,
    OidcSessionError,
    bind_oidc_session,
    build_authorization_url,
    clear_oidc_login_attempt,
    verify_callback_state,
    verify_oidc_claims,
)
from easyauth.accounts.logout_state import (
    clear_browser_logged_out,
    logged_out_response,
    mark_browser_logged_out,
)
from easyauth.accounts.oidc_exchange import exchange_authorization_code_for_claims

FIELD_AUTHORIZATION_CODE = "code"
LOCAL_LOOPBACK_HOSTS: Final = frozenset({"127.0.0.1", "::1", "localhost"})
REASON_CODE_REQUIRED = "is required"
SETTING_CLIENT_ID = "EASYAUTH_AUTHENTIK_OIDC_CLIENT_ID"
SETTING_CLIENT_SECRET = "EASYAUTH_AUTHENTIK_OIDC_CLIENT_SECRET"  # noqa: S105 - 配置键名, 不是密钥值.
SETTING_AUTHORIZATION_ENDPOINT = "EASYAUTH_AUTHENTIK_OIDC_AUTHORIZATION_ENDPOINT"
SETTING_AUTHENTIK_LOGOUT_URL = "EASYAUTH_AUTHENTIK_LOGOUT_URL"
SETTING_POST_LOGOUT_REDIRECT_URI = "EASYAUTH_AUTHENTIK_POST_LOGOUT_REDIRECT_URI"
SETTING_HTTP_TIMEOUT_SECONDS = "EASYAUTH_AUTHENTIK_OIDC_HTTP_TIMEOUT_SECONDS"
SETTING_ISSUER = "EASYAUTH_AUTHENTIK_OIDC_ISSUER"
SETTING_JWKS_URL = "EASYAUTH_AUTHENTIK_OIDC_JWKS_URL"
SETTING_REDIRECT_URI = "EASYAUTH_AUTHENTIK_OIDC_REDIRECT_URI"
SETTING_SIGNING_ALGORITHMS = "EASYAUTH_AUTHENTIK_OIDC_SIGNING_ALGORITHMS"
SETTING_SCOPES = "EASYAUTH_AUTHENTIK_OIDC_SCOPES"
SETTING_TOKEN_ENDPOINT = "EASYAUTH_AUTHENTIK_OIDC_TOKEN_ENDPOINT"  # noqa: S105 - 配置键名, 不是密钥值.
OIDC_ISSUER_PROVIDER_SLUG_SEGMENT_COUNT: Final = 3


def oidc_login(request: HttpRequest) -> HttpResponseRedirect:
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
    request.session[OIDC_STATE_SESSION_KEY] = state
    request.session[OIDC_NONCE_SESSION_KEY] = nonce
    request.session[OIDC_NEXT_SESSION_KEY] = _safe_auth_success_next(request)
    response = HttpResponseRedirect(
        build_authorization_url(
            config,
            state=state,
            nonce=nonce,
        ),
    )
    clear_browser_logged_out(response)
    return response


def oidc_callback(request: HttpRequest) -> HttpResponse:
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
    request.session.flush()
    redirect_url = _authentik_logout_url(id_token_hint=id_token_hint)
    if redirect_url == "":
        redirect_url = "/auth/logged-out/?next=%2Fportal%2F"
    response = HttpResponseRedirect(redirect_url)
    mark_browser_logged_out(response)
    return response


def logged_out(request: HttpRequest) -> HttpResponse:
    return logged_out_response(request)


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
    if (
        current.scheme == canonical.scheme
        and current.netloc == canonical.netloc
    ):
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


def _authentik_logout_url(*, id_token_hint: str) -> str:
    configured_url = _optional_string_setting(SETTING_AUTHENTIK_LOGOUT_URL)
    if configured_url != "":
        endpoint = configured_url
    else:
        endpoint = _authentik_logout_url_from_issuer(_optional_string_setting(SETTING_ISSUER))
    if endpoint == "":
        return ""
    return _with_logout_query(endpoint, id_token_hint=id_token_hint)


def _authentik_logout_url_from_issuer(issuer: str) -> str:
    parsed = urlsplit(issuer)
    if parsed.scheme == "" or parsed.netloc == "":
        return ""
    issuer_path = parsed.path.strip("/")
    issuer_segments = issuer_path.split("/")
    if (
        len(issuer_segments) < OIDC_ISSUER_PROVIDER_SLUG_SEGMENT_COUNT
        or issuer_segments[:2] != ["application", "o"]
    ):
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


def _with_logout_query(endpoint: str, *, id_token_hint: str) -> str:
    parsed = urlsplit(endpoint)
    query_params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if id_token_hint != "":
        query_params.setdefault("id_token_hint", id_token_hint)
        post_logout_redirect_uri = _optional_string_setting(SETTING_POST_LOGOUT_REDIRECT_URI)
        if post_logout_redirect_uri != "":
            query_params.setdefault("post_logout_redirect_uri", post_logout_redirect_uri)
    if not query_params:
        return endpoint
    query = urlencode(query_params)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, ""))


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
    next_path = request.GET.get("next", DEFAULT_AUTH_SUCCESS_NEXT)
    if _is_local_absolute_path(next_path):
        return next_path
    return DEFAULT_AUTH_SUCCESS_NEXT


def _is_local_absolute_path(value: str) -> bool:
    if not value.startswith("/") or value.startswith("//") or "\\" in value:
        return False
    parsed = urlsplit(value)
    return parsed.scheme == "" and parsed.netloc == ""


def _session_string(request: HttpRequest, key: str) -> str:
    match request.session.get(key):
        case str() as value:
            return value
        case _:
            return ""
