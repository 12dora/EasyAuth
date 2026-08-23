"""控制台交接 v2 新增端点(01 §6.3)。与门户只共享 domain service。"""

from __future__ import annotations

import hashlib
import json
from http import HTTPStatus
from typing import ClassVar, Final

from django.db import transaction
from django.db.models import Count
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
from easyauth.api.datetime_json import datetime_value
from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.applications.handover_capability import declare_handover_none
from easyauth.applications.models import App
from easyauth.lifecycle.api_errors import map_handover_exception, reason_error
from easyauth.lifecycle.api_payloads import (
    SURFACE_CONSOLE,
    action_item,
    asset_type_item,
    task_detail,
)
from easyauth.lifecycle.assignee import AssigneeApplyOptions, AssigneeResolution, apply_assignee
from easyauth.lifecycle.assignments import (
    OverrideEntry,
    list_overrides,
    patch_asset_type_defaults,
    put_overrides,
)
from easyauth.lifecycle.core import record_task_event
from easyauth.lifecycle.errors import HandoverConflictError, HandoverError
from easyauth.lifecycle.handover_actions import update_grant_receiver
from easyauth.lifecycle.handover_manual import async_abandon_action
from easyauth.lifecycle.handover_validation import FetchActionItemsSpec, fetch_action_items
from easyauth.lifecycle.jurisdiction import list_receiver_candidates
from easyauth.lifecycle.models import (
    ACTION_STATUS_BLOCKED,
    ASSIGNEE_STATE_MANAGER,
    ASSIGNEE_STATE_SUPERUSER_POOL,
    AUTHORITY_SOURCE_SUPERUSER,
    HANDOVER_ESCALATION_DAYS,
    HANDOVER_KIND_REASSIGN,
    TASK_OPEN_STATUSES,
    ApprovalRuleReplacementRequired,
    HandoverAppAction,
    HandoverTask,
)
from easyauth.lifecycle.offboarding import HandoverCreationSpec, ensure_handover_task
from easyauth.webhooks.hooks import HookCallError
from easyauth.webhooks.models import AppWebhookConfig

REASON_MIN: Final = 10
ITEMS_DEFAULT_PAGE_SIZE: Final = 50
ITEMS_MAX_PAGE_SIZE: Final = 200


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


class ResolveReplacementPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    approver_user_ids: list[str] = Field(min_length=1)


class AssetTypePatchPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    default_action: str = Field(min_length=1, max_length=8)
    default_to_user_id: str | None = Field(default=None, max_length=128)


class OverrideItemPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    asset_id: str = Field(min_length=1, max_length=128)
    action: str = Field(min_length=1, max_length=8)
    to_user_id: str | None = Field(default=None, max_length=128)
    label: str = Field(default="", max_length=120)


class OverridesPutPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    overrides_version: int = Field(ge=0)
    overrides: list[OverrideItemPayload] = Field(default_factory=list)


class GrantReceiverPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    grant_receiver_user_id: str | None = Field(default=None, max_length=128)


class DeclareNonePayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    reason: str = Field(min_length=1, max_length=2000)


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
        return _not_found()
    with transaction.atomic():
        locked = HandoverTask.objects.select_for_update().filter(pk=task.pk).first()
        if locked is None:
            return _not_found()
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
    if not idem or len(idem) > 128:
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
        return _not_found()
    with transaction.atomic():
        locked = HandoverTask.objects.select_for_update().get(pk=task.pk)
        if locked.escalation_deferred_at is not None:
            return reason_error("already_deferred")
        if locked.escalation_deadline is None:
            return reason_error("action_not_operable", "超管池单据无需顺延。")
        from datetime import timedelta

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
    action = _action_or_none(task_id, app_key)
    if action is None:
        return _not_found()
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


def console_approval_rule_replacements(request: HttpRequest) -> JsonResponse:
    match require_superuser(request):
        case str():
            pass
        case JsonResponse() as response:
            return response
    if request.method != "GET":
        return method_not_allowed_response()
    resolved_raw = request.GET.get("resolved", "false").strip().lower()
    qs = ApprovalRuleReplacementRequired.objects.select_related(
        "approval_rule",
        "departed_user",
    )
    if resolved_raw in {"false", "0", ""}:
        qs = qs.filter(resolved_at__isnull=True)
    elif resolved_raw in {"true", "1"}:
        qs = qs.filter(resolved_at__isnull=False)
    total = qs.count()
    items = []
    for row in qs.order_by("-created_at", "-id")[:200]:
        items.append(
            {
                "id": row.id,
                "approval_rule": {
                    "id": row.approval_rule_id,
                    "app_id": row.approval_rule.app_id,
                },
                "departed_user": {
                    "user_id": row.departed_user.authentik_user_id,
                    "name": row.departed_user.name,
                },
                "reason": row.reason,
                "created_at": datetime_value(row.created_at),
            },
        )
    return json_response({"items": items, "total": total})


def console_approval_rule_replacement_resolve(
    request: HttpRequest,
    replacement_id: int,
) -> JsonResponse:
    match require_superuser(request):
        case str() as actor_id:
            pass
        case JsonResponse() as response:
            return response
    if request.method != "POST":
        return method_not_allowed_response()
    return _resolve_approval_rule_replacement(request, replacement_id, actor_id=actor_id)


def _resolve_approval_rule_replacement(
    request: HttpRequest,
    replacement_id: int,
    *,
    actor_id: str,
) -> JsonResponse:
    try:
        payload = ResolveReplacementPayload.model_validate_json(request.body)
    except ValidationError as exc:
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            "参数无效。",
            {"errors": str(exc)},
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    from easyauth.lifecycle.approvals import resolve_approval_rule_replacement

    try:
        row = resolve_approval_rule_replacement(
            replacement_id,
            approver_user_ids=payload.approver_user_ids,
            actor_id=actor_id,
        )
    except LookupError:
        return _not_found()
    except HandoverConflictError as error:
        mapped = map_handover_exception(error)
        return mapped or reason_error("already_resolved")
    except ValueError as error:
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            str(error),
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    return json_response(
        {
            "id": row.id,
            "resolved_at": datetime_value(row.resolved_at),
            "resolved_by": row.resolved_by,
        },
    )


def console_handover_blocked_apps(request: HttpRequest) -> JsonResponse:
    match require_superuser(request):
        case str():
            pass
        case JsonResponse() as response:
            return response
    if request.method != "GET":
        return method_not_allowed_response()
    rows = (
        HandoverAppAction.objects.filter(
            status=ACTION_STATUS_BLOCKED,
            task__status__in=TASK_OPEN_STATUSES,
        )
        .values("app_id", "app__app_key", "app__name")
        .annotate(blocked_task_count=Count("task_id", distinct=True))
        .order_by("app__app_key")
    )
    apps = [
        {
            "app_key": row["app__app_key"],
            "app_name": row["app__name"],
            "blocked_task_count": row["blocked_task_count"],
        }
        for row in rows
    ]
    task_count = (
        HandoverTask.objects.filter(
            status__in=TASK_OPEN_STATUSES,
            app_actions__status=ACTION_STATUS_BLOCKED,
        )
        .distinct()
        .count()
    )
    return json_response(
        {
            "app_count": len(apps),
            "task_count": task_count,
            "apps": apps,
        },
    )


def console_handover_app_options(request: HttpRequest) -> JsonResponse:
    match require_superuser(request):
        case str():
            pass
        case JsonResponse() as response:
            return response
    if request.method != "GET":
        return method_not_allowed_response()
    # 超管跨部门: 不做管辖校验, subject_user_id 可选
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
    return json_response({"items": items})


def console_handover_candidates(request: HttpRequest, task_id: int) -> JsonResponse:
    match require_superuser(request):
        case str() as actor_id:
            pass
        case JsonResponse() as response:
            return response
    if request.method != "GET":
        return method_not_allowed_response()
    task = HandoverTask.objects.select_related("subject_user").filter(pk=task_id).first()
    if task is None:
        return _not_found()
    actor = UserMirror.objects.filter(authentik_user_id=actor_id).first()
    if actor is None:
        actor = task.subject_user
    q = request.GET.get("q", "")
    users = list_receiver_candidates(
        actor,
        subject=task.subject_user,
        q=q,
        exclude_actor=False,
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


def console_handover_items(
    request: HttpRequest,
    task_id: int,
    app_key: str,
    asset_type: str,
) -> JsonResponse:
    match require_superuser(request):
        case str() as actor_id:
            pass
        case JsonResponse() as response:
            return response
    if request.method != "GET":
        return method_not_allowed_response()
    action = _action_or_none(task_id, app_key)
    if action is None:
        return _not_found()
    page = _parse_int(request.GET.get("page"), 1)
    page_size = min(
        max(_parse_int(request.GET.get("page_size"), ITEMS_DEFAULT_PAGE_SIZE), 1),
        ITEMS_MAX_PAGE_SIZE,
    )
    try:
        result = fetch_action_items(
            action,
            FetchActionItemsSpec(
                asset_type=asset_type,
                page=page,
                page_size=page_size,
                q=request.GET.get("q", ""),
                actor_id=actor_id,
            ),
        )
    except (HandoverConflictError, HandoverError, HookCallError) as error:
        mapped = map_handover_exception(error)
        return mapped or error_response(
            ErrorCode.VALIDATION_ERROR,
            str(error),
            status=HTTPStatus.BAD_REQUEST,
        )
    return json_response(result)  # type: ignore[arg-type]


def console_handover_overrides(
    request: HttpRequest,
    task_id: int,
    app_key: str,
    asset_type: str,
) -> JsonResponse:
    match require_superuser(request):
        case str():
            pass
        case JsonResponse() as response:
            return response
    return _handle_handover_overrides(request, task_id, app_key, asset_type)


def _handle_handover_overrides(
    request: HttpRequest,
    task_id: int,
    app_key: str,
    asset_type: str,
) -> JsonResponse:
    action = _action_or_none(task_id, app_key)
    if action is None:
        return _not_found()
    if request.method == "GET":
        return _list_handover_overrides(action, asset_type=asset_type)
    if request.method == "PUT":
        return _put_handover_overrides(request, action, asset_type=asset_type)
    return method_not_allowed_response()


def _list_handover_overrides(
    action: HandoverAppAction,
    *,
    asset_type: str,
) -> JsonResponse:
    try:
        return json_response(list_overrides(action, type_key=asset_type))  # type: ignore[arg-type]
    except HandoverError as error:
        return error_response(ErrorCode.NOT_FOUND, str(error), status=HTTPStatus.NOT_FOUND)


def _put_handover_overrides(
    request: HttpRequest,
    action: HandoverAppAction,
    *,
    asset_type: str,
) -> JsonResponse:
    try:
        payload = OverridesPutPayload.model_validate_json(request.body)
    except ValidationError as exc:
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            "参数无效。",
            {"errors": str(exc)},
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    try:
        result = put_overrides(
            action,
            type_key=asset_type,
            overrides_version=payload.overrides_version,
            overrides=[
                OverrideEntry(
                    asset_id=i.asset_id,
                    action=i.action,
                    to_user_id=i.to_user_id,
                    label=i.label,
                )
                for i in payload.overrides
            ],
        )
    except (HandoverConflictError, HandoverError) as error:
        mapped = map_handover_exception(error)
        return mapped or error_response(
            ErrorCode.VALIDATION_ERROR,
            str(error),
            status=HTTPStatus.BAD_REQUEST,
        )
    return json_response(
        {
            "overrides_version": result.overrides_version,
            "confirm_version": result.confirm_version,
            "override_count": result.override_count,
            "dropped_invalid": result.dropped_invalid,
        },
    )


def console_handover_asset_type(
    request: HttpRequest,
    task_id: int,
    app_key: str,
    asset_type: str,
) -> JsonResponse:
    match require_superuser(request):
        case str():
            pass
        case JsonResponse() as response:
            return response
    if request.method != "PATCH":
        return method_not_allowed_response()
    action = _action_or_none(task_id, app_key)
    if action is None:
        return _not_found()
    try:
        payload = AssetTypePatchPayload.model_validate_json(request.body)
    except ValidationError as exc:
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            "参数无效。",
            {"errors": str(exc)},
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    try:
        asset, confirm_version = patch_asset_type_defaults(
            action,
            type_key=asset_type,
            default_action=payload.default_action,
            default_to_user_id=payload.default_to_user_id,
        )
    except (HandoverConflictError, HandoverError) as error:
        mapped = map_handover_exception(error)
        return mapped or error_response(
            ErrorCode.VALIDATION_ERROR,
            str(error),
            status=HTTPStatus.BAD_REQUEST,
        )
    return json_response(
        {"asset_type": asset_type_item(asset), "confirm_version": confirm_version},
    )


def console_handover_errors_raw(
    request: HttpRequest,
    task_id: int,
    app_key: str,
) -> JsonResponse:
    match require_superuser(request):
        case str() as actor_id:
            pass
        case JsonResponse() as response:
            return response
    if request.method != "GET":
        return method_not_allowed_response()
    action = _action_or_none(task_id, app_key)
    if action is None:
        return _not_found()
    # 每次读取先写审计
    record_task_event(
        action.task,
        action="handover_action_error_raw_viewed",
        actor_id=actor_id,
        actor_type="admin",
        extra={"app_key": app_key},
    )
    return json_response({"last_error_raw": action.last_error_raw})


def console_handover_action_patch(
    request: HttpRequest,
    task_id: int,
    app_key: str,
) -> JsonResponse:
    match require_superuser(request):
        case str():
            pass
        case JsonResponse() as response:
            return response
    if request.method != "PATCH":
        return method_not_allowed_response()
    return _patch_handover_action(request, task_id, app_key)


def _patch_handover_action(
    request: HttpRequest,
    task_id: int,
    app_key: str,
) -> JsonResponse:
    action = _action_or_none(task_id, app_key)
    if action is None:
        return _not_found()
    try:
        payload = GrantReceiverPayload.model_validate_json(request.body)
    except ValidationError as exc:
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            "参数无效。",
            {"errors": str(exc)},
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    receiver = None
    if payload.grant_receiver_user_id:
        receiver = UserMirror.objects.filter(
            authentik_user_id=payload.grant_receiver_user_id,
            status=USER_STATUS_ACTIVE,
        ).first()
        if receiver is None:
            return reason_error("receiver_not_active")
    try:
        action = update_grant_receiver(action=action, grant_receiver=receiver)
    except (HandoverConflictError, HandoverError) as error:
        mapped = map_handover_exception(error)
        return mapped or error_response(
            ErrorCode.VALIDATION_ERROR,
            str(error),
            status=HTTPStatus.BAD_REQUEST,
        )
    return json_response({"action": action_item(action, surface=SURFACE_CONSOLE)})


def console_handover_capability(request: HttpRequest, app_key: str) -> JsonResponse:
    match require_superuser(request):
        case str() as actor_id:
            pass
        case JsonResponse() as response:
            return response
    app = App.objects.filter(app_key=app_key).first()
    if app is None:
        return _not_found()
    if request.method == "GET":
        config = AppWebhookConfig.objects.filter(app=app).first()
        return json_response(
            {
                "handover_capability": app.handover_capability,
                "handover_asset_types": app.handover_asset_types or [],
                "handover_url": config.handover_url if config else "",
                "declared_by": app.handover_capability_declared_by,
                "declared_at": datetime_value(app.handover_capability_declared_at),
                "synced_at": datetime_value(app.handover_capability_synced_at),
            },
        )
    if request.method == "POST":
        try:
            payload = DeclareNonePayload.model_validate_json(request.body)
        except ValidationError as exc:
            return error_response(
                ErrorCode.VALIDATION_ERROR,
                "参数无效。",
                {"errors": str(exc)},
                status=HTTPStatus.UNPROCESSABLE_ENTITY,
            )
        app = declare_handover_none(app, actor_id=actor_id, reason=payload.reason)
        return json_response(
            {
                "handover_capability": app.handover_capability,
                "handover_asset_types": [],
                "handover_url": "",
                "declared_by": app.handover_capability_declared_by,
                "declared_at": datetime_value(app.handover_capability_declared_at),
                "synced_at": datetime_value(app.handover_capability_synced_at),
            },
        )
    return method_not_allowed_response()


def console_handover_capability_sync(request: HttpRequest, app_key: str) -> JsonResponse:
    match require_superuser(request):
        case str() as actor_id:
            pass
        case JsonResponse() as response:
            return response
    if request.method != "POST":
        return method_not_allowed_response()
    return _sync_handover_capability(app_key, actor_id=actor_id)


def _sync_handover_capability(app_key: str, *, actor_id: str) -> JsonResponse:
    app = App.objects.filter(app_key=app_key).first()
    if app is None:
        return _not_found()
    try:
        from easyauth.admin_console.auto_onboarding_api import (
            AutoOnboardingError,
            repull_app_descriptor,
        )
        from easyauth.applications.manifest_import import (
            ManifestVersionConflictError,
        )
        from easyauth.applications.permission_templates import PermissionTemplateImportError

        _ = repull_app_descriptor(app=app, actor_id=actor_id)
    except AutoOnboardingError as exc:
        return error_response(exc.code, exc.message, status=exc.status)
    except ManifestVersionConflictError as exc:
        return error_response(
            ErrorCode.CONFLICT,
            str(exc),
            status=HTTPStatus.CONFLICT,
        )
    except PermissionTemplateImportError as exc:
        return error_response(
            ErrorCode.SEMANTIC_VALIDATION_ERROR,
            f"manifest 导入失败: {exc.message}",
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    except Exception as exc:  # noqa: BLE001 - 网络/解析失败显式 502
        return error_response(
            ErrorCode.DEPENDENCY_UNAVAILABLE,
            f"descriptor 同步失败: {exc}",
            status=HTTPStatus.BAD_GATEWAY,
        )
    app.refresh_from_db()
    config = AppWebhookConfig.objects.filter(app=app).first()
    return json_response(
        {
            "handover_capability": app.handover_capability,
            "handover_asset_types": app.handover_asset_types or [],
            "handover_url": config.handover_url if config else "",
            "declared_by": app.handover_capability_declared_by,
            "declared_at": datetime_value(app.handover_capability_declared_at),
            "synced_at": datetime_value(app.handover_capability_synced_at),
        },
    )


def _action_or_none(task_id: int, app_key: str) -> HandoverAppAction | None:
    return (
        HandoverAppAction.objects.select_related(
            "app",
            "task",
            "task__subject_user",
            "grant_receiver",
        )
        .filter(task_id=task_id, app__app_key=app_key)
        .first()
    )


def _parse_int(raw: str | None, default: int) -> int:
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _not_found() -> JsonResponse:
    return error_response(ErrorCode.NOT_FOUND, "资源不存在。", status=HTTPStatus.NOT_FOUND)
