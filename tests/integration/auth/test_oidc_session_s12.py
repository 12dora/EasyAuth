from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, Final
from urllib.parse import parse_qs, urlsplit

import pytest
from django.test import Client, override_settings

from easyauth.accounts.auth import AUTHENTIK_SESSION_KEY
from easyauth.accounts.models import UserMirror

if TYPE_CHECKING:
    from django.http import HttpRequest

    from easyauth.accounts.auth import OidcClientConfig

pytestmark = pytest.mark.django_db

AUTHENTIK_ISSUER: Final = "https://authentik.example.test/application/o/easyauth/"
AUTHORIZATION_ENDPOINT: Final = "http://127.0.0.1:19000/application/o/authorize/"
CLIENT_ID: Final = "easyauth-portal-client"
REDIRECT_URI: Final = "http://testserver/auth/callback/"
CLIENT_SECRET: Final = "s12-client-secret"  # noqa: S105 - 测试夹具密钥值.
SESSION_KEY: Final = AUTHENTIK_SESSION_KEY
STATE_SESSION_KEY: Final = "easyauth_oidc_state"
NONCE_SESSION_KEY: Final = "easyauth_oidc_nonce"
OIDC_STATE: Final = "s12-state"
OIDC_NONCE: Final = "s12-nonce"
OIDC_CODE: Final = "s12-code"
OIDC_SUBJECT: Final = "s12-authentik-user"


type OidcClaimValue = str | tuple[str, ...]
type OidcClaims = dict[str, OidcClaimValue]


@override_settings(
    EASYAUTH_AUTHENTIK_OIDC_ISSUER=AUTHENTIK_ISSUER,
    EASYAUTH_AUTHENTIK_OIDC_AUTHORIZATION_ENDPOINT="",
    EASYAUTH_AUTHENTIK_OIDC_CLIENT_ID=CLIENT_ID,
    EASYAUTH_AUTHENTIK_OIDC_REDIRECT_URI=REDIRECT_URI,
    EASYAUTH_AUTHENTIK_OIDC_SCOPES=("openid", "profile", "email"),
)
def test_s12_login_redirects_to_authentik_authorization_endpoint_with_state_and_nonce() -> None:
    # Given
    client = Client()

    # When
    response = client.get("/auth/login/")

    # Then
    assert response.status_code == HTTPStatus.FOUND
    location = response.headers["Location"]
    parsed = urlsplit(location)
    query = parse_qs(parsed.query)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == (
        "https://authentik.example.test/application/o/authorize/"
    )
    assert query["client_id"] == [CLIENT_ID]
    assert query["redirect_uri"] == [REDIRECT_URI]
    assert query["response_type"] == ["code"]
    assert set(query["scope"][0].split()) == {"openid", "profile", "email"}
    assert query["state"][0] == client.session[STATE_SESSION_KEY]
    assert query["nonce"][0] == client.session[NONCE_SESSION_KEY]
    assert query["state"][0]
    assert query["nonce"][0]


@override_settings(
    EASYAUTH_AUTHENTIK_OIDC_ISSUER=AUTHENTIK_ISSUER,
    EASYAUTH_AUTHENTIK_OIDC_AUTHORIZATION_ENDPOINT=AUTHORIZATION_ENDPOINT,
    EASYAUTH_AUTHENTIK_OIDC_CLIENT_ID=CLIENT_ID,
    EASYAUTH_AUTHENTIK_OIDC_REDIRECT_URI=REDIRECT_URI,
    EASYAUTH_AUTHENTIK_OIDC_SCOPES=("openid", "profile", "email"),
)
def test_s12_login_uses_configured_browser_authorization_endpoint() -> None:
    # Given
    client = Client()

    # When
    response = client.get("/auth/login/")

    # Then
    assert response.status_code == HTTPStatus.FOUND
    location = response.headers["Location"]
    parsed = urlsplit(location)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == AUTHORIZATION_ENDPOINT


@override_settings(
    EASYAUTH_AUTHENTIK_OIDC_ISSUER=AUTHENTIK_ISSUER,
    EASYAUTH_AUTHENTIK_OIDC_CLIENT_ID=CLIENT_ID,
    EASYAUTH_AUTHENTIK_OIDC_CLIENT_SECRET=CLIENT_SECRET,
    EASYAUTH_AUTHENTIK_OIDC_REDIRECT_URI=REDIRECT_URI,
)
def test_s12_callback_binds_session_to_user_mirror_when_claims_are_valid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    client = Client()
    user = UserMirror.objects.create(authentik_user_id=OIDC_SUBJECT, name="OIDC 用户")
    _seed_oidc_attempt(client)
    _patch_claim_exchange(monkeypatch, _valid_claims())

    # When
    response = client.get(f"/auth/callback/?code={OIDC_CODE}&state={OIDC_STATE}")

    # Then
    assert response.status_code == HTTPStatus.FOUND
    assert response.headers["Location"] == "/portal/"
    assert client.session[SESSION_KEY] == user.authentik_user_id


def _valid_claims() -> OidcClaims:
    return {
        "iss": AUTHENTIK_ISSUER,
        "aud": CLIENT_ID,
        "sub": OIDC_SUBJECT,
        "nonce": OIDC_NONCE,
    }


@override_settings(
    EASYAUTH_AUTHENTIK_OIDC_ISSUER=AUTHENTIK_ISSUER,
    EASYAUTH_AUTHENTIK_OIDC_CLIENT_ID=CLIENT_ID,
    EASYAUTH_AUTHENTIK_OIDC_CLIENT_SECRET=CLIENT_SECRET,
    EASYAUTH_AUTHENTIK_OIDC_REDIRECT_URI=REDIRECT_URI,
)
@pytest.mark.parametrize(
    ("claims", "error_text"),
    [
        ({**_valid_claims(), "iss": "https://evil.example.test/application/o/easyauth/"}, "issuer"),
        ({**_valid_claims(), "aud": "other-client"}, "audience"),
        ({**_valid_claims(), "sub": ""}, "subject"),
    ],
)
def test_s12_callback_rejects_invalid_claims_without_writing_session(
    monkeypatch: pytest.MonkeyPatch,
    claims: OidcClaims,
    error_text: str,
) -> None:
    # Given
    client = Client()
    _seed_oidc_attempt(client)
    _patch_claim_exchange(monkeypatch, claims)

    # When
    response = client.get(f"/auth/callback/?code={OIDC_CODE}&state={OIDC_STATE}")

    # Then
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert error_text in response.content.decode()
    assert SESSION_KEY not in client.session
    assert STATE_SESSION_KEY not in client.session
    assert NONCE_SESSION_KEY not in client.session


@override_settings(
    EASYAUTH_AUTHENTIK_OIDC_ISSUER=AUTHENTIK_ISSUER,
    EASYAUTH_AUTHENTIK_OIDC_CLIENT_ID=CLIENT_ID,
    EASYAUTH_AUTHENTIK_OIDC_CLIENT_SECRET=CLIENT_SECRET,
    EASYAUTH_AUTHENTIK_OIDC_REDIRECT_URI=REDIRECT_URI,
)
def test_s12_callback_rejects_multiple_audiences_without_authorized_party(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    client = Client()
    _seed_oidc_attempt(client)
    _patch_claim_exchange(monkeypatch, {**_valid_claims(), "aud": (CLIENT_ID, "other-client")})

    # When
    response = client.get(f"/auth/callback/?code={OIDC_CODE}&state={OIDC_STATE}")

    # Then
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert "azp" in response.content.decode()


@override_settings(
    EASYAUTH_AUTHENTIK_OIDC_ISSUER=AUTHENTIK_ISSUER,
    EASYAUTH_AUTHENTIK_OIDC_CLIENT_ID=CLIENT_ID,
    EASYAUTH_AUTHENTIK_OIDC_CLIENT_SECRET=CLIENT_SECRET,
    EASYAUTH_AUTHENTIK_OIDC_REDIRECT_URI=REDIRECT_URI,
)
def test_s12_callback_rejects_state_mismatch_and_clears_login_attempt() -> None:
    # Given
    client = Client()
    _seed_oidc_attempt(client)

    # When
    response = client.get(f"/auth/callback/?code={OIDC_CODE}&state=wrong-state")

    # Then
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert "state" in response.content.decode()
    assert SESSION_KEY not in client.session
    assert STATE_SESSION_KEY not in client.session
    assert NONCE_SESSION_KEY not in client.session


def _seed_oidc_attempt(client: Client) -> None:
    session = client.session
    session[STATE_SESSION_KEY] = OIDC_STATE
    session[NONCE_SESSION_KEY] = OIDC_NONCE
    session.save()


def _patch_claim_exchange(monkeypatch: pytest.MonkeyPatch, claims: OidcClaims) -> None:
    def exchange_claims(
        _request: HttpRequest,
        _code: str,
        _config: OidcClientConfig,
    ) -> OidcClaims:
        return claims

    monkeypatch.setattr(
        "easyauth.accounts.views.exchange_authorization_code_for_claims",
        exchange_claims,
    )
