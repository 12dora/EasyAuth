"""生命周期 Celery 任务(01 §7 beat + 既有禁号任务)。"""

from __future__ import annotations

import logging
import uuid
from typing import Final

from celery import shared_task
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from easyauth.accounts.models import UserMirror
from easyauth.audit.services import AuditRecord, AuditService
from easyauth.integrations.authentik.admin_client import (
    AuthentikAdminClient,
    AuthentikAdminError,
    AuthentikAdminNotConfiguredError,
    AuthentikAdminPaginationLimitError,
    AuthentikAdminUserNotFoundError,
)
from easyauth.lifecycle.escalation import escalate_overdue_task
from easyauth.lifecycle.errors import HandoverConflictError
from easyauth.lifecycle.handover import poll_async_action, takeover_expired_lease
from easyauth.lifecycle.models import (
    ACTION_STATUS_ASYNC_ATTENTION_REQUIRED,
    ACTION_STATUS_ASYNC_PENDING,
    HandoverAppAction,
    HandoverExecutionLease,
    HandoverTask,
    TASK_OPEN_STATUSES,
)
from easyauth.lifecycle.tasks import (
    DISABLE_ACCOUNT_TASK_NAME,
    RETRY_OFFBOARDING_TASK_NAME,
)

logger = logging.getLogger(__name__)

LIFECYCLE_ESCALATION_TASK: Final = "easyauth.lifecycle.escalation"
LIFECYCLE_DAILY_REMINDER_TASK: Final = "easyauth.lifecycle.daily_reminder"
LIFECYCLE_RECOVER_LEASES_TASK: Final = "easyauth.lifecycle.recover_expired_execution_leases"
LIFECYCLE_POLL_ASYNC_TASK: Final = "easyauth.lifecycle.poll_async_actions"


@shared_task(
    name=DISABLE_ACCOUNT_TASK_NAME,
    autoretry_for=(AuthentikAdminError,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=5,
    acks_late=True,
)
def disable_departed_account_task(user_mirror_id: int) -> str:
    """离职禁号 + 吊销会话(§1.2): 调 Authentik 标准 API, 失败指数退避重试。"""
    user = UserMirror.objects.filter(id=user_mirror_id).first()
    if user is None:
        return "user_missing"
    try:
        result = AuthentikAdminClient.from_settings().disable_user_and_revoke_sessions(
            user.authentik_user_id,
        )
    except AuthentikAdminNotConfiguredError:
        _record_disable_event(user, ok=False, detail="authentik_admin_not_configured")
        raise
    except AuthentikAdminPaginationLimitError:
        _record_disable_event(user, ok=False, detail="authentik_admin_pagination_limit")
        raise
    except AuthentikAdminUserNotFoundError:
        _record_disable_event(user, ok=False, detail="authentik_user_not_found")
        raise
    _record_disable_event(
        user,
        ok=True,
        detail=f"sessions_revoked={result.revoked_session_count}",
    )
    return "disabled"


@shared_task(
    name=RETRY_OFFBOARDING_TASK_NAME,
    autoretry_for=(HandoverConflictError,),
    retry_backoff=True,
    retry_backoff_max=3600,
    retry_jitter=True,
    max_retries=None,
    acks_late=True,
)
def retry_departed_offboarding_task(
    user_mirror_id: int,
    snapshot_grant_ids: list[int],
) -> str:
    """重试被单据 kind 冲突隔离的单个离职身份编排。"""
    from easyauth.lifecycle.offboarding import start_offboarding

    user = UserMirror.objects.filter(id=user_mirror_id).first()
    if user is None:
        return "user_missing"
    _ = start_offboarding(user, snapshot_grant_ids=tuple(snapshot_grant_ids))
    return "offboarding_started"


@shared_task(name=LIFECYCLE_ESCALATION_TASK)
def lifecycle_escalation_task() -> dict[str, int]:
    """beat 每 10 分钟: 扫到期交接单逐个 escalate。"""
    from django.db import connection

    now = timezone.now()
    qs = (
        HandoverTask.objects.filter(
            status__in=TASK_OPEN_STATUSES,
            escalation_deadline__isnull=False,
            escalation_deadline__lte=now,
        )
        .exclude(assignee_state="superuser_pool")
        .order_by("escalation_deadline", "id")
    )
    processed = 0
    errors = 0
    batch_ids = list(qs.values_list("id", flat=True)[:100])
    use_skip_locked = connection.features.has_select_for_update_skip_locked
    for task_id in batch_ids:
        try:
            with transaction.atomic():
                locked_qs = HandoverTask.objects.filter(pk=task_id)
                if use_skip_locked:
                    locked_qs = locked_qs.select_for_update(skip_locked=True)
                else:
                    locked_qs = locked_qs.select_for_update()
                task = locked_qs.first()
                if task is None:
                    continue
                _ = escalate_overdue_task(task)
                processed += 1
        except Exception:
            logger.exception("lifecycle_escalation failed task_id=%s", task_id)
            errors += 1
    return {"processed": processed, "errors": errors}


LIFECYCLE_SEND_REMINDER_TASK: Final = "easyauth.lifecycle.send_reminder"
LIFECYCLE_REMINDER_BATCH_SIZE: Final = 200


class LifecycleNotifyIdentityMissingError(RuntimeError):
    """生命周期通知身份尚未就绪，必须由 Celery 持续退避重试。"""


@shared_task(
    name=LIFECYCLE_SEND_REMINDER_TASK,
    autoretry_for=(LifecycleNotifyIdentityMissingError,),
    retry_backoff=True,
    retry_backoff_max=3600,
    retry_jitter=True,
    max_retries=None,
    acks_late=True,
)
def lifecycle_send_reminder_task(
    task_id: int,
    kind: str,
    assignee_user_id: str = "",
) -> str:
    """outbox 消费者: 发送交接提醒。

    notify 身份(easyauth-lifecycle) 尚未落地时: 记审计后抛错, 使 outbox 保持未发布
    并在身份就绪后重试(测试 eager 模式下 send_task 会传播异常)。
    """
    from easyauth.audit.services import AuditRecord, AuditService

    task = HandoverTask.objects.filter(pk=task_id).first()
    if task is None:
        return "task_missing"
    # 完整钉钉发送依赖 §7 easyauth-lifecycle 身份; 缺身份不得冒充成功消费 outbox。
    _ = AuditService.record(
        AuditRecord(
            actor_type="system",
            actor_id="lifecycle",
            action="lifecycle_reminder_identity_missing",
            target_type="handover_task",
            target_id=str(task_id),
            metadata={
                "kind": kind,
                "assignee_user_id": assignee_user_id,
                "notify_identity": "pending",
                "detail": "easyauth-lifecycle notify identity not provisioned; reminder not sent",
            },
        ),
    )
    logger.warning(
        "lifecycle reminder blocked (notify identity pending): task_id=%s kind=%s",
        task_id,
        kind,
    )
    message = (
        "easyauth-lifecycle notify identity not provisioned; "
        f"reminder deferred task_id={task_id} kind={kind}"
    )
    raise LifecycleNotifyIdentityMissingError(message)


@shared_task(name=LIFECYCLE_DAILY_REMINDER_TASK)
def lifecycle_daily_reminder_task() -> dict[str, int]:
    """beat 每天 09:00: 未完成且有 assignee 的单发提醒(网络副作用走 outbox)。"""
    from datetime import timedelta

    from easyauth.outbox.services import enqueue_task

    now = timezone.now()
    business_date = timezone.localdate()
    claimed = 0
    enqueued = 0
    while True:
        with transaction.atomic():
            eligible = (
                HandoverTask.objects.select_related("assignee", "subject_user")
                .filter(status__in=TASK_OPEN_STATUSES, assignee__isnull=False)
                .filter(Q(last_reminded_on__isnull=True) | Q(last_reminded_on__lt=business_date))
                .order_by("id")
            )
            if connection.features.has_select_for_update_skip_locked:
                eligible = eligible.select_for_update(skip_locked=True)
            else:
                eligible = eligible.select_for_update()
            tasks = list(eligible[:LIFECYCLE_REMINDER_BATCH_SIZE])
            if not tasks:
                break
            for task in tasks:
                updated = HandoverTask.objects.filter(pk=task.id).filter(
                    Q(last_reminded_on__isnull=True) | Q(last_reminded_on__lt=business_date),
                ).update(last_reminded_on=business_date)
                if updated != 1:
                    continue
                claimed += 1
                kinds: list[str] = ["daily"]
                if task.escalation_deadline is not None:
                    deadline_local = timezone.localtime(task.escalation_deadline).date()
                    if deadline_local <= business_date + timedelta(days=1):
                        kinds.append("deadline_soon")
                for kind in kinds:
                    dedup = f"handover:{task.id}:{business_date.isoformat()}:{kind}"
                    enqueue_task(
                        event_key=dedup,
                        task_name=LIFECYCLE_SEND_REMINDER_TASK,
                        args=[],
                        kwargs={
                            "task_id": task.id,
                            "kind": kind,
                            "assignee_user_id": task.assignee.authentik_user_id,
                        },
                    )
                    enqueued += 1
    return {"claimed": claimed, "enqueued": enqueued, "as_of": str(now)}


@shared_task(name=LIFECYCLE_RECOVER_LEASES_TASK)
def lifecycle_recover_expired_execution_leases_task() -> dict[str, int]:
    """beat 每 1 分钟: 过期租约先抢占后查证。"""
    now = timezone.now()
    expired = list(
        HandoverExecutionLease.objects.filter(
            released_at__isnull=True,
            lease_expires_at__lte=now,
        ).values_list("id", flat=True)[:50],
    )
    recovered = 0
    errors = 0
    worker_id = f"lease-recover:{uuid.uuid4().hex[:10]}"
    for lease_id in expired:
        try:
            lease = HandoverExecutionLease.objects.filter(pk=lease_id).first()
            if lease is None:
                continue
            _ = takeover_expired_lease(lease, owner=worker_id)
            recovered += 1
        except Exception:
            logger.exception("recover lease failed id=%s", lease_id)
            errors += 1
    return {"recovered": recovered, "errors": errors, "scanned": len(expired)}


@shared_task(name=LIFECYCLE_POLL_ASYNC_TASK)
def lifecycle_poll_async_actions_task() -> dict[str, int]:
    """beat 每 1 分钟: 扫 async_pending / async_attention_required 并 poll。

    async_attention_required 用 ASYNC_ATTENTION_POLL_INTERVAL_SECONDS(30 分钟) 退避。
    """
    from datetime import timedelta

    from easyauth.lifecycle.core import ASYNC_ATTENTION_POLL_INTERVAL_SECONDS

    now = timezone.now()
    attention_cutoff = now - timedelta(seconds=ASYNC_ATTENTION_POLL_INTERVAL_SECONDS)
    pending_ids = list(
        HandoverAppAction.objects.filter(
            status=ACTION_STATUS_ASYNC_PENDING,
        ).values_list("id", flat=True)[:50],
    )
    # renewed_at / updated_at 作为 last_polled 近似; 优先用租约 renewed_at
    attention_qs = HandoverAppAction.objects.filter(
        status=ACTION_STATUS_ASYNC_ATTENTION_REQUIRED,
    )
    attention_ids: list[int] = []
    for action in attention_qs.select_related("task")[:50]:
        lease = HandoverExecutionLease.objects.filter(
            subject_user_id=action.task.subject_user_id,
            app_id=action.app_id,
            released_at__isnull=True,
        ).first()
        last = None
        if lease is not None:
            last = getattr(lease, "renewed_at", None) or lease.lease_expires_at
        if last is None or last <= attention_cutoff:
            attention_ids.append(int(action.pk))

    action_ids = pending_ids + attention_ids
    polled = 0
    errors = 0
    skipped = 0
    worker_id = f"async-poll:{uuid.uuid4().hex[:10]}"
    for action_id in action_ids:
        try:
            action = HandoverAppAction.objects.select_related(
                "app",
                "task",
                "task__subject_user",
            ).get(pk=action_id)
            _ = poll_async_action(action, worker_id=worker_id)
            polled += 1
        except Exception:
            logger.exception("poll async failed action_id=%s", action_id)
            errors += 1
    # 因 30min 退避跳过的 attention 数量
    skipped = max(
        0,
        HandoverAppAction.objects.filter(
            status=ACTION_STATUS_ASYNC_ATTENTION_REQUIRED,
        ).count()
        - len(attention_ids),
    )
    return {
        "polled": polled,
        "errors": errors,
        "scanned": len(action_ids),
        "attention_skipped": skipped,
    }


def _record_disable_event(user: UserMirror, *, ok: bool, detail: str) -> None:
    _ = AuditService.record(
        AuditRecord(
            actor_type="system",
            actor_id="lifecycle",
            action="lifecycle_account_disabled" if ok else "lifecycle_account_disable_failed",
            target_type="user",
            target_id=user.authentik_user_id,
            metadata={"detail": detail},
        ),
    )
