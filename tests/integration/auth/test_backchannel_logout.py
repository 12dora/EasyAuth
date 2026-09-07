from __future__ import annotations

import time
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.test import Client, RequestFactory

from easyauth.accounts.auth import VerifiedOidcClaims, bind_oidc_session, revoke_authentik_sessions
from easyauth.accounts.models import OidcSessionBinding
from easyauth.accounts.oidc_exchange import BACKCHANNEL_EVENT
from easyauth.audit.models import AuditLog
from tests.integration.auth.test_oidc_exchange_s12 import (
    AUTHENTIK_ISSUER,
    CLIENT_ID,
)

pytestmark = pytest.mark.django_db
URL = "/auth/backchannel-logout/"


def logout_claims() -> dict[str, object]:
    now = int(time.time())
    return {
        "iss": AUTHENTIK_ISSUER,
        "aud": CLIENT_ID,
        "iat": now,
        "exp": now + 300,
        "jti": str(uuid4()),
        "events": {BACKCHANNEL_EVENT: {}},
        "sub": "one",
        "sid": "sid-one",
    }


def signed(key: rsa.RSAPrivateKey, claims: dict[str, object]) -> str:
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "s12-kid"})


def bound_session(subject: str, sid: str) -> str:
    request = RequestFactory().get("/")
    request.session = SessionStore()
    bind_oidc_session(
        request,
        VerifiedOidcClaims(
            subject=subject,
            sid=sid,
            name="",
            email="",
        ),
    )
    request.session.save()
    key = request.session.session_key
    assert key is not None
    return key


@pytest.mark.parametrize("omit", ["", "sub", "sid"])
def test_logout_revokes_bound_sessions(signing_key: rsa.RSAPrivateKey, omit: str) -> None:
    target = bound_session("one", "sid-one")
    same_user_other = bound_session("one", "other-sid")
    other = bound_session("two", "sid-two")
    claims = logout_claims()
    if omit:
        del claims[omit]
    response = Client(enforce_csrf_checks=True).post(
        URL, {"logout_token": signed(signing_key, claims)}
    )
    assert response.status_code == 200
    assert response.content == b"{}"
    assert response.headers["Cache-Control"] == "no-store"
    assert not Session.objects.filter(session_key=target).exists()
    assert not OidcSessionBinding.objects.filter(session_key=target).exists()
    assert Session.objects.filter(session_key=other).exists()
    assert Session.objects.filter(session_key=same_user_other).exists() == (omit != "sid")
    audit = AuditLog.objects.get(event_type="oidc_backchannel_logout")
    assert audit.actor_type == "authentik"
    assert audit.metadata["revoked_sessions"] == (2 if omit == "sid" else 1)


def test_replay_is_rejected(signing_key: rsa.RSAPrivateKey) -> None:
    token = signed(signing_key, logout_claims())
    client = Client()
    assert client.post(URL, {"logout_token": token}).status_code == 200
    assert client.post(URL, {"logout_token": token}).status_code == 400


@pytest.mark.parametrize(
    "invalid",
    [
        "aud",
        "iss",
        "signature",
        "nonce",
        "events",
        "identity",
        "expired",
        "stale",
        "iat",
        "jti",
        "kid",
        "malformed",
    ],
)
def test_invalid_logout_preserves_session(signing_key: rsa.RSAPrivateKey, invalid: str) -> None:
    key = bound_session("one", "sid-one")
    claims = logout_claims()
    match invalid:
        case "aud" | "iss":
            claims[invalid] = "wrong"
        case "signature":
            signing_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        case "nonce":
            claims["nonce"] = None
        case "events" | "iat" | "jti":
            del claims[invalid]
        case "identity":
            del claims["sub"]
            del claims["sid"]
        case "expired":
            claims["exp"] = int(time.time()) - 1
        case "stale":
            del claims["exp"]
            claims["iat"] = int(time.time()) - 301
    token = signed(signing_key, claims)
    if invalid == "kid":
        token = jwt.encode(claims, signing_key, algorithm="RS256")
    if invalid == "malformed":
        token = "not-a-jwt"
    response = Client().post(URL, {"logout_token": token})
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request"
    assert response.headers["Cache-Control"] == "no-store"
    assert Session.objects.filter(session_key=key).exists()
    assert OidcSessionBinding.objects.filter(session_key=key).exists()


def test_fresh_logout_without_exp(signing_key: rsa.RSAPrivateKey) -> None:
    claims = logout_claims()
    del claims["exp"]
    assert Client().post(URL, {"logout_token": signed(signing_key, claims)}).status_code == 200


def test_get_is_not_allowed() -> None:
    assert Client().get(URL).status_code == 405


def test_failed_revocation_allows_retry(
    signing_key: rsa.RSAPrivateKey,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = bound_session("one", "sid-one")
    token = signed(signing_key, logout_claims())
    calls = 0

    def revoke_once(*, sid: str, subject: str) -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            message = "撤销暂时失败"
            raise RuntimeError(message)
        return revoke_authentik_sessions(sid=sid, subject=subject)

    monkeypatch.setattr("easyauth.accounts.views.revoke_authentik_sessions", revoke_once)
    client = Client()
    with pytest.raises(RuntimeError, match="撤销暂时失败"):
        client.post(URL, {"logout_token": token})
    assert Session.objects.filter(session_key=key).exists()
    assert client.post(URL, {"logout_token": token}).status_code == 200
    assert not Session.objects.filter(session_key=key).exists()
    assert AuditLog.objects.filter(event_type="oidc_backchannel_logout").count() == 1
    assert client.post(URL, {"logout_token": token}).status_code == 400
