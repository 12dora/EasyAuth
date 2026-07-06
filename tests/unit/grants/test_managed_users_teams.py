from __future__ import annotations

import pytest

from easyauth.accounts.models import USER_STATUS_DEPARTED, UserMirror
from easyauth.applications.models import App, ManagedScopePolicy
from easyauth.audit.models import AuditLog
from easyauth.grants.managed_users import (
    ManagedUsersResolutionUnavailableError,
    resolve_managed_users,
)
from easyauth.integrations.authentik.directory_client import (
    AuthentikDirectoryUnavailableError,
)
from easyauth.integrations.authentik.directory_payloads import DingTalkManagedUsers
from easyauth.teams.models import (
    TEAM_MEMBER_ROLE_LEADER,
    TEAM_MEMBER_ROLE_MEMBER,
    Team,
    TeamMember,
)

pytestmark = pytest.mark.django_db


def _app_with_policy(app_key: str, resolver: str) -> App:
    app = App.objects.create(app_key=app_key, name=app_key)
    _ = ManagedScopePolicy.objects.create(
        app=app,
        target_type="app_default",
        target_id=app.id,
        scope="MANAGED_USERS",
        resolver=resolver,
    )
    return app


def _team_with_leader(
    name: str,
    leader: UserMirror,
    members: tuple[UserMirror, ...],
    *,
    is_active: bool = True,
) -> Team:
    team = Team.objects.create(name=name, is_active=is_active)
    _ = TeamMember.objects.create(team=team, user=leader, role=TEAM_MEMBER_ROLE_LEADER)
    for member in members:
        _ = TeamMember.objects.create(team=team, user=member, role=TEAM_MEMBER_ROLE_MEMBER)
    return team


class _ManagedUsersClient:
    _user_ids: tuple[str, ...]

    def __init__(self, user_ids: tuple[str, ...]) -> None:
        self._user_ids = user_ids

    def get_managed_users(self, corp_id: str, manager_user_id: str) -> DingTalkManagedUsers:
        return DingTalkManagedUsers(
            source_slug="dingtalk",
            corp_id=corp_id,
            manager_user_id=manager_user_id,
            resolver="dingtalk_manager_chain",
            stale=False,
            resolved_at="2026-07-06T12:00:00+08:00",
            users=(),
            active_authentik_user_ids=self._user_ids,
        )


class _UnavailableManagedUsersClient:
    def get_managed_users(self, corp_id: str, manager_user_id: str) -> DingTalkManagedUsers:
        _ = corp_id, manager_user_id
        message = "目录不可用"
        raise AuthentikDirectoryUnavailableError(message)


def test_easyauth_team_resolver_returns_active_members_of_led_teams() -> None:
    # Given: leader 领导两个 active 团队, 其中包含离职成员与本人。
    leader = UserMirror.objects.create(authentik_user_id="team-leader-a")
    member_b = UserMirror.objects.create(authentik_user_id="team-member-b")
    member_c = UserMirror.objects.create(authentik_user_id="team-member-c")
    departed = UserMirror.objects.create(
        authentik_user_id="team-member-departed",
        status=USER_STATUS_DEPARTED,
    )
    _ = _team_with_leader("华东组", leader, (member_b, departed))
    _ = _team_with_leader("华北组", leader, (member_b, member_c))
    app = _app_with_policy("team-resolver-app", "easyauth_team")

    # When
    resolved = resolve_managed_users(user=leader, app=app)

    # Then: active 成员并集, 去重、排除本人与离职成员; 不依赖钉钉绑定。
    assert resolved is not None
    assert resolved.user_ids == ("team-member-b", "team-member-c")
    assert resolved.resolver == "easyauth_team"
    assert resolved.resolved_at != ""


def test_easyauth_team_resolver_ignores_inactive_teams_and_non_leader_membership() -> None:
    # Given: 用户在停用团队当 leader, 在 active 团队仅是普通成员。
    user = UserMirror.objects.create(authentik_user_id="team-plain-member")
    other = UserMirror.objects.create(authentik_user_id="team-other-member")
    _ = _team_with_leader("停用组", user, (other,), is_active=False)
    inactive_leader = UserMirror.objects.create(authentik_user_id="team-other-leader")
    _ = _team_with_leader("在役组", inactive_leader, (user, other))
    app = _app_with_policy("team-resolver-empty-app", "easyauth_team")

    # When
    resolved = resolve_managed_users(user=user, app=app)

    # Then: 没有任何 active 领导关系时解析为空集合(不是 None)。
    assert resolved is not None
    assert resolved.user_ids == ()


def test_union_resolver_merges_chain_and_team_members(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: 钉钉链下属与手工团队成员部分重叠。
    leader = UserMirror.objects.create(
        authentik_user_id="union-leader",
        dingtalk_corp_id="corp-1",
        dingtalk_userid="union-leader-dt",
    )
    member = UserMirror.objects.create(authentik_user_id="union-team-member")
    overlap = UserMirror.objects.create(authentik_user_id="union-overlap-member")
    _ = _team_with_leader("union组", leader, (member, overlap))
    app = _app_with_policy("union-resolver-app", "union")
    monkeypatch.setattr(
        "easyauth.grants.managed_users.AuthentikDirectoryClient.from_settings",
        lambda: _ManagedUsersClient(("chain-employee", "union-overlap-member", "union-leader")),
    )

    # When
    resolved = resolve_managed_users(user=leader, app=app)

    # Then: 并集去重、排除本人, resolver 如实回填 union。
    assert resolved is not None
    assert resolved.user_ids == (
        "chain-employee",
        "union-overlap-member",
        "union-team-member",
    )
    assert resolved.resolver == "union"
    assert resolved.resolved_at == "2026-07-06T12:00:00+08:00"


def test_union_resolver_returns_team_side_when_dingtalk_binding_missing() -> None:
    # Given: 用户没有钉钉绑定, 但领导一个 active 团队。
    leader = UserMirror.objects.create(authentik_user_id="union-no-binding-leader")
    member = UserMirror.objects.create(authentik_user_id="union-no-binding-member")
    _ = _team_with_leader("无绑定组", leader, (member,))
    app = _app_with_policy("union-no-binding-app", "union")

    # When
    resolved = resolve_managed_users(user=leader, app=app)

    # Then: 绑定缺失是稳定事实, 团队侧照常返回并审计留痕。
    assert resolved is not None
    assert resolved.user_ids == ("union-no-binding-member",)
    assert resolved.resolver == "union"
    audit_log = AuditLog.objects.get(event_type="managed_users_resolution_failed")
    assert audit_log.metadata["error_code"] == "managed_scope_user_dingtalk_binding_missing"
    assert audit_log.metadata["resolver"] == "union"


def test_union_resolver_fails_fast_when_directory_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: union 策略, 钉钉目录瞬时不可用。
    leader = UserMirror.objects.create(
        authentik_user_id="union-unavailable-leader",
        dingtalk_corp_id="corp-1",
        dingtalk_userid="union-unavailable-dt",
    )
    member = UserMirror.objects.create(authentik_user_id="union-unavailable-member")
    _ = _team_with_leader("不可用组", leader, (member,))
    app = _app_with_policy("union-unavailable-app", "union")
    monkeypatch.setattr(
        "easyauth.grants.managed_users.AuthentikDirectoryClient.from_settings",
        lambda: _UnavailableManagedUsersClient(),
    )

    # When / Then: 瞬时故障必须 fail-fast, 不得降级成只剩团队侧的"成功"响应。
    with pytest.raises(ManagedUsersResolutionUnavailableError):
        _ = resolve_managed_users(user=leader, app=app)


def test_chain_resolver_still_returns_none_when_binding_missing() -> None:
    # Given: dingtalk_manager_chain 策略, 用户无钉钉绑定。
    user = UserMirror.objects.create(authentik_user_id="chain-no-binding")
    app = _app_with_policy("chain-no-binding-app", "dingtalk_manager_chain")

    # When
    resolved = resolve_managed_users(user=user, app=app)

    # Then: 既有语义不变。
    assert resolved is None
