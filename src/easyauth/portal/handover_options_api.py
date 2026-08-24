"""提供门户交接应用选项和候选人查询端点。"""

from __future__ import annotations

from http import HTTPStatus
from typing import cast

from django.http import HttpRequest, JsonResponse

from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.api.responses import error_response, json_response
from easyauth.applications.models import App
from easyauth.lifecycle.api_errors import reason_error
from easyauth.lifecycle.jurisdiction import (
    assert_manager_of,
    list_reassign_subject_candidates,
    list_receiver_candidates,
)
from easyauth.portal.handover_api import method_not_allowed, portal_user


def portal_handover_app_options(request: HttpRequest) -> JsonResponse:
    match portal_user(request):
        case UserMirror() as user:
            pass
        case JsonResponse() as response:
            return response
    if request.method != "GET":
        return method_not_allowed()
    subject_id = request.GET.get("subject_user_id", "").strip()
    if not subject_id:
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            "subject_user_id 必填。",
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    subject = UserMirror.objects.filter(
        authentik_user_id=subject_id,
        status=USER_STATUS_ACTIVE,
    ).first()
    if subject is None:
        return reason_error("out_of_managed_scope")
    jurisdiction = assert_manager_of(user, subject)
    if not jurisdiction.allowed:
        return reason_error(jurisdiction.reason)
    items = [
        {
            "app_key": app.app_key,
            "app_name": app.name,
            "handover_capability": app.handover_capability,
            "blocked_reason": (
                ""
                if app.handover_capability == "declared"
                else (
                    "capability_none"
                    if app.handover_capability == "none"
                    else "capability_undeclared"
                )
            ),
        }
        for app in App.objects.filter(is_active=True).order_by("app_key")
    ]
    return json_response(cast("dict[str, JsonValue]", {"items": items}))


def portal_handover_candidates(request: HttpRequest) -> JsonResponse:
    match portal_user(request):
        case UserMirror() as user:
            pass
        case JsonResponse() as response:
            return response
    if request.method != "GET":
        return method_not_allowed()
    purpose = request.GET.get("purpose", "").strip()
    if not purpose:
        return reason_error("purpose_required")
    q = request.GET.get("q", "")
    if purpose == "receiver":
        users = list_receiver_candidates(user, q=q)
    elif purpose == "reassign_subject":
        result = list_reassign_subject_candidates(user, q=q)
        if isinstance(result, str):
            return reason_error(result)
        users = result
    else:
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            "purpose 必须为 receiver 或 reassign_subject。",
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    return json_response(
        {
            "items": [
                {
                    "user_id": u.authentik_user_id,
                    "name": u.name,
                    "department": u.department,
                }
                for u in users
            ],
        },
    )
