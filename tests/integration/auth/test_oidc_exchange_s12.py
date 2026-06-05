from __future__ import annotations

from base64 import urlsafe_b64encode
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from json import dumps
from typing import TYPE_CHECKING, Final, Self
from urllib.parse import parse_qs

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from django.test import Client, override_settings

from easyauth.accounts.auth import AUTHENTIK_SESSION_KEY

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

type ResponsePayload = dict[str, str | list[dict[str, str]]]


@dataclass(frozen=True, slots=True)
class FakeResponse:
    payload: ResponsePayload

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
        return dumps(self.payload).encode("utf-8")


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


def _signed_id_token(private_key: rsa.RSAPrivateKey, *, nonce: str) -> str:
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
        algorithm="RS256",
        headers={"kid": "s12-kid"},
    )


def _public_jwk(public_key: rsa.RSAPublicKey) -> dict[str, str]:
    public_numbers = public_key.public_numbers()
    return {
        "alg": "RS256",
        "e": _base64url_uint(public_numbers.e),
        "kid": "s12-kid",
        "kty": "RSA",
        "n": _base64url_uint(public_numbers.n),
        "use": "sig",
    }


def _patch_authentik_http(
    monkeypatch: pytest.MonkeyPatch,
    *,
    id_token: str,
    jwk: dict[str, str],
    captured_form: dict[str, str],
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
            return FakeResponse({"keys": [jwk]})
        raise AssertionError(request.full_url)

    monkeypatch.setattr("easyauth.accounts.oidc_exchange.urlopen", fake_urlopen)


def _base64url_uint(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, byteorder="big")
    return urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
