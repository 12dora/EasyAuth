from __future__ import annotations

from typing import Final
from urllib.parse import urlencode

from django.http import HttpRequest, HttpResponse, HttpResponseNotAllowed, HttpResponseRedirect

from easyauth.accounts.auth import AUTHENTIK_SESSION_KEY
from easyauth.accounts.logout_state import browser_is_marked_logged_out, logged_out_redirect
from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.frontend_shell import render_react_shell, shell_user_from_user

LOGIN_URL: Final = "/auth/login/"


def portal_home(request: HttpRequest) -> HttpResponse:
    authentik_user_id = request.session.get(AUTHENTIK_SESSION_KEY)
    if not isinstance(authentik_user_id, str):
        return _login_redirect(request)

    user = UserMirror.objects.filter(
        authentik_user_id=authentik_user_id,
        status=USER_STATUS_ACTIVE,
    ).first()
    if user is None:
        request.session.pop(AUTHENTIK_SESSION_KEY, None)
        return _login_redirect(request)

    if request.method == "POST":
        return HttpResponseNotAllowed(
            ["GET"],
            "旧门户表单入口已关闭, 请使用 /portal/api/v1/me/access-requests 接口。",
            content_type="text/plain; charset=utf-8",
        )

    return render_react_shell(
        request,
        surface="portal",
        title="员工门户",
        current_user=shell_user_from_user(request, user),
    )


def portal_react_route(request: HttpRequest, _portal_path: str) -> HttpResponse:
    return portal_home(request)


def _login_redirect(request: HttpRequest) -> HttpResponseRedirect:
    if browser_is_marked_logged_out(request):
        return logged_out_redirect(request)
    query = urlencode({"next": request.get_full_path()})
    return HttpResponseRedirect(f"{LOGIN_URL}?{query}")
