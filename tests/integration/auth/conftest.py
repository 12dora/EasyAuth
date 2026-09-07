from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from django.core.cache import cache
from django.test import override_settings

from easyauth.accounts.oidc_exchange import clear_jwks_cache
from tests.integration.auth.test_oidc_exchange_s12 import (
    AUTHENTIK_ISSUER,
    CLIENT_ID,
    JWKS_URL,
    REDIRECT_URI,
    TOKEN_ENDPOINT,
    FakeResponse,
    _public_jwk,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from urllib.request import Request


@pytest.fixture
def signing_key(monkeypatch: pytest.MonkeyPatch) -> Iterator[rsa.RSAPrivateKey]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    clear_jwks_cache()
    cache.clear()

    def urlopen(request: Request, *, timeout: float) -> FakeResponse:
        assert request.full_url == JWKS_URL
        assert timeout > 0
        return FakeResponse({"keys": [_public_jwk(key.public_key())]})

    monkeypatch.setattr("easyauth.accounts.oidc_exchange.urlopen", urlopen)
    with override_settings(
        EASYAUTH_AUTHENTIK_OIDC_ISSUER=AUTHENTIK_ISSUER,
        EASYAUTH_AUTHENTIK_OIDC_CLIENT_ID=CLIENT_ID,
        EASYAUTH_AUTHENTIK_OIDC_REDIRECT_URI=REDIRECT_URI,
        EASYAUTH_AUTHENTIK_OIDC_TOKEN_ENDPOINT=TOKEN_ENDPOINT,
        EASYAUTH_AUTHENTIK_OIDC_JWKS_URL=JWKS_URL,
        EASYAUTH_AUTHENTIK_OIDC_SIGNING_ALGORITHMS=("RS256",),
    ):
        yield key
    clear_jwks_cache()
    cache.clear()
