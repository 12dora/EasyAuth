from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

from easyauth.accounts.models import UserMirror
from easyauth.connectors.base import DesiredState, DesiredUserProfile
from easyauth.connectors.models import ConnectorInstance
from easyauth.connectors.netbird import connector as connector_module
from easyauth.connectors.netbird.client import (
    NetBirdApiError,
    NetBirdGroup,
    NetBirdUser,
)
from easyauth.connectors.netbird.connector import NetBirdConnector

if TYPE_CHECKING:
    from easyauth.applications.ops_models import JsonValue

PERMANENT_CREATE_ERROR = "permanent create error"
PERMANENT_UPDATE_ERROR = "permanent update error"


@dataclass(slots=True)
class _FakeNetBirdClient:
    users: dict[str, NetBirdUser] = field(default_factory=dict)
    groups: list[NetBirdGroup] = field(default_factory=list)
    created_users: list[dict[str, object]] = field(default_factory=list)
    updated_users: list[dict[str, object]] = field(default_factory=list)
    created_groups: list[str] = field(default_factory=list)
    fail_with: str = ""
    fail_create_user_ids: set[str] = field(default_factory=set)
    fail_update_user_ids: set[str] = field(default_factory=set)

    def list_users(self) -> list[NetBirdUser]:
        if self.fail_with:
            raise NetBirdApiError(self.fail_with)
        return list(self.users.values())

    def list_groups(self) -> list[NetBirdGroup]:
        if self.fail_with:
            raise NetBirdApiError(self.fail_with)
        return list(self.groups)

    def create_group(self, *, name: str) -> NetBirdGroup:
        group = NetBirdGroup(group_id=f"gid-{name}", name=name)
        self.groups.append(group)
        self.created_groups.append(name)
        return group

    def create_user(
        self,
        *,
        user_id: str,
        name: str,
        email: str,
        auto_group_ids: list[str],
    ) -> None:
        if user_id in self.fail_create_user_ids:
            raise NetBirdApiError(PERMANENT_CREATE_ERROR, status_code=400)
        self.created_users.append(
            {"user_id": user_id, "name": name, "email": email, "auto_group_ids": auto_group_ids},
        )
        self.users[user_id] = NetBirdUser(
            user_id=user_id,
            name=name,
            email=email,
            role="user",
            is_blocked=False,
            is_service_user=False,
            auto_group_ids=frozenset(auto_group_ids),
        )

    def update_user(
        self,
        *,
        user_id: str,
        role: str,
        auto_group_ids: list[str],
        is_blocked: bool,
    ) -> None:
        if user_id in self.fail_update_user_ids:
            raise NetBirdApiError(PERMANENT_UPDATE_ERROR, status_code=400)
        self.updated_users.append(
            {
                "user_id": user_id,
                "role": role,
                "auto_group_ids": auto_group_ids,
                "is_blocked": is_blocked,
            },
        )


def _netbird_user(
    user_id: str,
    *,
    role: str = "user",
    is_blocked: bool = False,
    is_service_user: bool = False,
    auto_group_ids: frozenset[str] | None = None,
) -> NetBirdUser:
    return NetBirdUser(
        user_id=user_id,
        name=user_id,
        email=f"{user_id}@example.com",
        role=role,
        is_blocked=is_blocked,
        is_service_user=is_service_user,
        auto_group_ids=auto_group_ids or frozenset(),
    )


def _instance(config: dict[str, JsonValue] | None = None) -> ConnectorInstance:
    instance = ConnectorInstance(connector_key="netbird")
    base_config: dict[str, JsonValue] = {
        "api_url": "https://netbird.example.com",
        "api_token": "nb-token",
    }
    base_config.update(config or {})
    instance.set_config(base_config)
    return instance


def _desired(
    user_groups: dict[str, frozenset[str]],
    *,
    managed: frozenset[str],
    auto_create: frozenset[str] | None = None,
) -> DesiredState:
    profiles = {
        user_id: DesiredUserProfile(
            user_id=user_id,
            name=f"名字-{user_id}",
            email=f"{user_id}@example.com",
        )
        for user_id in user_groups
    }
    return DesiredState(
        user_groups=user_groups,
        profiles=profiles,
        managed_group_refs=managed,
        auto_create_group_refs=auto_create or frozenset(),
    )


@pytest.fixture
def fake_client(monkeypatch: pytest.MonkeyPatch) -> _FakeNetBirdClient:
    client = _FakeNetBirdClient()

    def client_from_config(_config: dict[str, JsonValue]) -> _FakeNetBirdClient:
        return client

    monkeypatch.setattr(connector_module, "_client_from_config", client_from_config)
    monkeypatch.setattr(connector_module, "_expansion_allowed", lambda *_args: True)
    return client


def test_reconcile_precreates_missing_user_with_mapped_groups(
    fake_client: _FakeNetBirdClient,
) -> None:
    # Given: 外部组已存在, 用户尚未在 NetBird 出现。
    fake_client.groups = [NetBirdGroup(group_id="g1", name="vpn-users")]
    desired = _desired(
        {"u-1": frozenset({"g1"})},
        managed=frozenset({"g1"}),
    )

    # When
    report = NetBirdConnector().reconcile(_instance(), desired)

    # Then: 按 UserMirror 画像预创建, auto_groups 直接带映射组。
    assert report.status == "success"
    assert fake_client.created_users == [
        {
            "user_id": "u-1",
            "name": "名字-u-1",
            "email": "u-1@example.com",
            "auto_group_ids": ["g1"],
        },
    ]
    assert report.stats["users_precreated"] == 1


def test_reconcile_skips_precreate_when_disabled(fake_client: _FakeNetBirdClient) -> None:
    # Given
    fake_client.groups = [NetBirdGroup(group_id="g1", name="vpn-users")]
    desired = _desired({"u-1": frozenset({"g1"})}, managed=frozenset({"g1"}))

    # When
    report = NetBirdConnector().reconcile(_instance({"precreate_users": False}), desired)

    # Then: 等首次登录被收养后下一轮收敛。
    assert fake_client.created_users == []
    assert report.stats["users_skipped"] == 1


def test_reconcile_adopts_existing_user_and_preserves_unmanaged_groups(
    fake_client: _FakeNetBirdClient,
) -> None:
    # Given: 已注册用户带无关组 g9 与过期映射组 g2, 且被 block。
    fake_client.groups = [
        NetBirdGroup(group_id="g1", name="vpn-users"),
        NetBirdGroup(group_id="g2", name="vpn-dev"),
    ]
    fake_client.users = {
        "u-1": _netbird_user(
            "u-1",
            is_blocked=True,
            auto_group_ids=frozenset({"g9", "g2"}),
        ),
    }
    desired = _desired(
        {"u-1": frozenset({"g1"})},
        managed=frozenset({"g1", "g2"}),
    )

    # When
    report = NetBirdConnector().reconcile(_instance(), desired)

    # Then: 只动映射管理的组(g9 保留), 解除 block。
    assert fake_client.updated_users == [
        {
            "user_id": "u-1",
            "role": "user",
            "auto_group_ids": ["g9"],
            "is_blocked": True,
        },
        {
            "user_id": "u-1",
            "role": "user",
            "auto_group_ids": ["g1", "g9"],
            "is_blocked": False,
        },
    ]
    assert report.stats["groups_added"] == 1
    assert report.stats["groups_removed"] == 1
    assert report.stats["users_unblocked"] == 1


def test_reconcile_converged_state_makes_no_writes(fake_client: _FakeNetBirdClient) -> None:
    # Given: 用户组与期望完全一致。
    fake_client.groups = [NetBirdGroup(group_id="g1", name="vpn-users")]
    fake_client.users = {
        "u-1": _netbird_user("u-1", auto_group_ids=frozenset({"g1"})),
    }
    desired = _desired({"u-1": frozenset({"g1"})}, managed=frozenset({"g1"}))

    # When
    report = NetBirdConnector().reconcile(_instance(), desired)

    # Then: 幂等——无任何写调用。
    assert fake_client.updated_users == []
    assert fake_client.created_users == []
    assert report.status == "success"


def test_reconcile_blocks_ungranted_user_and_strips_managed_groups(
    fake_client: _FakeNetBirdClient,
) -> None:
    # Given: u-2 无授权但持有映射组 g1 与无关组 g9。
    fake_client.groups = [NetBirdGroup(group_id="g1", name="vpn-users")]
    fake_client.users = {
        "u-2": _netbird_user("u-2", auto_group_ids=frozenset({"g1", "g9"})),
    }
    desired = _desired({}, managed=frozenset({"g1"}))

    # When
    report = NetBirdConnector().reconcile(_instance(), desired)

    # Then: 移除映射组、保留 g9、执行 block; 计入逆序用户数据口。
    assert fake_client.updated_users == [
        {
            "user_id": "u-2",
            "role": "user",
            "auto_group_ids": ["g9"],
            "is_blocked": True,
        },
    ]
    assert report.stats["users_blocked"] == 1
    assert report.ungranted_user_ids == ("u-2",)


def test_reconcile_respects_block_opt_out(fake_client: _FakeNetBirdClient) -> None:
    # Given: 关闭 block_users_without_grant。
    fake_client.groups = [NetBirdGroup(group_id="g1", name="vpn-users")]
    fake_client.users = {
        "u-2": _netbird_user("u-2", auto_group_ids=frozenset({"g1"})),
        "u-3": _netbird_user("u-3", auto_group_ids=frozenset({"g9"})),
    }
    desired = _desired({}, managed=frozenset({"g1"}))

    # When
    report = NetBirdConnector().reconcile(
        _instance({"block_users_without_grant": False}),
        desired,
    )

    # Then: 仍移除映射组但不 block; 完全无映射组的用户不产生任何调用。
    assert fake_client.updated_users == [
        {
            "user_id": "u-2",
            "role": "user",
            "auto_group_ids": [],
            "is_blocked": False,
        },
    ]
    assert "users_blocked" not in report.stats
    assert set(report.ungranted_user_ids) == {"u-2", "u-3"}


def test_reconcile_never_touches_service_users_owners_or_admins(
    fake_client: _FakeNetBirdClient,
) -> None:
    # Given: service user / owner / admin 均持有映射组且无授权。
    fake_client.groups = [NetBirdGroup(group_id="g1", name="vpn-users")]
    fake_client.users = {
        "svc": _netbird_user("svc", is_service_user=True, auto_group_ids=frozenset({"g1"})),
        "boss": _netbird_user("boss", role="owner", auto_group_ids=frozenset({"g1"})),
        "ops": _netbird_user("ops", role="admin", auto_group_ids=frozenset({"g1"})),
    }
    # admin 同时出现在 desired 中也不触碰(护栏优先)。
    desired = _desired({"ops": frozenset({"g1"})}, managed=frozenset({"g1"}))

    # When
    report = NetBirdConnector().reconcile(_instance(), desired)

    # Then
    assert fake_client.updated_users == []
    assert fake_client.created_users == []
    assert report.stats.get("users_exempt") == 1
    assert report.ungranted_user_ids == ()


def test_reconcile_reports_missing_immutable_group_ids(
    fake_client: _FakeNetBirdClient,
) -> None:
    # Given: 映射只保存不可变 ID; 外部缺失时不得按名称静默重建身份。
    desired = _desired(
        {"u-1": frozenset({"g1", "g2"})},
        managed=frozenset({"g1", "g2"}),
        auto_create=frozenset({"g1"}),
    )

    # When
    report = NetBirdConnector().reconcile(_instance(), desired)

    # Then: 缺组整轮失败关闭, 不得创建用户/组或假成功。
    assert fake_client.created_groups == []
    assert fake_client.created_users == []
    assert fake_client.updated_users == []
    expected_missing = 2
    assert report.status == "failed"
    assert report.stats["groups_missing"] == expected_missing
    assert "不可变组 ID" in report.error


def test_reconcile_stops_at_api_budget_and_reports_partial(
    fake_client: _FakeNetBirdClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: 预算只够 list_groups + list_users 两次调用。
    monkeypatch.setattr(connector_module, "MAX_API_CALLS_PER_RUN", 2)
    fake_client.groups = [NetBirdGroup(group_id="g1", name="vpn-users")]
    desired = _desired(
        {"u-1": frozenset({"g1"}), "u-2": frozenset({"g1"})},
        managed=frozenset({"g1"}),
    )

    # When
    report = NetBirdConnector().reconcile(_instance(), desired)

    # Then: 第一笔写操作触顶, 报 partial 防失控。
    assert report.status == "partial"
    assert fake_client.created_users == []
    assert "上限" in report.error


def test_api_budget_is_reserved_for_safety_shrink_first(
    fake_client: _FakeNetBirdClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 两次 list 后只剩一次写预算, 必须先用于无授权用户撤权而不是创建用户。
    monkeypatch.setattr(connector_module, "MAX_API_CALLS_PER_RUN", 3)
    fake_client.groups = [NetBirdGroup(group_id="g1", name="vpn-users")]
    fake_client.users = {
        "revoke-me": _netbird_user("revoke-me", auto_group_ids=frozenset({"g1"})),
    }
    desired = _desired(
        {"create-later": frozenset({"g1"})},
        managed=frozenset({"g1"}),
    )

    report = NetBirdConnector().reconcile(_instance(), desired)

    assert report.status == "partial"
    assert fake_client.updated_users[0]["user_id"] == "revoke-me"
    assert fake_client.updated_users[0]["is_blocked"] is True
    assert fake_client.created_users == []


def test_permanent_provisioning_error_does_not_block_revokes(
    fake_client: _FakeNetBirdClient,
) -> None:
    fake_client.groups = [NetBirdGroup(group_id="g1", name="vpn-users")]
    fake_client.users = {
        "revoke-me": _netbird_user("revoke-me", auto_group_ids=frozenset({"g1"})),
    }
    fake_client.fail_create_user_ids = {"create-fails"}
    desired = _desired(
        {"create-fails": frozenset({"g1"})},
        managed=frozenset({"g1"}),
    )

    report = NetBirdConnector().reconcile(_instance(), desired)

    assert report.status == "partial"
    assert fake_client.updated_users == [
        {
            "user_id": "revoke-me",
            "role": "user",
            "auto_group_ids": [],
            "is_blocked": True,
        }
    ]
    assert report.stats["users_blocked"] == 1
    assert report.stats["object_errors"] == 1


def test_on_user_offboarded_blocks_only_regular_users(
    fake_client: _FakeNetBirdClient,
) -> None:
    # Given
    fake_client.users = {
        "u-1": _netbird_user("u-1", auto_group_ids=frozenset({"g1"})),
        "boss": _netbird_user("boss", role="owner"),
    }
    connector = NetBirdConnector()

    # When: 普通用户立即 block(组保持原样, 清理交给周期对账)。
    handled = connector.on_user_offboarded(
        _instance(),
        UserMirror(authentik_user_id="u-1"),
    )

    # Then
    assert handled is True
    assert fake_client.updated_users == [
        {"user_id": "u-1", "role": "user", "auto_group_ids": ["g1"], "is_blocked": True},
    ]

    # owner 与不存在的用户都视为已处理但零调用。
    fake_client.updated_users.clear()
    assert connector.on_user_offboarded(_instance(), UserMirror(authentik_user_id="boss"))
    assert connector.on_user_offboarded(_instance(), UserMirror(authentik_user_id="ghost"))
    assert fake_client.updated_users == []


def test_test_connection_reports_probe_result(fake_client: _FakeNetBirdClient) -> None:
    # Given / When / Then: 正常返回组数; 失败翻译为 ok=False 而非异常。
    fake_client.groups = [NetBirdGroup(group_id="g1", name="vpn-users")]
    connector = NetBirdConnector()
    ok_probe = connector.test_connection({"api_url": "https://nb", "api_token": "t"})
    assert ok_probe.ok is True

    fake_client.fail_with = "HTTP 401"
    failed_probe = connector.test_connection({"api_url": "https://nb", "api_token": "t"})
    assert failed_probe.ok is False
    assert "401" in failed_probe.message


def test_external_groups_use_immutable_ids(fake_client: _FakeNetBirdClient) -> None:
    fake_client.groups = [NetBirdGroup(group_id="immutable-g1", name="VPN Users")]

    groups = NetBirdConnector().list_external_groups(
        {"api_url": "https://nb", "api_token": "t"}
    )

    assert [(group.ref, group.name) for group in groups] == [("immutable-g1", "VPN Users")]


def test_validate_config_rejects_plain_http_and_unknown_fields() -> None:
    connector = NetBirdConnector()
    problems = connector.validate_config(
        {"api_url": "http://netbird.internal", "api_token": "t", "bogus": 1},
    )
    assert any("https" in problem for problem in problems)
    assert any("bogus" in problem for problem in problems)
    assert connector.validate_config({"api_url": "https://nb", "api_token": "t"}) == []
