from __future__ import annotations

from time import time
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlsplit

import pytest
from django.contrib.sessions.models import Session
from django.test import Client, override_settings

from easyauth.accounts.auth import (
    AUTHENTIK_SESSION_KEY,
    LOCAL_ADMIN_SESSION_FLAG,
    OIDC_NEXT_SESSION_KEY,
    OIDC_NONCE_SESSION_KEY,
    OIDC_SILENT_ATTEMPTS_SESSION_KEY,
    OIDC_STATE_SESSION_KEY,
)
from easyauth.accounts.models import USER_STATUS_DISABLED, OidcSessionBinding, UserMirror
from tests.integration.auth.test_backchannel_logout import bound_session, logout_claims, signed
from tests.integration.auth.test_oidc_exchange_s12 import (
    JWKS_URL,
    TOKEN_ENDPOINT,
    FakeResponse,
    _public_jwk,
)

if TYPE_CHECKING:
    from urllib.request import Request

    from cryptography.hazmat.primitives.asymmetric import rsa

pytestmark = pytest.mark.django_db


def silent_client(subject: str = "one") -> Client:
    key = bound_session(subject, "sid-one")
    client = Client()
    client.cookies["sessionid"] = key
    return client


def assert_outcome(client: Client, outcome: str, **params: str) -> None:
    response = client.get("/auth/callback/", params)
    assert response.status_code == 200
    assert f'>"{outcome}"</script>' in response.content.decode()
    user_id = client.session[AUTHENTIK_SESSION_KEY] if outcome in {"unchanged", "changed"} else ""
    assert response.context["user_id"] == user_id
    assert (
        f'id="identity-check-user-id" type="application/json">"{user_id}"</script>'
        in response.content.decode()
    )
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert params["state"] not in client.session[OIDC_SILENT_ATTEMPTS_SESSION_KEY]


@pytest.mark.parametrize("subject", ["one", "two", ""])
def test_silent_identity_binds_current_upstream_user(
    signing_key: rsa.RSAPrivateKey,
    monkeypatch: pytest.MonkeyPatch,
    subject: str,
) -> None:
    client = silent_client(subject) if subject else Client()
    old_key = client.session.session_key
    response = client.get("/auth/login/?silent=1&next=/portal/")
    query = parse_qs(urlsplit(response.headers["Location"]).query)
    assert query["prompt"] == ["none"]
    claims = logout_claims()
    claims["sub"] = "one"
    claims["sid"] = "sid-refreshed"
    claims["name"] = "更新后的姓名"
    claims["nonce"] = next(iter(client.session[OIDC_SILENT_ATTEMPTS_SESSION_KEY].values()))["nonce"]

    def urlopen(request: Request, *, timeout: float) -> FakeResponse:
        assert timeout > 0
        if request.full_url == TOKEN_ENDPOINT:
            return FakeResponse({"id_token": signed(signing_key, claims)})
        assert request.full_url == JWKS_URL
        return FakeResponse({"keys": [_public_jwk(signing_key.public_key())]})

    monkeypatch.setattr("easyauth.accounts.oidc_exchange.urlopen", urlopen)
    with override_settings(EASYAUTH_AUTHENTIK_OIDC_CLIENT_SECRET="silent-client-secret"):
        assert_outcome(
            client,
            "unchanged" if subject == "one" else "changed",
            code="silent-code",
            state=next(iter(client.session[OIDC_SILENT_ATTEMPTS_SESSION_KEY])),
        )
    assert client.session[AUTHENTIK_SESSION_KEY] == "one"
    assert (client.session.session_key == old_key) == (subject == "one")
    assert Session.objects.filter(session_key=old_key).exists() == (subject == "one")
    assert OidcSessionBinding.objects.filter(session_key=old_key).exists() == (subject == "one")
    assert (
        OidcSessionBinding.objects.get(session_key=client.session.session_key).sid
        == "sid-refreshed"
    )
    assert UserMirror.objects.get(authentik_user_id="one").name == "更新后的姓名"
    if subject == "one":
        previous_cookie_client = Client()
        previous_cookie_client.cookies["sessionid"] = old_key
        assert previous_cookie_client.get("/portal/api/v1/me/grants").status_code == 200
    assert (
        OidcSessionBinding.objects.get(
            session_key=client.session.session_key,
        ).authentik_user_id
        == "one"
    )


@pytest.mark.parametrize(
    "error",
    [
        "login_required",
        "interaction_required",
        "consent_required",
        "access_denied",
    ],
)
def test_silent_upstream_logout(signing_key: rsa.RSAPrivateKey, error: str) -> None:
    assert signing_key
    client = silent_client()
    old_key = client.session.session_key
    client.get("/auth/login/?silent=1")
    assert_outcome(
        client,
        "logged_out",
        error=error,
        state=next(iter(client.session[OIDC_SILENT_ATTEMPTS_SESSION_KEY])),
    )
    assert AUTHENTIK_SESSION_KEY not in client.session
    assert not OidcSessionBinding.objects.filter(session_key=old_key).exists()


@pytest.mark.parametrize("failure", ["unknown_error", "missing_code"])
def test_silent_error_preserves_identity(signing_key: rsa.RSAPrivateKey, failure: str) -> None:
    assert signing_key
    client = silent_client()
    client.get("/auth/login/?silent=1")
    params = {"state": next(iter(client.session[OIDC_SILENT_ATTEMPTS_SESSION_KEY]))}
    if failure == "unknown_error":
        params["error"] = "server_error"
    assert_outcome(client, "error", **params)
    assert client.session[AUTHENTIK_SESSION_KEY] == "one"
    assert OidcSessionBinding.objects.filter(session_key=client.session.session_key).exists()


def test_silent_disabled_user_logs_out(
    signing_key: rsa.RSAPrivateKey,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = silent_client()
    UserMirror.objects.filter(authentik_user_id="one").update(status=USER_STATUS_DISABLED)
    client.get("/auth/login/?silent=1")
    claims = logout_claims()
    claims["nonce"] = next(iter(client.session[OIDC_SILENT_ATTEMPTS_SESSION_KEY].values()))["nonce"]

    def urlopen(request: Request, *, timeout: float) -> FakeResponse:
        assert timeout > 0
        if request.full_url == TOKEN_ENDPOINT:
            return FakeResponse({"id_token": signed(signing_key, claims)})
        assert request.full_url == JWKS_URL
        return FakeResponse({"keys": [_public_jwk(signing_key.public_key())]})

    monkeypatch.setattr("easyauth.accounts.oidc_exchange.urlopen", urlopen)
    with override_settings(EASYAUTH_AUTHENTIK_OIDC_CLIENT_SECRET="silent-client-secret"):
        assert_outcome(
            client,
            "logged_out",
            code="code",
            state=next(iter(client.session[OIDC_SILENT_ATTEMPTS_SESSION_KEY])),
        )
    assert AUTHENTIK_SESSION_KEY not in client.session
    assert not OidcSessionBinding.objects.exists()


def test_canonical_login_keeps_silent_query(signing_key: rsa.RSAPrivateKey) -> None:
    assert signing_key
    with override_settings(
        EASYAUTH_AUTHENTIK_OIDC_REDIRECT_URI="https://iam.example/auth/callback/"
    ):
        response = Client().get("/auth/login/?silent=1")
    assert response.headers["Location"] == "https://iam.example/auth/login/?silent=1"


def test_silent_login_skips_local_admin() -> None:
    client = Client()
    session = client.session
    session[LOCAL_ADMIN_SESSION_FLAG] = True
    session[AUTHENTIK_SESSION_KEY] = "local-admin:root"
    session.save()
    response = client.get("/auth/login/?silent=1")
    assert response.status_code == 200
    assert '>"unchanged"</script>' in response.content.decode()
    assert client.session[AUTHENTIK_SESSION_KEY] == "local-admin:root"
    assert OIDC_STATE_SESSION_KEY not in client.session


@pytest.mark.parametrize("interactive_first", [False, True])
def test_interleaved_silent_and_interactive_attempts(
    signing_key: rsa.RSAPrivateKey,
    monkeypatch: pytest.MonkeyPatch,
    *,
    interactive_first: bool,
) -> None:
    client = silent_client()
    first = parse_qs(urlsplit(client.get("/auth/login/?silent=1").headers["Location"]).query)
    second = parse_qs(urlsplit(client.get("/auth/login/?silent=1").headers["Location"]).query)
    interactive = parse_qs(
        urlsplit(client.get("/auth/login/?next=/portal/").headers["Location"]).query
    )
    nonces = {q["state"][0]: q["nonce"][0] for q in (first, second, interactive)}

    def urlopen(request: Request, *, timeout: float) -> FakeResponse:
        assert timeout > 0
        if request.full_url == TOKEN_ENDPOINT:
            assert request.data is not None
            state = parse_qs(request.data.decode())["code"][0]
            claims = logout_claims()
            claims["nonce"] = nonces[state]
            return FakeResponse({"id_token": signed(signing_key, claims)})
        assert request.full_url == JWKS_URL
        return FakeResponse({"keys": [_public_jwk(signing_key.public_key())]})

    monkeypatch.setattr("easyauth.accounts.oidc_exchange.urlopen", urlopen)
    order = (interactive, first, second) if interactive_first else (second, first, interactive)
    with override_settings(EASYAUTH_AUTHENTIK_OIDC_CLIENT_SECRET="silent-client-secret"):
        for query in order:
            state = query["state"][0]
            if query is interactive:
                response = client.get("/auth/callback/", {"state": state, "code": state})
                assert response.status_code == 302
                assert response.headers["Location"] == "/portal/"
            else:
                assert_outcome(client, "unchanged", state=state, code=state)
                if not interactive_first:
                    assert client.session[OIDC_STATE_SESSION_KEY] == interactive["state"][0]
                    assert client.session[OIDC_NONCE_SESSION_KEY] == interactive["nonce"][0]
                    assert client.session[OIDC_NEXT_SESSION_KEY] == "/portal/"
    assert client.session[OIDC_SILENT_ATTEMPTS_SESSION_KEY] == {}


def test_silent_attempt_expiry_cap_and_unknown_state(signing_key: rsa.RSAPrivateKey) -> None:
    assert signing_key
    client = silent_client()
    session = client.session
    session[OIDC_SILENT_ATTEMPTS_SESSION_KEY] = {
        "expired": {"nonce": "old", "created_at": time() - 601},
    }
    session.save()
    states = []
    for _ in range(11):
        response = client.get("/auth/login/?silent=1")
        states.append(parse_qs(urlsplit(response.headers["Location"]).query)["state"][0])
    attempts = client.session[OIDC_SILENT_ATTEMPTS_SESSION_KEY]
    assert len(attempts) == 10
    assert "expired" not in attempts
    assert states[0] not in attempts
    assert set(attempts) == set(states[1:])
    response = client.get("/auth/callback/", {"state": "unknown", "error": "login_required"})
    assert response.status_code == 400
    assert client.session[OIDC_SILENT_ATTEMPTS_SESSION_KEY] == attempts
    assert client.session[AUTHENTIK_SESSION_KEY] == "one"
