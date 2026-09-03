from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import JsonResponse
from django.test import RequestFactory, override_settings

from easyauth.accounts.auth import AUTHENTIK_SESSION_KEY
from easyauth.accounts.models import UserMirror
from easyauth.admin_console.identity import _oidc_actor
from easyauth.applications.ownership import ConsoleActor
from easyauth.integrations.authentik.admin_client import AuthentikAdminError

if TYPE_CHECKING:
    from django.http import HttpRequest

pytestmark = pytest.mark.django_db


@override_settings(EASYAUTH_CONSOLE_SUPERUSER_GROUPS=("easyauth-admins",))
def test_oidc_actor_is_superuser_from_stored_flag_when_authentik_groups_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = UserMirror.objects.create(
        authentik_user_id="flag-admin-no-group",
        is_console_admin=True,
    )
    _patch_authentik_groups(monkeypatch, user.authentik_user_id, ())
    request = _request_with_session(authentik_user_id=user.authentik_user_id)

    actor = _oidc_actor(request, user.authentik_user_id)

    assert actor == ConsoleActor(user_id=user.authentik_user_id, is_superuser=True)


@override_settings(EASYAUTH_CONSOLE_SUPERUSER_GROUPS=("easyauth-admins",))
def test_oidc_actor_is_superuser_from_stored_flag_when_authentik_admin_api_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = UserMirror.objects.create(
        authentik_user_id="flag-admin-api-down",
        is_console_admin=True,
    )
    _patch_authentik_error(monkeypatch)
    request = _request_with_session(authentik_user_id=user.authentik_user_id)

    actor = _oidc_actor(request, user.authentik_user_id)

    assert actor == ConsoleActor(user_id=user.authentik_user_id, is_superuser=True)


@override_settings(EASYAUTH_CONSOLE_SUPERUSER_GROUPS=("easyauth-admins",))
def test_oidc_actor_is_superuser_from_authentik_group_when_flag_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = UserMirror.objects.create(authentik_user_id="group-bootstrap-admin")
    _patch_authentik_groups(monkeypatch, user.authentik_user_id, ("easyauth-admins",))
    request = _request_with_session(authentik_user_id=user.authentik_user_id)

    actor = _oidc_actor(request, user.authentik_user_id)

    assert actor == ConsoleActor(user_id=user.authentik_user_id, is_superuser=True)


@override_settings(EASYAUTH_CONSOLE_SUPERUSER_GROUPS=("easyauth-admins",))
def test_oidc_actor_is_not_superuser_when_flag_unset_and_authentik_admin_api_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = UserMirror.objects.create(authentik_user_id="plain-user-api-down")
    _patch_authentik_error(monkeypatch)
    request = _request_with_session(authentik_user_id=user.authentik_user_id)

    actor = _oidc_actor(request, user.authentik_user_id)

    assert actor == ConsoleActor(user_id=user.authentik_user_id, is_superuser=False)


def _request_with_session(*, authentik_user_id: str) -> HttpRequest:
    request = RequestFactory().get("/console/")
    middleware = SessionMiddleware(lambda _request: JsonResponse({}))
    middleware.process_request(request)
    request.session[AUTHENTIK_SESSION_KEY] = authentik_user_id
    request.session.save()
    request.user = AnonymousUser()
    return request


def _patch_authentik_groups(
    monkeypatch: pytest.MonkeyPatch,
    authentik_user_id: str,
    groups: tuple[str, ...],
) -> None:
    class FakeAuthentikClient:
        def user_group_names_by_uid(self, authentik_user_uid: str) -> tuple[str, ...]:
            assert authentik_user_uid == authentik_user_id
            return groups

    monkeypatch.setattr(
        "easyauth.admin_console.identity.AuthentikAdminClient.from_settings",
        lambda: FakeAuthentikClient(),
    )


def _patch_authentik_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class RaisingAuthentikClient:
        def user_group_names_by_uid(self, authentik_user_uid: str) -> tuple[str, ...]:
            del authentik_user_uid
            raise AuthentikAdminError

    monkeypatch.setattr(
        "easyauth.admin_console.identity.AuthentikAdminClient.from_settings",
        lambda: RaisingAuthentikClient(),
    )
