from __future__ import annotations

from typing import TYPE_CHECKING

from easyauth.connectors.base import (
    RECONCILE_STATUS_FAILED,
    RECONCILE_STATUS_PARTIAL,
    RECONCILE_STATUS_SUCCESS,
    ReconcileReport,
)
from easyauth.connectors.netbird import runtime as runtime_module
from easyauth.connectors.netbird.client import (
    USER_ROLE_USER,
    NetBirdApiError,
    NetBirdUser,
)
from easyauth.connectors.netbird.runtime import (
    MISSING_MANAGED_GROUPS_MESSAGE,
    _ApiBudget,
    _bump,
    _FenceLostError,
    _PeerCache,
    _ReconcileContext,
    _ReconcileOptions,
)

if TYPE_CHECKING:
    from easyauth.connectors.base import DesiredState
    from easyauth.connectors.models import ConnectorInstance
    from easyauth.connectors.netbird.client import NetBirdClient

__all__ = [
    "_completed_report",
    "_interrupted_report",
    "_prepare_reconcile_context",
    "_run_desired_user_phases",
]


def _prepare_reconcile_context(
    client: NetBirdClient,
    instance: ConnectorInstance,
    desired: DesiredState,
    stats: dict[str, int],
    object_errors: list[str],
) -> _ReconcileContext | ReconcileReport:
    budget = _ApiBudget(runtime_module.MAX_API_CALLS_PER_RUN)
    budget.charge()
    actual_group_ids = frozenset(group.group_id for group in client.list_groups())
    missing_group_ids = desired.managed_group_refs - actual_group_ids
    if missing_group_ids:
        # external_ref 是不可变组 ID; 缺组时不得假成功或静默扩权, 整轮失败关闭。
        stats["groups_missing"] = len(missing_group_ids)
        return ReconcileReport(
            status=RECONCILE_STATUS_FAILED,
            stats=stats,
            error=MISSING_MANAGED_GROUPS_MESSAGE.format(
                refs=", ".join(sorted(missing_group_ids)),
            ),
        )
    budget.charge()
    actual_users = {user.user_id: user for user in client.list_users() if not user.is_service_user}
    return _ReconcileContext(
        client=client,
        budget=budget,
        instance=instance,
        desired=desired,
        stats=stats,
        managed_group_ids=desired.managed_group_refs & actual_group_ids,
        actual_users=actual_users,
        object_errors=object_errors,
        peers=_PeerCache(),
    )


def _run_desired_user_phases(
    context: _ReconcileContext,
    options: _ReconcileOptions,
) -> None:
    _shrink_desired_users(context)
    _expand_desired_users(
        context,
        precreate_users=options.precreate_users,
    )


def _interrupted_report(
    status: str,
    stats: dict[str, int],
    ungranted_user_ids: list[str],
    error: str,
) -> ReconcileReport:
    return ReconcileReport(
        status=status,
        stats=dict(stats),
        ungranted_user_ids=tuple(ungranted_user_ids),
        error=error,
    )


def _completed_report(
    budget: _ApiBudget,
    stats: dict[str, int],
    object_errors: list[str],
    ungranted_user_ids: list[str],
) -> ReconcileReport:
    stats["api_calls"] = budget.used
    if object_errors:
        stats["object_errors"] = len(object_errors)
        return ReconcileReport(
            status=RECONCILE_STATUS_PARTIAL,
            stats=stats,
            ungranted_user_ids=tuple(ungranted_user_ids),
            error="; ".join(object_errors),
        )
    return ReconcileReport(
        status=RECONCILE_STATUS_SUCCESS,
        stats=stats,
        ungranted_user_ids=tuple(ungranted_user_ids),
    )


def _expand_desired_users(
    context: _ReconcileContext,
    *,
    precreate_users: bool,
) -> None:
    for user_id in sorted(context.desired.user_groups):
        _expand_desired_user(context, user_id, precreate_users=precreate_users)


def _expand_desired_user(
    context: _ReconcileContext,
    user_id: str,
    *,
    precreate_users: bool,
) -> None:
    want_group_ids = context.desired.user_groups[user_id] & context.managed_group_ids
    current = context.actual_users.get(user_id)
    if current is None:
        _precreate_desired_user(
            context,
            user_id,
            want_group_ids,
            precreate_users=precreate_users,
        )
        return
    if current.role != USER_ROLE_USER:
        _bump(context.stats, "users_exempt")
        return
    additions = want_group_ids - (current.auto_group_ids & context.managed_group_ids)
    if not additions and not current.is_blocked and not current.pending_approval:
        return
    if not runtime_module._expansion_allowed(context.instance, user_id):  # noqa: SLF001
        _bump(context.stats, "users_fenced")
        return
    _update_expanded_user(context, current, additions)


def _precreate_desired_user(
    context: _ReconcileContext,
    user_id: str,
    want_group_ids: frozenset[str],
    *,
    precreate_users: bool,
) -> None:
    if not precreate_users:
        # 等员工首次登录被收养后, 下一轮对账收敛。
        _bump(context.stats, "users_skipped")
        return
    if not runtime_module._expansion_allowed(context.instance, user_id):  # noqa: SLF001
        _bump(context.stats, "users_fenced")
        return
    profile = context.desired.profiles[user_id]
    context.budget.charge()
    try:
        context.client.create_user(
            user_id=user_id,
            name=profile.name,
            email=profile.email,
            auto_group_ids=sorted(want_group_ids),
        )
    except NetBirdApiError as error:
        context.object_errors.append(f"用户 {user_id} 创建失败: {error}")
        return
    _bump(context.stats, "users_precreated")


def _update_expanded_user(
    context: _ReconcileContext,
    current: NetBirdUser,
    additions: frozenset[str],
) -> None:
    # UserApprovalRequired 下 SSO 首登用户是 blocked+pending; PUT is_blocked=false
    # 清不掉 pending_approval。pending 期间 peer 注册仍被拒, 因此先 PUT 组,
    # 审批作为最后一次外部写; 组未就绪不得激活用户。
    still_blocked = current.is_blocked and not current.pending_approval
    if additions or still_blocked:
        context.budget.charge()
        try:
            context.client.update_user(
                user_id=current.user_id,
                role=current.role,
                auto_group_ids=sorted(current.auto_group_ids | additions),
                is_blocked=False,
            )
        except NetBirdApiError as error:
            context.object_errors.append(f"用户 {current.user_id} 扩权失败: {error}")
            return
        _bump(context.stats, "groups_added", len(additions))
        if still_blocked:
            _bump(context.stats, "users_unblocked")
    if current.pending_approval:
        context.budget.charge()
        try:
            approved = context.client.approve_user(current.user_id)
        except NetBirdApiError as error:
            context.object_errors.append(f"用户 {current.user_id} 审批失败: {error}")
            return
        context.actual_users[current.user_id] = approved
        _bump(context.stats, "users_approved")


def _shrink_desired_users(context: _ReconcileContext) -> None:
    for user_id in sorted(context.desired.user_groups):
        current = context.actual_users.get(user_id)
        if current is None or current.role != USER_ROLE_USER:
            continue
        want_group_ids = context.desired.user_groups[user_id] & context.managed_group_ids
        removals = (current.auto_group_ids & context.managed_group_ids) - want_group_ids
        if not removals:
            continue
        _shrink_desired_user(context, current, removals)


def _shrink_desired_user(
    context: _ReconcileContext,
    current: NetBirdUser,
    removals: frozenset[str],
) -> None:
    if not runtime_module._external_write_allowed(  # noqa: SLF001
        context.instance,
        current.user_id,
        require_active_user=False,
    ):
        _bump(context.stats, "users_fenced")
        raise _FenceLostError
    context.budget.charge()
    try:
        context.client.update_user(
            user_id=current.user_id,
            role=current.role,
            auto_group_ids=sorted(current.auto_group_ids - removals),
            is_blocked=current.is_blocked,
        )
    except NetBirdApiError as error:
        context.object_errors.append(f"用户 {current.user_id} 收缩失败: {error}")
        return
    context.actual_users[current.user_id] = NetBirdUser(
        user_id=current.user_id,
        name=current.name,
        email=current.email,
        role=current.role,
        is_blocked=current.is_blocked,
        pending_approval=current.pending_approval,
        is_service_user=current.is_service_user,
        auto_group_ids=current.auto_group_ids - removals,
    )
    _bump(context.stats, "groups_removed", len(removals))
