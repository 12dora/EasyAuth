from __future__ import annotations

from base64 import urlsafe_b64encode
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.message import Message
from http import HTTPStatus
from json import dumps
from typing import TYPE_CHECKING, Final, Self
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from django.test import Client, RequestFactory, override_settings

from easyauth.accounts.auth import AUTHENTIK_SESSION_KEY, OidcClientConfig, OidcSessionError
from easyauth.accounts.oidc_exchange import exchange_authorization_code_for_claims

if TYPE_CHECKING:
    from types import TracebackType
    from urllib.request import Request

pytestmark = pytest.mark.django_db

AUTHENTIK_ISSUER: Final = "https://authentik.example.test/application/o/easyauth/"
CLIENT_ID: Final = "easyauth-portal-client"
CLIENT_SECRET: Final = "s12-client-secret"  # noqa: S105 - 测试夹具密钥值.
REDIRECT_URI: Final = "http://testserver/auth/callback/"
TOKEN_ENDPOINT: Final = "https://authentik.example.test/application/o/token/"  # noqa: S105 - 测试 URL, 不是密钥值.
JWKS_URL: Final = "https://authentik.example.test/application/o/easyauth/jwks/"
SESSION_KEY: Final = AUTHENTIK_SESSION_KEY
STATE_SESSION_KEY: Final = "easyauth_oidc_state"
NONCE_SESSION_KEY: Final = "easyauth_oidc_nonce"
OIDC_STATE: Final = "s12-state"
OIDC_NONCE: Final = "s12-nonce"
OIDC_CODE: Final = "s12-code"
OIDC_SUBJECT: Final = "s12-authentik-user"

@dataclass(frozen=True, slots=True)
class FakeResponse:
    payload: object

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    def read(self) -> bytes:
        if isinstance(self.payload, bytes):
            return self.payload
        return dumps(self.payload).encode("utf-8")


def test_exchange_rejects_empty_client_secret_before_token_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    token_endpoint_called = False

    def fake_urlopen(_request: Request, *, timeout: float) -> FakeResponse:
        assert timeout > 0
        nonlocal token_endpoint_called
        token_endpoint_called = True
        return FakeResponse({"id_token": "unused"})

    monkeypatch.setattr("easyauth.accounts.oidc_exchange.urlopen", fake_urlopen)

    # When / Then
    with pytest.raises(OidcSessionError) as error:
        _ = exchange_authorization_code_for_claims(
            RequestFactory().get("/auth/callback/"),
            OIDC_CODE,
            _oidc_config(client_secret=""),
        )
    assert error.value.field == "code_exchange"
    assert token_endpoint_called is False


@override_settings(
    EASYAUTH_AUTHENTIK_OIDC_ISSUER=AUTHENTIK_ISSUER,
    EASYAUTH_AUTHENTIK_OIDC_CLIENT_ID=CLIENT_ID,
    EASYAUTH_AUTHENTIK_OIDC_CLIENT_SECRET=CLIENT_SECRET,
    EASYAUTH_AUTHENTIK_OIDC_REDIRECT_URI=REDIRECT_URI,
    EASYAUTH_AUTHENTIK_OIDC_TOKEN_ENDPOINT=TOKEN_ENDPOINT,
    EASYAUTH_AUTHENTIK_OIDC_JWKS_URL=JWKS_URL,
    EASYAUTH_AUTHENTIK_OIDC_SIGNING_ALGORITHMS=("RS256",),
)
def test_s12_callback_exchanges_code_and_verifies_jwks_id_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    client = Client()
    _seed_oidc_attempt(client)
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    captured_form: dict[str, str] = {}
    id_token = _signed_id_token(private_key, nonce=OIDC_NONCE)
    jwk = _public_jwk(private_key.public_key())
    _patch_authentik_http(monkeypatch, id_token=id_token, jwk=jwk, captured_form=captured_form)
    old_session_key = client.session.session_key

    # When
    response = client.get(f"/auth/callback/?code={OIDC_CODE}&state={OIDC_STATE}")

    # Then
    assert response.status_code == HTTPStatus.FOUND
    assert response.headers["Location"] == "/portal/"
    assert captured_form["grant_type"] == "authorization_code"
    assert captured_form["code"] == OIDC_CODE
    assert captured_form["client_id"] == CLIENT_ID
    assert captured_form["client_secret"] == CLIENT_SECRET
    assert captured_form["redirect_uri"] == REDIRECT_URI
    assert client.session[SESSION_KEY] == OIDC_SUBJECT
    assert client.session.session_key != old_session_key
    assert STATE_SESSION_KEY not in client.session
    assert NONCE_SESSION_KEY not in client.session


@pytest.mark.parametrize(
    "failure_kind",
    [
        "http_error",
        "url_error",
        "non_json",
        "json_non_object",
        "missing_id_token",
    ],
)
@override_settings(
    EASYAUTH_AUTHENTIK_OIDC_ISSUER=AUTHENTIK_ISSUER,
    EASYAUTH_AUTHENTIK_OIDC_CLIENT_ID=CLIENT_ID,
    EASYAUTH_AUTHENTIK_OIDC_CLIENT_SECRET=CLIENT_SECRET,
    EASYAUTH_AUTHENTIK_OIDC_REDIRECT_URI=REDIRECT_URI,
    EASYAUTH_AUTHENTIK_OIDC_TOKEN_ENDPOINT=TOKEN_ENDPOINT,
    EASYAUTH_AUTHENTIK_OIDC_JWKS_URL=JWKS_URL,
    EASYAUTH_AUTHENTIK_OIDC_SIGNING_ALGORITHMS=("RS256",),
)
def test_s12_callback_rejects_token_endpoint_failure_without_session_write(
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
) -> None:
    # Given
    client = Client()
    _seed_oidc_attempt(client)
    _patch_token_endpoint_failure(monkeypatch, failure_kind)

    # When
    response = client.get(f"/auth/callback/?code={OIDC_CODE}&state={OIDC_STATE}")

    # Then
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert "Invalid OIDC" in response.content.decode()
    assert SESSION_KEY not in client.session


@pytest.mark.parametrize(
    "failure_kind",
    [
        "missing_matching_kid",
        "algorithm_not_allowed",
        "jwk_not_rsa",
        "jwk_missing_modulus",
        "jwk_missing_exponent",
    ],
)
@override_settings(
    EASYAUTH_AUTHENTIK_OIDC_ISSUER=AUTHENTIK_ISSUER,
    EASYAUTH_AUTHENTIK_OIDC_CLIENT_ID=CLIENT_ID,
    EASYAUTH_AUTHENTIK_OIDC_CLIENT_SECRET=CLIENT_SECRET,
    EASYAUTH_AUTHENTIK_OIDC_REDIRECT_URI=REDIRECT_URI,
    EASYAUTH_AUTHENTIK_OIDC_TOKEN_ENDPOINT=TOKEN_ENDPOINT,
    EASYAUTH_AUTHENTIK_OIDC_JWKS_URL=JWKS_URL,
    EASYAUTH_AUTHENTIK_OIDC_SIGNING_ALGORITHMS=("RS256",),
)
def test_s12_callback_rejects_jwks_verification_failures(
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
) -> None:
    # Given
    client = Client()
    _seed_oidc_attempt(client)
    signing_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    id_token = _signed_id_token(
        signing_key,
        nonce=OIDC_NONCE,
        algorithm="RS512" if failure_kind == "algorithm_not_allowed" else "RS256",
    )
    jwk = _failing_jwk(failure_kind, signing_key.public_key())
    _patch_authentik_http(
        monkeypatch,
        id_token=id_token,
        jwk=jwk,
        captured_form={},
        fail_on_jwks=failure_kind == "algorithm_not_allowed",
    )

    # When
    response = client.get(f"/auth/callback/?code={OIDC_CODE}&state={OIDC_STATE}")

    # Then
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert "Invalid OIDC" in response.content.decode()
    assert SESSION_KEY not in client.session


@override_settings(
    EASYAUTH_AUTHENTIK_OIDC_ISSUER=AUTHENTIK_ISSUER,
    EASYAUTH_AUTHENTIK_OIDC_CLIENT_ID=CLIENT_ID,
    EASYAUTH_AUTHENTIK_OIDC_CLIENT_SECRET=CLIENT_SECRET,
    EASYAUTH_AUTHENTIK_OIDC_REDIRECT_URI=REDIRECT_URI,
    EASYAUTH_AUTHENTIK_OIDC_TOKEN_ENDPOINT=TOKEN_ENDPOINT,
    EASYAUTH_AUTHENTIK_OIDC_JWKS_URL=JWKS_URL,
    EASYAUTH_AUTHENTIK_OIDC_SIGNING_ALGORITHMS=("RS256",),
)
def test_s12_callback_rejects_id_token_with_wrong_jwks_signature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    client = Client()
    _seed_oidc_attempt(client)
    signing_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    wrong_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    captured_form: dict[str, str] = {}
    id_token = _signed_id_token(signing_key, nonce=OIDC_NONCE)
    jwk = _public_jwk(wrong_key.public_key())
    _patch_authentik_http(monkeypatch, id_token=id_token, jwk=jwk, captured_form=captured_form)

    # When
    response = client.get(f"/auth/callback/?code={OIDC_CODE}&state={OIDC_STATE}")

    # Then
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert "jwt_signature" in response.content.decode()
    assert SESSION_KEY not in client.session
    assert STATE_SESSION_KEY not in client.session
    assert NONCE_SESSION_KEY not in client.session


def _seed_oidc_attempt(client: Client) -> None:
    session = client.session
    session[STATE_SESSION_KEY] = OIDC_STATE
    session[NONCE_SESSION_KEY] = OIDC_NONCE
    session.save()


def _oidc_config(*, client_secret: str = CLIENT_SECRET) -> OidcClientConfig:
    return OidcClientConfig(
        issuer=AUTHENTIK_ISSUER,
        authorization_endpoint="",
        client_id=CLIENT_ID,
        client_secret=client_secret,
        redirect_uri=REDIRECT_URI,
        scopes=("openid", "profile", "email"),
        token_endpoint=TOKEN_ENDPOINT,
        jwks_url=JWKS_URL,
        signing_algorithms=("RS256",),
        http_timeout_seconds=5,
    )


def _signed_id_token(
    private_key: rsa.RSAPrivateKey,
    *,
    nonce: str,
    algorithm: str = "RS256",
) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "aud": CLIENT_ID,
            "email": "s12-jwks@example.test",
            "exp": now + timedelta(minutes=5),
            "iat": now,
            "iss": AUTHENTIK_ISSUER,
            "name": "JWKS 用户",
            "nonce": nonce,
            "sub": OIDC_SUBJECT,
        },
        private_key,
        algorithm=algorithm,
        headers={"kid": "s12-kid"},
    )


def _public_jwk(
    public_key: rsa.RSAPublicKey,
    *,
    kid: str = "s12-kid",
    kty: str = "RSA",
    include_modulus: bool = True,
    include_exponent: bool = True,
) -> dict[str, str]:
    public_numbers = public_key.public_numbers()
    jwk = {
        "alg": "RS256",
        "kid": kid,
        "kty": kty,
        "use": "sig",
    }
    if include_exponent:
        jwk["e"] = _base64url_uint(public_numbers.e)
    if include_modulus:
        jwk["n"] = _base64url_uint(public_numbers.n)
    return jwk


def _failing_jwk(failure_kind: str, public_key: rsa.RSAPublicKey) -> dict[str, str]:
    match failure_kind:
        case "missing_matching_kid":
            return _public_jwk(public_key, kid="other-kid")
        case "algorithm_not_allowed":
            return _public_jwk(public_key)
        case "jwk_not_rsa":
            return _public_jwk(public_key, kty="EC")
        case "jwk_missing_modulus":
            return _public_jwk(public_key, include_modulus=False)
        case "jwk_missing_exponent":
            return _public_jwk(public_key, include_exponent=False)
        case _:
            raise AssertionError(failure_kind)


def _patch_authentik_http(
    monkeypatch: pytest.MonkeyPatch,
    *,
    id_token: str,
    jwk: dict[str, str],
    captured_form: dict[str, str],
    fail_on_jwks: bool = False,
) -> None:
    def fake_urlopen(request: Request, *, timeout: float) -> FakeResponse:
        assert timeout > 0
        if request.full_url == TOKEN_ENDPOINT:
            body = request.data
            assert isinstance(body, bytes)
            parsed_form: dict[str, list[str]] = parse_qs(body.decode("ascii"))
            captured_form.update({key: value[0] for key, value in parsed_form.items()})
            return FakeResponse({"id_token": id_token})
        if request.full_url == JWKS_URL:
            if fail_on_jwks:
                raise AssertionError
            return FakeResponse({"keys": [jwk]})
        raise AssertionError(request.full_url)

    monkeypatch.setattr("easyauth.accounts.oidc_exchange.urlopen", fake_urlopen)


def _patch_token_endpoint_failure(monkeypatch: pytest.MonkeyPatch, failure_kind: str) -> None:
    def fake_urlopen(request: Request, *, timeout: float) -> FakeResponse:
        assert request.full_url == TOKEN_ENDPOINT
        assert timeout > 0
        match failure_kind:
            case "http_error":
                raise HTTPError(
                    TOKEN_ENDPOINT,
                    HTTPStatus.BAD_GATEWAY,
                    "bad gateway",
                    Message(),
                    None,
                )
            case "url_error":
                reason = "connection refused"
                raise URLError(reason)
            case "non_json":
                return FakeResponse(b"not-json")
            case "json_non_object":
                return FakeResponse(["not", "an", "object"])
            case "missing_id_token":
                return FakeResponse({"access_token": "token-only"})
            case _:
                raise AssertionError(failure_kind)

    monkeypatch.setattr("easyauth.accounts.oidc_exchange.urlopen", fake_urlopen)


def _base64url_uint(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, byteorder="big")
    return urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
