"""提供门户交接任务列表, 详情, 预离职和转交端点。"""

from __future__ import annotations

from http import HTTPStatus
from typing import ClassVar, Final, cast

from django.http import HttpRequest, JsonResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.api.responses import error_response, json_response
from easyauth.lifecycle.api_errors import map_handover_exception, reason_error
from easyauth.lifecycle.api_payloads import SURFACE_PORTAL, task_detail, task_list_item
from easyauth.lifecycle.assignee import AssigneeResolution
from easyauth.lifecycle.core import TASK_KIND_CONFLICT_MESSAGE
from easyauth.lifecycle.errors import HandoverConflictError, HandoverError
from easyauth.lifecycle.jurisdiction import assert_manager_of
from easyauth.lifecycle.models import (
    ASSIGNEE_STATE_MANAGER,
    AUTHORITY_SOURCE_MANAGER_CHAIN,
    HANDOVER_KIND_PRE_OFFBOARD,
    HANDOVER_KIND_REASSIGN,
    TASK_OPEN_STATUSES,
    HandoverTask,
)
from easyauth.lifecycle.offboarding import HandoverCreationSpec, ensure_handover_task
from easyauth.portal.handover_api import (
    idempotency_key,
    method_not_allowed,
    not_found,
    payload_sha256,
    portal_user,
    portal_user_for_method,
    recheck_reassign_scope,
    task_visible_to,
)

REASON_MIN_LEN: Final = 10


class PreOffboardPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    reason: str = Field(default="", max_length=2000)


class ReassignPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    subject_user_id: str = Field(min_length=1, max_length=128)
    app_keys: list[str] = Field(min_length=1)
    reason: str = Field(default="", max_length=2000)


type ReassignRequest = tuple[str, ReassignPayload, UserMirror]


def portal_me_handover_tasks(request: HttpRequest) -> JsonResponse:
    match portal_user(request):
        case UserMirror() as user:
            pass
        case JsonResponse() as response:
            return response
    if request.method != "GET":
        return method_not_allowed()
    as_assignee = [
        task_list_item(t)
        for t in HandoverTask.objects.select_related("subject_user", "assignee")
        .filter(assignee=user, status__in=TASK_OPEN_STATUSES)
        .order_by("-created_at", "-id")
    ]
    as_subject = [
        task_list_item(t)
        for t in HandoverTask.objects.select_related("subject_user", "assignee")
        .filter(subject_user=user)
        .order_by("-created_at", "-id")
    ]
    payload = cast(
        "dict[str, JsonValue]",
        {"handover_tasks": {"as_assignee": as_assignee, "as_subject": as_subject}},
    )
    return json_response(payload)


def portal_handover_pre_offboard(request: HttpRequest) -> JsonResponse:
    match portal_user_for_method(request, "POST"):
        case UserMirror() as user:
            pass
        case JsonResponse() as response:
            return response
    idem = idempotency_key(request)
    if isinstance(idem, JsonResponse):
        return idem
    try:
        payload = PreOffboardPayload.model_validate_json(request.body or b"{}")
    except ValidationError as exc:
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            "请求参数无效。",
            {"errors": str(exc)},
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    body_hash = payload_sha256(
        {"kind": HANDOVER_KIND_PRE_OFFBOARD, "reason": payload.reason},
    )
    try:
        task, _created = ensure_handover_task(
            subject=user,
            kind=HANDOVER_KIND_PRE_OFFBOARD,
            created_by=user.authentik_user_id,
            spec=HandoverCreationSpec(
                reason=payload.reason,
                creation_idempotency_key=idem,
                creation_payload_sha256=body_hash,
                raise_on_existing=True,
            ),
        )
    except (HandoverConflictError, HandoverError) as error:
        return _pre_offboard_error_response(error)
    return json_response(
        {"handover_task": task_detail(task, surface=SURFACE_PORTAL)},
        status=HTTPStatus.CREATED,
    )


def portal_handover_reassign(request: HttpRequest) -> JsonResponse:
    match portal_user_for_method(request, "POST"):
        case UserMirror() as user:
            pass
        case JsonResponse() as response:
            return response
    prepared = _prepare_reassign_request(request, user)
    if isinstance(prepared, JsonResponse):
        return prepared
    idem, payload, subject = prepared
    body_hash = payload_sha256(
        {
            "subject_user_id": payload.subject_user_id,
            "app_keys": sorted(payload.app_keys),
            "reason": payload.reason,
        },
    )
    try:
        task, _created = ensure_handover_task(
            subject=subject,
            kind=HANDOVER_KIND_REASSIGN,
            created_by=user.authentik_user_id,
            spec=HandoverCreationSpec(
                reason=payload.reason.strip(),
                app_keys=tuple(payload.app_keys),
                authority_source=AUTHORITY_SOURCE_MANAGER_CHAIN,
                creation_idempotency_key=idem,
                creation_payload_sha256=body_hash,
                assignee_resolution=AssigneeResolution(
                    user=user,
                    state=ASSIGNEE_STATE_MANAGER,
                    level=0,
                    degraded=False,
                ),
            ),
        )
    except (HandoverConflictError, HandoverError) as error:
        mapped = map_handover_exception(error)
        return mapped or error_response(
            ErrorCode.VALIDATION_ERROR,
            str(error),
            status=HTTPStatus.BAD_REQUEST,
        )
    return json_response(
        {"handover_task": task_detail(task, surface=SURFACE_PORTAL)},
        status=HTTPStatus.CREATED,
    )


def portal_handover_task_detail(request: HttpRequest, task_id: int) -> JsonResponse:
    match portal_user(request):
        case UserMirror() as user:
            pass
        case JsonResponse() as response:
            return response
    if request.method != "GET":
        return method_not_allowed()
    task = task_visible_to(user, task_id)
    if task is None:
        return not_found()
    revoked = recheck_reassign_scope(task, user)
    if isinstance(revoked, JsonResponse):
        return revoked
    return json_response({"handover_task": task_detail(task, surface=SURFACE_PORTAL)})


def _pre_offboard_error_response(error: HandoverConflictError | HandoverError) -> JsonResponse:
    text = str(error)
    if text == "idempotency_conflict":
        return reason_error("idempotency_conflict")
    # 已有其他类型 open 生命周期单 → 门户语义 open_task_exists
    if text in {TASK_KIND_CONFLICT_MESSAGE, "task_kind_conflict"}:
        return reason_error("open_task_exists")
    mapped = map_handover_exception(error)
    return mapped or reason_error("open_task_exists", text)


def _prepare_reassign_request(
    request: HttpRequest,
    user: UserMirror,
) -> ReassignRequest | JsonResponse:
    idem = idempotency_key(request)
    if isinstance(idem, JsonResponse):
        return idem
    payload = _parse_reassign_payload(request)
    if isinstance(payload, JsonResponse):
        return payload
    subject = UserMirror.objects.filter(
        authentik_user_id=payload.subject_user_id,
        status=USER_STATUS_ACTIVE,
    ).first()
    if subject is None:
        return reason_error("out_of_managed_scope")
    jurisdiction = assert_manager_of(user, subject)
    if not jurisdiction.allowed:
        return reason_error(jurisdiction.reason)
    return idem, payload, subject


def _parse_reassign_payload(request: HttpRequest) -> ReassignPayload | JsonResponse:
    try:
        payload = ReassignPayload.model_validate_json(request.body)
    except ValidationError as exc:
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            "请求参数无效。",
            {"errors": str(exc)},
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    if len(payload.reason.strip()) < REASON_MIN_LEN:
        return reason_error("reason_required")
    if not payload.app_keys:
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            "app_keys 必填且非空。",
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    return payload
