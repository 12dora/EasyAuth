from __future__ import annotations

from base64 import urlsafe_b64decode
from dataclasses import dataclass
from ipaddress import ip_address
from json import JSONDecodeError, loads
from typing import TYPE_CHECKING, Final, Protocol, Self, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt import InvalidTokenError

from easyauth.accounts.auth import (
    FIELD_CODE_EXCHANGE,
    OidcClaimsInput,
    OidcClaimValue,
    OidcClientConfig,
    OidcSessionError,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from types import TracebackType

    from django.http import HttpRequest

type JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
type JsonObject = dict[str, JsonValue]

FIELD_ID_TOKEN: Final = "id_token"  # noqa: S105 - OIDC 响应字段名, 不是密钥值.
FIELD_JWKS: Final = "jwks"
FIELD_JWT_HEADER: Final = "jwt_header"
FIELD_JWT_SIGNATURE: Final = "jwt_signature"
HEADER_ACCEPT: Final = "application/json"
HEADER_FORM: Final = "application/x-www-form-urlencoded"
REASON_CLIENT_SECRET_REQUIRED: Final = "client secret is not configured"  # noqa: S105 - 错误说明, 不是密钥值.
REASON_HTTP_FAILED: Final = "request failed"
REASON_ID_TOKEN_REQUIRED: Final = "id token is required"  # noqa: S105 - 错误说明, 不是密钥值.
REASON_INVALID_JSON: Final = "response is not valid JSON"
REASON_JWKS_KEY_MISSING: Final = "matching signing key is missing"
REASON_JWT_INVALID: Final = "id token is invalid"
REASON_ENDPOINT_HTTPS_REQUIRED: Final = "endpoint must use HTTPS"
REASON_RSA_KEY_REQUIRED: Final = "RSA signing key is required"
REASON_UNSUPPORTED_ALGORITHM: Final = "signing algorithm is not allowed"
LOCAL_HTTP_OIDC_HOSTS: Final[frozenset[str]] = frozenset({"host.docker.internal", "localhost"})


@dataclass(frozen=True, slots=True)
class _JwtHeader:
    algorithm: str
    key_id: str


class _ReadableResponse(Protocol):
    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    def read(self) -> bytes: ...


def exchange_authorization_code_for_claims(
    _request: HttpRequest,
    code: str,
    config: OidcClientConfig,
) -> OidcClaimsInput:
    if config.client_secret == "":
        raise OidcSessionError(FIELD_CODE_EXCHANGE, REASON_CLIENT_SECRET_REQUIRED)

    token_response = _post_token_request(code, config)
    id_token = _required_json_string(token_response, FIELD_ID_TOKEN)
    return _verify_id_token(id_token, config)


def _post_token_request(code: str, config: OidcClientConfig) -> JsonObject:
    form_body = urlencode(
        {
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": config.redirect_uri,
        },
    ).encode("ascii")
    request = oidc_endpoint_request(
        config.token_endpoint,
        data=form_body,
        headers={"Accept": HEADER_ACCEPT, "Content-Type": HEADER_FORM},
        method="POST",
    )
    return _request_json(request, timeout_seconds=config.http_timeout_seconds)


def _request_json(request: Request, *, timeout_seconds: float) -> JsonObject:
    try:
        response_context = cast(
            "_ReadableResponse",
            urlopen(  # noqa: S310 - URL 已在构造 Request 前限制为 HTTPS.
                request,
                timeout=timeout_seconds,
            ),
        )
        with response_context as response:
            raw_body = response.read()
    except HTTPError as error:
        raise OidcSessionError(FIELD_CODE_EXCHANGE, REASON_HTTP_FAILED) from error
    except URLError as error:
        raise OidcSessionError(FIELD_CODE_EXCHANGE, REASON_HTTP_FAILED) from error
    return _parse_json_object(raw_body)


def _verify_id_token(id_token: str, config: OidcClientConfig) -> OidcClaimsInput:
    header = _jwt_header(id_token)
    if header.algorithm not in config.signing_algorithms:
        raise OidcSessionError(FIELD_JWT_HEADER, REASON_UNSUPPORTED_ALGORITHM)

    public_key = _jwks_public_key(
        jwks_url=config.jwks_url,
        key_id=header.key_id,
        algorithm=header.algorithm,
        timeout_seconds=config.http_timeout_seconds,
    )
    try:
        decoded = cast(
            "JsonValue",
            jwt.decode(
                id_token,
                public_key,
                algorithms=(header.algorithm,),
                audience=config.client_id,
                issuer=config.issuer,
                options={"require": ["exp", "iss", "aud", "sub"]},
            ),
        )
    except InvalidTokenError as error:
        raise OidcSessionError(FIELD_JWT_SIGNATURE, REASON_JWT_INVALID) from error
    return _json_claims(decoded)


def _jwt_header(id_token: str) -> _JwtHeader:
    header_segment = id_token.split(".", maxsplit=1)[0]
    header = _parse_json_object(_base64url_decode(header_segment))
    algorithm = _required_json_string(header, "alg")
    key_id = _required_json_string(header, "kid")
    return _JwtHeader(algorithm=algorithm, key_id=key_id)


def _jwks_public_key(
    *,
    jwks_url: str,
    key_id: str,
    algorithm: str,
    timeout_seconds: float,
) -> rsa.RSAPublicKey:
    request = oidc_endpoint_request(jwks_url, headers={"Accept": HEADER_ACCEPT})
    jwks = _request_json(request, timeout_seconds=timeout_seconds)
    keys = jwks.get("keys")
    match keys:
        case list() as jwk_values:
            for jwk_value in jwk_values:
                jwk = _json_object_or_none(jwk_value)
                if jwk is not None and _jwk_matches(jwk, key_id=key_id, algorithm=algorithm):
                    return _rsa_public_key(jwk)
        case _:
            pass
    raise OidcSessionError(FIELD_JWKS, REASON_JWKS_KEY_MISSING)


def _jwk_matches(jwk: JsonObject, *, key_id: str, algorithm: str) -> bool:
    return (
        jwk.get("kid") == key_id
        and jwk.get("kty") == "RSA"
        and jwk.get("alg", algorithm) == algorithm
        and jwk.get("use", "sig") == "sig"
    )


def _rsa_public_key(jwk: JsonObject) -> rsa.RSAPublicKey:
    if jwk.get("kty") != "RSA":
        raise OidcSessionError(FIELD_JWKS, REASON_RSA_KEY_REQUIRED)
    modulus = _base64url_uint(_required_json_string(jwk, "n"))
    exponent = _base64url_uint(_required_json_string(jwk, "e"))
    return rsa.RSAPublicNumbers(exponent, modulus).public_key()


def _json_claims(decoded: JsonValue) -> OidcClaimsInput:
    match decoded:
        case dict() as mapping:
            claims: dict[str, OidcClaimValue] = {}
            for key, value in mapping.items():
                claim_value = _oidc_claim_value_or_none(value)
                if claim_value is not None:
                    claims[key] = claim_value
            return claims
        case _:
            raise OidcSessionError(FIELD_JWT_SIGNATURE, REASON_JWT_INVALID)


def _oidc_claim_value_or_none(value: JsonValue) -> OidcClaimValue:
    match value:
        case None | bool() | int() | float() | str():
            return value
        case list() as items:
            return _string_list_or_empty(items)
        case dict() as mapping:
            return cast("dict[str, object]", mapping)


def _string_list_or_empty(items: list[JsonValue]) -> list[str]:
    strings: list[str] = []
    for item in items:
        match item:
            case str() as string_item:
                strings.append(string_item)
            case _:
                return []
    return strings


def _parse_json_object(raw_body: bytes) -> JsonObject:
    try:
        parsed = cast("JsonValue", loads(raw_body.decode("utf-8")))
    except (JSONDecodeError, UnicodeDecodeError) as error:
        raise OidcSessionError(FIELD_CODE_EXCHANGE, REASON_INVALID_JSON) from error
    match parsed:
        case dict() as parsed_object:
            return parsed_object
        case _:
            raise OidcSessionError(FIELD_CODE_EXCHANGE, REASON_INVALID_JSON)


def _json_object_or_none(value: JsonValue) -> JsonObject | None:
    match value:
        case dict() as mapping:
            return mapping
        case _:
            return None


def _required_json_string(mapping: Mapping[str, JsonValue], key: str) -> str:
    value = mapping.get(key)
    match value:
        case str() as string_value:
            if string_value == "":
                raise OidcSessionError(key, "is required")
            return string_value
        case _:
            raise OidcSessionError(key, "must be a string")


def _base64url_uint(encoded: str) -> int:
    return int.from_bytes(_base64url_decode(encoded), byteorder="big")


def _base64url_decode(encoded: str) -> bytes:
    padding = "=" * (-len(encoded) % 4)
    return urlsafe_b64decode((encoded + padding).encode("ascii"))


def oidc_endpoint_request(
    url: str,
    *,
    data: bytes | None = None,
    headers: dict[str, str],
    method: str | None = None,
) -> Request:
    parsed = urlsplit(url)
    if parsed.scheme != "https" and not _is_local_http_oidc_endpoint(
        parsed.scheme,
        parsed.hostname,
    ):
        raise OidcSessionError(FIELD_CODE_EXCHANGE, REASON_ENDPOINT_HTTPS_REQUIRED)
    return Request(  # noqa: S310 - 仅允许上方校验过的 HTTPS 或回环 HTTP OIDC endpoint.
        url,
        data=data,
        headers=headers,
        method=method,
    )


def _is_local_http_oidc_endpoint(scheme: str, hostname: str | None) -> bool:
    if scheme != "http" or hostname is None:
        return False
    if hostname in LOCAL_HTTP_OIDC_HOSTS:
        return True
    try:
        return ip_address(hostname).is_loopback
    except ValueError:
        return False
