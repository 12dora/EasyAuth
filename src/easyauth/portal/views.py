from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final
from urllib.parse import urlencode

from django.http import HttpRequest, HttpResponse, HttpResponseNotAllowed, HttpResponseRedirect

from easyauth.access_requests.models import AccessRequest, AccessRequestGroup
from easyauth.accounts.auth import AUTHENTIK_SESSION_KEY
from easyauth.accounts.logout_state import browser_is_marked_logged_out, logged_out_redirect
from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.frontend_shell import render_react_shell, shell_user_from_user
from easyauth.portal.status_text import StatusTone, status_label, status_tone

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime


LOGIN_URL: Final = "/auth/login/"


@dataclass(frozen=True, slots=True)
class AccessRequestRow:
    app_name: str
    grant_label: str
    reason: str
    role_names: str
    status: str
    status_label: str
    status_tone: StatusTone
    submitted_at: datetime


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


def request_rows_for_user(user: UserMirror) -> list[AccessRequestRow]:
    access_requests = list(
        AccessRequest.objects.select_related("app")
        .filter(user=user)
        .order_by("-submitted_at", "id")
    )
    group_names_by_request_id = _group_names_by_request_id(
        [access_request.id for access_request in access_requests],
    )
    return [
        AccessRequestRow(
            app_name=access_request.app.name,
            grant_label=_grant_label(access_request),
            reason=access_request.reason,
            role_names=group_names_by_request_id.get(access_request.id, "-"),
            status=access_request.status,
            status_label=status_label(access_request.status),
            status_tone=status_tone(access_request.status),
            submitted_at=access_request.submitted_at,
        )
        for access_request in access_requests
    ]


def _group_names_by_request_id(request_ids: Sequence[int]) -> dict[int, str]:
    if not request_ids:
        return {}

    group_name_lists: dict[int, list[str]] = {request_id: [] for request_id in request_ids}
    request_groups = (
        AccessRequestGroup.objects.select_related("authorization_group")
        .filter(access_request_id__in=request_ids)
        .order_by("access_request_id", "authorization_group__key")
    )
    for request_group in request_groups:
        group_name_lists.setdefault(request_group.access_request_id, []).append(
            request_group.authorization_group.name,
        )
    return {
        request_id: "、".join(group_names) if group_names else "-"
        for request_id, group_names in group_name_lists.items()
    }


def _grant_label(access_request: AccessRequest) -> str:
    match access_request.grant_type:
        case "permanent":
            return "长期"
        case "timed":
            return "限时"
        case _:
            return "-"
