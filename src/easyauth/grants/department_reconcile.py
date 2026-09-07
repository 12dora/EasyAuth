from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, cast, final

from django.db import transaction
from django.db.models import Prefetch, Q
from django.utils import timezone

from easyauth.accounts.department_tree import DepartmentTree
from easyauth.accounts.models import DingTalkUserMirror, UserMirror
from easyauth.grants.inputs import AuthorizationGroupGrantInput, ScopedDirectGrantInput
from easyauth.grants.models import (
    GRANT_STATUS_ACTIVE,
    GRANT_STATUS_REVOKED,
    MEMBERSHIP_SOURCE_DEPARTMENT,
    AccessGrant,
    AccessGrantGroup,
    AccessGrantPermission,
    DepartmentGrantPolicy,
    DepartmentGrantPolicyGroup,
    DepartmentGrantPolicyPermission,
)
from easyauth.grants.operations import department_input_state, department_membership_state
from easyauth.grants.services import GrantService
from easyauth.outbox.services import enqueue_task

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime

    from easyauth.applications.models import App
    from easyauth.grants.operations import DepartmentMembershipState

# 部门预授权对账任务, 由目录同步完成、策略增删改与 beat 定时触发。
DEPARTMENT_GRANT_RECONCILE_TASK_NAME = "easyauth.grants.reconcile_department_grants"
_ENQUEUE_COUNTDOWN_SECONDS = 2

__all__ = [
    "DEPARTMENT_GRANT_RECONCILE_TASK_NAME",
    "DepartmentGrantReconcileError",
    "DepartmentGrantReconcileResult",
    "reconcile_department_grants",
    "schedule_department_grant_reconcile",
]


def schedule_department_grant_reconcile(*, trigger: str) -> None:
    """在当前事务提交后经 outbox 幂等入队一次全量对账。

    event_key 按 (trigger, 秒) 归并: 同一秒内的重复调用只保留一条; countdown 大于归并窗口,
    因此归并到的事件一定尚未派发, 不会漏掉窗口末尾的变更。
    """
    bucket = int(timezone.now().timestamp())
    event_key = f"department-grant-reconcile:{trigger}:{bucket}"

    def _enqueue() -> None:
        _ = enqueue_task(
            event_key=event_key,
            task_name=DEPARTMENT_GRANT_RECONCILE_TASK_NAME,
            countdown=_ENQUEUE_COUNTDOWN_SECONDS,
        )

    transaction.on_commit(_enqueue)


@dataclass(frozen=True, slots=True)
class DepartmentGrantReconcileResult:
    users_considered: int
    grants_created: int
    grants_changed: int
    grants_revoked: int
    unchanged: int


@final
class DepartmentGrantReconcileError(RuntimeError):
    """批次已处理完毕; 成功项已提交, 失败项及统计随异常返回。"""

    def __init__(self, result: DepartmentGrantReconcileResult, failures: list[Exception]) -> None:
        self.result = result
        self.failures = tuple(failures)
        super().__init__(
            f"department grant reconciliation failed for {len(failures)} pairs; {result}"
        )


@dataclass(frozen=True, slots=True)
class _Policy:
    model: DepartmentGrantPolicy
    groups: tuple[AuthorizationGroupGrantInput, ...]
    permissions: tuple[ScopedDirectGrantInput, ...]


@dataclass(frozen=True, slots=True)
class _Desired:
    groups: tuple[AuthorizationGroupGrantInput, ...] = ()
    permissions: tuple[ScopedDirectGrantInput, ...] = ()


class _PolicyPrefetch(Protocol):
    loaded_groups: list[DepartmentGrantPolicyGroup]
    loaded_permissions: list[DepartmentGrantPolicyPermission]


class _GrantPrefetch(Protocol):
    loaded_groups: list[AccessGrantGroup]
    loaded_permissions: list[AccessGrantPermission]


def _load_policies() -> list[_Policy]:
    policies = (
        DepartmentGrantPolicy.objects.select_related("app")
        .prefetch_related(
            Prefetch(
                "policy_groups",
                queryset=DepartmentGrantPolicyGroup.objects.select_related("authorization_group"),
                to_attr="loaded_groups",
            ),
            Prefetch(
                "policy_permissions",
                queryset=DepartmentGrantPolicyPermission.objects.select_related("permission"),
                to_attr="loaded_permissions",
            ),
        )
        .order_by("id")
    )
    return [
        _Policy(
            model=policy,
            groups=tuple(
                AuthorizationGroupGrantInput(
                    row.authorization_group,
                    policy.expires_at,
                    source=MEMBERSHIP_SOURCE_DEPARTMENT,
                    department_policy_id=policy.id,
                )
                for row in cast("_PolicyPrefetch", cast("object", policy)).loaded_groups
            ),
            permissions=tuple(
                ScopedDirectGrantInput(
                    row.permission,
                    row.scope_key,
                    policy.expires_at,
                    source=MEMBERSHIP_SOURCE_DEPARTMENT,
                    department_policy_id=policy.id,
                )
                for row in cast("_PolicyPrefetch", cast("object", policy)).loaded_permissions
            ),
        )
        for policy in policies
    ]


def _directory_users(
    corps: set[tuple[str, str]],
) -> tuple[dict[int, UserMirror], dict[int, DingTalkUserMirror]]:
    if not corps:
        return {}, {}
    user_filter = Q(pk__in=[])
    mirror_filter = Q(pk__in=[])
    for source, corp in sorted(corps):
        user_filter |= Q(dingtalk_source_slug=source, dingtalk_corp_id=corp)
        mirror_filter |= Q(source_slug=source, corp_id=corp)
    mirrors = {
        (row.source_slug, row.corp_id, row.user_id): row
        for row in DingTalkUserMirror.objects.filter(
            mirror_filter, status="active", is_tombstone=False
        )
    }
    users: dict[int, UserMirror] = {}
    bindings: dict[int, DingTalkUserMirror] = {}
    for user in UserMirror.objects.filter(user_filter, status="active"):
        mirror = mirrors.get(
            (user.dingtalk_source_slug, user.dingtalk_corp_id, user.dingtalk_userid)
        )
        if mirror is not None:
            users[user.id] = user
            bindings[user.id] = mirror
    return users, bindings


def _longer(left: datetime | None, right: datetime | None) -> bool:
    # 相同期限保留先遇到的策略; 策略按 id 升序加载, 归因稳定。
    return left is not None and (right is None or right > left)


def _desired_memberships(policies: Iterable[_Policy]) -> _Desired:
    groups: dict[int, AuthorizationGroupGrantInput] = {}
    permissions: dict[tuple[int, str], ScopedDirectGrantInput] = {}
    for policy in policies:
        for group in policy.groups:
            existing = groups.get(group.authorization_group.id)
            if existing is None or _longer(existing.expires_at, group.expires_at):
                groups[group.authorization_group.id] = group
        for permission in policy.permissions:
            identity = (permission.permission.id, permission.scope_key)
            previous = permissions.get(identity)
            if previous is None or _longer(previous.expires_at, permission.expires_at):
                permissions[identity] = permission
    return _Desired(tuple(groups.values()), tuple(permissions.values()))


def _load_current_grants(user_ids: Iterable[int]) -> dict[tuple[int, int], AccessGrant]:
    return {
        (grant.user_id, grant.app_id): grant
        for grant in AccessGrant.objects.filter(
            Q(user_id__in=user_ids)
            | Q(grant_groups__source=MEMBERSHIP_SOURCE_DEPARTMENT)
            | Q(grant_permissions__source=MEMBERSHIP_SOURCE_DEPARTMENT),
            is_current=True,
            status=GRANT_STATUS_ACTIVE,
        )
        .select_related("user", "app")
        .prefetch_related(
            Prefetch("grant_groups", to_attr="loaded_groups"),
            Prefetch("grant_permissions", to_attr="loaded_permissions"),
        )
        .distinct()
    }


def _current_state(grant: AccessGrant | None) -> DepartmentMembershipState:
    if grant is None:
        return frozenset(), frozenset()
    return department_membership_state(
        cast("_GrantPrefetch", cast("object", grant)).loaded_groups,
        cast("_GrantPrefetch", cast("object", grant)).loaded_permissions,
    )


def reconcile_department_grants(*, now: datetime | None = None) -> DepartmentGrantReconcileResult:
    cutoff = timezone.now() if now is None else now
    policies = _load_policies()
    corps = {(policy.model.source_slug, policy.model.corp_id) for policy in policies}
    trees = {key: DepartmentTree.load(source_slug=key[0], corp_id=key[1]) for key in sorted(corps)}
    # 写入前验证所有部门, 包括没有在职员工引用的孤立环; 数据损坏不能部分成功。
    for tree in trees.values():
        for dept_id in tree.nodes:
            _ = tree.ancestors_or_self(dept_id)
    users, bindings = _directory_users(corps)
    current = _load_current_grants(users)
    desired, apps = _desired_by_pair(policies, users, bindings, trees, cutoff)
    for pair, grant in current.items():
        state = _current_state(grant)
        if state[0] or state[1]:
            _ = desired.setdefault(pair, _Desired())
            _ = users.setdefault(grant.user_id, grant.user)
            _ = apps.setdefault(grant.app_id, grant.app)
    return _sync_pairs(users, apps, current, desired)


def _sync_pairs(
    users: dict[int, UserMirror],
    apps: dict[int, App],
    current: dict[tuple[int, int], AccessGrant],
    desired: dict[tuple[int, int], _Desired],
) -> DepartmentGrantReconcileResult:
    counts = {"grants_created": 0, "grants_changed": 0, "grants_revoked": 0, "unchanged": 0}
    failures: list[Exception] = []
    for pair, memberships in sorted(desired.items()):
        grant = current.get(pair)
        if _current_state(grant) == department_input_state(
            memberships.groups, memberships.permissions
        ):
            counts["unchanged"] += 1
            continue
        try:
            # 每个人/应用独立提交; 某项失败不回滚其他员工, 批次最后显式抛错。
            with transaction.atomic():
                result = GrantService.sync_department_memberships(
                    user=users[pair[0]],
                    app=apps[pair[1]],
                    authorization_groups=memberships.groups,
                    direct_grants=memberships.permissions,
                )
        except Exception as exc:  # noqa: BLE001 - 汇总失败后重新抛出, 不降级为成功。
            exc.add_note(f"user_id={pair[0]}, app_id={pair[1]}")
            failures.append(exc)
        else:
            if result is None or (grant is not None and result.version == grant.version):
                counts["unchanged"] += 1
            elif result.status == GRANT_STATUS_REVOKED:
                counts["grants_revoked"] += 1
            elif grant is None:
                counts["grants_created"] += 1
            else:
                counts["grants_changed"] += 1
    summary = DepartmentGrantReconcileResult(users_considered=len(users), **counts)
    if failures:
        raise DepartmentGrantReconcileError(summary, failures) from ExceptionGroup(
            "department grant failures", failures
        )
    return summary


def _desired_by_pair(
    policies: list[_Policy],
    users: dict[int, UserMirror],
    bindings: dict[int, DingTalkUserMirror],
    trees: dict[tuple[str, str], DepartmentTree],
    cutoff: datetime,
) -> tuple[dict[tuple[int, int], _Desired], dict[int, App]]:
    indexed: dict[tuple[str, str, str, int], list[_Policy]] = {}
    apps_by_corp: dict[tuple[str, str], set[int]] = {}
    apps: dict[int, App] = {}
    for policy in policies:
        row = policy.model
        corp = (row.source_slug, row.corp_id)
        apps[row.app_id] = row.app
        apps_by_corp.setdefault(corp, set()).add(row.app_id)
        if row.dept_id in trees[corp].nodes and (row.expires_at is None or row.expires_at > cutoff):
            indexed.setdefault((*corp, row.dept_id, row.app_id), []).append(policy)
    desired: dict[tuple[int, int], _Desired] = {}
    for user_id in users:
        mirror = bindings[user_id]
        corp = (mirror.source_slug, mirror.corp_id)
        departments = mirror.department_ids
        tree = trees[corp]
        ancestors = tree.ancestors_or_self_for(dept for dept in departments if dept in tree.nodes)
        for app_id in sorted(apps_by_corp[corp]):
            matching = sorted(
                (policy for dept in ancestors for policy in indexed.get((*corp, dept, app_id), ())),
                key=lambda policy: policy.model.id,
            )
            desired[(user_id, app_id)] = _desired_memberships(matching)
    return desired, apps
