from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING, Final, Literal
from urllib.parse import urlencode

from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import render

from easyauth.access_requests.models import AccessRequest, AccessRequestRole
from easyauth.access_requests.services import (
    AccessRequestService,
    AccessRequestSubmission,
    AccessRequestSubmissionError,
)
from easyauth.accounts.auth import AUTHENTIK_SESSION_KEY
from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.portal.forms import AccessRequestForm, app_options, role_options

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from easyauth.applications.models import App, Role

LOGIN_URL: Final = "/auth/login/"
PORTAL_TEMPLATE: Final = "portal/home.html"

type StatusTone = Literal["primary", "secondary", "success", "danger"]


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


@dataclass(frozen=True, slots=True)
class PortalSubmission:
    app: App
    grant_expires_at: datetime | None
    lifetime: str
    reason: str
    roles: tuple[Role, ...]


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

    submitted_request: AccessRequest | None = None
    if request.method == "POST":
        form = AccessRequestForm.bind(request.POST)
        if form.is_valid():
            selected_role = form.selected_role()
            try:
                submitted_request = _submit_access_request(
                    requester=user,
                    submission=PortalSubmission(
                        app=form.selected_app(),
                        grant_expires_at=form.selected_grant_expires_at(),
                        lifetime=form.selected_lifetime(),
                        reason=form.selected_reason(),
                        roles=(selected_role,),
                    ),
                )
            except AccessRequestSubmissionError as exc:
                form = form.with_role_error(str(exc))
            else:
                form = AccessRequestForm.empty()
    else:
        form = AccessRequestForm.empty()

    return render(
        request,
        PORTAL_TEMPLATE,
        {
            "app_options": app_options(),
            "form": form,
            "role_options": role_options(),
            "request_rows": request_rows_for_user(user),
            "submitted_request": submitted_request,
            "user": user,
        },
        status=HTTPStatus.OK,
    )


def _login_redirect(request: HttpRequest) -> HttpResponseRedirect:
    query = urlencode({"next": request.get_full_path()})
    return HttpResponseRedirect(f"{LOGIN_URL}?{query}")


def request_rows_for_user(user: UserMirror) -> list[AccessRequestRow]:
    access_requests = list(
        AccessRequest.objects.select_related("app")
        .filter(user=user)
        .order_by("-submitted_at", "id")
    )
    role_names_by_request_id = _role_names_by_request_id(
        [access_request.id for access_request in access_requests],
    )
    return [
        AccessRequestRow(
            app_name=access_request.app.name,
            grant_label=_grant_label(access_request),
            reason=access_request.reason,
            role_names=role_names_by_request_id.get(access_request.id, "-"),
            status=access_request.status,
            status_label=_status_label(access_request.status),
            status_tone=_status_tone(access_request.status),
            submitted_at=access_request.submitted_at,
        )
        for access_request in access_requests
    ]


def _role_names_by_request_id(request_ids: Sequence[int]) -> dict[int, str]:
    if not request_ids:
        return {}

    role_name_lists: dict[int, list[str]] = {request_id: [] for request_id in request_ids}
    request_roles = (
        AccessRequestRole.objects.select_related("role")
        .filter(access_request_id__in=request_ids)
        .order_by("access_request_id", "role__key")
    )
    for request_role in request_roles:
        role_name_lists.setdefault(request_role.access_request_id, []).append(
            request_role.role.name,
        )
    return {
        request_id: "、".join(role_names) if role_names else "-"
        for request_id, role_names in role_name_lists.items()
    }


def _grant_label(access_request: AccessRequest) -> str:
    match access_request.grant_type:
        case "permanent":
            return "长期"
        case "timed":
            return "限时"
        case _:
            return "-"


def _status_label(status: str) -> str:
    match status:
        case "submitted":
            return "已提交"
        case "approved":
            return "已批准"
        case "grant_applied":
            return "已授权"
        case "rejected":
            return "已拒绝"
        case "grant_failed":
            return "授权失败"
        case _:
            return "未知"


def _status_tone(status: str) -> StatusTone:
    match status:
        case "submitted":
            return "primary"
        case "approved":
            return "secondary"
        case "grant_applied":
            return "success"
        case "rejected" | "grant_failed":
            return "danger"
        case _:
            return "secondary"


def _submit_access_request(
    *,
    requester: UserMirror,
    submission: PortalSubmission,
) -> AccessRequest:
    return AccessRequestService.submit_grant_request(
        AccessRequestSubmission(
            user=requester,
            app=submission.app,
            roles=submission.roles,
            grant_type=_grant_type(submission.lifetime),
            grant_expires_at=submission.grant_expires_at,
            reason=submission.reason,
            actor_type="user",
            actor_id=requester.authentik_user_id,
        ),
    )


def _grant_type(lifetime: str) -> Literal["permanent", "timed"]:
    match lifetime:
        case "permanent":
            return "permanent"
        case "timed":
            return "timed"
        case _:
            message = "授权期限必须是 permanent 或 timed。"
            raise TypeError(message)
