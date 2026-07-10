from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Final, final, override

from easyauth.config.net import InsecureUrlError, require_secure_url
from easyauth.connectors.base import (
    RECONCILE_STATUS_PARTIAL,
    RECONCILE_STATUS_SUCCESS,
    BaseConnector,
    ConnectorProbe,
    DesiredState,
    ExternalGroup,
    ReconcileReport,
)
from easyauth.connectors.netbird.client import (
    USER_ROLE_USER,
    NetBirdApiError,
    NetBirdClient,
    NetBirdGroup,
    NetBirdUser,
)

if TYPE_CHECKING:
    from easyauth.accounts.models import UserMirror
    from easyauth.applications.ops_models import JsonValue
    from easyauth.connectors.models import ConnectorInstance

# 单轮对账 API 调用上限护栏: 超限报 partial 防失控(方案 §3.8); 下一轮继续收敛。
MAX_API_CALLS_PER_RUN: Final = 500
API_BUDGET_EXHAUSTED_MESSAGE: Final = (
    f"单轮对账 API 调用达到上限({MAX_API_CALLS_PER_RUN} 次), 本轮提前结束, 下一轮继续收敛。"
)
API_URL_INSECURE_MESSAGE: Final = "api_url 必须使用 https(仅本地开发允许 http://localhost)。"


class _ApiBudgetExceededError(Exception):
    """内部信号: 本轮 API 预算耗尽, 对账提前收口为 partial。"""


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
class NetBirdConnector(BaseConnector):
    key: ClassVar[str] = "netbird"
    display_name: ClassVar[str] = "NetBird VPN"
    config_schema: ClassVar[dict[str, JsonValue]] = {
        "type": "object",
        "properties": {
            "api_url": {
                "type": "string",
                "title": "管理 API 地址",
                "description": "NetBird 管理服务地址, 例如 https://netbird.example.com。",
            },
            "api_token": {
                "type": "string",
                "title": "服务用户 API Token",
                "description": "NetBird service user 的个人访问令牌, 静态加密落库。",
                "x-secret": True,
            },
            "precreate_users": {
                "type": "boolean",
                "title": "预创建用户",
                "description": (
                    "审批通过即预创建 NetBird 用户(依赖 fork 补丁), 首次登录原样收养; "
                    "关闭时等员工首次登录后下一轮对账收敛。"
                ),
                "default": True,
            },
            "block_users_without_grant": {
                "type": "boolean",
                "title": "封禁无授权用户",
                "description": "对存在于 NetBird 但无任何映射授权的普通用户执行 block(默认拒绝)。",
                "default": True,
            },
        },
        "required": ["api_url", "api_token"],
    }

    @override
    def validate_config(self, config: dict[str, JsonValue]) -> list[str]:
        problems = super().validate_config(config)
        api_url = config.get("api_url")
        if isinstance(api_url, str) and api_url:
            # api_token 走 Authorization 头, 明文 http 会导致 token 明文传输。
            try:
                require_secure_url(api_url, allow_local_http=True)
            except InsecureUrlError:
                problems.append(API_URL_INSECURE_MESSAGE)
        return problems

    @override
    def test_connection(self, config: dict[str, JsonValue]) -> ConnectorProbe:
        client = _client_from_config(config)
        try:
            groups = client.list_groups()
        except NetBirdApiError as error:
            return ConnectorProbe(ok=False, message=str(error))
        return ConnectorProbe(ok=True, message=f"连接成功, NetBird 现有 {len(groups)} 个组。")

    @override
    def list_external_groups(self, config: dict[str, JsonValue]) -> list[ExternalGroup]:
        # external_ref 语义 = NetBird 组名(实例间稳定、人类可读); 组 ID 仅对账内部使用。
        client = _client_from_config(config)
        return [
            ExternalGroup(ref=group.name, name=group.name)
            for group in client.list_groups()
            if group.name
        ]

    @override
    def reconcile(self, instance: ConnectorInstance, desired: DesiredState) -> ReconcileReport:
        # 幂等全量对账(方案 §3.8)。护栏: 绝不删除 NetBird 用户; 绝不触碰 service user
        # 与 owner/admin; 只增删映射表管理的组; 单轮 API 调用设上限。
        config = instance.config
        client = _client_from_config(config)
        precreate_users = config.get("precreate_users", True) is not False
        block_users_without_grant = config.get("block_users_without_grant", True) is not False
        budget = _ApiBudget(MAX_API_CALLS_PER_RUN)
        stats: dict[str, int] = {}
        ungranted_user_ids: list[str] = []
        try:
            group_id_by_name = _ensure_groups(client, budget, desired, stats)
            managed_group_ids = frozenset(
                group_id_by_name[name]
                for name in desired.managed_group_refs
                if name in group_id_by_name
            )
            budget.charge()
            actual_users = {
                user.user_id: user for user in client.list_users() if not user.is_service_user
            }
            _apply_desired_users(
                client,
                budget,
                desired,
                stats,
                group_id_by_name=group_id_by_name,
                managed_group_ids=managed_group_ids,
                actual_users=actual_users,
                precreate_users=precreate_users,
            )
            ungranted_user_ids = _handle_ungranted_users(
                client,
                budget,
                desired,
                stats,
                managed_group_ids=managed_group_ids,
                actual_users=actual_users,
                block_users_without_grant=block_users_without_grant,
            )
        except _ApiBudgetExceededError:
            return ReconcileReport(
                status=RECONCILE_STATUS_PARTIAL,
                stats=dict(stats),
                ungranted_user_ids=tuple(ungranted_user_ids),
                error=API_BUDGET_EXHAUSTED_MESSAGE,
            )
        stats["api_calls"] = budget.used
        return ReconcileReport(
            status=RECONCILE_STATUS_SUCCESS,
            stats=stats,
            ungranted_user_ids=tuple(ungranted_user_ids),
        )

    @override
    def on_user_offboarded(self, instance: ConnectorInstance, user: UserMirror) -> bool:
        # 离职快路径: 立即 block 秒级断连; 组清理交给后续周期对账(方案 §3.8)。
        client = _client_from_config(instance.config)
        target_id = user.authentik_user_id
        target = next(
            (
                candidate
                for candidate in client.list_users()
                if candidate.user_id == target_id and not candidate.is_service_user
            ),
            None,
        )
        if target is None or target.role != USER_ROLE_USER or target.is_blocked:
            # 不存在/已封禁无事可做; owner/admin 是护栏豁免账号, 同样不触碰。
            return True
        client.update_user(
            user_id=target.user_id,
            role=target.role,
            auto_group_ids=sorted(target.auto_group_ids),
            is_blocked=True,
        )
        return True


def _client_from_config(config: dict[str, JsonValue]) -> NetBirdClient:
    api_url = config.get("api_url")
    api_token = config.get("api_token")
    return NetBirdClient(
        api_url=api_url if isinstance(api_url, str) else "",
        api_token=api_token if isinstance(api_token, str) else "",
    )


def _ensure_groups(
    client: NetBirdClient,
    budget: _ApiBudget,
    desired: DesiredState,
    stats: dict[str, int],
) -> dict[str, str]:
    budget.charge()
    group_id_by_name: dict[str, str] = {}
    for group in client.list_groups():
        _ = group_id_by_name.setdefault(group.name, group.group_id)
    for name in sorted(desired.managed_group_refs):
        if name in group_id_by_name:
            continue
        if name not in desired.auto_create_group_refs:
            # 未开 auto_create 且外部缺组: 跳过该组(映射页可见), 不静默创建。
            _bump(stats, "groups_missing")
            continue
        budget.charge()
        created: NetBirdGroup = client.create_group(name=name)
        group_id_by_name[name] = created.group_id
        _bump(stats, "groups_created")
    return group_id_by_name


def _apply_desired_users(  # noqa: PLR0913 - 对账循环的完整上下文, 拆包装反而失真。
    client: NetBirdClient,
    budget: _ApiBudget,
    desired: DesiredState,
    stats: dict[str, int],
    *,
    group_id_by_name: dict[str, str],
    managed_group_ids: frozenset[str],
    actual_users: dict[str, NetBirdUser],
    precreate_users: bool,
) -> None:
    for user_id in sorted(desired.user_groups):
        want_group_ids = frozenset(
            group_id_by_name[name]
            for name in desired.user_groups[user_id]
            if name in group_id_by_name
        )
        current = actual_users.get(user_id)
        if current is None:
            if not precreate_users:
                # 等员工首次登录被收养后, 下一轮对账收敛。
                _bump(stats, "users_skipped")
                continue
            profile = desired.profiles[user_id]
            budget.charge()
            client.create_user(
                user_id=user_id,
                name=profile.name,
                email=profile.email,
                auto_group_ids=sorted(want_group_ids),
            )
            _bump(stats, "users_precreated")
            continue
        _reconcile_existing_user(
            client,
            budget,
            stats,
            current=current,
            want_group_ids=want_group_ids,
            managed_group_ids=managed_group_ids,
        )


def _reconcile_existing_user(  # noqa: PLR0913 - 对账循环的完整上下文, 拆包装反而失真。
    client: NetBirdClient,
    budget: _ApiBudget,
    stats: dict[str, int],
    *,
    current: NetBirdUser,
    want_group_ids: frozenset[str],
    managed_group_ids: frozenset[str],
) -> None:
    if current.role != USER_ROLE_USER:
        # 护栏: owner/admin 人工账号不纳入管理。
        _bump(stats, "users_exempt")
        return
    managed_current = current.auto_group_ids & managed_group_ids
    if managed_current == want_group_ids and not current.is_blocked:
        return
    next_group_ids = (current.auto_group_ids - managed_group_ids) | want_group_ids
    budget.charge()
    client.update_user(
        user_id=current.user_id,
        role=current.role,
        auto_group_ids=sorted(next_group_ids),
        is_blocked=False,
    )
    _bump(stats, "groups_added", len(want_group_ids - managed_current))
    _bump(stats, "groups_removed", len(managed_current - want_group_ids))
    if current.is_blocked:
        _bump(stats, "users_unblocked")


def _handle_ungranted_users(  # noqa: PLR0913 - 对账循环的完整上下文, 拆包装反而失真。
    client: NetBirdClient,
    budget: _ApiBudget,
    desired: DesiredState,
    stats: dict[str, int],
    *,
    managed_group_ids: frozenset[str],
    actual_users: dict[str, NetBirdUser],
    block_users_without_grant: bool,
) -> list[str]:
    ungranted_user_ids: list[str] = []
    for user_id in sorted(actual_users):
        if user_id in desired.user_groups:
            continue
        current = actual_users[user_id]
        if current.role != USER_ROLE_USER:
            continue
        # 逆序用户(先装客户端后申请)数据口: Phase 2 钉钉引导消息消费。
        ungranted_user_ids.append(user_id)
        managed_current = current.auto_group_ids & managed_group_ids
        should_block = block_users_without_grant and not current.is_blocked
        if not managed_current and not should_block:
            continue
        budget.charge()
        client.update_user(
            user_id=current.user_id,
            role=current.role,
            auto_group_ids=sorted(current.auto_group_ids - managed_group_ids),
            is_blocked=current.is_blocked or block_users_without_grant,
        )
        _bump(stats, "groups_removed", len(managed_current))
        if should_block:
            _bump(stats, "users_blocked")
    return ungranted_user_ids


def _bump(stats: dict[str, int], key: str, amount: int = 1) -> None:
    if amount <= 0:
        return
    stats[key] = stats.get(key, 0) + amount
