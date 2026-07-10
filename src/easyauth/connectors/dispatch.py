from __future__ import annotations

from typing import TYPE_CHECKING, Final

from celery import current_app
from django.core.cache import cache
from django.db import transaction

from easyauth.connectors.models import SYNC_TRIGGER_EVENT, ConnectorInstance

if TYPE_CHECKING:
    from easyauth.accounts.models import UserMirror
    from easyauth.grants.models import AccessGrant

RECONCILE_TASK_NAME: Final = "easyauth.connectors.reconcile_instance"
OFFBOARD_TASK_NAME: Final = "easyauth.connectors.offboard_user"

# 事件风暴合并(复用钉钉 Stream 的合流模式): 去抖窗口内的多次 grant 变更只排一次
# 对账; 任务开始执行时先清除标记, 之后到达的事件会再次排队, 保证任何事件都被其后
# 的一次完整对账覆盖。丢失事件不影响最终一致(周期对账兜底, 方案 §2 原则 2)。
RECONCILE_PENDING_CACHE_KEY_TEMPLATE: Final = "easyauth:connectors:reconcile-pending:{instance_id}"
RECONCILE_COALESCE_SECONDS: Final = 5
# pending 标记必须有限期: 若任务在执行前丢失(broker 故障), 标记过期后事件恢复排队。
RECONCILE_PENDING_TTL_SECONDS: Final = 600


def reconcile_pending_cache_key(instance_id: int) -> str:
    return RECONCILE_PENDING_CACHE_KEY_TEMPLATE.format(instance_id=instance_id)


def notify_grant_mutation(grant: AccessGrant) -> None:
    """GrantService 事务内的唯一挂点(F2): 提交成功后才分发, 失败不阻塞授权事务。"""
    app_id = grant.app_id
    user_id = grant.user.authentik_user_id
    transaction.on_commit(
        lambda: dispatch_grant_event(app_id=app_id, user_id=user_id, action="grant_mutated"),
    )


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
    """请求一次防抖合并的实例对账; 返回是否真正排队了新任务。"""
    if not cache.add(
        reconcile_pending_cache_key(instance_id),
        "1",
        timeout=RECONCILE_PENDING_TTL_SECONDS,
    ):
        return False
    _ = current_app.send_task(
        RECONCILE_TASK_NAME,
        args=[instance_id, trigger],
        countdown=countdown,
    )
    return True


def dispatch_user_offboarded(user: UserMirror) -> None:
    """离职快路径(方案 §3.5): 事务提交后对全部启用实例异步执行 on_user_offboarded。"""
    user_id = user.authentik_user_id
    transaction.on_commit(
        lambda: _send_offboard_task(user_id),
    )


def _send_offboard_task(user_id: str) -> None:
    if not ConnectorInstance.objects.filter(enabled=True).exists():
        return
    _ = current_app.send_task(OFFBOARD_TASK_NAME, args=[user_id])
