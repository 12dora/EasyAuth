from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, final

from easyauth.connectors.netbird.client import NetBirdClient, NetBirdPeer, NetBirdUser

if TYPE_CHECKING:
    from easyauth.applications.ops_models import JsonValue
    from easyauth.connectors.base import DesiredState
    from easyauth.connectors.models import ConnectorInstance

__all__ = [
    "API_BUDGET_EXHAUSTED_MESSAGE",
    "API_URL_INSECURE_MESSAGE",
    "FENCE_LOST_MESSAGE",
    "MAX_API_CALLS_PER_RUN",
    "MISSING_MANAGED_GROUPS_MESSAGE",
    "_ApiBudget",
    "_ApiBudgetExceededError",
    "_FenceLostError",
    "_PeerCache",
    "_ReconcileContext",
    "_ReconcileOptions",
    "_bump",
    "_client_from_config",
    "_expansion_allowed",
    "_external_write_allowed",
    "_reconcile_options",
    "logger",
]

# 单轮对账 API 调用上限护栏: 超限报 partial 防失控(方案 §3.8); 下一轮继续收敛。
MAX_API_CALLS_PER_RUN: Final = 500
API_BUDGET_EXHAUSTED_MESSAGE: Final = (
    f"单轮对账 API 调用达到上限({MAX_API_CALLS_PER_RUN} 次), 本轮提前结束, 下一轮继续收敛。"
)
API_URL_INSECURE_MESSAGE: Final = "api_url 必须使用 https(仅本地开发允许 http://localhost)。"
MISSING_MANAGED_GROUPS_MESSAGE: Final = (
    "映射的 NetBird 组不存在(external_ref 为不可变组 ID, 不支持自动创建): {refs}。"
)
FENCE_LOST_MESSAGE: Final = "连接器对账失去租约或 generation fence, 本轮已停止外部写入。"
logger = logging.getLogger(__name__)


class _ApiBudgetExceededError(Exception):
    """内部信号: 本轮 API 预算耗尽, 对账提前收口为 partial。"""


class _FenceLostError(Exception):
    """内部信号: worker 已失去外部写入 fence, 必须终止本轮。"""


@final
class _ApiBudget:
    def __init__(self, limit: int) -> None:
        self._limit: int = limit
        self.used: int = 0

    def charge(self) -> None:
        if self.used >= self._limit:
            raise _ApiBudgetExceededError
        self.used += 1


@final
class _PeerCache:
    def __init__(self) -> None:
        self.items: list[NetBirdPeer] | None = None
        self.failed: bool = False


@dataclass(frozen=True, slots=True)
class _ReconcileContext:
    client: NetBirdClient
    budget: _ApiBudget
    instance: ConnectorInstance
    desired: DesiredState
    stats: dict[str, int]
    managed_group_ids: frozenset[str]
    actual_users: dict[str, NetBirdUser]
    object_errors: list[str]
    peers: _PeerCache


@dataclass(frozen=True, slots=True)
class _ReconcileOptions:
    precreate_users: bool
    block_users_without_grant: bool


def _client_from_config(config: dict[str, JsonValue]) -> NetBirdClient:
    api_url = config.get("api_url")
    api_token = config.get("api_token")
    return NetBirdClient(
        api_url=api_url if isinstance(api_url, str) else "",
        api_token=api_token if isinstance(api_token, str) else "",
    )


def _reconcile_options(config: dict[str, JsonValue]) -> _ReconcileOptions:
    return _ReconcileOptions(
        precreate_users=config.get("precreate_users", True) is not False,
        block_users_without_grant=(config.get("block_users_without_grant", True) is not False),
    )


def _expansion_allowed(instance: ConnectorInstance, user_id: str) -> bool:
    # 局部导入避免框架加载连接器注册表时形成循环依赖。
    from easyauth.connectors.reconcile import expansion_allowed  # noqa: PLC0415

    return expansion_allowed(instance, user_id=user_id)


def _external_write_allowed(
    instance: ConnectorInstance,
    user_id: str,
    *,
    require_active_user: bool,
    allow_unknown_user: bool = False,
    require_clean_dirty: bool = True,
) -> bool:
    # 局部导入避免框架加载连接器注册表时形成循环依赖。
    from easyauth.connectors.reconcile import external_write_allowed  # noqa: PLC0415

    return external_write_allowed(
        instance,
        user_id=user_id,
        require_active_user=require_active_user,
        allow_unknown_user=allow_unknown_user,
        require_clean_dirty=require_clean_dirty,
    )


def _bump(stats: dict[str, int], key: str, amount: int = 1) -> None:
    if amount <= 0:
        return
    stats[key] = stats.get(key, 0) + amount
