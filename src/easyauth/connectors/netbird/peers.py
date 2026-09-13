from __future__ import annotations

from typing import TYPE_CHECKING

from easyauth.connectors.netbird import runtime as runtime_module
from easyauth.connectors.netbird.client import (
    USER_ROLE_USER,
    NetBirdApiError,
    NetBirdPeer,
    NetBirdUser,
)
from easyauth.connectors.netbird.runtime import (
    _ApiBudget,
    _bump,
    _FenceLostError,
    _ReconcileContext,
    logger,
)

if TYPE_CHECKING:
    from easyauth.connectors.models import ConnectorInstance
    from easyauth.connectors.netbird.client import NetBirdClient

__all__ = [
    "_handle_ungranted_users",
    "_kick_peers_for_user",
]


def _handle_ungranted_users(
    context: _ReconcileContext,
    *,
    block_users_without_grant: bool,
) -> list[str]:
    ungranted_user_ids: list[str] = []
    for user_id in sorted(context.actual_users):
        current = context.actual_users[user_id]
        if user_id in context.desired.user_groups or current.role != USER_ROLE_USER:
            continue
        # 逆序用户(先装客户端后申请)数据口: Phase 2 钉钉引导消息消费。
        ungranted_user_ids.append(user_id)
        _revoke_ungranted_user(
            context,
            current,
            block_users_without_grant=block_users_without_grant,
        )
    return ungranted_user_ids


def _revoke_ungranted_user(
    context: _ReconcileContext,
    current: NetBirdUser,
    *,
    block_users_without_grant: bool,
) -> None:
    managed_current = current.auto_group_ids & context.managed_group_ids
    should_block = block_users_without_grant and not current.is_blocked
    should_kick = block_users_without_grant
    if not managed_current and not should_block and not should_kick:
        return
    if not runtime_module._external_write_allowed(  # noqa: SLF001
        context.instance,
        current.user_id,
        require_active_user=False,
        allow_unknown_user=True,
    ):
        _bump(context.stats, "users_fenced")
        raise _FenceLostError
    if managed_current or should_block:
        context.budget.charge()
        try:
            context.client.update_user(
                user_id=current.user_id,
                role=current.role,
                auto_group_ids=sorted(current.auto_group_ids - context.managed_group_ids),
                is_blocked=current.is_blocked or block_users_without_grant,
            )
        except NetBirdApiError as error:
            context.object_errors.append(f"用户 {current.user_id} 撤权失败: {error}")
            return
        _bump(context.stats, "groups_removed", len(managed_current))
        if should_block:
            _bump(context.stats, "users_blocked")
    if should_kick:
        _kick_cached_user_peers(context, current.user_id)


def _kick_cached_user_peers(context: _ReconcileContext, user_id: str) -> None:
    peers = _load_peers(context)
    if peers is None:
        return
    try:
        removed = _delete_matching_peers(
            context.client,
            context.instance,
            user_id,
            peers,
            budget=context.budget,
            object_errors=context.object_errors,
            require_active_user=False,
            allow_unknown_user=True,
        )
    except _FenceLostError:
        _bump(context.stats, "users_fenced")
        raise
    _bump(context.stats, "peers_removed", removed)


def _load_peers(context: _ReconcileContext) -> list[NetBirdPeer] | None:
    if context.peers.failed:
        return None
    if context.peers.items is not None:
        return context.peers.items
    context.budget.charge()
    try:
        loaded = context.client.list_peers()
    except NetBirdApiError as error:
        context.object_errors.append(f"列出 NetBird peer 失败: {error}")
        context.peers.failed = True
        return None
    context.peers.items = loaded
    return loaded


def _kick_peers_for_user(
    client: NetBirdClient,
    instance: ConnectorInstance,
    user_id: str,
) -> bool:
    try:
        peers = client.list_peers()
    except NetBirdApiError as error:
        logger.warning("列出用户 %s 的 NetBird peer 失败: %s", user_id, error)
        return False
    errors: list[str] = []
    try:
        _ = _delete_matching_peers(
            client,
            instance,
            user_id,
            peers,
            budget=None,
            object_errors=errors,
            require_active_user=False,
            require_clean_dirty=False,
        )
    except _FenceLostError:
        return False
    for message in errors:
        logger.warning("%s", message)
    return not errors


def _delete_matching_peers(  # noqa: PLR0913 - 踢线循环需要 client/fence/预算/错误桶同时在场。
    client: NetBirdClient,
    instance: ConnectorInstance,
    user_id: str,
    peers: list[NetBirdPeer],
    *,
    budget: _ApiBudget | None,
    object_errors: list[str],
    require_active_user: bool,
    allow_unknown_user: bool = False,
    require_clean_dirty: bool = True,
) -> int:
    removed = 0
    for peer in peers:
        if peer.user_id != user_id:
            continue
        if not runtime_module._external_write_allowed(  # noqa: SLF001
            instance,
            user_id,
            require_active_user=require_active_user,
            allow_unknown_user=allow_unknown_user,
            require_clean_dirty=require_clean_dirty,
        ):
            raise _FenceLostError
        if budget is not None:
            budget.charge()
        try:
            client.delete_peer(peer.peer_id)
        except NetBirdApiError as error:
            object_errors.append(f"删除用户 {user_id} 的 peer {peer.peer_id} 失败: {error}")
            continue
        removed += 1
    if removed:
        logger.info("已踢出用户 %s 的 %s 个 NetBird peer。", user_id, removed)
    return removed
