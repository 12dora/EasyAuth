from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import JsonResponse
from django.test import RequestFactory, override_settings

from easyauth.accounts.auth import AUTHENTIK_SESSION_KEY
from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App, AppMembership
from easyauth.frontend_shell import shell_user_from_user

if TYPE_CHECKING:
    from django.http import HttpRequest

pytestmark = pytest.mark.django_db

_AUTHORITY_GROUPS_BY_UID: dict[str, tuple[str, ...]] = {}


class _FakeAuthentikAuthority:
    def user_group_names_by_uid(self, authentik_user_uid: str) -> tuple[str, ...]:
        return _AUTHORITY_GROUPS_BY_UID.get(authentik_user_uid, ())


@pytest.mark.parametrize("role", ["owner", "developer"])
@override_settings(EASYAUTH_CONSOLE_SUPERUSER_GROUPS=("easyauth-admins",))
def test_shell_user_hides_console_from_app_member_who_is_not_admin(
    role: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = UserMirror.objects.create(
        authentik_user_id=f"shell-{role}",
        name="应用成员",
    )
    app = App.objects.create(app_key=f"shell-{role}-crm", name="Shell CRM")
    _ = AppMembership.objects.create(app=app, user_id=user.authentik_user_id, role=role)
    request = _session_request(monkeypatch, user.authentik_user_id, groups=())

    shell = shell_user_from_user(request, user)

    assert shell.can_access_console is False
    assert shell.is_superuser is False


@override_settings(EASYAUTH_CONSOLE_SUPERUSER_GROUPS=("easyauth-admins",))
def test_shell_user_shows_console_for_stored_flag_administrator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = UserMirror.objects.create(
        authentik_user_id="shell-flag-admin",
        name="控制台管理员",
        is_console_admin=True,
    )
    request = _session_request(monkeypatch, user.authentik_user_id, groups=())

    shell = shell_user_from_user(request, user)

    assert shell.can_access_console is True
    assert shell.is_superuser is True


@override_settings(EASYAUTH_CONSOLE_SUPERUSER_GROUPS=("easyauth-admins",))
def test_shell_user_shows_console_for_authentik_group_administrator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = UserMirror.objects.create(
        authentik_user_id="shell-group-admin",
        name="组引导管理员",
    )
    request = _session_request(monkeypatch, user.authentik_user_id, groups=("easyauth-admins",))

    shell = shell_user_from_user(request, user)

    assert shell.can_access_console is True
    assert shell.is_superuser is True


def _session_request(
    monkeypatch: pytest.MonkeyPatch,
    user_id: str,
    *,
    groups: tuple[str, ...],
) -> HttpRequest:
    request = RequestFactory().get("/portal/")
    middleware = SessionMiddleware(lambda _request: JsonResponse({}))
    middleware.process_request(request)
    _AUTHORITY_GROUPS_BY_UID.clear()
    _AUTHORITY_GROUPS_BY_UID[user_id] = groups
    monkeypatch.setattr(
        "easyauth.admin_console.identity.AuthentikAdminClient.from_settings",
        lambda: _FakeAuthentikAuthority(),
    )
    request.session[AUTHENTIK_SESSION_KEY] = user_id
    request.session.save()
    request.user = AnonymousUser()
    return request
