from __future__ import annotations

import pytest
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.test import RequestFactory

from easyauth.accounts.auth import (
    VerifiedOidcClaims,
    bind_oidc_session,
    clear_auth_session,
    revoke_authentik_sessions,
)
from easyauth.accounts.models import OidcSessionBinding

pytestmark = pytest.mark.django_db


def test_binding_rotates_rebinds_and_clears() -> None:
    request = RequestFactory().get("/")
    request.session = SessionStore()
    bind_oidc_session(request, VerifiedOidcClaims(sid="first", subject="one", name="", email=""))
    first_key = request.session.session_key
    bind_oidc_session(request, VerifiedOidcClaims(sid="second", subject="two", name="", email=""))
    assert request.session.session_key != first_key
    assert not OidcSessionBinding.objects.filter(session_key=first_key).exists()
    binding = OidcSessionBinding.objects.get(session_key=request.session.session_key)
    assert (binding.sid, binding.authentik_user_id) == ("second", "two")
    clear_auth_session(request)
    assert not OidcSessionBinding.objects.exists()


def test_revocation_preserves_other_sessions_and_local_admin() -> None:
    requests = []
    for subject, sid, local in [
        ("one", "shared", False),
        ("two", "other", False),
        ("local-admin:root", "", True),
    ]:
        request = RequestFactory().get("/")
        request.session = SessionStore()
        bind_oidc_session(
            request,
            VerifiedOidcClaims(sid=sid, subject=subject, name="", email=""),
            local_admin=local,
        )
        request.session.save()
        requests.append(request)
    assert OidcSessionBinding.objects.count() == 2
    assert revoke_authentik_sessions(sid="shared") == 1
    assert not Session.objects.filter(session_key=requests[0].session.session_key).exists()
    assert Session.objects.filter(session_key=requests[1].session.session_key).exists()
    assert revoke_authentik_sessions(subject="two") == 1
    assert revoke_authentik_sessions(subject="local-admin:root") == 0
    assert Session.objects.filter(session_key=requests[2].session.session_key).exists()
