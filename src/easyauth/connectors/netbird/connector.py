from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, final, override

from easyauth.config.net import InsecureUrlError, require_secure_url
from easyauth.connectors.base import (
    RECONCILE_STATUS_FAILED,
    RECONCILE_STATUS_PARTIAL,
    BaseConnector,
    ConnectorProbe,
    DesiredState,
    ExternalGroup,
    ExternalGroupPage,
    ReconcileReport,
)
from easyauth.connectors.netbird import runtime as runtime_module
from easyauth.connectors.netbird.client import USER_ROLE_USER, NetBirdApiError
from easyauth.connectors.netbird.peers import _handle_ungranted_users, _kick_peers_for_user
from easyauth.connectors.netbird.reconcile import (
    _completed_report,
    _interrupted_report,
    _prepare_reconcile_context,
    _run_desired_user_phases,
)
from easyauth.connectors.netbird.runtime import (
    API_BUDGET_EXHAUSTED_MESSAGE,
    API_URL_INSECURE_MESSAGE,
    FENCE_LOST_MESSAGE,
    MAX_API_CALLS_PER_RUN,
    _ApiBudgetExceededError,
    _client_from_config,
    _FenceLostError,
    _reconcile_options,
)

if TYPE_CHECKING:
    from easyauth.accounts.models import UserMirror
    from easyauth.applications.ops_models import JsonValue
    from easyauth.connectors.models import ConnectorInstance

__all__ = ["MAX_API_CALLS_PER_RUN", "NetBirdConnector"]


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
        # ref 必须使用 NetBird 不可变组 ID; 名称只用于控制台展示。
        client = _client_from_config(config)
        return [
            ExternalGroup(ref=group.group_id, name=group.name)
            for group in client.list_groups()
            if group.group_id and group.name
        ]

    @override
    def iter_external_group_pages(
        self,
        config: dict[str, JsonValue],
    ) -> tuple[ExternalGroupPage, ...]:
        client = _client_from_config(config)
        return tuple(
            ExternalGroupPage(
                groups=tuple(
                    ExternalGroup(ref=group.group_id, name=group.name)
                    for group in page
                    if group.group_id and group.name
                ),
                cursor=str(index),
            )
            for index, page in enumerate(client.iter_group_pages(), start=1)
        )

    @override
    def external_account_id(self, config: dict[str, JsonValue]) -> str:
        return _client_from_config(config).get_account_id()

    @override
    def reconcile(self, instance: ConnectorInstance, desired: DesiredState) -> ReconcileReport:
        # 幂等全量对账(方案 §3.8)。护栏: 绝不删除 NetBird 用户; 绝不触碰 service user
        # 与 owner/admin; 只增删映射表管理的组; 单轮 API 调用设上限。
        config = instance.config
        client = _client_from_config(config)
        options = _reconcile_options(config)
        stats: dict[str, int] = {}
        object_errors: list[str] = []
        ungranted_user_ids: list[str] = []
        try:
            context_or_report = _prepare_reconcile_context(
                client,
                instance,
                desired,
                stats,
                object_errors,
            )
            if isinstance(context_or_report, ReconcileReport):
                return context_or_report
            # 安全收缩独占第一阶段预算: 先撤组/封禁, 再执行任何创建、加组或解封。
            ungranted_user_ids = _handle_ungranted_users(
                context_or_report,
                block_users_without_grant=options.block_users_without_grant,
            )
            _run_desired_user_phases(context_or_report, options)
        except _ApiBudgetExceededError:
            return _interrupted_report(
                RECONCILE_STATUS_PARTIAL,
                stats,
                ungranted_user_ids,
                API_BUDGET_EXHAUSTED_MESSAGE,
            )
        except _FenceLostError:
            return _interrupted_report(
                RECONCILE_STATUS_FAILED,
                stats,
                ungranted_user_ids,
                FENCE_LOST_MESSAGE,
            )
        return _completed_report(
            context_or_report.budget,
            stats,
            object_errors,
            ungranted_user_ids,
        )

    @override
    def on_user_offboarded(self, instance: ConnectorInstance, user: UserMirror) -> bool:
        # 离职快路径: 立即 block 并踢掉该用户全部 peer; 组清理交给后续周期对账。
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
        if target is None or target.role != USER_ROLE_USER:
            # 不存在无事可做; owner/admin 是护栏豁免账号, 同样不触碰。
            return True
        if not runtime_module._external_write_allowed(  # noqa: SLF001
            instance,
            target.user_id,
            require_active_user=False,
            require_clean_dirty=False,
        ):
            return False
        if not target.is_blocked:
            client.update_user(
                user_id=target.user_id,
                role=target.role,
                auto_group_ids=sorted(target.auto_group_ids),
                is_blocked=True,
            )
        return _kick_peers_for_user(client, instance, target.user_id)
