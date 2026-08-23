"""门户交接 API(01 §6.1): 14 端点, 与控制台只共享 domain service。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from http import HTTPStatus
from typing import ClassVar, Final, Literal, cast

from django.db import transaction
from django.http import HttpRequest, JsonResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from easyauth.accounts.auth import AUTHENTIK_SESSION_KEY
from easyauth.accounts.local_admin import LOCAL_ADMIN_SUBJECT_PREFIX
from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.api.responses import error_response, json_response
from easyauth.applications.models import App
from easyauth.lifecycle.api_errors import map_handover_exception, reason_error
from easyauth.lifecycle.api_payloads import (
    SURFACE_PORTAL,
    action_item,
    asset_type_item,
    task_detail,
    task_list_item,
)
from easyauth.lifecycle.assignee import AssigneeResolution
from easyauth.lifecycle.assignments import (
    OverrideEntry,
    list_overrides,
    patch_asset_type_defaults,
    put_overrides,
)
from easyauth.lifecycle.errors import HandoverConflictError, HandoverError
from easyauth.lifecycle.handover import execute_action, retry_action
from easyauth.lifecycle.handover_actions import update_grant_receiver
from easyauth.lifecycle.handover_preview import preview_action
from easyauth.lifecycle.handover_shared import MutationGuard
from easyauth.lifecycle.handover_validation import FetchActionItemsSpec, fetch_action_items
from easyauth.lifecycle.jurisdiction import (
    assert_manager_of,
    list_reassign_subject_candidates,
    list_receiver_candidates,
)
from easyauth.lifecycle.models import (
    ACTION_STATUS_BLOCKED,
    ASSIGNEE_STATE_MANAGER,
    ASSIGNEE_STATE_SUPERUSER_POOL,
    AUTHORITY_SOURCE_MANAGER_CHAIN,
    AUTHORITY_SOURCE_SUPERUSER,
    HANDOVER_KIND_PRE_OFFBOARD,
    HANDOVER_KIND_REASSIGN,
    TASK_OPEN_STATUSES,
    HandoverAppAction,
    HandoverTask,
)
from easyauth.lifecycle.offboarding import HandoverCreationSpec, ensure_handover_task
from easyauth.webhooks.hooks import HookCallError

type PortalApiResult = UserMirror | JsonResponse
type ReassignRequest = tuple[str, ReassignPayload, UserMirror]

IDEMPOTENCY_KEY_MAX: Final = 128
REASON_MIN_LEN: Final = 10
ITEMS_DEFAULT_PAGE_SIZE: Final = 50
ITEMS_MAX_PAGE_SIZE: Final = 200
ITEMS_MAX_PAGE: Final = 100_000
PORTAL_ASSIGNEE_REQUIRED: Final = "portal_assignee_required"


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
    action: Literal["transfer", "release", "skip"]
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

    grant_receiver_user_id: str | None = Field(max_length=128)


class ExecutePayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    confirm_version: int = Field(ge=0)


@dataclass(frozen=True, slots=True)
class _OverrideRequest:
    user: UserMirror
    task_id: int
    app_key: str
    asset_type: str


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def portal_me_handover_tasks(request: HttpRequest) -> JsonResponse:
    match _portal_user(request):
        case UserMirror() as user:
            pass
        case JsonResponse() as response:
            return response
    if request.method != "GET":
        return _method_not_allowed()
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
    return json_response(
        {"handover_tasks": {"as_assignee": as_assignee, "as_subject": as_subject}},
    )


def portal_handover_pre_offboard(request: HttpRequest) -> JsonResponse:
    match _portal_user_for_method(request, "POST"):
        case UserMirror() as user:
            pass
        case JsonResponse() as response:
            return response
    idem = _idempotency_key(request)
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
    body_hash = _payload_sha256(
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
    match _portal_user_for_method(request, "POST"):
        case UserMirror() as user:
            pass
        case JsonResponse() as response:
            return response
    prepared = _prepare_reassign_request(request, user)
    if isinstance(prepared, JsonResponse):
        return prepared
    idem, payload, subject = prepared
    body_hash = _payload_sha256(
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
    match _portal_user(request):
        case UserMirror() as user:
            pass
        case JsonResponse() as response:
            return response
    if request.method != "GET":
        return _method_not_allowed()
    task = _task_visible_to(user, task_id)
    if task is None:
        return _not_found()
    revoked = _recheck_reassign_scope(task, user)
    if isinstance(revoked, JsonResponse):
        return revoked
    return json_response({"handover_task": task_detail(task, surface=SURFACE_PORTAL)})


def portal_handover_items(
    request: HttpRequest,
    task_id: int,
    app_key: str,
    asset_type: str,
) -> JsonResponse:
    match _portal_user(request):
        case UserMirror() as user:
            pass
        case JsonResponse() as response:
            return response
    if request.method != "GET":
        return _method_not_allowed()
    action = _action_for_user(user, task_id, app_key, require_assignee=False)
    if isinstance(action, JsonResponse):
        return action
    page = _parse_page(request.GET.get("page"))
    if page is None:
        return reason_error("items_page_out_of_range")
    page_size = _parse_int(request.GET.get("page_size"), default=ITEMS_DEFAULT_PAGE_SIZE)
    page_size = min(max(page_size, 1), ITEMS_MAX_PAGE_SIZE)
    q = request.GET.get("q", "")
    try:
        result = fetch_action_items(
            action,
            FetchActionItemsSpec(
                asset_type=asset_type,
                page=page,
                page_size=page_size,
                q=q,
                actor_id=user.authentik_user_id,
            ),
        )
    except (HandoverConflictError, HandoverError, HookCallError) as error:
        mapped = map_handover_exception(error)
        return mapped or error_response(
            ErrorCode.VALIDATION_ERROR,
            str(error),
            {"reason": str(error)},
            status=HTTPStatus.BAD_REQUEST,
        )
    return json_response(result)  # type: ignore[arg-type]


def portal_handover_overrides(
    request: HttpRequest,
    task_id: int,
    app_key: str,
    asset_type: str,
) -> JsonResponse:
    match _portal_user(request):
        case UserMirror() as user:
            pass
        case JsonResponse() as response:
            return response
    override_request = _OverrideRequest(user, task_id, app_key, asset_type)
    if request.method == "GET":
        return _get_portal_overrides(override_request)
    if request.method == "PUT":
        return _put_portal_overrides(request, override_request)
    return _method_not_allowed()


def portal_handover_asset_type(
    request: HttpRequest,
    task_id: int,
    app_key: str,
    asset_type: str,
) -> JsonResponse:
    match _portal_user(request):
        case UserMirror() as user:
            pass
        case JsonResponse() as response:
            return response
    if request.method != "PATCH":
        return _method_not_allowed()
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
        with transaction.atomic():
            action = _action_for_user(
                user,
                task_id,
                app_key,
                require_assignee=True,
                lock_for_mutation=True,
            )
            if isinstance(action, JsonResponse):
                return action
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
        {
            "asset_type": asset_type_item(asset),
            "confirm_version": confirm_version,
        },
    )


def portal_handover_action_patch(
    request: HttpRequest,
    task_id: int,
    app_key: str,
) -> JsonResponse:
    match _portal_user_for_method(request, "PATCH"):
        case UserMirror() as user:
            pass
        case JsonResponse() as response:
            return response
    receiver = _grant_receiver_from_request(request)
    if isinstance(receiver, JsonResponse):
        return receiver
    try:
        with transaction.atomic():
            action = _action_for_user(
                user,
                task_id,
                app_key,
                require_assignee=True,
                lock_for_mutation=True,
            )
            if isinstance(action, JsonResponse):
                return action
            action = update_grant_receiver(action=action, grant_receiver=receiver)
    except (HandoverConflictError, HandoverError) as error:
        mapped = map_handover_exception(error)
        return mapped or error_response(
            ErrorCode.VALIDATION_ERROR,
            str(error),
            status=HTTPStatus.BAD_REQUEST,
        )
    return json_response({"action": action_item(action, surface=SURFACE_PORTAL)})


def portal_handover_action_operation(
    request: HttpRequest,
    task_id: int,
    app_key: str,
    operation: str,
) -> JsonResponse:
    match _portal_user_for_method(request, "POST"):
        case UserMirror() as user:
            pass
        case JsonResponse() as response:
            return response
    action = _action_for_user(user, task_id, app_key, require_assignee=True)
    if isinstance(action, JsonResponse):
        return action
    if action.status == ACTION_STATUS_BLOCKED and operation in {"preview", "execute"}:
        return reason_error("action_blocked")
    mutation_guard = _portal_mutation_guard(user)
    try:
        outcome = _dispatch_portal_action(
            action,
            operation=operation,
            request=request,
            mutation_guard=mutation_guard,
        )
    except (HandoverConflictError, HandoverError, HookCallError) as error:
        return _portal_action_error_response(error, action=action, task_id=task_id, user=user)
    if isinstance(outcome, JsonResponse):
        return outcome
    return json_response({"action": action_item(outcome, surface=SURFACE_PORTAL)})


def _dispatch_portal_action(
    action: HandoverAppAction,
    *,
    operation: str,
    request: HttpRequest,
    mutation_guard: MutationGuard,
) -> HandoverAppAction | JsonResponse:
    """把 operation 派发到对应的领域调用; 返回 JsonResponse 表示入参已判负。"""
    if operation == "preview":
        return preview_action(action, mutation_guard=mutation_guard)
    if operation == "execute":
        try:
            body = ExecutePayload.model_validate_json(request.body or b"{}")
        except ValidationError:
            return error_response(
                ErrorCode.VALIDATION_ERROR,
                "confirm_version 必填。",
                status=HTTPStatus.UNPROCESSABLE_ENTITY,
            )
        return execute_action(
            action,
            confirm_version=body.confirm_version,
            mutation_guard=mutation_guard,
        )
    if operation == "retry":
        return retry_action(action, mutation_guard=mutation_guard)
    return error_response(
        ErrorCode.VALIDATION_ERROR,
        "操作必须为 preview、execute 或 retry。",
        status=HTTPStatus.BAD_REQUEST,
    )


def _portal_scope_error_response(
    error: HandoverError | HookCallError,
    *,
    task_id: int,
    user: UserMirror,
) -> JsonResponse | None:
    """门户特有的前置映射: 非受理人一律 404; 管辖权失效要先复核并可能回收 reassign。"""
    if str(error) == PORTAL_ASSIGNEE_REQUIRED:
        return _not_found()
    if str(error) in {"out_of_managed_scope", "directory_unavailable"}:
        revoked = _recheck_reassign_scope_locked(task_id, user)
        if isinstance(revoked, JsonResponse):
            return revoked
    return None


def _portal_action_error_response(
    error: HandoverError | HookCallError,
    *,
    action: HandoverAppAction,
    task_id: int,
    user: UserMirror,
) -> JsonResponse:
    """管辖权失效要先复核 reassign 授权; 下游 412/413/423 映射成稳定 reason。"""
    scoped = _portal_scope_error_response(error, task_id=task_id, user=user)
    if scoped is not None:
        return scoped
    from easyauth.lifecycle.api_payloads import batch_progress

    extra_details: dict[str, JsonValue] | None = None
    if (
        isinstance(error, HookCallError)
        and error.status_code == HTTPStatus.REQUEST_ENTITY_TOO_LARGE
    ) or "413" in str(error):
        action.refresh_from_db()
        extra_details = {"batch_progress": batch_progress(action)}
    mapped = map_handover_exception(error, details=extra_details)
    if mapped is not None:
        return mapped
    text = str(error)
    # 412/413/423 from downstream may surface as HandoverError with HTTP hint
    if "412" in text:
        return reason_error("snapshot_stale")
    if "413" in text:
        action.refresh_from_db()
        return reason_error(
            "payload_too_large",
            details={"batch_progress": batch_progress(action)},
        )
    if "423" in text:
        return reason_error("downstream_locked")
    return error_response(
        ErrorCode.VALIDATION_ERROR,
        text,
        status=HTTPStatus.BAD_REQUEST,
    )


def portal_handover_app_options(request: HttpRequest) -> JsonResponse:
    match _portal_user(request):
        case UserMirror() as user:
            pass
        case JsonResponse() as response:
            return response
    if request.method != "GET":
        return _method_not_allowed()
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
    return json_response({"items": items})


def portal_handover_candidates(request: HttpRequest) -> JsonResponse:
    match _portal_user(request):
        case UserMirror() as user:
            pass
        case JsonResponse() as response:
            return response
    if request.method != "GET":
        return _method_not_allowed()
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


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _portal_user_for_method(request: HttpRequest, method: str) -> PortalApiResult:
    user = _portal_user(request)
    if isinstance(user, JsonResponse):
        return user
    if request.method != method:
        return _method_not_allowed()
    return user


def _pre_offboard_error_response(error: HandoverConflictError | HandoverError) -> JsonResponse:
    text = str(error)
    if text == "idempotency_conflict":
        return reason_error("idempotency_conflict")
    # 已有其他类型 open 生命周期单 → 门户语义 open_task_exists
    from easyauth.lifecycle.core import TASK_KIND_CONFLICT_MESSAGE

    if text == TASK_KIND_CONFLICT_MESSAGE or text == "task_kind_conflict":
        return reason_error("open_task_exists")
    mapped = map_handover_exception(error)
    return mapped or reason_error("open_task_exists", text)


def _prepare_reassign_request(
    request: HttpRequest,
    user: UserMirror,
) -> ReassignRequest | JsonResponse:
    idem = _idempotency_key(request)
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


def _get_portal_overrides(spec: _OverrideRequest) -> JsonResponse:
    try:
        action = _action_for_user(
            spec.user,
            spec.task_id,
            spec.app_key,
            require_assignee=False,
        )
        if isinstance(action, JsonResponse):
            return action
        payload = cast("dict[str, JsonValue]", list_overrides(action, type_key=spec.asset_type))
        return json_response(payload)
    except HandoverError as error:
        return error_response(
            ErrorCode.NOT_FOUND,
            str(error),
            status=HTTPStatus.NOT_FOUND,
        )


def _put_portal_overrides(request: HttpRequest, spec: _OverrideRequest) -> JsonResponse:
    try:
        payload = OverridesPutPayload.model_validate_json(request.body)
    except ValidationError as exc:
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            "参数无效。",
            {"errors": str(exc)},
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    asset_ids = [item.asset_id for item in payload.overrides]
    if len(asset_ids) != len(set(asset_ids)):
        return reason_error("duplicate_assignment")
    try:
        with transaction.atomic():
            action = _action_for_user(
                spec.user,
                spec.task_id,
                spec.app_key,
                require_assignee=True,
                lock_for_mutation=True,
            )
            if isinstance(action, JsonResponse):
                return action
            result = put_overrides(
                action,
                type_key=spec.asset_type,
                overrides_version=payload.overrides_version,
                overrides=[
                    OverrideEntry(
                        asset_id=item.asset_id,
                        action=item.action,
                        to_user_id=item.to_user_id,
                        label=item.label,
                    )
                    for item in payload.overrides
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


def _grant_receiver_from_request(request: HttpRequest) -> UserMirror | JsonResponse | None:
    try:
        payload = GrantReceiverPayload.model_validate_json(request.body)
    except ValidationError as exc:
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            "参数无效。",
            {"errors": str(exc)},
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    if not payload.grant_receiver_user_id:
        return None
    receiver = UserMirror.objects.filter(
        authentik_user_id=payload.grant_receiver_user_id,
        status=USER_STATUS_ACTIVE,
    ).first()
    if receiver is None:
        return reason_error("receiver_not_active")
    return receiver


def _portal_user(request: HttpRequest) -> PortalApiResult:
    authentik_user_id = request.session.get(AUTHENTIK_SESSION_KEY)
    if not isinstance(authentik_user_id, str):
        return error_response(
            ErrorCode.AUTHENTICATION_FAILED,
            "员工门户登录已失效。",
            status=HTTPStatus.UNAUTHORIZED,
        )
    if authentik_user_id.startswith(LOCAL_ADMIN_SUBJECT_PREFIX):
        return error_response(
            ErrorCode.PERMISSION_DENIED,
            "本地管理员不能使用员工门户交接接口。",
            status=HTTPStatus.FORBIDDEN,
        )
    user = UserMirror.objects.filter(
        authentik_user_id=authentik_user_id,
        status=USER_STATUS_ACTIVE,
    ).first()
    if user is None:
        request.session.pop(AUTHENTIK_SESSION_KEY, None)
        return error_response(
            ErrorCode.AUTHENTICATION_FAILED,
            "员工门户登录已失效。",
            status=HTTPStatus.UNAUTHORIZED,
        )
    return user


def _idempotency_key(request: HttpRequest) -> str | JsonResponse:
    value = request.headers.get("Idempotency-Key", "")
    if not value or value != value.strip() or len(value) > IDEMPOTENCY_KEY_MAX:
        return reason_error("idempotency_key_required")
    return value


def _payload_sha256(body: dict[str, object]) -> str:
    raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _task_visible_to(user: UserMirror, task_id: int) -> HandoverTask | None:
    return (
        HandoverTask.objects.select_related("subject_user", "assignee")
        .filter(pk=task_id)
        .filter(
            # assignee 或 subject
            models_Q_assignee_or_subject(user),
        )
        .first()
    )


def models_Q_assignee_or_subject(user: UserMirror):  # noqa: ANN201
    from django.db.models import Q

    return Q(assignee=user) | Q(subject_user=user)


def _action_for_user(
    user: UserMirror,
    task_id: int,
    app_key: str,
    *,
    require_assignee: bool,
    lock_for_mutation: bool = False,
) -> HandoverAppAction | JsonResponse:
    if lock_for_mutation:
        task = (
            HandoverTask.objects.select_for_update(of=("self",))
            .select_related("subject_user", "assignee")
            .filter(pk=task_id)
            .filter(models_Q_assignee_or_subject(user))
            .first()
        )
    else:
        task = _task_visible_to(user, task_id)
    if task is None:
        return _not_found()
    if require_assignee and task.assignee_id != user.pk:
        return _not_found()
    revoked = _recheck_reassign_scope(task, user, lock_context=lock_for_mutation)
    if isinstance(revoked, JsonResponse):
        return revoked
    actions = HandoverAppAction.objects
    if lock_for_mutation:
        actions = actions.select_for_update(of=("self",))
    action = (
        actions.select_related(
            "app",
            "task",
            "task__subject_user",
            "grant_receiver",
        )
        .filter(task=task, app__app_key=app_key)
        .first()
    )
    if action is None:
        return _not_found()
    return action


def _recheck_reassign_scope(
    task: HandoverTask,
    actor: UserMirror,
    *,
    lock_context: bool = False,
) -> JsonResponse | None:
    """Reassign 单持续复核管辖权; 失权 → 403 + 移交超管池。"""
    if task.kind != HANDOVER_KIND_REASSIGN:
        return None
    if task.authority_source == AUTHORITY_SOURCE_SUPERUSER:
        return None
    if task.assignee_id != actor.pk:
        return None
    if lock_context:
        locked_users = {
            item.pk: item
            for item in UserMirror.objects.select_for_update()
            .filter(
                pk__in={actor.pk, task.subject_user_id},
            )
            .order_by("pk")
        }
        actor = locked_users[actor.pk]
        task.subject_user = locked_users[task.subject_user_id]
    result = assert_manager_of(actor, task.subject_user, lock_context=lock_context)
    if result.allowed:
        return None
    # 失权: 移交 superuser_pool
    from easyauth.lifecycle.assignee import (
        AssigneeApplyOptions,
        AssigneeResolution,
        apply_assignee,
    )
    from easyauth.lifecycle.core import record_task_event

    if task.status in TASK_OPEN_STATUSES:
        _ = apply_assignee(
            task,
            AssigneeResolution(
                user=None,
                state=ASSIGNEE_STATE_SUPERUSER_POOL,
                level=0,
                degraded=True,
            ),
            actor_id=actor.authentik_user_id,
            options=AssigneeApplyOptions(actor_type="user", reason="reassign_scope_revoked"),
        )
        record_task_event(
            task,
            action="handover_reassign_scope_revoked",
            actor_id=actor.authentik_user_id,
            actor_type="user",
            extra={"reason": result.reason},
        )
    return reason_error(result.reason or "out_of_managed_scope")


def _portal_mutation_guard(user: UserMirror):  # noqa: ANN202
    def guard(action: HandoverAppAction) -> None:
        task = action.task
        if task.assignee_id != user.pk:
            raise HandoverError(PORTAL_ASSIGNEE_REQUIRED)
        if task.kind != HANDOVER_KIND_REASSIGN:
            return
        if task.authority_source == AUTHORITY_SOURCE_SUPERUSER:
            return
        locked_users = {
            item.pk: item
            for item in UserMirror.objects.select_for_update()
            .filter(pk__in={user.pk, task.subject_user_id})
            .order_by("pk")
        }
        actor = locked_users[user.pk]
        subject = locked_users[task.subject_user_id]
        result = assert_manager_of(actor, subject, lock_context=True)
        if not result.allowed:
            raise HandoverError(result.reason or "out_of_managed_scope")

    return guard


def _recheck_reassign_scope_locked(
    task_id: int,
    actor: UserMirror,
) -> JsonResponse | None:
    with transaction.atomic():
        task = (
            HandoverTask.objects.select_for_update(of=("self",))
            .select_related("subject_user", "assignee")
            .filter(pk=task_id)
            .first()
        )
        if task is None:
            return _not_found()
        return _recheck_reassign_scope(task, actor, lock_context=True)


def _parse_int(raw: str | None, *, default: int) -> int:
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _parse_page(raw: str | None) -> int | None:
    if raw is None or raw == "":
        return 1
    try:
        page = int(raw)
    except ValueError:
        return None
    if page < 1 or page > ITEMS_MAX_PAGE:
        return None
    return page


def _not_found() -> JsonResponse:
    return error_response(
        ErrorCode.NOT_FOUND,
        "交接单不存在。",
        status=HTTPStatus.NOT_FOUND,
    )


def _method_not_allowed() -> JsonResponse:
    return error_response(
        ErrorCode.VALIDATION_ERROR,
        "不支持的请求方法。",
        status=HTTPStatus.METHOD_NOT_ALLOWED,
    )
