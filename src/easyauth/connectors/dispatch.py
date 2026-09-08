from __future__ import annotations

from typing import TYPE_CHECKING, Final

from django.db import transaction

from easyauth.connectors.models import SYNC_TRIGGER_EVENT, ConnectorInstance
from easyauth.connectors.services import mark_reconcile_dirty
from easyauth.grants.models import GRANT_STATUS_EXPIRED
from easyauth.outbox.services import enqueue_task
from easyauth.webhooks.events import emit_grant_changed

if TYPE_CHECKING:
    from easyauth.accounts.models import UserMirror
    from easyauth.grants.models import AccessGrant

RECONCILE_TASK_NAME: Final = "easyauth.connectors.reconcile_instance"
OFFBOARD_TASK_NAME: Final = "easyauth.connectors.offboard_user"

RECONCILE_COALESCE_SECONDS: Final = 5


def notify_grant_mutation(grant: AccessGrant, *, urgent: bool = False) -> None:
    """GrantService 事务内的唯一挂点(F2): 授权事实与分发事件一同提交。"""
    if getattr(grant, "connector_dispatch_emitted", False):
        return
    grant.connector_dispatch_emitted = True
    app_id = grant.app_id
    user_id = grant.user.authentik_user_id
    dispatch_grant_event(
        app_id=app_id,
        user_id=user_id,
        action="grant_mutated",
        urgent=urgent
        or bool(getattr(grant, "connector_dispatch_urgent", False))
        or grant.status == GRANT_STATUS_EXPIRED,
    )
    emit_grant_changed(grant)


def notify_grant_expired(grant: AccessGrant) -> None:
    """过期清理路径: 部分过期时 status 仍为 active, 仍立即对账撤权。"""
    grant.connector_dispatch_urgent = True
    notify_grant_mutation(grant, urgent=True)


def dispatch_grant_event(
    *,
    app_id: int,
    user_id: str,
    action: str,
    urgent: bool = False,
) -> None:
    # user_id/action 仅供观测; 对账是全量幂等的, 不依赖事件载荷。
    _ = (user_id, action)
    for instance in ConnectorInstance.objects.filter(app_id=app_id, enabled=True).only("id"):
        _ = request_instance_reconcile(
            instance.id,
            trigger=SYNC_TRIGGER_EVENT,
            urgent=urgent,
        )


def request_instance_reconcile(
    instance_id: int,
    *,
    trigger: str,
    countdown: int = RECONCILE_COALESCE_SECONDS,
    urgent: bool = False,
) -> bool:
    """持久推进 generation, 并在没有活跃 worker 时投递唯一任务。"""
    delay = 0 if urgent else countdown
    with transaction.atomic():
        if not mark_reconcile_dirty(instance_id, trigger=trigger):
            return False
        instance = ConnectorInstance.objects.only("reconcile_generation").get(id=instance_id)
        _ = enqueue_task(
            event_key=f"connector-reconcile:{instance_id}:{instance.reconcile_generation}",
            task_name=RECONCILE_TASK_NAME,
            args=[instance_id],
            countdown=delay,
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
