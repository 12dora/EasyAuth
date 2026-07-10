from __future__ import annotations

from typing import TYPE_CHECKING, Final

from django.db import transaction

from easyauth.connectors.models import SYNC_TRIGGER_EVENT, ConnectorInstance
from easyauth.connectors.services import mark_reconcile_dirty
from easyauth.outbox.services import enqueue_task

if TYPE_CHECKING:
    from easyauth.accounts.models import UserMirror
    from easyauth.grants.models import AccessGrant

RECONCILE_TASK_NAME: Final = "easyauth.connectors.reconcile_instance"
OFFBOARD_TASK_NAME: Final = "easyauth.connectors.offboard_user"

RECONCILE_COALESCE_SECONDS: Final = 5


def notify_grant_mutation(grant: AccessGrant) -> None:
    """GrantService 事务内的唯一挂点(F2): 授权事实与分发事件一同提交。"""
    app_id = grant.app_id
    user_id = grant.user.authentik_user_id
    dispatch_grant_event(app_id=app_id, user_id=user_id, action="grant_mutated")


def dispatch_grant_event(*, app_id: int, user_id: str, action: str) -> None:
    # user_id/action 仅供观测; 对账是全量幂等的, 不依赖事件载荷。
    _ = (user_id, action)
    for instance in ConnectorInstance.objects.filter(app_id=app_id, enabled=True).only("id"):
        _ = request_instance_reconcile(instance.id, trigger=SYNC_TRIGGER_EVENT)


def request_instance_reconcile(
    instance_id: int,
    *,
    trigger: str,
    countdown: int = RECONCILE_COALESCE_SECONDS,
) -> bool:
    """持久推进 generation, 并在没有活跃 worker 时投递唯一任务。"""
    with transaction.atomic():
        if not mark_reconcile_dirty(instance_id, trigger=trigger):
            return False
        instance = ConnectorInstance.objects.only("reconcile_generation").get(id=instance_id)
        _ = enqueue_task(
            event_key=f"connector-reconcile:{instance_id}:{instance.reconcile_generation}",
            task_name=RECONCILE_TASK_NAME,
            args=[instance_id],
            countdown=countdown,
        )
    return True


def dispatch_user_offboarded(user: UserMirror) -> None:
    """离职快路径(方案 §3.5): 与离职事实同事务持久化异步任务。"""
    user_id = user.authentik_user_id
    if not ConnectorInstance.objects.filter(enabled=True).exists():
        return
    _ = enqueue_task(
        event_key=f"connector-offboard:{user.id}:{user.updated_at.isoformat()}",
        task_name=OFFBOARD_TASK_NAME,
        args=[user_id],
    )
