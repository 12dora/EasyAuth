from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, override
from urllib.parse import urlencode, urlsplit, urlunsplit

from django.db import transaction

from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.accounts.org_context import apply_dingtalk_org_context

if TYPE_CHECKING:
    from django.http import HttpRequest

AUTHENTIK_SESSION_KEY: Final = "easyauth_authentik_user_id"
AUTHENTIK_GROUPS_SESSION_KEY: Final = "easyauth_authentik_groups"
OIDC_STATE_SESSION_KEY: Final = "easyauth_oidc_state"
OIDC_NONCE_SESSION_KEY: Final = "easyauth_oidc_nonce"
OIDC_NEXT_SESSION_KEY: Final = "easyauth_oidc_next"
OIDC_ID_TOKEN_SESSION_KEY: Final = "easyauth_oidc_id_token"  # noqa: S105 - session key 名称, 不是 token 值.
DEFAULT_AUTH_SUCCESS_NEXT: Final = "/portal/"
FIELD_AUDIENCE: Final = "audience"
FIELD_AUTHORIZED_PARTY: Final = "azp"
FIELD_AVATAR_URL: Final = "picture"
FIELD_ISSUER: Final = "issuer"
FIELD_NONCE: Final = "nonce"
FIELD_STATE: Final = "state"
FIELD_CODE_EXCHANGE: Final = "code_exchange"
REASON_AUTHORIZED_PARTY_MISMATCH: Final = "does not match configured client"
REASON_AUTHORIZED_PARTY_REQUIRED: Final = "is required for multiple audiences"
REASON_AUDIENCE_TYPE: Final = "must be a string or string list"
REASON_CLIENT_MISSING: Final = "does not include configured client"
REASON_ISSUER_MISMATCH: Final = "does not match configured issuer"
REASON_LOGIN_NONCE_MISMATCH: Final = "does not match login attempt"
REASON_LOGIN_STATE_MISMATCH: Final = "does not match login attempt"
REASON_LOGIN_STATE_MISSING: Final = "login state is missing"
REASON_CODE_EXCHANGE_UNIMPLEMENTED: Final = "is not implemented"

type OidcClaimValue = (
    None | bool | int | float | str | tuple[str, ...] | list[str] | dict[str, object]
)
type OidcClaimsInput = Mapping[str, OidcClaimValue]


@dataclass(frozen=True, slots=True)
class OidcClientConfig:
    issuer: str
    authorization_endpoint: str
    client_id: str
    client_secret: str
    redirect_uri: str
    scopes: tuple[str, ...]
    token_endpoint: str
    jwks_url: str
    signing_algorithms: tuple[str, ...]
    http_timeout_seconds: float


@dataclass(frozen=True, slots=True)
class VerifiedOidcClaims:
    subject: str
    name: str
    email: str
    avatar_url: str = ""
    groups: tuple[str, ...] = ()
    dingtalk_org: object | None = None


@dataclass(frozen=True, slots=True)
class OidcSessionError(ValueError):
    field: str
    reason: str

    @override
    def __str__(self) -> str:
        return f"Invalid OIDC {self.field}: {self.reason}"


def build_authorization_url(
    config: OidcClientConfig,
    *,
    state: str,
    nonce: str,
    prompt: str = "",
    max_age: str = "",
) -> str:
    query_params = {
        "client_id": config.client_id,
        "nonce": nonce,
        "redirect_uri": config.redirect_uri,
        "response_type": "code",
        "scope": " ".join(config.scopes),
        "state": state,
    }
    if prompt:
        query_params["prompt"] = prompt
    if max_age:
        query_params["max_age"] = max_age
    query = urlencode(query_params)
    endpoint = config.authorization_endpoint or _authorization_endpoint(config.issuer)
    return f"{endpoint}?{query}"


def verify_callback_state(*, received_state: str, expected_state: str) -> None:
    if expected_state == "":
        raise OidcSessionError(FIELD_STATE, REASON_LOGIN_STATE_MISSING)
    if received_state != expected_state:
        raise OidcSessionError(FIELD_STATE, REASON_LOGIN_STATE_MISMATCH)


def verify_oidc_claims(
    claims: OidcClaimsInput,
    config: OidcClientConfig,
    *,
    expected_nonce: str,
) -> VerifiedOidcClaims:
    issuer = _required_string_claim(claims, "iss", "issuer")
    if issuer != config.issuer:
        raise OidcSessionError(FIELD_ISSUER, REASON_ISSUER_MISMATCH)

    audiences = _audience_values(claims)
    if config.client_id not in audiences:
        raise OidcSessionError(FIELD_AUDIENCE, REASON_CLIENT_MISSING)
    _verify_authorized_party(claims, audiences=audiences, client_id=config.client_id)

    subject = _required_string_claim(claims, "sub", "subject")
    nonce = _required_string_claim(claims, "nonce", FIELD_NONCE)
    if nonce != expected_nonce:
        raise OidcSessionError(FIELD_NONCE, REASON_LOGIN_NONCE_MISMATCH)

    return VerifiedOidcClaims(
        subject=subject,
        name=_display_name_claim(claims),
        email=_optional_string_claim(claims, "email"),
        avatar_url=_avatar_url_claim(claims),
        groups=_optional_string_tuple_claim(claims, "groups"),
        dingtalk_org=claims.get("dingtalk_org"),
    )


def bind_oidc_session(request: HttpRequest, claims: VerifiedOidcClaims) -> UserMirror:
    with transaction.atomic():
        user, created = UserMirror.objects.select_for_update().get_or_create(
            authentik_user_id=claims.subject,
            defaults={
                "avatar_url": claims.avatar_url,
                "email": claims.email,
                "name": claims.name,
                "status": USER_STATUS_ACTIVE,
            },
        )
        if not created:
            _update_existing_user_profile(user, claims)
        changed_fields = apply_dingtalk_org_context(user, claims.dingtalk_org)
        if changed_fields:
            changed_fields.append("updated_at")
            user.full_clean()
            user.save(update_fields=changed_fields)
    request.session.cycle_key()
    request.session[AUTHENTIK_SESSION_KEY] = user.authentik_user_id
    if claims.groups:
        request.session[AUTHENTIK_GROUPS_SESSION_KEY] = list(claims.groups)
    else:
        request.session.pop(AUTHENTIK_GROUPS_SESSION_KEY, None)
    return user


def clear_oidc_login_attempt(request: HttpRequest) -> None:
    request.session.pop(OIDC_STATE_SESSION_KEY, None)
    request.session.pop(OIDC_NONCE_SESSION_KEY, None)
    request.session.pop(OIDC_NEXT_SESSION_KEY, None)


def clear_auth_session(request: HttpRequest) -> None:
    request.session.pop(AUTHENTIK_SESSION_KEY, None)
    request.session.pop(AUTHENTIK_GROUPS_SESSION_KEY, None)
    request.session.pop(OIDC_ID_TOKEN_SESSION_KEY, None)


def exchange_authorization_code_for_claims(
    _request: HttpRequest,
    _code: str,
) -> OidcClaimsInput:
    raise OidcSessionError(FIELD_CODE_EXCHANGE, REASON_CODE_EXCHANGE_UNIMPLEMENTED)


def _authorization_endpoint(issuer: str) -> str:
    parsed = urlsplit(issuer)
    return urlunsplit((parsed.scheme, parsed.netloc, "/application/o/authorize/", "", ""))


def _required_string_claim(claims: OidcClaimsInput, key: str, field: str) -> str:
    value = claims.get(key, "")
    match value:
        case str() as claim:
            if claim == "":
                raise OidcSessionError(field, "is required")
            return claim
        case _:
            raise OidcSessionError(field, "must be a string")


def _optional_string_claim(claims: OidcClaimsInput, key: str) -> str:
    value = claims.get(key, "")
    match value:
        case str() as claim:
            return claim
        case _:
            return ""


def _optional_string_tuple_claim(claims: OidcClaimsInput, key: str) -> tuple[str, ...]:
    value = claims.get(key)
    match value:
        case None:
            return ()
        case str() as claim:
            return (claim,) if claim else ()
        case tuple() as values:
            return tuple(value for value in values if value)
        case list() as values:
            return tuple(value for value in values if value)
        case _:
            raise OidcSessionError(key, "must be a string sequence")


def _audience_values(claims: OidcClaimsInput) -> frozenset[str]:
    value = claims.get("aud", "")
    match value:
        case str() as audience:
            return frozenset({audience})
        case tuple() as audiences:
            return frozenset(audiences)
        case list() as audiences:
            return frozenset(audiences)
        case _:
            raise OidcSessionError(FIELD_AUDIENCE, REASON_AUDIENCE_TYPE)


def _verify_authorized_party(
    claims: OidcClaimsInput,
    *,
    audiences: frozenset[str],
    client_id: str,
) -> None:
    authorized_party = _optional_string_claim(claims, FIELD_AUTHORIZED_PARTY)
    if len(audiences) > 1 and authorized_party == "":
        raise OidcSessionError(FIELD_AUTHORIZED_PARTY, REASON_AUTHORIZED_PARTY_REQUIRED)
    if authorized_party not in {"", client_id}:
        raise OidcSessionError(FIELD_AUTHORIZED_PARTY, REASON_AUTHORIZED_PARTY_MISMATCH)


def _update_existing_user_profile(user: UserMirror, claims: VerifiedOidcClaims) -> None:
    changed_fields: list[str] = []
    if claims.name and user.name != claims.name:
        user.name = claims.name
        changed_fields.append("name")
    if claims.email and user.email != claims.email:
        user.email = claims.email
        changed_fields.append("email")
    if user.avatar_url != claims.avatar_url:
        user.avatar_url = claims.avatar_url
        changed_fields.append("avatar_url")
    if changed_fields:
        changed_fields.append("updated_at")
        user.full_clean()
        user.save(update_fields=changed_fields)


def _display_name_claim(claims: OidcClaimsInput) -> str:
    for key in ("name", "preferred_username", "nickname", "email"):
        value = _optional_string_claim(claims, key)
        if value:
            return value
    return _dingtalk_display_name_claim(claims)


def _dingtalk_display_name_claim(claims: OidcClaimsInput) -> str:
    for section_key in ("dingtalk", "dingtalk_org"):
        value = claims.get(section_key)
        if isinstance(value, dict):
            for field in ("name", "nick"):
                field_value = value.get(field)
                if isinstance(field_value, str) and field_value:
                    return field_value
    return ""


def _avatar_url_claim(claims: OidcClaimsInput) -> str:
    avatar_url = _optional_string_claim(claims, FIELD_AVATAR_URL)
    if _is_safe_avatar_url(avatar_url):
        return avatar_url
    return ""


def _is_safe_avatar_url(value: str) -> bool:
    if value == "":
        return True
    if value.startswith("/") and not value.startswith("//") and "\\" not in value:
        return True
    parsed = urlsplit(value)
    return parsed.scheme == "https" and parsed.netloc != ""
