"""交接执行租约: 取号 / 续约 / 抢占 / CAS(01 §2.4.2)。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from django.db import connection, transaction
from django.db.utils import IntegrityError
from django.utils import timezone

from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App
from easyauth.lifecycle.errors import HandoverConflictError
from easyauth.lifecycle.models import (
    ASSIGNMENT_MUTATION_IN_FLIGHT_STATUSES,
    BATCH_IN_FLIGHT_STATUSES,
    LEASE_TTL,
    HandoverAppAction,
    HandoverExecutionBatch,
    HandoverExecutionLease,
    HandoverLeaseFence,
)

if TYPE_CHECKING:
    from datetime import datetime

HANDOVER_EXECUTION_IN_FLIGHT: Final = "handover_execution_in_flight"
LEASE_CAS_FAILED_MESSAGE: Final = "执行租约 CAS 失败, 丢弃本次写回。"


@dataclass(frozen=True, slots=True)
class LeaseHandle:
    lease_id: int
    owner: str
    fence: int
    expires_at: datetime


def allocate_fence(*, subject_user: UserMirror, app: App) -> int:
    """原子取新 fence。首行由本语句创建, 禁止 get_or_create + UPDATE。"""
    subject_pk = int(subject_user.pk)  # type: ignore[arg-type]
    app_pk = int(app.pk)  # type: ignore[arg-type]
    vendor = connection.vendor
    with connection.cursor() as cursor:
        if vendor == "postgresql":
            cursor.execute(
                """
                INSERT INTO lifecycle_handoverleasefence
                    (subject_user_id, app_id, next_fence)
                VALUES (%s, %s, 2)
                ON CONFLICT (subject_user_id, app_id)
                DO UPDATE SET next_fence = lifecycle_handoverleasefence.next_fence + 1
                RETURNING next_fence - 1
                """,
                [subject_pk, app_pk],
            )
            row = cursor.fetchone()
            if row is None:
                message = "fence 取号失败。"
                raise HandoverConflictError(message)
            return int(row[0])
        # SQLite 回退: 事务内锁行手写。生产互斥以 PG 条件唯一约束为准。
        fence_row = (
            HandoverLeaseFence.objects.select_for_update()
            .filter(subject_user_id=subject_pk, app_id=app_pk)
            .first()
        )
        if fence_row is None:
            try:
                with transaction.atomic():
                    fence_row = HandoverLeaseFence.objects.create(
                        subject_user_id=subject_pk,
                        app_id=app_pk,
                        next_fence=2,
                    )
            except IntegrityError:
                fence_row = (
                    HandoverLeaseFence.objects.select_for_update()
                    .filter(subject_user_id=subject_pk, app_id=app_pk)
                    .get()
                )
            else:
                return 1
        fence = int(fence_row.next_fence)
        fence_row.next_fence = fence + 1
        fence_row.save(update_fields=["next_fence"])
        return fence


def take_lease(
    *,
    action: HandoverAppAction,
    owner: str,
    batch_seq: int,
    generation: int | None = None,
) -> LeaseHandle:
    """Execute 入口事务内取租约。条件唯一冲突 → 409 handover_execution_in_flight。"""
    subject = action.task.subject_user
    app = action.app
    gen = generation if generation is not None else action.generation
    fence = allocate_fence(subject_user=subject, app=app)
    now = timezone.now()
    expires = now + LEASE_TTL
    try:
        lease = HandoverExecutionLease.objects.create(
            subject_user=subject,
            app=app,
            action=action,
            generation=gen,
            batch_seq=batch_seq,
            owner=owner,
            fence=fence,
            lease_expires_at=expires,
        )
    except IntegrityError as exc:
        raise HandoverConflictError(HANDOVER_EXECUTION_IN_FLIGHT) from exc
    return LeaseHandle(
        lease_id=int(lease.pk),  # type: ignore[arg-type]
        owner=owner,
        fence=fence,
        expires_at=expires,
    )


def renew_lease(handle: LeaseHandle) -> bool:
    """续约: owner+fence+未释放+未过期。已过期 owner 不许复活。谓词用 db_now()。"""
    now = timezone.now()
    expires = now + LEASE_TTL
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE lifecycle_handoverexecutionlease
                SET lease_expires_at = NOW() + (%s * INTERVAL '1 second'),
                    renewed_at = NOW()
                WHERE id = %s
                  AND owner = %s
                  AND fence = %s
                  AND released_at IS NULL
                  AND lease_expires_at > NOW()
                """,
                [LEASE_TTL.total_seconds(), handle.lease_id, handle.owner, handle.fence],
            )
            return cursor.rowcount == 1
    updated = HandoverExecutionLease.objects.filter(
        pk=handle.lease_id,
        owner=handle.owner,
        fence=handle.fence,
        released_at__isnull=True,
        lease_expires_at__gt=now,
    ).update(lease_expires_at=expires, renewed_at=now)
    return updated == 1


def cas_release(handle: LeaseHandle) -> bool:
    """同一次 fence CAS 释放租约。影响行数不为 1 → 调用方丢弃写回。"""
    now = timezone.now()
    updated = HandoverExecutionLease.objects.filter(
        pk=handle.lease_id,
        owner=handle.owner,
        fence=handle.fence,
        released_at__isnull=True,
    ).update(released_at=now)
    return updated == 1


def cas_update_owner(
    handle: LeaseHandle,
    *,
    new_owner: str,
    renew: bool = True,
) -> LeaseHandle | None:
    """CAS 改 owner 并递增 fence(sentinel 移交 / claim)。"""
    subject_user_id = (
        HandoverExecutionLease.objects.filter(pk=handle.lease_id)
        .values_list("subject_user_id", flat=True)
        .first()
    )
    app_id = (
        HandoverExecutionLease.objects.filter(pk=handle.lease_id)
        .values_list("app_id", flat=True)
        .first()
    )
    if subject_user_id is None or app_id is None:
        return None
    # 取新 fence 与 CAS 必须同事务; 调用方应已在 atomic 内。
    subject = UserMirror.objects.get(pk=subject_user_id)
    app = App.objects.get(pk=app_id)
    new_fence = allocate_fence(subject_user=subject, app=app)
    now = timezone.now()
    expires = now + LEASE_TTL
    updates: dict[str, object] = {
        "owner": new_owner,
        "fence": new_fence,
        "renewed_at": now,
    }
    if renew:
        updates["lease_expires_at"] = expires
    updated = HandoverExecutionLease.objects.filter(
        pk=handle.lease_id,
        owner=handle.owner,
        fence=handle.fence,
        released_at__isnull=True,
    ).update(**updates)
    if updated != 1:
        return None
    return LeaseHandle(
        lease_id=handle.lease_id,
        owner=new_owner,
        fence=new_fence,
        expires_at=expires if renew else handle.expires_at,
    )


def preempt_expired_lease(
    lease: HandoverExecutionLease,
    *,
    new_owner: str,
) -> LeaseHandle | None:
    """先抢占后查证: 过期 active 行, 写新 owner/fence/续期。谓词用 db_now()。"""
    if lease.released_at is not None:
        return None
    new_fence = allocate_fence(subject_user=lease.subject_user, app=lease.app)
    now = timezone.now()
    expires = now + LEASE_TTL
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE lifecycle_handoverexecutionlease
                SET owner = %s,
                    fence = %s,
                    renewed_at = NOW(),
                    lease_expires_at = NOW() + (%s * INTERVAL '1 second')
                WHERE id = %s
                  AND owner = %s
                  AND fence = %s
                  AND released_at IS NULL
                  AND lease_expires_at <= NOW()
                """,
                [
                    new_owner,
                    new_fence,
                    LEASE_TTL.total_seconds(),
                    lease.pk,
                    lease.owner,
                    lease.fence,
                ],
            )
            if cursor.rowcount != 1:
                return None
        refreshed = HandoverExecutionLease.objects.get(pk=lease.pk)
        return LeaseHandle(
            lease_id=int(lease.pk),  # type: ignore[arg-type]
            owner=new_owner,
            fence=new_fence,
            expires_at=refreshed.lease_expires_at,
        )
    if lease.lease_expires_at > now:
        return None
    updated = HandoverExecutionLease.objects.filter(
        pk=lease.pk,
        owner=lease.owner,
        fence=lease.fence,
        released_at__isnull=True,
        lease_expires_at__lte=now,
    ).update(
        owner=new_owner,
        fence=new_fence,
        renewed_at=now,
        lease_expires_at=expires,
    )
    if updated != 1:
        return None
    return LeaseHandle(
        lease_id=int(lease.pk),  # type: ignore[arg-type]
        owner=new_owner,
        fence=new_fence,
        expires_at=expires,
    )


def has_active_lease(*, subject_user_id: int, app_id: int) -> bool:
    return HandoverExecutionLease.objects.filter(
        subject_user_id=subject_user_id,
        app_id=app_id,
        released_at__isnull=True,
    ).exists()


def action_execution_in_flight(action: HandoverAppAction) -> bool:
    """§5.5.1 skip/cancel: 未释放租约或在途 batch(executing/async_pending)。"""
    if has_active_lease(
        subject_user_id=int(action.task.subject_user_id),  # type: ignore[arg-type]
        app_id=int(action.app_id),  # type: ignore[arg-type]
    ):
        return True
    return HandoverExecutionBatch.objects.filter(
        action_id=action.id,
        generation=action.generation,
        status__in=BATCH_IN_FLIGHT_STATUSES,
    ).exists()


def assignment_mutation_in_flight(action: HandoverAppAction) -> bool:
    """§2.4.1.1 改分配三端点: 含 pending batch(429 重排队中)。"""
    if has_active_lease(
        subject_user_id=int(action.task.subject_user_id),  # type: ignore[arg-type]
        app_id=int(action.app_id),  # type: ignore[arg-type]
    ):
        return True
    return HandoverExecutionBatch.objects.filter(
        action_id=action.id,
        generation=action.generation,
        status__in=ASSIGNMENT_MUTATION_IN_FLIGHT_STATUSES,
    ).exists()


def require_cas(handle: LeaseHandle) -> HandoverExecutionLease:
    """持有租约行锁到本阶段提交; 不匹配则抛冲突(调用方必须丢弃写回)。"""
    lease = (
        HandoverExecutionLease.objects.select_for_update()
        .filter(
            pk=handle.lease_id,
            owner=handle.owner,
            fence=handle.fence,
            released_at__isnull=True,
        )
        .first()
    )
    if lease is None:
        raise HandoverConflictError(LEASE_CAS_FAILED_MESSAGE)
    return lease


def must_cas_release(handle: LeaseHandle) -> None:
    """CAS 释放失败即冲突 — 调用方不得再依赖已写状态。"""
    if not cas_release(handle):
        raise HandoverConflictError(HANDOVER_EXECUTION_IN_FLIGHT)
