"""提供门户交接 API 共用的用户识别, 权限复核和请求解析支持。"""

from __future__ import annotations

import hashlib
import json
from http import HTTPStatus
from typing import Final, cast

from django.db import transaction
from django.db.models import Q
from django.http import HttpRequest, JsonResponse

from easyauth.accounts.auth import AUTHENTIK_SESSION_KEY
from easyauth.accounts.local_admin import LOCAL_ADMIN_SUBJECT_PREFIX
from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.api.errors import ErrorCode
from easyauth.api.responses import error_response
from easyauth.lifecycle.api_errors import reason_error
from easyauth.lifecycle.assignee import AssigneeApplyOptions, AssigneeResolution, apply_assignee
from easyauth.lifecycle.core import record_task_event
from easyauth.lifecycle.errors import HandoverError
from easyauth.lifecycle.jurisdiction import assert_manager_of
from easyauth.lifecycle.models import (
    ASSIGNEE_STATE_SUPERUSER_POOL,
    AUTHORITY_SOURCE_SUPERUSER,
    HANDOVER_KIND_REASSIGN,
    TASK_OPEN_STATUSES,
    HandoverAppAction,
    HandoverTask,
)

type PortalApiResult = UserMirror | JsonResponse

IDEMPOTENCY_KEY_MAX: Final = 128
ITEMS_MAX_PAGE: Final = 100_000
PORTAL_ASSIGNEE_REQUIRED: Final = "portal_assignee_required"


def _portal_user_for_method(request: HttpRequest, method: str) -> PortalApiResult:
    user = _portal_user(request)
    if isinstance(user, JsonResponse):
        return user
    if request.method != method:
        return _method_not_allowed()
    return user


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
            _assignee_or_subject_query(user),
        )
        .first()
    )


def _assignee_or_subject_query(user: UserMirror) -> Q:
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
            .filter(_assignee_or_subject_query(user))
            .first()
        )
    else:
        task = _task_visible_to(user, task_id)
    if task is None:
        return _not_found()
    if require_assignee and task.assignee_id != cast("int", user.pk):
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
    if task.assignee_id != cast("int", actor.pk):
        return None
    if lock_context:
        locked_users = {
            cast("int", item.pk): item
            for item in UserMirror.objects.select_for_update()
            .filter(
                pk__in={cast("int", actor.pk), task.subject_user_id},
            )
            .order_by("pk")
        }
        actor = locked_users[cast("int", actor.pk)]
        task.subject_user = locked_users[task.subject_user_id]
    result = assert_manager_of(actor, task.subject_user, lock_context=lock_context)
    if result.allowed:
        return None
    # 失权: 移交 superuser_pool
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
        if task.assignee_id != cast("int", user.pk):
            raise HandoverError(PORTAL_ASSIGNEE_REQUIRED)
        if task.kind != HANDOVER_KIND_REASSIGN:
            return
        if task.authority_source == AUTHORITY_SOURCE_SUPERUSER:
            return
        locked_users = {
            cast("int", item.pk): item
            for item in UserMirror.objects.select_for_update()
            .filter(pk__in={cast("int", user.pk), task.subject_user_id})
            .order_by("pk")
        }
        actor = locked_users[cast("int", user.pk)]
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


portal_user_for_method = _portal_user_for_method
portal_user = _portal_user
idempotency_key = _idempotency_key
payload_sha256 = _payload_sha256
task_visible_to = _task_visible_to
action_for_user = _action_for_user
recheck_reassign_scope = _recheck_reassign_scope
portal_mutation_guard = _portal_mutation_guard
recheck_reassign_scope_locked = _recheck_reassign_scope_locked
parse_int = _parse_int
parse_page = _parse_page
not_found = _not_found
method_not_allowed = _method_not_allowed
