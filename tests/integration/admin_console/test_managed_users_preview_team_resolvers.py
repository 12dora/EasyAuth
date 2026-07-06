from __future__ import annotations

from http import HTTPStatus
from json import dumps
from typing import Final, Protocol

import pytest
from django.contrib.auth.models import User
from django.test import Client
from pydantic import TypeAdapter

from easyauth.accounts.models import UserMirror
from easyauth.api.errors import JsonValue
from easyauth.applications.models import App, AppMembership, ManagedScopePolicy
from easyauth.integrations.authentik.directory_payloads import DingTalkManagedUsers
from easyauth.teams.models import Team, TeamMember

pytestmark = pytest.mark.django_db

LOGIN_VALUE: Final = "console-preview-team-resolver"
JSON_VALUE_ADAPTER: Final[TypeAdapter[JsonValue]] = TypeAdapter(JsonValue)


class HttpResponseLike(Protocol):
    content: bytes


class DirectoryClientStub:
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
            resolved_at="2026-07-06T09:30:00Z",
            users=(),
            active_authentik_user_ids=self._user_ids,
        )


def test_preview_resolves_easyauth_team_members_without_dingtalk_binding() -> None:
    # Given: 策略为 easyauth_team, 目标用户没有钉钉绑定但领导一个团队。
    client = _logged_in_client("preview-team-owner")
    app = _member_app("preview-team-app", "preview-team-owner")
    _ = _policy(app, "easyauth_team")
    leader = UserMirror.objects.create(authentik_user_id="preview-team-leader")
    member = UserMirror.objects.create(authentik_user_id="preview-team-member")
    team = Team.objects.create(name="预览团队")
    _ = TeamMember.objects.create(team=team, user=leader, role="leader")
    _ = TeamMember.objects.create(team=team, user=member, role="member")

    # When
    response = client.post(
        _preview_url(app.app_key),
        data=dumps({"user_id": leader.authentik_user_id}),
        content_type="application/json",
    )

    # Then: 本地团队解析成功, resolver 如实回填。
    body = _response_json(response)
    assert response.status_code == HTTPStatus.OK
    resolved = body["resolved"]
    assert isinstance(resolved, dict)
    assert resolved["user_ids"] == ["preview-team-member"]
    assert resolved["resolver"] == "easyauth_team"


def test_preview_union_resolver_merges_directory_and_team(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: union 策略, 目标用户同时有钉钉链下属与团队成员。
    client = _logged_in_client("preview-union-owner")
    app = _member_app("preview-union-app", "preview-union-owner")
    _ = _policy(app, "union")
    leader = UserMirror.objects.create(
        authentik_user_id="preview-union-leader",
        dingtalk_corp_id="ding-corp",
        dingtalk_userid="ding-union-leader",
    )
    member = UserMirror.objects.create(authentik_user_id="preview-union-member")
    team = Team.objects.create(name="预览union团队")
    _ = TeamMember.objects.create(team=team, user=leader, role="leader")
    _ = TeamMember.objects.create(team=team, user=member, role="member")
    monkeypatch.setattr(
        "easyauth.admin_console.managed_users_preview_api.AuthentikDirectoryClient.from_settings",
        lambda: DirectoryClientStub(("preview-chain-employee", "preview-union-leader")),
    )

    # When
    response = client.post(
        _preview_url(app.app_key),
        data=dumps({"user_id": leader.authentik_user_id}),
        content_type="application/json",
    )

    # Then: 两侧并集、排除本人, resolved_at 取目录侧时间。
    body = _response_json(response)
    assert response.status_code == HTTPStatus.OK
    resolved = body["resolved"]
    assert isinstance(resolved, dict)
    assert resolved["user_ids"] == ["preview-chain-employee", "preview-union-member"]
    assert resolved["resolver"] == "union"
    assert resolved["resolved_at"] == "2026-07-06T09:30:00Z"


def test_preview_union_resolver_returns_team_side_when_binding_missing() -> None:
    # Given: union 策略, 目标用户无钉钉绑定。
    client = _logged_in_client("preview-union-nobind-owner")
    app = _member_app("preview-union-nobind-app", "preview-union-nobind-owner")
    _ = _policy(app, "union")
    leader = UserMirror.objects.create(authentik_user_id="preview-union-nobind-leader")
    member = UserMirror.objects.create(authentik_user_id="preview-union-nobind-member")
    team = Team.objects.create(name="预览无绑定团队")
    _ = TeamMember.objects.create(team=team, user=leader, role="leader")
    _ = TeamMember.objects.create(team=team, user=member, role="member")

    # When
    response = client.post(
        _preview_url(app.app_key),
        data=dumps({"user_id": leader.authentik_user_id}),
        content_type="application/json",
    )

    # Then: 与运行时语义一致, 团队侧照常返回。
    body = _response_json(response)
    assert response.status_code == HTTPStatus.OK
    resolved = body["resolved"]
    assert isinstance(resolved, dict)
    assert resolved["user_ids"] == ["preview-union-nobind-member"]
    assert resolved["resolver"] == "union"


def _member_app(app_key: str, username: str) -> App:
    app = App.objects.create(app_key=app_key, name=app_key)
    _ = AppMembership.objects.create(app=app, user_id=username, role="owner")
    return app


def _policy(app: App, resolver: str) -> ManagedScopePolicy:
    return ManagedScopePolicy.objects.create(
        app=app,
        target_type="app_default",
        target_id=app.id,
        scope="MANAGED_USERS",
        resolver=resolver,
    )


def _logged_in_client(username: str) -> Client:
    _ = User.objects.create_user(username=username, password=LOGIN_VALUE)
    client = Client(HTTP_HOST="localhost")
    assert client.login(username=username, password=LOGIN_VALUE) is True
    return client


def _preview_url(app_key: str) -> str:
    return f"/console/api/v1/apps/{app_key}/managed-users-preview"


def _response_json(response: HttpResponseLike) -> dict[str, JsonValue]:
    parsed = JSON_VALUE_ADAPTER.validate_json(response.content)
    assert isinstance(parsed, dict), response.content.decode()
    return parsed
