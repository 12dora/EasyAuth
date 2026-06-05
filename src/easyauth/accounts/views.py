from __future__ import annotations

from http import HTTPStatus
from secrets import token_urlsafe

from django.conf import settings as django_settings
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect

from easyauth.accounts.auth import (
    OIDC_NONCE_SESSION_KEY,
    OIDC_STATE_SESSION_KEY,
    OidcClientConfig,
    OidcSessionError,
    bind_oidc_session,
    build_authorization_url,
    clear_auth_session,
    clear_oidc_login_attempt,
    verify_callback_state,
    verify_oidc_claims,
)
from easyauth.accounts.oidc_exchange import exchange_authorization_code_for_claims

FIELD_AUTHORIZATION_CODE = "code"
REASON_CODE_REQUIRED = "is required"
SETTING_CLIENT_ID = "EASYAUTH_AUTHENTIK_OIDC_CLIENT_ID"
SETTING_CLIENT_SECRET = "EASYAUTH_AUTHENTIK_OIDC_CLIENT_SECRET"  # noqa: S105 - 配置键名, 不是密钥值.
SETTING_AUTHORIZATION_ENDPOINT = "EASYAUTH_AUTHENTIK_OIDC_AUTHORIZATION_ENDPOINT"
SETTING_HTTP_TIMEOUT_SECONDS = "EASYAUTH_AUTHENTIK_OIDC_HTTP_TIMEOUT_SECONDS"
SETTING_ISSUER = "EASYAUTH_AUTHENTIK_OIDC_ISSUER"
SETTING_JWKS_URL = "EASYAUTH_AUTHENTIK_OIDC_JWKS_URL"
SETTING_REDIRECT_URI = "EASYAUTH_AUTHENTIK_OIDC_REDIRECT_URI"
SETTING_SIGNING_ALGORITHMS = "EASYAUTH_AUTHENTIK_OIDC_SIGNING_ALGORITHMS"
SETTING_SCOPES = "EASYAUTH_AUTHENTIK_OIDC_SCOPES"
SETTING_TOKEN_ENDPOINT = "EASYAUTH_AUTHENTIK_OIDC_TOKEN_ENDPOINT"  # noqa: S105 - 配置键名, 不是密钥值.


def oidc_login(request: HttpRequest) -> HttpResponseRedirect:
    config = _oidc_config_from_settings()
    state = token_urlsafe(32)
    nonce = token_urlsafe(32)
    request.session[OIDC_STATE_SESSION_KEY] = state
    request.session[OIDC_NONCE_SESSION_KEY] = nonce
    return HttpResponseRedirect(build_authorization_url(config, state=state, nonce=nonce))


def oidc_callback(request: HttpRequest) -> HttpResponse:
    config = _oidc_config_from_settings()
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
        clear_auth_session(request)
        clear_oidc_login_attempt(request)
        return HttpResponse(str(error), status=HTTPStatus.BAD_REQUEST, content_type="text/plain")

    clear_oidc_login_attempt(request)
    return HttpResponseRedirect("/portal/")


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


def _required_setting(name: str) -> str:
    value = _string_setting(name)
    if value == "":
        raise OidcSessionError(name, "is not configured")
    return value


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


def _session_string(request: HttpRequest, key: str) -> str:
    match request.session.get(key):
        case str() as value:
            return value
        case _:
            return ""
