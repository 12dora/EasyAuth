"""交接执行链 v2: preview / execute / lease / complete_data_phase / poll(01 §5, §7)。"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING, Final, cast

from django.db import transaction
from django.utils import timezone

from easyauth.config.rate_limit import rate_limit_exceeded

from easyauth.accounts.models import USER_STATUS_ACTIVE
from easyauth.applications.models import (
    HANDOVER_CAPABILITY_DECLARED,
    HANDOVER_CAPABILITY_NONE,
    HANDOVER_CAPABILITY_UNDECLARED,
    App,
)
from easyauth.lifecycle.core import (
    ACTION_NOT_OPERABLE_MESSAGE,
    ACTION_SELF_RECEIVER_MESSAGE,
    ASYNC_ACCEPTED_LOCATION_REQUIRED_MESSAGE,
    ASYNC_POLL_LIMIT_MESSAGE,
    ASYNC_POLL_MAX_ATTEMPTS,
    ASYNC_STATUS_URL_REQUIRED_MESSAGE,
    EXECUTE_ACCEPTED_LOCATION_REQUIRED_MESSAGE,
    HOOK_EVENT_EXECUTE,
    HOOK_EVENT_ITEMS,
    HOOK_EVENT_PREVIEW,
    LIFECYCLE_ACTOR_ID,
    PREVIEW_GENERATION_CONFLICT_MESSAGE,
    PREVIEW_SYNC_REQUIRED_MESSAGE,
    TASK_NOT_DELETABLE_MESSAGE,
    ensure_action_status,
    ensure_task_open,
    record_task_event,
    refresh_task_status,
    refresh_task_status_locked,
)
from easyauth.lifecycle.errors import HandoverConflictError, HandoverError
from easyauth.lifecycle.lease import (
    HANDOVER_EXECUTION_IN_FLIGHT,
    LeaseHandle,
    action_execution_in_flight,
    cas_release,
    cas_update_owner,
    must_cas_release,
    require_cas,
    take_lease,
)
from easyauth.lifecycle.models import (
    ACTION_FINISHED_STATUSES,
    ACTION_GRANT_TRANSFER_KINDS,
    ACTION_STATUS_ASYNC_ATTENTION_REQUIRED,
    ACTION_STATUS_ASYNC_PENDING,
    ACTION_STATUS_BLOCKED,
    ACTION_STATUS_DONE,
    ACTION_STATUS_EXECUTING,
    ACTION_STATUS_FAILED,
    ACTION_STATUS_PENDING,
    ACTION_STATUS_PREVIEWED,
    ACTION_STATUS_SKIPPED,
    ASSET_ACTION_RELEASE,
    ASSET_ACTION_SKIP,
    ASSET_ACTION_TRANSFER,
    BATCH_STATUS_ASYNC_PENDING,
    BATCH_STATUS_DATA_COMPLETED,
    BATCH_STATUS_DONE,
    BATCH_STATUS_EXECUTING,
    BATCH_STATUS_FAILED,
    BATCH_STATUS_PENDING,
    BLOCKED_REASON_CAPABILITY_UNDECLARED,
    DELIVERY_OUTCOME_ASYNC_ACCEPTED,
    DELIVERY_OUTCOME_FAILED,
    DELIVERY_OUTCOME_SENT,
    DELIVERY_OUTCOME_SUCCEEDED,
    DELIVERY_OUTCOME_SUPERSEDED,
    HANDOVER_KIND_OFFBOARD,
    ITEM_STATUS_DONE,
    ITEM_STATUS_PENDING,
    ITEM_STATUS_SKIPPED,
    TASK_STATUS_CANCELLED,
    TEAM_ITEM_ACTION_ASSIGN_LEADER,
    TEAM_ITEM_ACTION_DEACTIVATE,
    BATCH_PLAN_STATUS_ACTIVE,
    BATCH_PLAN_STATUS_DONE,
    HandoverActionSkipRecord,
    HandoverAppAction,
    HandoverAssetOverride,
    HandoverAssetType,
    HandoverBatchPlan,
    HandoverDeliveryAttempt,
    HandoverExecutionBatch,
    HandoverExecutionLease,
    HandoverGrantItem,
    HandoverTask,
    HandoverTeamItem,
)
from easyauth.lifecycle.transfer import transfer_selected_grants
from easyauth.teams.models import TEAM_MEMBER_ROLE_LEADER, TeamMember
from easyauth.webhooks.hooks import HookCallError, HookResponse, signed_hook_get, signed_hook_post
from easyauth.webhooks.models import AppWebhookConfig

if TYPE_CHECKING:
    from easyauth.accounts.models import UserMirror
    from easyauth.applications.ops_models import JsonValue

logger = logging.getLogger(__name__)

TASK_ID_PATTERN: Final = re.compile(r"\A[0-9]+:[0-9]+\Z")
ITEMS_PAGE_MAX: Final = 100_000
ITEMS_PAGE_SIZE_MAX: Final = 200
ITEMS_QUERY_MAX_BYTES: Final = 128
ITEMS_RATE_LIMIT_WINDOW_SECONDS: Final = 60
ITEMS_RATE_LIMIT_MAX: Final = 120
PAYLOAD_SOFT_LIMIT_BYTES: Final = 200 * 1024
SNAPSHOT_TOKEN_MAX_LEN: Final = 128
RESPONSE_PAYLOAD_DIGEST_MAX: Final = 512
SKIP_REASON_CAPABILITY_NONE: Final = "运营已声明本应用无用户级数据"
DECLARED_WITHOUT_URL_MESSAGE: Final = "declared 能力与 webhook 配置不一致"
POLICY_REMOVED_MESSAGE: Final = (
    "policy / release_to_pool 已移除; 权限接收人请用 grant_receiver, 数据接收人请用资产级分配。"
)
RATE_LIMITED_MESSAGE: Final = "rate_limited"
ITEMS_RATE_LIMIT_NAMESPACE: Final = "handover-items"


@dataclass(frozen=True, slots=True)
class _PreviewRequest:
    action_id: int
    preview_generation: int
    generation: int
    app: App
    hook_url: str
    payload: dict[str, JsonValue]


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------


def update_grant_receiver(
    *,
    action: HandoverAppAction,
    grant_receiver: UserMirror | None,
) -> HandoverAppAction:
    with transaction.atomic():
        locked = _locked_action(action.id)
        ensure_task_open(locked.task)
        if action_execution_in_flight(locked):
            raise HandoverConflictError(HANDOVER_EXECUTION_IN_FLIGHT)
        if grant_receiver is not None and locked.task.kind != HANDOVER_KIND_OFFBOARD:
            raise HandoverError("grant_receiver 仅 offboard 允许非空。")
        if (
            grant_receiver is not None
            and cast("int", grant_receiver.pk) == locked.task.subject_user_id
        ):
            raise HandoverError(ACTION_SELF_RECEIVER_MESSAGE)
        locked.grant_receiver = grant_receiver
        locked.confirm_version += 1
        if locked.status in {ACTION_STATUS_FAILED, ACTION_STATUS_PREVIEWED}:
            locked.status = ACTION_STATUS_PENDING
            locked.snapshot_token = ""
            locked.last_error = ""
        locked.save(
            update_fields=[
                "grant_receiver",
                "confirm_version",
                "status",
                "snapshot_token",
                "last_error",
                "updated_at",
            ],
        )
        return locked


# 兼容旧名: 控制台尚未迁完时避免 ImportError; 语义已变为 grant_receiver。
def update_action_receiver(
    *,
    action: HandoverAppAction,
    to_user: UserMirror | None,
    policy: dict[str, JsonValue] | None = None,
) -> HandoverAppAction:
    # 禁止静默丢弃: 旧 policy/release_to_pool 已无法兑现, 必须 400。
    if policy is not None and policy:
        raise HandoverError(POLICY_REMOVED_MESSAGE)
    return update_grant_receiver(action=action, grant_receiver=to_user)


def preview_action(action: HandoverAppAction) -> HandoverAppAction:
    request = _reserve_preview_request(action.id)
    if not request.hook_url:
        raise HandoverError(DECLARED_WITHOUT_URL_MESSAGE)
    try:
        response = signed_hook_post(
            app=request.app,
            url=request.hook_url,
            event_type=HOOK_EVENT_PREVIEW,
            delivery_id=uuid.uuid4().hex,
            payload=request.payload,
        )
        payload = _preview_response_payload(response)
    except HookCallError as error:
        _record_preview_error(request, error)
        raise
    return _complete_preview_request(request, payload=payload)


def execute_action(
    action: HandoverAppAction,
    *,
    confirm_version: int | None = None,
    owner: str | None = None,
) -> HandoverAppAction:
    return _execute_action(
        action,
        allowed_status=ACTION_STATUS_PREVIEWED,
        confirm_version=confirm_version,
        owner=owner,
        is_retry=False,
    )


def retry_action(
    action: HandoverAppAction,
    *,
    owner: str | None = None,
) -> HandoverAppAction:
    return _execute_action(
        action,
        allowed_status=ACTION_STATUS_FAILED,
        confirm_version=None,
        owner=owner,
        is_retry=True,
    )


def poll_async_action(action: HandoverAppAction, *, worker_id: str | None = None) -> HandoverAppAction:
    """异步轮询: claim → GET → 终态走 complete_data_phase; 超次数 → async_attention_required。"""
    poller = worker_id or f"poller:{uuid.uuid4().hex[:12]}"
    with transaction.atomic():
        action = _locked_action(action.id)
        ensure_action_status(
            action,
            allowed={ACTION_STATUS_ASYNC_PENDING, ACTION_STATUS_ASYNC_ATTENTION_REQUIRED},
        )
        if not action.async_status_url:
            raise HandoverConflictError(ASYNC_STATUS_URL_REQUIRED_MESSAGE)
        lease = (
            HandoverExecutionLease.objects.select_for_update()
            .filter(
                action=action,
                generation=action.generation,
                released_at__isnull=True,
            )
            .first()
        )
        if lease is None:
            raise HandoverConflictError(HANDOVER_EXECUTION_IN_FLIGHT)
        batch = (
            HandoverExecutionBatch.objects.filter(
                action=action,
                generation=action.generation,
                batch_seq=lease.batch_seq,
            )
            .order_by("-id")
            .first()
        )
        if batch is None:
            raise HandoverConflictError(ACTION_NOT_OPERABLE_MESSAGE)
        # 从 async sentinel claim
        sentinel_owner = f"async:{batch.pk}"
        handle = LeaseHandle(
            lease_id=int(lease.pk),  # type: ignore[arg-type]
            owner=lease.owner,
            fence=int(lease.fence),
            expires_at=lease.lease_expires_at,
        )
        if lease.owner.startswith("async:") or lease.owner == sentinel_owner:
            claimed = cas_update_owner(handle, new_owner=poller, renew=True)
            if claimed is None:
                raise HandoverConflictError(HANDOVER_EXECUTION_IN_FLIGHT)
            handle = claimed
        elif lease.owner.startswith("poller:"):
            # 已被其他 poller 持有
            if lease.owner != poller:
                raise HandoverConflictError(HANDOVER_EXECUTION_IN_FLIGHT)
            handle = LeaseHandle(
                lease_id=int(lease.pk),  # type: ignore[arg-type]
                owner=lease.owner,
                fence=int(lease.fence),
                expires_at=lease.lease_expires_at,
            )
        else:
            raise HandoverConflictError(HANDOVER_EXECUTION_IN_FLIGHT)

        if action.status == ACTION_STATUS_ASYNC_PENDING:
            if action.async_poll_attempts >= ASYNC_POLL_MAX_ATTEMPTS:
                action.status = ACTION_STATUS_ASYNC_ATTENTION_REQUIRED
                action.save(update_fields=["status", "updated_at"])
                # 移回 sentinel 并续租, 不释放
                _ = cas_update_owner(handle, new_owner=f"async:{batch.pk}", renew=True)
                logger.warning(
                    "async poll limit reached: action_id=%s app=%s attempts=%s",
                    action.id,
                    action.app_key_snapshot,
                    action.async_poll_attempts,
                )
                record_task_event(
                    action.task,
                    action="handover_async_attention_required",
                    actor_id=LIFECYCLE_ACTOR_ID,
                    actor_type="system",
                    extra={
                        "app_key": action.app_key_snapshot,
                        "async_poll_attempts": action.async_poll_attempts,
                        "message": ASYNC_POLL_LIMIT_MESSAGE,
                    },
                )
                return action
            action.async_poll_attempts += 1
            action.save(update_fields=["async_poll_attempts", "updated_at"])

    try:
        response = signed_hook_get(
            app=action.app,
            url=action.async_status_url,
            event_type=HOOK_EVENT_EXECUTE,
            delivery_id=uuid.uuid4().hex,
        )
        _validate_poll_response(response)
    except (HookCallError, HandoverError) as error:
        with transaction.atomic():
            action = _locked_action(action.id)
            if action.status in {
                ACTION_STATUS_ASYNC_PENDING,
                ACTION_STATUS_ASYNC_ATTENTION_REQUIRED,
            }:
                action.last_error = str(error)[:500]
                action.last_error_raw = str(error)[:2000]
                action.save(update_fields=["last_error", "last_error_raw", "updated_at"])
            # 移回 sentinel
            _handoff_to_async_sentinel(action, handle, batch_id=batch.pk)
        raise

    if response.status_code == HTTPStatus.ACCEPTED:
        with transaction.atomic():
            action = _locked_action(action.id)
            require_cas(handle)
            if action.status not in {
                ACTION_STATUS_ASYNC_PENDING,
                ACTION_STATUS_ASYNC_ATTENTION_REQUIRED,
            }:
                raise HandoverConflictError(ACTION_NOT_OPERABLE_MESSAGE)
            action.async_status_url = response.location
            action.last_error = ""
            action.save(update_fields=["async_status_url", "last_error", "updated_at"])
            _handoff_to_async_sentinel(action, handle, batch_id=batch.pk)
        return action

    # 终态 200: complete_data_phase 自管 A/B/C 事务, 调用方不得再包 atomic。
    complete_data_phase(
        HandoverExecutionBatch.objects.get(pk=batch.pk),
        handle=handle,
        response_payload=response.payload,
    )
    action = HandoverAppAction.objects.get(pk=action.id)
    record_task_event(
        action.task,
        action="handover_action_executed",
        actor_id=LIFECYCLE_ACTOR_ID,
        actor_type="system",
        extra={"app_key": action.app_key_snapshot, "via": "async_poll"},
    )
    return action


def complete_data_phase(
    batch: HandoverExecutionBatch,
    *,
    handle: LeaseHandle,
    response_payload: dict[str, JsonValue] | None = None,
) -> None:
    """同步 200 与异步终态汇合的收尾(01 §5.5)。A/B/C 必须各自 commit。"""
    _ = response_payload
    action_id = batch.action_id
    is_final = batch.is_final
    needs_grant = False

    # —— 事务 A: data_completed 标记必须先提交, 授权失败也不能丢 ——
    with transaction.atomic():
        require_cas(handle)
        batch = HandoverExecutionBatch.objects.select_for_update().get(pk=batch.pk)
        now = timezone.now()
        batch.status = BATCH_STATUS_DATA_COMPLETED
        batch.data_completed_at = now
        batch.save(update_fields=["status", "data_completed_at"])

        action: HandoverAppAction | None = None
        if action_id is not None:
            action = _locked_action_after_task(int(action_id))

        if not is_final:
            batch.status = BATCH_STATUS_DONE
            batch.save(update_fields=["status"])
            if action is not None:
                # 非最终批: 同步 executing 与异步 async_* 都要退回 previewed 并释放租约。
                if action.status in {
                    ACTION_STATUS_EXECUTING,
                    ACTION_STATUS_ASYNC_PENDING,
                    ACTION_STATUS_ASYNC_ATTENTION_REQUIRED,
                }:
                    action.status = ACTION_STATUS_PREVIEWED
                    action.snapshot_token = ""
                    action.async_status_url = ""
                    action.save(
                        update_fields=[
                            "status",
                            "snapshot_token",
                            "async_status_url",
                            "updated_at",
                        ],
                    )
                _bump_plan_progress(action)
            must_cas_release(handle)
            return

        if action is not None:
            action.data_completed_at = now
            action.save(update_fields=["data_completed_at", "updated_at"])
            needs_grant = action.task.kind in ACTION_GRANT_TRANSFER_KINDS

    # —— 事务 B: 仅 offboard 转授权; 失败写 failed+释放并提交, 再 raise ——
    grant_error: Exception | None = None
    if needs_grant and action_id is not None:
        with transaction.atomic():
            require_cas(handle)
            action = _locked_action_after_task(int(action_id))
            batch = HandoverExecutionBatch.objects.select_for_update().get(pk=batch.pk)
            try:
                _ = transfer_selected_grants(action)
            except Exception as error:
                action.status = ACTION_STATUS_FAILED
                action.last_error = "授权转移失败"
                action.last_error_raw = str(error)[:2000]
                action.save(
                    update_fields=["status", "last_error", "last_error_raw", "updated_at"],
                )
                batch.status = BATCH_STATUS_FAILED
                batch.save(update_fields=["status"])
                must_cas_release(handle)
                task = HandoverTask.objects.select_for_update().get(pk=action.task_id)
                _ = refresh_task_status_locked(task)
                grant_error = error
        if grant_error is not None:
            raise HandoverError("授权转移失败") from grant_error

    # —— 事务 C: done + 清空 snapshot_token + 释放 ——
    with transaction.atomic():
        require_cas(handle)
        batch = HandoverExecutionBatch.objects.select_for_update().get(pk=batch.pk)
        if action_id is not None:
            action = _locked_action_after_task(int(action_id))
            action.status = ACTION_STATUS_DONE
            action.async_status_url = ""
            action.last_error = ""
            action.snapshot_token = ""
            action.save(
                update_fields=[
                    "status",
                    "async_status_url",
                    "last_error",
                    "snapshot_token",
                    "updated_at",
                ],
            )
            _complete_active_plan(action)
            task = HandoverTask.objects.select_for_update().get(pk=action.task_id)
            _ = refresh_task_status_locked(task)
        batch.status = BATCH_STATUS_DONE
        batch.save(update_fields=["status"])
        must_cas_release(handle)


def skip_action(
    action: HandoverAppAction,
    *,
    actor_id: str,
    reason: str = "",
) -> HandoverAppAction:
    with transaction.atomic():
        action = _locked_action(action.id)
        ensure_action_status(
            action,
            allowed={
                ACTION_STATUS_PENDING,
                ACTION_STATUS_PREVIEWED,
                ACTION_STATUS_FAILED,
                ACTION_STATUS_BLOCKED,
            },
        )
        if action_execution_in_flight(action):
            raise HandoverConflictError(ACTION_NOT_OPERABLE_MESSAGE)
        now = timezone.now()
        action.status = ACTION_STATUS_SKIPPED
        action.skip_reason = reason
        action.skipped_by = actor_id
        action.skipped_at = now
        action.save(
            update_fields=[
                "status",
                "skip_reason",
                "skipped_by",
                "skipped_at",
                "updated_at",
            ],
        )
        _ = HandoverActionSkipRecord.objects.create(
            task=action.task,
            task_id_snapshot=int(action.task_id),
            action_snapshot_id=int(action.id),
            generation=action.generation,
            app_key=action.app_key_snapshot or action.app.app_key,
            actor_id=actor_id,
            reason=reason,
        )
        _ = HandoverGrantItem.objects.filter(
            task=action.task,
            app=action.app,
            generation=action.generation,
            status=ITEM_STATUS_PENDING,
        ).update(status=ITEM_STATUS_SKIPPED)
        task = HandoverTask.objects.select_for_update().get(pk=action.task_id)
        _ = refresh_task_status_locked(task)
    record_task_event(
        action.task,
        action="handover_action_skipped",
        actor_id=actor_id,
        extra={"app_key": action.app.app_key, "reason": reason},
    )
    return action


def apply_team_item(
    *,
    item: HandoverTeamItem,
    action: str,
    to_user: UserMirror | None,
    actor_id: str,
) -> HandoverTeamItem:
    with transaction.atomic():
        item = (
            HandoverTeamItem.objects.select_for_update(of=("self",))
            .select_related("task", "team")
            .get(pk=item.id)
        )
        ensure_task_open(item.task)
        if item.status != ITEM_STATUS_PENDING:
            raise HandoverConflictError(ACTION_NOT_OPERABLE_MESSAGE)
        if action == TEAM_ITEM_ACTION_ASSIGN_LEADER:
            if to_user is None:
                message = "接任负责人时必须指定接收人。"
                raise HandoverError(message)
            if cast("int", to_user.pk) == item.task.subject_user_id:
                raise HandoverError(ACTION_SELF_RECEIVER_MESSAGE)
            _ = TeamMember.objects.update_or_create(
                team=item.team,
                user=to_user,
                defaults={"role": TEAM_MEMBER_ROLE_LEADER, "added_by": actor_id},
            )
        elif action == TEAM_ITEM_ACTION_DEACTIVATE:
            item.team.is_active = False
            item.team.save(update_fields=["is_active", "updated_at"])
        else:
            message = "团队交接动作必须为 assign_leader 或 deactivate。"
            raise HandoverError(message)
        item.action = action
        item.to_user = to_user
        item.status = ITEM_STATUS_DONE
        item.save()
        task = HandoverTask.objects.select_for_update().get(pk=item.task_id)
        _ = refresh_task_status_locked(task)
    record_task_event(
        item.task,
        action="handover_team_item_applied",
        actor_id=actor_id,
        extra={
            "team_name": item.team.name,
            "team_action": action,
            "to_user_id": to_user.authentik_user_id if to_user is not None else "",
        },
    )
    return item


def cancel_task(task: HandoverTask, *, actor_id: str) -> HandoverTask:
    with transaction.atomic():
        # §2.2 统一锁序: task → 子项
        task = HandoverTask.objects.select_for_update().get(pk=task.id)
        ensure_task_open(task)
        actions = list(
            HandoverAppAction.objects.select_for_update(of=("self",))
            .filter(task=task)
            .order_by("id"),
        )
        if any(
            a.status in {ACTION_STATUS_EXECUTING, ACTION_STATUS_ASYNC_PENDING}
            for a in actions
        ) or HandoverExecutionLease.objects.filter(
            action__task=task,
            released_at__isnull=True,
        ).exists():
            raise HandoverConflictError(ACTION_NOT_OPERABLE_MESSAGE)
        for action in actions:
            if action.snapshot_token:
                action.snapshot_token = ""
                action.save(update_fields=["snapshot_token", "updated_at"])
        task.status = TASK_STATUS_CANCELLED
        task.escalation_deadline = None
        task.save(update_fields=["status", "escalation_deadline", "updated_at"])
    record_task_event(task, action="handover_task_cancelled", actor_id=actor_id)
    return task


def delete_task(task: HandoverTask, *, actor_id: str) -> None:
    with transaction.atomic():
        task = HandoverTask.objects.select_for_update().get(pk=task.id)
        if task.status != TASK_STATUS_CANCELLED:
            raise HandoverConflictError(TASK_NOT_DELETABLE_MESSAGE)
        if HandoverActionSkipRecord.objects.filter(task_id_snapshot=task.id).exists():
            message = "带有强行跳过历史的交接单不允许删除。"
            raise HandoverConflictError(message)
        record_task_event(task, action="handover_task_deleted", actor_id=actor_id)
        _ = task.delete()


def validate_assignments(action: HandoverAppAction) -> None:
    """execute 前置校验(01 §5.4)。不通过即 422, 不发 webhook。"""
    types = list(
        HandoverAssetType.objects.filter(
            action=action,
            generation=action.generation,
        ).prefetch_related("overrides"),
    )
    seen_type_keys: set[str] = set()
    for asset_type in types:
        if asset_type.type_key in seen_type_keys:
            raise HandoverError("duplicate_assignment")
        seen_type_keys.add(asset_type.type_key)
        if asset_type.default_action == ASSET_ACTION_RELEASE and not asset_type.releasable:
            raise HandoverError("asset_type_not_releasable")
        if asset_type.default_action == ASSET_ACTION_TRANSFER:
            if asset_type.default_to_user is None:
                raise HandoverError("receiver_required")
            _assert_receiver_ok(action, asset_type.default_to_user)
        seen_ids: set[str] = set()
        for ov in asset_type.overrides.all():
            if ov.asset_id in seen_ids:
                raise HandoverError("duplicate_assignment")
            seen_ids.add(ov.asset_id)
            if ov.action == ASSET_ACTION_RELEASE and not asset_type.releasable:
                raise HandoverError("asset_type_not_releasable")
            if ov.action == ASSET_ACTION_TRANSFER:
                if ov.to_user is None:
                    raise HandoverError("receiver_required")
                _assert_receiver_ok(action, ov.to_user)
    if action.task.kind == HANDOVER_KIND_OFFBOARD and action.grant_receiver is not None:
        _assert_receiver_ok(action, action.grant_receiver)


def fetch_action_items(
    action: HandoverAppAction,
    *,
    asset_type: str,
    page: int,
    page_size: int,
    q: str,
    actor_id: str = LIFECYCLE_ACTOR_ID,
) -> dict[str, JsonValue]:
    """透传 items; 参数上界与限流(01 §5.6)。"""
    ensure_task_open(action.task)
    if action.status in ACTION_FINISHED_STATUSES or action.data_completed_at is not None:
        raise HandoverConflictError("items_not_available")
    if page < 1 or page > ITEMS_PAGE_MAX:
        raise HandoverError("items_page_out_of_range")
    page_size = min(max(page_size, 1), ITEMS_PAGE_SIZE_MAX)
    q_stripped = q.strip()
    if len(q_stripped.encode("utf-8")) > ITEMS_QUERY_MAX_BYTES:
        raise HandoverError("items_query_too_long")
    rate_identity = f"{actor_id}:{action.task_id}:{action.app_id}"
    if rate_limit_exceeded(
        ITEMS_RATE_LIMIT_NAMESPACE,
        rate_identity,
        limit=ITEMS_RATE_LIMIT_MAX,
        window_seconds=ITEMS_RATE_LIMIT_WINDOW_SECONDS,
    ):
        raise HandoverConflictError(RATE_LIMITED_MESSAGE)
    asset = HandoverAssetType.objects.filter(
        action=action,
        generation=action.generation,
        type_key=asset_type,
    ).first()
    if asset is None or not asset.detail_supported:
        raise HandoverError("detail_not_supported")
    hook_url = _handover_hook_url(action.app)
    if not hook_url:
        raise HandoverError(DECLARED_WITHOUT_URL_MESSAGE)
    payload: dict[str, JsonValue] = {
        "task_id": _task_id(action),
        "event_type": HOOK_EVENT_ITEMS,
        "kind": action.task.kind,
        "from_user_id": action.task.subject_user.authentik_user_id,
        "generation": action.generation,
        "snapshot_token": action.snapshot_token,
        "asset_type": asset_type,
        "page": page,
        "page_size": page_size,
        "q": q_stripped,
    }
    response = signed_hook_post(
        app=action.app,
        url=hook_url,
        event_type=HOOK_EVENT_ITEMS,
        delivery_id=uuid.uuid4().hex,
        payload=payload,
    )
    if response.status_code != HTTPStatus.OK:
        raise HandoverError(f"items 接口返回 {response.status_code}")
    body = response.payload
    total = int(body.get("total", 0) or 0)
    unfiltered = body.get("unfiltered_total")
    stale = False
    if q_stripped == "" and total != asset.count:
        stale = True
    elif q_stripped and unfiltered is not None and int(unfiltered) != asset.count:
        stale = True
    return {
        "items": body.get("items", []),
        "page": page,
        "page_size": page_size,
        "total": total,
        "unfiltered_total": unfiltered,
        "stale": stale,
    }


def reset_action_for_upgrade(action: HandoverAppAction, *, task: HandoverTask) -> HandoverAppAction:
    """§5.1.2 升级字段重置。调用方已锁 task → action; 有未释放租约则 409。"""
    from easyauth.applications.handover_capability import _seed_asset_type_placeholders
    from easyauth.lifecycle.lease import has_active_lease

    if has_active_lease(
        subject_user_id=int(task.subject_user_id),  # type: ignore[arg-type]
        app_id=int(action.app_id),  # type: ignore[arg-type]
    ):
        raise HandoverConflictError(HANDOVER_EXECUTION_IN_FLIGHT)

    action.generation = task.generation
    action.data_completed_at = None
    action.snapshot_token = ""
    action.batch_seq = 0
    action.last_error = ""
    action.last_error_raw = ""
    action.async_status_url = ""
    action.async_poll_attempts = 0
    action.skipped_at = None
    action.skipped_by = ""
    action.skip_reason = ""
    action.attempts = 0
    action.confirm_version += 1
    action.overrides_version += 1
    # status 按 capability 重判
    cap = action.app.handover_capability
    if cap == HANDOVER_CAPABILITY_DECLARED:
        action.status = ACTION_STATUS_PENDING
        action.blocked_reason = ""
    elif cap == HANDOVER_CAPABILITY_NONE:
        action.status = ACTION_STATUS_SKIPPED
        action.skip_reason = SKIP_REASON_CAPABILITY_NONE
        action.skipped_by = action.app.handover_capability_declared_by
        action.skipped_at = timezone.now()
        action.blocked_reason = ""
    else:
        action.status = ACTION_STATUS_BLOCKED
        action.blocked_reason = BLOCKED_REASON_CAPABILITY_UNDECLARED
    action.save()
    if action.status == ACTION_STATUS_PENDING:
        _seed_asset_type_placeholders(action)
    return action


# ---------------------------------------------------------------------------
# 执行内部
# ---------------------------------------------------------------------------


def _execute_action(
    action: HandoverAppAction,
    *,
    allowed_status: str,
    confirm_version: int | None,
    owner: str | None,
    is_retry: bool,
) -> HandoverAppAction:
    worker_owner = owner or f"http:{uuid.uuid4().hex[:12]}"
    grant_only_error: Exception | None = None
    grant_only_done_id: int | None = None
    action_id: int | None = None
    batch_id: int | None = None
    delivery_id: int | None = None
    handle: LeaseHandle | None = None
    app: App | None = None
    url = ""
    body: dict[str, JsonValue] = {}

    with transaction.atomic():
        action = _locked_action(action.id)
        ensure_action_status(action, allowed={allowed_status})
        if confirm_version is not None and confirm_version != action.confirm_version:
            raise HandoverConflictError("confirm_version_stale")
        validate_assignments(action)

        # 纯授权重试: data_completed_at 非空 — 失败态提交后在 atomic 外 raise
        if is_retry and action.data_completed_at is not None:
            handle = take_lease(
                action=action,
                owner=worker_owner,
                batch_seq=action.batch_seq or 1,
            )
            action.status = ACTION_STATUS_EXECUTING
            action.attempts += 1
            action.save(update_fields=["status", "attempts", "updated_at"])
            action_id_grant = action.id
            try:
                require_cas(handle)
                if action.task.kind in ACTION_GRANT_TRANSFER_KINDS:
                    _ = transfer_selected_grants(action)
                action.status = ACTION_STATUS_DONE
                action.last_error = ""
                action.snapshot_token = ""
                action.save(
                    update_fields=["status", "last_error", "snapshot_token", "updated_at"],
                )
                task = HandoverTask.objects.select_for_update().get(pk=action.task_id)
                _ = refresh_task_status_locked(task)
                must_cas_release(handle)
                grant_only_done_id = action_id_grant
            except Exception as error:
                action = HandoverAppAction.objects.select_for_update(of=("self",)).get(
                    pk=action_id_grant,
                )
                action.status = ACTION_STATUS_FAILED
                action.last_error = str(error)[:500]
                action.last_error_raw = str(error)[:2000]
                action.save(
                    update_fields=["status", "last_error", "last_error_raw", "updated_at"],
                )
                _ = cas_release(handle)
                grant_only_error = error
        else:
            hook_url = _handover_hook_url(action.app)
            if not hook_url:
                raise HandoverError(DECLARED_WITHOUT_URL_MESSAGE)

            plan = _active_batch_plan(action)
            payload, is_final, plan_batch_no = _build_execute_payload_for_plan(action, plan)
            payload_bytes = json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            request_hash = hashlib.sha256(payload_bytes).hexdigest()

            if is_retry:
                batch = (
                    HandoverExecutionBatch.objects.select_for_update()
                    .filter(
                        action=action,
                        generation=action.generation,
                        status=BATCH_STATUS_FAILED,
                    )
                    .order_by("-batch_seq")
                    .first()
                )
                if batch is None:
                    raise HandoverConflictError("action_not_retryable")
                # 失败重试必须用原 canonical body, 不得改写 request_payload。
                handle = take_lease(
                    action=action,
                    owner=worker_owner,
                    batch_seq=batch.batch_seq,
                )
                batch.status = BATCH_STATUS_EXECUTING
                batch.save(update_fields=["status"])
                next_seq = HandoverDeliveryAttempt.objects.filter(batch=batch).count() + 1
                delivery = HandoverDeliveryAttempt.objects.create(
                    batch=batch,
                    delivery_seq=next_seq,
                    lease_fence=handle.fence,
                    outcome=DELIVERY_OUTCOME_SENT,
                )
            else:
                next_batch_seq = action.batch_seq + 1
                handle = take_lease(
                    action=action,
                    owner=worker_owner,
                    batch_seq=next_batch_seq,
                )
                action.batch_seq = next_batch_seq
                action.status = ACTION_STATUS_EXECUTING
                action.attempts += 1
                action.last_error = ""
                action.save(
                    update_fields=[
                        "batch_seq",
                        "status",
                        "attempts",
                        "last_error",
                        "updated_at",
                    ],
                )
                batch = HandoverExecutionBatch.objects.create(
                    action=action,
                    action_snapshot_id=int(action.id),
                    generation=action.generation,
                    batch_seq=next_batch_seq,
                    is_final=is_final,
                    plan=plan,
                    plan_batch_no=plan_batch_no,
                    snapshot_token=action.snapshot_token,
                    request_payload=payload,
                    request_hash=request_hash,
                    status=BATCH_STATUS_EXECUTING,
                    task_snapshot={
                        "task_id": action.task_id,
                        "kind": action.task.kind,
                        "app_key": action.app.app_key,
                        "subject_user_id": action.task.subject_user.authentik_user_id,
                    },
                )
                delivery = HandoverDeliveryAttempt.objects.create(
                    batch=batch,
                    delivery_seq=1,
                    lease_fence=handle.fence,
                    outcome=DELIVERY_OUTCOME_SENT,
                )

            delivery_owner = f"delivery:{delivery.pk}"
            handed = cas_update_owner(handle, new_owner=delivery_owner, renew=True)
            if handed is None:
                raise HandoverConflictError(HANDOVER_EXECUTION_IN_FLIGHT)
            handle = handed
            sender_owner = f"sender:{worker_owner}"
            claimed = cas_update_owner(handle, new_owner=sender_owner, renew=True)
            if claimed is None:
                raise HandoverConflictError(HANDOVER_EXECUTION_IN_FLIGHT)
            handle = claimed
            action_id = action.id
            batch_id = batch.id
            delivery_id = delivery.id
            app = action.app
            url = hook_url
            body = dict(batch.request_payload)

    if grant_only_error is not None:
        raise HandoverError(str(grant_only_error)[:500]) from grant_only_error
    if grant_only_done_id is not None:
        return HandoverAppAction.objects.get(pk=grant_only_done_id)

    assert action_id is not None and batch_id is not None and delivery_id is not None
    assert handle is not None and app is not None

    # 网络调用在事务外
    superseded = False
    try:
        with transaction.atomic():
            action = _locked_action(action_id)
            batch = HandoverExecutionBatch.objects.select_for_update().get(pk=batch_id)
            if batch.generation != action.generation or batch.generation != action.task.generation:
                delivery = HandoverDeliveryAttempt.objects.select_for_update().get(
                    pk=delivery_id,
                )
                delivery.outcome = DELIVERY_OUTCOME_SUPERSEDED
                delivery.error_text = "generation_superseded"
                delivery.save(update_fields=["outcome", "error_text"])
                batch.status = BATCH_STATUS_FAILED
                batch.save(update_fields=["status"])
                must_cas_release(handle)
                superseded = True
                record_task_event(
                    action.task,
                    action="handover_delivery_superseded",
                    actor_id=LIFECYCLE_ACTOR_ID,
                    actor_type="system",
                    extra={"app_key": action.app_key_snapshot, "batch_id": batch_id},
                )
        if superseded:
            raise HandoverConflictError("generation_superseded")
        response = signed_hook_post(
            app=app,
            url=url,
            event_type=HOOK_EVENT_EXECUTE,
            delivery_id=uuid.uuid4().hex,
            payload=body,
        )
    except HookCallError as error:
        _finish_delivery_failure(
            action_id=action_id,
            batch_id=batch_id,
            delivery_id=delivery_id,
            handle=handle,
            error=error,
            http_status=error.status_code,
        )
        raise

    return _handle_execute_response(
        action_id=action_id,
        batch_id=batch_id,
        delivery_id=delivery_id,
        handle=handle,
        response=response,
    )


def _handle_execute_response(
    *,
    action_id: int,
    batch_id: int,
    delivery_id: int,
    handle: LeaseHandle,
    response: HookResponse,
) -> HandoverAppAction:
    status = response.status_code
    if status == HTTPStatus.ACCEPTED:
        _ensure_accepted_location(response, message=EXECUTE_ACCEPTED_LOCATION_REQUIRED_MESSAGE)
        with transaction.atomic():
            require_cas(handle)
            action = _locked_action(action_id)
            batch = HandoverExecutionBatch.objects.select_for_update().get(pk=batch_id)
            delivery = HandoverDeliveryAttempt.objects.select_for_update().get(pk=delivery_id)
            delivery.outcome = DELIVERY_OUTCOME_ASYNC_ACCEPTED
            delivery.http_status = status
            delivery.response_payload = _redact_response_payload(response.payload)
            delivery.save(
                update_fields=["outcome", "http_status", "response_payload"],
            )
            batch.status = BATCH_STATUS_ASYNC_PENDING
            batch.save(update_fields=["status"])
            action.status = ACTION_STATUS_ASYNC_PENDING
            action.async_status_url = response.location
            action.last_error = ""
            action.save(
                update_fields=["status", "async_status_url", "last_error", "updated_at"],
            )
            # 202 不释放, 移交 async sentinel
            handed = cas_update_owner(handle, new_owner=f"async:{batch.pk}", renew=True)
            if handed is None:
                raise HandoverConflictError(HANDOVER_EXECUTION_IN_FLIGHT)
            task = HandoverTask.objects.select_for_update().get(pk=action.task_id)
            _ = refresh_task_status_locked(task)
        return action

    if status == HTTPStatus.OK:
        # delivery 成功标记与 complete_data_phase 分离, 避免 A/B/C 被外层 atomic 回滚。
        with transaction.atomic():
            require_cas(handle)
            delivery = HandoverDeliveryAttempt.objects.select_for_update().get(pk=delivery_id)
            delivery.outcome = DELIVERY_OUTCOME_SUCCEEDED
            delivery.http_status = status
            delivery.response_payload = _redact_response_payload(response.payload)
            delivery.save(
                update_fields=["outcome", "http_status", "response_payload"],
            )
        complete_data_phase(
            HandoverExecutionBatch.objects.get(pk=batch_id),
            handle=handle,
            response_payload=response.payload,
        )
        action = HandoverAppAction.objects.get(pk=action_id)
        record_task_event(
            action.task,
            action="handover_action_executed",
            actor_id=LIFECYCLE_ACTOR_ID,
            actor_type="system",
            extra={"app_key": action.app.app_key},
        )
        return action

    # 412 / 413 / 423 / 429 / 4xx / 5xx
    _finish_delivery_failure(
        action_id=action_id,
        batch_id=batch_id,
        delivery_id=delivery_id,
        handle=handle,
        error=HandoverError(f"execute HTTP {status}"),
        http_status=status,
        response_payload=response.payload,
    )
    action = HandoverAppAction.objects.get(pk=action_id)
    raise HandoverError(action.last_error or f"execute HTTP {status}")


def _finish_delivery_failure(
    *,
    action_id: int,
    batch_id: int,
    delivery_id: int,
    handle: LeaseHandle,
    error: Exception,
    http_status: int | None,
    response_payload: dict[str, JsonValue] | None = None,
) -> None:
    with transaction.atomic():
        require_cas(handle)
        action = _locked_action(action_id)
        batch = HandoverExecutionBatch.objects.select_for_update().get(pk=batch_id)
        delivery = HandoverDeliveryAttempt.objects.select_for_update().get(pk=delivery_id)
        delivery.outcome = DELIVERY_OUTCOME_FAILED
        delivery.http_status = http_status
        delivery.error_text = _redact_error_text(str(error))
        if response_payload is not None:
            delivery.response_payload = _redact_response_payload(response_payload)
        delivery.save(
            update_fields=["outcome", "http_status", "error_text", "response_payload"],
        )
        # 412 / 423 / 429 / 413 → 退回 previewed/pending 并释放
        if http_status in {
            HTTPStatus.PRECONDITION_FAILED,  # 412
            HTTPStatus.LOCKED,  # 423
            HTTPStatus.TOO_MANY_REQUESTS,  # 429
            HTTPStatus.REQUEST_ENTITY_TOO_LARGE,  # 413
        }:
            if http_status == HTTPStatus.TOO_MANY_REQUESTS:
                batch.status = BATCH_STATUS_PENDING
                action.status = ACTION_STATUS_PREVIEWED
            elif http_status == HTTPStatus.REQUEST_ENTITY_TOO_LARGE:
                batch.status = BATCH_STATUS_FAILED
                action.status = ACTION_STATUS_PREVIEWED
                action.snapshot_token = ""
                _ensure_batch_plan_on_413(action)
            elif http_status in {HTTPStatus.PRECONDITION_FAILED, HTTPStatus.LOCKED}:
                batch.status = BATCH_STATUS_FAILED
                action.status = ACTION_STATUS_PENDING
                action.snapshot_token = ""
            else:
                batch.status = BATCH_STATUS_FAILED
                action.status = ACTION_STATUS_PREVIEWED
            action.last_error = str(error)[:500]
            action.last_error_raw = str(error)[:2000]
            action.save(
                update_fields=[
                    "status",
                    "snapshot_token",
                    "last_error",
                    "last_error_raw",
                    "updated_at",
                ],
            )
            batch.save(update_fields=["status"])
            must_cas_release(handle)
            return
        batch.status = BATCH_STATUS_FAILED
        batch.save(update_fields=["status"])
        action.status = ACTION_STATUS_FAILED
        action.last_error = str(error)[:500]
        action.last_error_raw = str(error)[:2000]
        action.save(
            update_fields=["status", "last_error", "last_error_raw", "updated_at"],
        )
        must_cas_release(handle)
        task = HandoverTask.objects.select_for_update().get(pk=action.task_id)
        _ = refresh_task_status_locked(task)
    record_task_event(
        action.task,
        action="handover_action_failed",
        actor_id=LIFECYCLE_ACTOR_ID,
        actor_type="system",
        extra={"app_key": action.app.app_key, "error": str(error)[:200]},
    )


# ---------------------------------------------------------------------------
# preview 内部
# ---------------------------------------------------------------------------


def _locked_action(action_id: int) -> HandoverAppAction:
    # of=("self",): PG 禁止对 nullable outer join 侧 FOR UPDATE(grant_receiver 可空)。
    return (
        HandoverAppAction.objects.select_for_update(of=("self",))
        .select_related(
            "app",
            "task",
            "task__subject_user",
            "grant_receiver",
        )
        .get(pk=action_id)
    )


def _locked_action_after_task(action_id: int) -> HandoverAppAction:
    """§2.2 锁序 task → action: 先锁 task 再锁 action。"""
    task_id = (
        HandoverAppAction.objects.filter(pk=action_id).values_list("task_id", flat=True).first()
    )
    if task_id is None:
        raise HandoverAppAction.DoesNotExist
    _ = HandoverTask.objects.select_for_update().get(pk=task_id)
    return _locked_action(action_id)


def _reserve_preview_request(action_id: int) -> _PreviewRequest:
    with transaction.atomic():
        action = _locked_action(action_id)
        ensure_action_status(
            action,
            allowed={ACTION_STATUS_PENDING, ACTION_STATUS_PREVIEWED},
        )
        if action.app.handover_capability != HANDOVER_CAPABILITY_DECLARED:
            raise HandoverConflictError("action_blocked")
        action.preview_generation += 1
        action.save(update_fields=["preview_generation", "updated_at"])
        hook_url = _handover_hook_url(action.app)
        if not hook_url:
            raise HandoverError(DECLARED_WITHOUT_URL_MESSAGE)
        return _PreviewRequest(
            action_id=action.id,
            preview_generation=action.preview_generation,
            generation=action.generation,
            app=action.app,
            hook_url=hook_url,
            payload=_build_preview_payload(action),
        )


def _record_preview_error(request: _PreviewRequest, error: Exception) -> None:
    with transaction.atomic():
        action = _locked_preview_action(request)
        if action is None:
            return
        action.last_error = str(error)[:500]
        action.save(update_fields=["last_error", "updated_at"])
        task = HandoverTask.objects.select_for_update().get(pk=action.task_id)
        _ = refresh_task_status_locked(task)


def _complete_preview_request(
    request: _PreviewRequest,
    *,
    payload: dict[str, JsonValue],
) -> HandoverAppAction:
    preview_error: HandoverError | None = None
    result: HandoverAppAction | None = None
    with transaction.atomic():
        action = _locked_preview_action(request)
        if action is None:
            raise HandoverConflictError(PREVIEW_GENERATION_CONFLICT_MESSAGE)
        ensure_action_status(action, allowed={ACTION_STATUS_PENDING, ACTION_STATUS_PREVIEWED})
        try:
            _apply_preview_assets(action, payload)
            token = str(payload.get("snapshot_token", "") or "")
            if len(token) > SNAPSHOT_TOKEN_MAX_LEN:
                raise HandoverError(
                    f"snapshot_token 超过 {SNAPSHOT_TOKEN_MAX_LEN} 字节上限",
                )
            action.snapshot_token = token
            action.status = ACTION_STATUS_PREVIEWED
            action.last_error = ""
            action.confirm_version += 1
            action.save(
                update_fields=[
                    "snapshot_token",
                    "status",
                    "last_error",
                    "confirm_version",
                    "updated_at",
                ],
            )
            record_task_event(
                action.task,
                action="handover_action_previewed",
                actor_id=LIFECYCLE_ACTOR_ID,
                actor_type="system",
                extra={"app_key": action.app_key_snapshot},
            )
            task = HandoverTask.objects.select_for_update().get(pk=action.task_id)
            _ = refresh_task_status_locked(task)
            result = action
        except HandoverError as error:
            # failed 必须提交后再 raise, 不能被 atomic 回滚。
            action.status = ACTION_STATUS_FAILED
            action.last_error = str(error)[:500]
            action.last_error_raw = str(error)[:2000]
            action.save(
                update_fields=["status", "last_error", "last_error_raw", "updated_at"],
            )
            task = HandoverTask.objects.select_for_update().get(pk=action.task_id)
            _ = refresh_task_status_locked(task)
            preview_error = error
    if preview_error is not None:
        raise preview_error
    assert result is not None
    return result


def _locked_preview_action(request: _PreviewRequest) -> HandoverAppAction | None:
    return (
        HandoverAppAction.objects.select_for_update(of=("self",))
        .select_related("app", "task", "task__subject_user", "grant_receiver")
        .filter(
            pk=request.action_id,
            preview_generation=request.preview_generation,
            generation=request.generation,
        )
        .first()
    )


def _apply_preview_assets(action: HandoverAppAction, payload: dict[str, JsonValue]) -> None:
    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise HandoverError("preview 响应缺少 assets")
    declared = {
        str(item.get("type", "")): item
        for item in (action.app.handover_asset_types or [])
        if isinstance(item, dict)
    }
    seen: set[str] = set()
    for raw in assets:
        if not isinstance(raw, dict):
            continue
        type_key = str(raw.get("type", ""))
        if not type_key:
            continue
        if type_key not in declared:
            raise HandoverError(f"undeclared_asset_type: {type_key}")
        seen.add(type_key)
        existing = HandoverAssetType.objects.filter(
            action=action,
            generation=action.generation,
            type_key=type_key,
        ).first()
        label = str(raw.get("label", type_key))[:120]
        try:
            count = int(raw.get("count", 0) or 0)
        except (TypeError, ValueError) as error:
            raise HandoverError(f"invalid_asset_count: {type_key}") from error
        if count < 0:
            raise HandoverError(f"invalid_asset_count: {type_key}")
        detail = bool(raw.get("detail_supported", declared[type_key].get("detail_supported", False)))
        releasable = bool(raw.get("releasable", declared[type_key].get("releasable", False)))
        if existing is None:
            _ = HandoverAssetType.objects.create(
                action=action,
                generation=action.generation,
                type_key=type_key,
                label_snapshot=label,
                count=count,
                detail_supported=detail,
                releasable=releasable,
            )
        else:
            existing.label_snapshot = label
            existing.count = count
            existing.detail_supported = detail
            existing.releasable = releasable
            existing.save(
                update_fields=[
                    "label_snapshot",
                    "count",
                    "detail_supported",
                    "releasable",
                ],
            )
    missing = set(declared) - seen
    if missing:
        raise HandoverError(f"preview 缺少已声明类型: {', '.join(sorted(missing))}")


# ---------------------------------------------------------------------------
# payload / helpers
# ---------------------------------------------------------------------------


def _build_preview_payload(action: HandoverAppAction) -> dict[str, JsonValue]:
    return {
        "task_id": _task_id(action),
        "event_type": HOOK_EVENT_PREVIEW,
        "kind": action.task.kind,
        "from_user_id": action.task.subject_user.authentik_user_id,
        "generation": action.generation,
        "mode": "preview",
    }


def _build_execute_payload(action: HandoverAppAction) -> dict[str, JsonValue]:
    payload, _is_final, _plan_no = _build_execute_payload_for_plan(action, plan=None)
    return payload


def _build_execute_payload_for_plan(
    action: HandoverAppAction,
    plan: HandoverBatchPlan | None,
) -> tuple[dict[str, JsonValue], bool, int | None]:
    """契约 §10.5: assignments 用 asset_type / id, 不是 type / asset_id。"""
    if plan is None:
        assignments = _full_assignments(action)
        return (
            _execute_envelope(action, assignments=assignments, batch_id=action.batch_seq + 1),
            True,
            None,
        )
    next_no = int(plan.completed_batches) + 1
    if next_no > int(plan.total):
        raise HandoverConflictError("batch_plan_exhausted")
    chunks = plan.chunks if isinstance(plan.chunks, list) else []
    chunk = chunks[next_no - 1] if next_no - 1 < len(chunks) else []
    is_final = next_no >= int(plan.total)
    assignments = _chunk_assignments(action, chunk=chunk, is_final=is_final)
    return (
        _execute_envelope(action, assignments=assignments, batch_id=action.batch_seq + 1),
        is_final,
        next_no,
    )


def _execute_envelope(
    action: HandoverAppAction,
    *,
    assignments: list[dict[str, JsonValue]],
    batch_id: int,
) -> dict[str, JsonValue]:
    return {
        "task_id": _task_id(action),
        "event_type": HOOK_EVENT_EXECUTE,
        "kind": action.task.kind,
        "from_user_id": action.task.subject_user.authentik_user_id,
        "generation": action.generation,
        "snapshot_token": action.snapshot_token,
        "mode": "execute",
        "batch_id": batch_id,
        "assignments": assignments,
    }


def _full_assignments(action: HandoverAppAction) -> list[dict[str, JsonValue]]:
    assignments: list[dict[str, JsonValue]] = []
    types = HandoverAssetType.objects.filter(
        action=action,
        generation=action.generation,
    ).prefetch_related("overrides", "default_to_user", "overrides__to_user")
    for asset_type in types:
        overrides: list[dict[str, JsonValue]] = []
        for ov in asset_type.overrides.all():
            overrides.append(
                {
                    "id": ov.asset_id,
                    "action": ov.action,
                    "to_user_id": (
                        ov.to_user.authentik_user_id if ov.to_user is not None else None
                    ),
                },
            )
        assignments.append(
            {
                "asset_type": asset_type.type_key,
                "default_action": asset_type.default_action,
                "default_to_user_id": (
                    asset_type.default_to_user.authentik_user_id
                    if asset_type.default_to_user is not None
                    else None
                ),
                "overrides": overrides,
            },
        )
    return assignments


def _chunk_assignments(
    action: HandoverAppAction,
    *,
    chunk: object,
    is_final: bool,
) -> list[dict[str, JsonValue]]:
    """§2.4.1.1: 非最终批 default_action 强制 skip; 最终批带真实 default + 全部 skip override。"""
    allowed_ids_by_type: dict[str, set[str]] = {}
    if isinstance(chunk, list):
        for entry in chunk:
            if not isinstance(entry, dict):
                continue
            type_key = str(entry.get("asset_type", ""))
            ids = entry.get("ids", [])
            if not type_key:
                continue
            allowed_ids_by_type[type_key] = {
                str(i) for i in ids if isinstance(i, str | int)
            }
    result: list[dict[str, JsonValue]] = []
    types = HandoverAssetType.objects.filter(
        action=action,
        generation=action.generation,
    ).prefetch_related("overrides", "default_to_user", "overrides__to_user")
    for asset_type in types:
        type_key = asset_type.type_key
        allowed = allowed_ids_by_type.get(type_key, set())
        overrides: list[dict[str, JsonValue]] = []
        for ov in asset_type.overrides.all():
            if not is_final and ov.asset_id not in allowed:
                continue
            if is_final:
                # 最终批: 本批 remaining transfer/release + 全部 skip
                if ov.action != ASSET_ACTION_SKIP and ov.asset_id not in allowed:
                    # 已在前序批消耗的 transfer/release 不再带
                    continue
            overrides.append(
                {
                    "id": ov.asset_id,
                    "action": ov.action,
                    "to_user_id": (
                        ov.to_user.authentik_user_id if ov.to_user is not None else None
                    ),
                },
            )
        default_action = (
            asset_type.default_action if is_final else ASSET_ACTION_SKIP
        )
        default_to = (
            asset_type.default_to_user.authentik_user_id
            if is_final and asset_type.default_to_user is not None
            else None
        )
        result.append(
            {
                "asset_type": type_key,
                "default_action": default_action,
                "default_to_user_id": default_to,
                "overrides": overrides,
            },
        )
    return result


def _task_id(action: HandoverAppAction) -> str:
    value = f"{action.task_id}:{action.app_id}"
    if not TASK_ID_PATTERN.fullmatch(value) or len(value) > 64:
        message = f"非法 task_id: {value!r}"
        raise HandoverError(message)
    return value


def _handover_hook_url(app: App) -> str:
    config = AppWebhookConfig.objects.filter(app=app, enabled=True).first()
    if config is None:
        return ""
    return config.handover_url


def _preview_response_payload(response: HookResponse) -> dict[str, JsonValue]:
    if response.status_code != HTTPStatus.OK:
        raise HandoverError(PREVIEW_SYNC_REQUIRED_MESSAGE)
    return response.payload


def _ensure_accepted_location(response: HookResponse, *, message: str) -> None:
    if not response.location:
        raise HandoverError(message)


def _validate_poll_response(response: HookResponse) -> None:
    if response.status_code not in {HTTPStatus.OK, HTTPStatus.ACCEPTED}:
        message = f"应用交接状态接口返回不支持的成功状态 {response.status_code}。"
        raise HandoverError(message)
    if response.status_code == HTTPStatus.ACCEPTED:
        _ensure_accepted_location(
            response,
            message=ASYNC_ACCEPTED_LOCATION_REQUIRED_MESSAGE,
        )


def _assert_receiver_ok(action: HandoverAppAction, user: UserMirror) -> None:
    if user.status != USER_STATUS_ACTIVE:
        raise HandoverError("receiver_not_active")
    if cast("int", user.pk) == action.task.subject_user_id:
        raise HandoverError("receiver_is_subject")


def _handoff_to_async_sentinel(
    action: HandoverAppAction,
    handle: LeaseHandle,
    *,
    batch_id: int,
) -> None:
    _ = action
    handed = cas_update_owner(handle, new_owner=f"async:{batch_id}", renew=True)
    if handed is None:
        raise HandoverConflictError(HANDOVER_EXECUTION_IN_FLIGHT)


def initial_action_status_for_app(app: App) -> tuple[str, str, str, str]:
    """返回 (status, blocked_reason, skip_reason, skipped_by)。"""
    if app.handover_capability == HANDOVER_CAPABILITY_DECLARED:
        if not _handover_hook_url(app):
            raise HandoverError(DECLARED_WITHOUT_URL_MESSAGE)
        return ACTION_STATUS_PENDING, "", "", ""
    if app.handover_capability == HANDOVER_CAPABILITY_NONE:
        return (
            ACTION_STATUS_SKIPPED,
            "",
            SKIP_REASON_CAPABILITY_NONE,
            app.handover_capability_declared_by,
        )
    return (
        ACTION_STATUS_BLOCKED,
        BLOCKED_REASON_CAPABILITY_UNDECLARED,
        "",
        "",
    )


def takeover_expired_lease(
    lease: HandoverExecutionLease,
    *,
    owner: str | None = None,
) -> HandoverAppAction | None:
    """§2.4.2 先抢占后查证: 用原 canonical body 重放 execute。"""
    from easyauth.lifecycle.lease import preempt_expired_lease

    worker = owner or f"recover:{uuid.uuid4().hex[:12]}"
    handle = preempt_expired_lease(lease, new_owner=worker)
    if handle is None:
        return None
    batch = (
        HandoverExecutionBatch.objects.filter(
            action_id=lease.action_id,
            generation=lease.generation,
            batch_seq=lease.batch_seq,
        )
        .order_by("-id")
        .first()
    )
    if batch is None or lease.action_id is None:
        _ = cas_release(handle)
        return None
    action = HandoverAppAction.objects.select_related("app", "task").get(pk=lease.action_id)
    if action.status == ACTION_STATUS_ASYNC_PENDING:
        # 异步在途: 续约后交给 poll 路径
        _ = cas_update_owner(handle, new_owner=f"async:{batch.pk}", renew=True)
        return poll_async_action(action, worker_id=worker)
    hook_url = _handover_hook_url(action.app)
    if not hook_url:
        logger.warning("takeover: no hook url action=%s", action.id)
        return None
    delivery = HandoverDeliveryAttempt.objects.create(
        batch=batch,
        delivery_seq=HandoverDeliveryAttempt.objects.filter(batch=batch).count() + 1,
        lease_fence=handle.fence,
        outcome=DELIVERY_OUTCOME_SENT,
    )
    handed = cas_update_owner(handle, new_owner=f"sender:{worker}", renew=True)
    if handed is None:
        return None
    handle = handed
    try:
        response = signed_hook_post(
            app=action.app,
            url=hook_url,
            event_type=HOOK_EVENT_EXECUTE,
            delivery_id=uuid.uuid4().hex,
            payload=dict(batch.request_payload),
        )
    except HookCallError as error:
        # 不可达: 续约, 不释放
        logger.warning("takeover unreachable action=%s error=%s", action.id, error)
        _ = cas_update_owner(handle, new_owner=worker, renew=True)
        return None
    if response.status_code == HTTPStatus.CONFLICT:
        logger.error(
            "takeover payload conflict action=%s batch=%s — 转人工告警, 保持租约",
            action.id,
            batch.id,
        )
        record_task_event(
            action.task,
            action="handover_takeover_payload_conflict",
            actor_id=LIFECYCLE_ACTOR_ID,
            actor_type="system",
            extra={"app_key": action.app_key_snapshot, "batch_id": batch.id},
        )
        return None
    return _handle_execute_response(
        action_id=action.id,
        batch_id=batch.id,
        delivery_id=delivery.id,
        handle=handle,
        response=response,
    )


def _active_batch_plan(action: HandoverAppAction) -> HandoverBatchPlan | None:
    return (
        HandoverBatchPlan.objects.filter(
            action_snapshot_id=action.id,
            generation=action.generation,
            status=BATCH_PLAN_STATUS_ACTIVE,
        )
        .order_by("-id")
        .first()
    )


def _ensure_batch_plan_on_413(action: HandoverAppAction) -> HandoverBatchPlan:
    """413: 一次性算好分片计划, 下次 execute 按 chunk 发送。"""
    existing = _active_batch_plan(action)
    if existing is not None and existing.completed_batches == 0:
        existing.status = "abandoned"
        existing.save(update_fields=["status"])
    assignments = _full_assignments(action)
    chunks = _split_assignments_into_chunks(assignments)
    assignment_hash = hashlib.sha256(
        json.dumps(assignments, sort_keys=True, separators=(",", ":")).encode("utf-8"),
    ).hexdigest()
    return HandoverBatchPlan.objects.create(
        action=action,
        action_snapshot_id=int(action.id),
        generation=action.generation,
        total=max(len(chunks), 1),
        chunks=chunks,
        assignment_hash=assignment_hash,
        status=BATCH_PLAN_STATUS_ACTIVE,
        completed_batches=0,
    )


def _split_assignments_into_chunks(
    assignments: list[dict[str, JsonValue]],
) -> list[JsonValue]:
    """按 soft limit 切 override; 无 override 时整包一批。"""
    # 简化: 把所有 transfer/release override 均分到多批, 每批约 soft limit。
    work_items: list[dict[str, JsonValue]] = []
    for asn in assignments:
        type_key = str(asn.get("asset_type", ""))
        for ov in asn.get("overrides", []) or []:
            if not isinstance(ov, dict):
                continue
            if ov.get("action") in {ASSET_ACTION_TRANSFER, ASSET_ACTION_RELEASE}:
                work_items.append({"asset_type": type_key, "id": str(ov.get("id", ""))})
    if not work_items:
        return [[{"asset_type": str(a.get("asset_type", "")), "ids": []} for a in assignments]]
    # 按字节预算切: 粗略每 50 条一组
    group_size = 50
    chunks: list[JsonValue] = []
    for i in range(0, len(work_items), group_size):
        group = work_items[i : i + group_size]
        by_type: dict[str, list[str]] = {}
        for item in group:
            by_type.setdefault(str(item["asset_type"]), []).append(str(item["id"]))
        chunks.append(
            [{"asset_type": k, "ids": v} for k, v in sorted(by_type.items())],
        )
    return chunks


def _bump_plan_progress(action: HandoverAppAction) -> None:
    plan = _active_batch_plan(action)
    if plan is None:
        return
    plan.completed_batches = min(int(plan.completed_batches) + 1, int(plan.total))
    if plan.completed_batches >= plan.total:
        plan.status = BATCH_PLAN_STATUS_DONE
        plan.save(update_fields=["completed_batches", "status"])
    else:
        plan.save(update_fields=["completed_batches"])


def _complete_active_plan(action: HandoverAppAction) -> None:
    plan = _active_batch_plan(action)
    if plan is None:
        return
    plan.completed_batches = int(plan.total)
    plan.status = BATCH_PLAN_STATUS_DONE
    plan.save(update_fields=["completed_batches", "status"])


def _redact_response_payload(payload: dict[str, JsonValue] | None) -> dict[str, JsonValue]:
    """00 §10.6: 只存摘要 + SHA-256, 不存未限长原文。"""
    if not payload:
        return {}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    summary: dict[str, JsonValue] = {"sha256": digest, "byte_length": len(raw.encode("utf-8"))}
    if "summary" in payload and isinstance(payload["summary"], dict):
        # 白名单: summary 计数类字段
        safe = {
            k: v
            for k, v in payload["summary"].items()
            if isinstance(v, int | float | str | bool) and len(str(k)) < 64
        }
        summary["summary"] = cast("JsonValue", safe)
    return summary


def _redact_error_text(text: str) -> str:
    return text[:512]



