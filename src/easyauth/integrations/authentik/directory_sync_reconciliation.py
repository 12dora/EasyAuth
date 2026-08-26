from __future__ import annotations

from typing import TYPE_CHECKING, cast

from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from easyauth.accounts.models import (
    USER_STATUS_DEPARTED,
    DingTalkDepartmentMirror,
    DingTalkUserMirror,
    DingTalkUserOrgContext,
    UserMirror,
)
from easyauth.accounts.services import AuthentikSyncService
from easyauth.grants.models import (
    GRANT_STATUS_ACTIVE,
    AccessGrant,
    AccessGrantGroup,
    AccessGrantPermission,
)
from easyauth.integrations.authentik.directory_contract import directory_user_key
from easyauth.integrations.authentik.directory_sync_snapshot import (
    _directory_user_status,
    _string,
)
from easyauth.integrations.authentik.directory_sync_types import (
    _DirectorySnapshot,
    _StatusReconciliation,
)
from easyauth.lifecycle.errors import HandoverConflictError
from easyauth.lifecycle.offboarding import start_offboarding
from easyauth.lifecycle.tasks import RETRY_OFFBOARDING_TASK_NAME
from easyauth.outbox.services import enqueue_task

if TYPE_CHECKING:
    from easyauth.accounts.status import UserStatus

__all__ = [
    "_reconcile_missing_rows",
    "_reconcile_user_mirror_status",
]


def _reconcile_missing_rows(snapshot: _DirectorySnapshot) -> tuple[int, int]:
    corp_ids = _synced_corp_ids(snapshot)
    if not corp_ids:
        return (0, 0)

    seen_departments, seen_users = _collect_seen_keys(snapshot)
    pruned_departments = _prune_missing_departments(snapshot, corp_ids, seen_departments)
    tombstoned_users = _tombstone_missing_users(snapshot, corp_ids, seen_users)
    _delete_missing_org_context(snapshot, corp_ids, seen_users)
    return (pruned_departments, tombstoned_users)


def _collect_seen_keys(
    snapshot: _DirectorySnapshot,
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    seen_departments: dict[str, set[str]] = {}
    for item in snapshot.departments:
        corp_id = _string(item.get("corp_id"))
        seen_departments.setdefault(corp_id, set()).add(_string(item.get("dept_id")))
    seen_users: dict[str, set[str]] = {}
    for item in snapshot.users:
        corp_id, user_id = directory_user_key(item)
        seen_users.setdefault(corp_id, set()).add(user_id)
    return (seen_departments, seen_users)


def _prune_missing_departments(
    snapshot: _DirectorySnapshot,
    corp_ids: frozenset[str],
    seen_departments: dict[str, set[str]],
) -> int:
    # 按 corp 批量删除, 避免同步事务里逐行 DELETE 拉长锁持有时间。
    pruned_departments = 0
    for corp_id in sorted(corp_ids):
        queryset = DingTalkDepartmentMirror.objects.filter(
            source_slug=snapshot.source_slug,
            corp_id=corp_id,
        )
        seen_ids = seen_departments.get(corp_id, set())
        if seen_ids:
            queryset = queryset.exclude(dept_id__in=seen_ids)
        deleted_count, _deleted_per_model = queryset.delete()
        pruned_departments += deleted_count
    return pruned_departments


def _tombstone_missing_users(
    snapshot: _DirectorySnapshot,
    corp_ids: frozenset[str],
    seen_users: dict[str, set[str]],
) -> int:
    # 按 corp 取出需要 tombstone 的缺失用户, 一次 bulk_update 写回, 字段与原先 save() 一致。
    now = timezone.now()
    tombstoned_users = 0
    for corp_id in sorted(corp_ids):
        queryset = DingTalkUserMirror.objects.filter(
            source_slug=snapshot.source_slug,
            corp_id=corp_id,
        )
        seen_ids = seen_users.get(corp_id, set())
        if seen_ids:
            queryset = queryset.exclude(user_id__in=seen_ids)
        to_update = list(queryset.exclude(is_tombstone=True, status=USER_STATUS_DEPARTED))
        for user in to_update:
            user.status = USER_STATUS_DEPARTED
            user.is_tombstone = True
            user.departed_at = user.departed_at or now
            user.department_ids = []
            user.manager_userid = ""
            user.last_synced_at = now
        if to_update:
            _ = DingTalkUserMirror.objects.bulk_update(
                to_update,
                fields=[
                    "status",
                    "is_tombstone",
                    "departed_at",
                    "department_ids",
                    "manager_userid",
                    "last_synced_at",
                ],
            )
        tombstoned_users += len(to_update)
    return tombstoned_users


def _delete_missing_org_context(
    snapshot: _DirectorySnapshot,
    corp_ids: frozenset[str],
    seen_users: dict[str, set[str]],
) -> None:
    # 只删仍有用户镜像、但本轮快照已消失的组织上下文; 已 tombstone 的缺失用户同样清掉。
    for corp_id in sorted(corp_ids):
        missing_users = DingTalkUserMirror.objects.filter(
            source_slug=snapshot.source_slug,
            corp_id=corp_id,
        )
        seen_ids = seen_users.get(corp_id, set())
        if seen_ids:
            missing_users = missing_users.exclude(user_id__in=seen_ids)
        _ = DingTalkUserOrgContext.objects.filter(
            source_slug=snapshot.source_slug,
            corp_id=corp_id,
            user_id__in=missing_users.values("user_id"),
        ).delete()


def _reconcile_user_mirror_status(snapshot: _DirectorySnapshot) -> _StatusReconciliation:
    corp_ids = _synced_corp_ids(snapshot)
    if not corp_ids:
        return _empty_status_reconciliation()

    # 状态已在任何写入前完成契约校验, 这里仅把权威快照映射为本地域状态。
    status_by_key = _directory_status_by_user(snapshot)

    applied_count = 0
    departed_count = 0
    revoked_count = 0
    offboarding_deferred_count = 0
    bound_users = UserMirror.objects.filter(
        dingtalk_source_slug=snapshot.source_slug,
        dingtalk_corp_id__in=corp_ids,
    ).exclude(
        dingtalk_userid="",
    )
    for user in bound_users:
        reconciliation = _reconcile_bound_user(snapshot, user, status_by_key=status_by_key)
        applied_count += reconciliation.applied_count
        departed_count += reconciliation.departed_count
        revoked_count += reconciliation.revoked_count
        offboarding_deferred_count += reconciliation.offboarding_deferred_count

    return _StatusReconciliation(
        applied_count=applied_count,
        departed_count=departed_count,
        revoked_count=revoked_count,
        offboarding_deferred_count=offboarding_deferred_count,
    )


def _empty_status_reconciliation() -> _StatusReconciliation:
    return _StatusReconciliation(
        applied_count=0,
        departed_count=0,
        revoked_count=0,
        offboarding_deferred_count=0,
    )


def _directory_status_by_user(
    snapshot: _DirectorySnapshot,
) -> dict[tuple[str, str, str], UserStatus]:
    return {
        (snapshot.source_slug, *directory_user_key(payload)): _directory_user_status(payload)
        for payload in snapshot.users
    }


def _reconcile_bound_user(
    snapshot: _DirectorySnapshot,
    user: UserMirror,
    *,
    status_by_key: dict[tuple[str, str, str], UserStatus],
) -> _StatusReconciliation:
    key = (user.dingtalk_source_slug, user.dingtalk_corp_id, user.dingtalk_userid)
    # 目录里已经不存在的绑定用户按离职处理, 与上游硬删除口径一致。
    target_status = status_by_key.get(key, cast("UserStatus", USER_STATUS_DEPARTED))
    was_departed = user.status == USER_STATUS_DEPARTED
    grant_ids = (
        _active_grant_ids_for_departure(user)
        if (target_status == USER_STATUS_DEPARTED and not was_departed)
        else ()
    )
    result = AuthentikSyncService.apply_directory_status(user, target_status)
    departed = result.user.status == USER_STATUS_DEPARTED
    deferred = (
        departed and not was_departed and _start_user_offboarding(snapshot, result.user, grant_ids)
    )
    return _StatusReconciliation(
        applied_count=1,
        departed_count=int(departed),
        revoked_count=result.revoked_count,
        offboarding_deferred_count=int(deferred),
    )


def _active_grant_ids_for_departure(user: UserMirror) -> tuple[int, ...]:
    now = timezone.now()
    effective_groups = AccessGrantGroup.objects.filter(grant_id=OuterRef("pk")).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=now),
    )
    effective_permissions = AccessGrantPermission.objects.filter(grant_id=OuterRef("pk")).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=now),
    )
    return tuple(
        AccessGrant.objects.filter(
            user=user,
            is_current=True,
            status=GRANT_STATUS_ACTIVE,
        )
        .annotate(
            has_effective_group=Exists(effective_groups),
            has_effective_permission=Exists(effective_permissions),
        )
        .filter(Q(has_effective_group=True) | Q(has_effective_permission=True))
        .order_by("id")
        .values_list("id", flat=True),
    )


def _start_user_offboarding(
    snapshot: _DirectorySnapshot,
    user: UserMirror,
    grant_ids: tuple[int, ...],
) -> bool:
    # 首次检出离职: 撤权已由 apply_directory_status 完成,
    # 这里补齐生命周期立即项(自动建交接单+禁号+移出团队, §2.4)。
    try:
        # start_offboarding 自带 atomic(savepoint); 单个身份冲突不得污染外层同步事务。
        _ = start_offboarding(user, snapshot_grant_ids=grant_ids)
    except HandoverConflictError:
        user_pk = cast("int", user.pk)
        _ = enqueue_task(
            event_key=(
                f"lifecycle-retry-offboarding:{user_pk}:"
                f"{_writable_generation_for_user(snapshot, user)}"
            ),
            task_name=RETRY_OFFBOARDING_TASK_NAME,
            args=[user_pk, list(grant_ids)],
        )
        return True
    return False


def _writable_generation_for_user(snapshot: _DirectorySnapshot, user: UserMirror) -> int:
    return snapshot.contracts[user.dingtalk_corp_id].generation


def _synced_corp_ids(snapshot: _DirectorySnapshot) -> frozenset[str]:
    # corp 权威范围来自已验证的 success status, 而不是用户行。这样 users=0 的合法
    # 权威快照仍会清理最后一名员工; 缺失/畸形 status 已在任何写入前失败。
    return frozenset(snapshot.contracts)
