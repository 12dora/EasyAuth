"""生命周期 Celery 任务(01 §7 beat + 既有禁号任务)。"""

from __future__ import annotations

import logging
import uuid
from typing import Final

from celery import shared_task
from django.db import transaction
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
from easyauth.lifecycle.handover import poll_async_action, takeover_expired_lease
from easyauth.lifecycle.models import (
    ACTION_STATUS_ASYNC_ATTENTION_REQUIRED,
    ACTION_STATUS_ASYNC_PENDING,
    HandoverAppAction,
    HandoverExecutionLease,
    HandoverTask,
    TASK_OPEN_STATUSES,
)
from easyauth.lifecycle.tasks import DISABLE_ACCOUNT_TASK_NAME

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


@shared_task(name=LIFECYCLE_ESCALATION_TASK)
def lifecycle_escalation_task() -> dict[str, int]:
    """beat 每 10 分钟: 扫到期交接单逐个 escalate。"""
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
    # SQLite 无 skip_locked; PG 下用 skip_locked
    batch_ids = list(qs.values_list("id", flat=True)[:100])
    for task_id in batch_ids:
        try:
            with transaction.atomic():
                task = (
                    HandoverTask.objects.select_for_update(skip_locked=True)
                    .filter(pk=task_id)
                    .first()
                )
                if task is None:
                    continue
                _ = escalate_overdue_task(task)
                processed += 1
        except Exception:
            logger.exception("lifecycle_escalation failed task_id=%s", task_id)
            errors += 1
    return {"processed": processed, "errors": errors}


@shared_task(name=LIFECYCLE_DAILY_REMINDER_TASK)
def lifecycle_daily_reminder_task() -> dict[str, int]:
    """beat 每天 09:00: 未完成且有 assignee 的单发提醒(网络副作用走 outbox)。"""
    from datetime import timedelta

    from easyauth.outbox.services import enqueue_task

    now = timezone.now()
    business_date = timezone.localdate()
    claimed = 0
    enqueued = 0
    qs = HandoverTask.objects.filter(
        status__in=TASK_OPEN_STATUSES,
        assignee__isnull=False,
    ).filter(Q(last_reminded_on__isnull=True) | Q(last_reminded_on__lt=business_date))
    for task_id in list(qs.values_list("id", flat=True)[:200]):
        with transaction.atomic():
            updated = HandoverTask.objects.filter(
                pk=task_id,
            ).filter(
                Q(last_reminded_on__isnull=True) | Q(last_reminded_on__lt=business_date),
            ).update(last_reminded_on=business_date)
            if updated != 1:
                continue
            claimed += 1
            task = HandoverTask.objects.select_related("assignee", "subject_user").get(
                pk=task_id,
            )
            kind = "daily"
            if task.escalation_deadline is not None:
                if task.escalation_deadline.date() <= business_date + timedelta(days=1):
                    kind = "deadline_soon"
            dedup = f"handover:{task.id}:{business_date.isoformat()}:{kind}"
            # 通知发送走 outbox 事件键; 实际 notify 身份若未配置则 dispatch 侧告警。
            try:
                enqueue_task(
                    event_key=dedup,
                    task_name="easyauth.lifecycle.send_reminder",
                    args=[],
                    kwargs={
                        "task_id": task.id,
                        "kind": kind,
                        "assignee_user_id": (
                            task.assignee.authentik_user_id if task.assignee else ""
                        ),
                    },
                )
                enqueued += 1
            except Exception:
                logger.exception("enqueue reminder failed task_id=%s", task_id)
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
    """beat 每 1 分钟: 扫 async_pending / async_attention_required 并 poll。"""
    action_ids = list(
        HandoverAppAction.objects.filter(
            status__in={
                ACTION_STATUS_ASYNC_PENDING,
                ACTION_STATUS_ASYNC_ATTENTION_REQUIRED,
            },
        ).values_list("id", flat=True)[:50],
    )
    polled = 0
    errors = 0
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
    return {"polled": polled, "errors": errors, "scanned": len(action_ids)}


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
