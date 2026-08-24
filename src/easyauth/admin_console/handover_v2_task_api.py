"""处理控制台交接 v2 的任务认领、改派、顺延与异步放弃。"""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from http import HTTPStatus
from typing import ClassVar, Final, cast

from django.db import transaction
from django.http import HttpRequest, JsonResponse
from django.utils import timezone
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from easyauth.accounts.local_admin import LOCAL_ADMIN_SUBJECT_PREFIX
from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.admin_console.api_responses import (
    error_response,
    json_response,
    method_not_allowed_response,
)
from easyauth.admin_console.authz import require_superuser
from easyauth.admin_console.handover_v2_support import action_or_none, not_found
from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.lifecycle.api_errors import map_handover_exception, reason_error
from easyauth.lifecycle.api_payloads import SURFACE_CONSOLE, action_item, task_detail
from easyauth.lifecycle.assignee import AssigneeApplyOptions, AssigneeResolution, apply_assignee
from easyauth.lifecycle.core import record_task_event
from easyauth.lifecycle.errors import HandoverConflictError, HandoverError
from easyauth.lifecycle.handover_manual import async_abandon_action
from easyauth.lifecycle.models import (
    ASSIGNEE_STATE_MANAGER,
    ASSIGNEE_STATE_SUPERUSER_POOL,
    AUTHORITY_SOURCE_SUPERUSER,
    HANDOVER_ESCALATION_DAYS,
    HANDOVER_KIND_REASSIGN,
    TASK_OPEN_STATUSES,
    HandoverTask,
)
from easyauth.lifecycle.offboarding import HandoverCreationSpec, ensure_handover_task

REASON_MIN: Final = 10
IDEMPOTENCY_KEY_MAX_LENGTH: Final = 128


class ReasonPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    reason: str = Field(min_length=1, max_length=2000)


class AsyncAbandonPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    outcome: str = Field(min_length=1, max_length=16)
    reason: str = Field(min_length=1, max_length=2000)
    summary: dict[str, JsonValue] | None = None


class ReassignPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    subject_user_id: str = Field(min_length=1, max_length=128)
    app_keys: list[str] = Field(min_length=1)
    reason: str = Field(default="", max_length=2000)


def console_handover_claim(request: HttpRequest, task_id: int) -> JsonResponse:
    match require_superuser(request):
        case str() as actor_id:
            pass
        case JsonResponse() as response:
            return response
    if request.method != "POST":
        return method_not_allowed_response()
    return _claim_handover_task(task_id, actor_id=actor_id)


def _claim_handover_task(task_id: int, *, actor_id: str) -> JsonResponse:
    if actor_id.startswith(LOCAL_ADMIN_SUBJECT_PREFIX):
        return reason_error("local_admin_cannot_claim")
    actor = UserMirror.objects.filter(
        authentik_user_id=actor_id,
        status=USER_STATUS_ACTIVE,
    ).first()
    if actor is None or not actor.dingtalk_userid:
        return reason_error("local_admin_cannot_claim")
    task = HandoverTask.objects.filter(pk=task_id).first()
    if task is None:
        return not_found()
    with transaction.atomic():
        locked = (
            HandoverTask.objects.select_for_update()
            .filter(pk=cast("int", task.pk))
            .first()
        )
        if locked is None:
            return not_found()
        # 状态校验必须在行锁内, 防止双超管抢领/认领已关闭单(§6.3)
        if (
            locked.assignee_state != ASSIGNEE_STATE_SUPERUSER_POOL
            or locked.status not in TASK_OPEN_STATUSES
        ):
            return reason_error("action_not_operable", "仅超管池中的进行中单据可认领。")
        _ = apply_assignee(
            locked,
            AssigneeResolution(
                user=actor,
                state=ASSIGNEE_STATE_MANAGER,
                level=locked.escalation_level,
                degraded=False,
            ),
            actor_id=actor_id,
            options=AssigneeApplyOptions(
                actor_type="admin",
                reason="superuser_claim",
                set_deadline=True,
                escalation_days=HANDOVER_ESCALATION_DAYS,
            ),
        )
        locked.authority_source = AUTHORITY_SOURCE_SUPERUSER
        locked.save(update_fields=["authority_source", "updated_at"])
    locked.refresh_from_db()
    return json_response({"handover_task": task_detail(locked, surface=SURFACE_CONSOLE)})


def console_handover_reassign(request: HttpRequest) -> JsonResponse:
    match require_superuser(request):
        case str() as actor_id:
            pass
        case JsonResponse() as response:
            return response
    if request.method != "POST":
        return method_not_allowed_response()
    return _create_reassign_handover(request, actor_id=actor_id)


def _create_reassign_handover(request: HttpRequest, *, actor_id: str) -> JsonResponse:
    idem = request.headers.get("Idempotency-Key", "").strip()
    if not idem or len(idem) > IDEMPOTENCY_KEY_MAX_LENGTH:
        return reason_error("idempotency_key_required")
    try:
        payload = ReassignPayload.model_validate_json(request.body)
    except ValidationError as exc:
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            "参数无效。",
            {"errors": str(exc)},
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    if len(payload.reason.strip()) < REASON_MIN:
        return reason_error("reason_required")
    subject = (
        UserMirror.objects.filter(
            authentik_user_id=payload.subject_user_id,
            status=USER_STATUS_ACTIVE,
        )
        .exclude(authentik_user_id__startswith=LOCAL_ADMIN_SUBJECT_PREFIX)
        .first()
    )
    if subject is None:
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            "当事人不存在或已停用。",
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    body_hash = _reassign_body_hash(payload)
    try:
        task, created = ensure_handover_task(
            subject=subject,
            kind=HANDOVER_KIND_REASSIGN,
            created_by=actor_id,
            spec=HandoverCreationSpec(
                reason=payload.reason.strip(),
                app_keys=tuple(payload.app_keys),
                authority_source=AUTHORITY_SOURCE_SUPERUSER,
                creation_idempotency_key=idem,
                creation_payload_sha256=body_hash,
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
        {"handover_task": task_detail(task, surface=SURFACE_CONSOLE)},
        status=HTTPStatus.CREATED if created else HTTPStatus.OK,
    )


def _reassign_body_hash(payload: ReassignPayload) -> str:
    body = {
        "subject_user_id": payload.subject_user_id,
        "app_keys": sorted(payload.app_keys),
        "reason": payload.reason,
    }
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode(),
    ).hexdigest()


def console_handover_defer(request: HttpRequest, task_id: int) -> JsonResponse:
    match require_superuser(request):
        case str() as actor_id:
            pass
        case JsonResponse() as response:
            return response
    if request.method != "POST":
        return method_not_allowed_response()
    return _defer_handover_task(request, task_id, actor_id=actor_id)


def _defer_handover_task(
    request: HttpRequest,
    task_id: int,
    *,
    actor_id: str,
) -> JsonResponse:
    try:
        payload = ReasonPayload.model_validate_json(request.body or b"{}")
    except ValidationError:
        return reason_error("reason_required")
    if len(payload.reason.strip()) < REASON_MIN:
        return reason_error("reason_required")
    task = HandoverTask.objects.filter(pk=task_id).first()
    if task is None:
        return not_found()
    with transaction.atomic():
        locked = HandoverTask.objects.select_for_update().get(pk=cast("int", task.pk))
        if locked.escalation_deferred_at is not None:
            return reason_error("already_deferred")
        if locked.escalation_deadline is None:
            return reason_error("action_not_operable", "超管池单据无需顺延。")
        locked.escalation_deadline = locked.escalation_deadline + timedelta(
            days=HANDOVER_ESCALATION_DAYS,
        )
        locked.escalation_deferred_at = timezone.now()
        locked.save(
            update_fields=["escalation_deadline", "escalation_deferred_at", "updated_at"],
        )
        record_task_event(
            locked,
            action="handover_task_deferred",
            actor_id=actor_id,
            actor_type="admin",
            extra={
                "reason": payload.reason.strip(),
                "escalation_level": locked.escalation_level,
            },
        )
    locked.refresh_from_db()
    return json_response({"handover_task": task_detail(locked, surface=SURFACE_CONSOLE)})


def console_handover_async_abandon(
    request: HttpRequest,
    task_id: int,
    app_key: str,
) -> JsonResponse:
    match require_superuser(request):
        case str() as actor_id:
            pass
        case JsonResponse() as response:
            return response
    if request.method != "POST":
        return method_not_allowed_response()
    action = action_or_none(task_id, app_key)
    if action is None:
        return not_found()
    try:
        payload = AsyncAbandonPayload.model_validate_json(request.body)
    except ValidationError as exc:
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            "参数无效。",
            {"errors": str(exc)},
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    try:
        action = async_abandon_action(
            action,
            outcome=payload.outcome,
            reason=payload.reason,
            summary=payload.summary,
            actor_id=actor_id,
        )
    except (HandoverConflictError, HandoverError) as error:
        mapped = map_handover_exception(error)
        return mapped or error_response(
            ErrorCode.VALIDATION_ERROR,
            str(error),
            status=HTTPStatus.BAD_REQUEST,
        )
    return json_response({"action": action_item(action, surface=SURFACE_CONSOLE)})
