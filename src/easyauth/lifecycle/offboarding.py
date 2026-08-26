"""离职立即项编排; 建单入口再导出自 handover_creation。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from django.db import transaction

from easyauth.lifecycle.core import LIFECYCLE_ACTOR_ID, record_task_event
from easyauth.lifecycle.handover_creation import (
    HandoverCreationSpec,
    _create_task_with_idempotency_constraint,  # pyright: ignore[reportPrivateUsage]
    ensure_handover_task,
    upgrade_pre_offboard_to_offboard,
)
from easyauth.lifecycle.models import HANDOVER_KIND_OFFBOARD, HandoverTask
from easyauth.lifecycle.tasks import DISABLE_ACCOUNT_TASK_NAME
from easyauth.outbox.services import enqueue_task
from easyauth.teams.models import TeamMember

if TYPE_CHECKING:
    from easyauth.accounts.models import UserMirror

__all__ = [
    "HandoverCreationSpec",
    "OffboardingStartResult",
    "_create_task_with_idempotency_constraint",
    "ensure_handover_task",
    "start_offboarding",
    "upgrade_pre_offboard_to_offboard",
]


@dataclass(frozen=True, slots=True)
class OffboardingStartResult:
    task: HandoverTask
    created: bool
    removed_membership_count: int


def start_offboarding(
    subject: UserMirror,
    *,
    created_by: str = "directory_sync",
    snapshot_grant_ids: tuple[int, ...] | None = None,
) -> OffboardingStartResult:
    """离职立即项(§2.2 铁律一): 建单 + 禁号入列 + 移出所有团队; 数据交接进入缓冲。

    调用方须保证授权撤销已由既有离职回收完成(apply_directory_status)。
    open pre_offboard → 升级(ensure_handover_task 内)。
    """
    with transaction.atomic():
        task, created = ensure_handover_task(
            subject=subject,
            kind=HANDOVER_KIND_OFFBOARD,
            created_by=created_by,
            spec=HandoverCreationSpec(
                reason="目录同步检出离职" if created_by == "directory_sync" else "",
                snapshot_grant_ids=snapshot_grant_ids,
            ),
        )
        removed = _remove_team_memberships(subject, task)
        _schedule_account_disable(subject, task=task)
    return OffboardingStartResult(
        task=task,
        created=created,
        removed_membership_count=removed,
    )


def _remove_team_memberships(subject: UserMirror, task: HandoverTask) -> int:
    removed, _detail = TeamMember.objects.filter(user=subject).delete()
    if removed:
        record_task_event(
            task,
            action="handover_memberships_removed",
            actor_id=LIFECYCLE_ACTOR_ID,
            extra={"removed_count": removed},
        )
    return removed


def _schedule_account_disable(subject: UserMirror, *, task: HandoverTask) -> None:
    # Authentik 禁号/吊销会话走 Celery(可重试), 不阻塞目录同步事务。
    user_pk = cast("int", subject.pk)
    _ = enqueue_task(
        event_key=f"lifecycle-disable-account:{task.id}",
        task_name=DISABLE_ACCOUNT_TASK_NAME,
        args=[user_pk],
    )
