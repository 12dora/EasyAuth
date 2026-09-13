from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest
from django.contrib.sessions.backends.db import SessionStore
from django.test import RequestFactory

from easyauth.accounts.auth import VerifiedOidcClaims, bind_oidc_session
from easyauth.accounts.models import UserMirror

if TYPE_CHECKING:
    from django.http import HttpRequest

pytestmark = pytest.mark.django_db

EXISTING_AVATAR: str = "https://static-legacy.dingtalk.com/media/existing.jpg"
SAFE_AVATAR: str = "https://static-legacy.dingtalk.com/media/oidc.jpg"


def test_bind_oidc_session_keeps_existing_avatar_when_claim_is_empty() -> None:
    user = UserMirror.objects.create(
        authentik_user_id="oidc-avatar-keep-empty",
        avatar_url=EXISTING_AVATAR,
    )

    bind_oidc_session(_request(), _claims(subject=user.authentik_user_id, avatar_url=""))

    user.refresh_from_db()
    assert user.avatar_url == EXISTING_AVATAR


def test_bind_oidc_session_overwrites_avatar_when_claim_is_safe() -> None:
    user = UserMirror.objects.create(
        authentik_user_id="oidc-avatar-overwrite",
        avatar_url=EXISTING_AVATAR,
    )

    bind_oidc_session(
        _request(),
        _claims(subject=user.authentik_user_id, avatar_url=SAFE_AVATAR),
    )

    user.refresh_from_db()
    assert user.avatar_url == SAFE_AVATAR


def _request() -> HttpRequest:
    request = RequestFactory().get("/")
    request.session = SessionStore()
    return cast("HttpRequest", request)


def _claims(*, subject: str, avatar_url: str) -> VerifiedOidcClaims:
    return VerifiedOidcClaims(
        sid="oidc-avatar-sid",
        subject=subject,
        name="张三",
        email="",
        avatar_url=avatar_url,
    )
