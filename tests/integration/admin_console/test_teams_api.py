from __future__ import annotations

from http import HTTPStatus
from json import dumps
from typing import Final, Protocol

import pytest
from django.contrib.auth.models import User
from django.test import Client
from pydantic import TypeAdapter

from easyauth.accounts.models import USER_STATUS_DEPARTED, UserMirror
from easyauth.api.errors import JsonValue
from easyauth.audit.models import AuditLog
from easyauth.teams.models import Team, TeamMember

pytestmark = pytest.mark.django_db

LOGIN_VALUE: Final = "console-teams-api"
JSON_VALUE_ADAPTER: Final[TypeAdapter[JsonValue]] = TypeAdapter(JsonValue)
EXPECTED_MEMBER_COUNT: Final = 2


class HttpResponseLike(Protocol):
    content: bytes


def test_superuser_creates_team_and_manages_members() -> None:
    # Given: 控制台超级管理员与两个活跃用户。
    client = _logged_in_superuser("teams-super-admin")
    leader = UserMirror.objects.create(authentik_user_id="teams-leader", name="张三")
    member = UserMirror.objects.create(authentik_user_id="teams-member", name="李四")

    # When: 创建团队并添加 leader 与成员。
    created = client.post(
        "/console/api/v1/teams",
        data=dumps({"name": "华东销售组", "description": "华东区"}),
        content_type="application/json",
    )
    team_id = _team_id(created)
    leader_added = client.post(
        f"/console/api/v1/teams/{team_id}/members",
        data=dumps({"user_id": leader.authentik_user_id, "role": "leader"}),
        content_type="application/json",
    )
    member_added = client.post(
        f"/console/api/v1/teams/{team_id}/members",
        data=dumps({"user_id": member.authentik_user_id, "role": "member"}),
        content_type="application/json",
    )
    listed = client.get("/console/api/v1/teams")

    # Then: 团队与成员落库, 列表包含 leader 摘要, 审计成链。
    assert created.status_code == HTTPStatus.CREATED
    assert leader_added.status_code == HTTPStatus.CREATED
    assert member_added.status_code == HTTPStatus.CREATED
    assert listed.status_code == HTTPStatus.OK
    team = Team.objects.get(id=team_id)
    assert team.name == "华东销售组"
    assert team.created_by == "teams-super-admin"
    assert TeamMember.objects.filter(team=team).count() == EXPECTED_MEMBER_COUNT
    listed_body = _response_json(listed)
    teams_data = listed_body["data"]
    assert isinstance(teams_data, list)
    first_team = teams_data[0]
    assert isinstance(first_team, dict)
    assert first_team["member_count"] == EXPECTED_MEMBER_COUNT
    assert first_team["leaders"] == [{"user_id": "teams-leader", "name": "张三"}]
    assert AuditLog.objects.filter(event_type="team_created").exists()
    assert (
        AuditLog.objects.filter(event_type="team_member_added").count() == EXPECTED_MEMBER_COUNT
    )


def test_superuser_updates_member_role_and_removes_member() -> None:
    # Given: 已有团队与一名成员。
    client = _logged_in_superuser("teams-role-admin")
    team = Team.objects.create(name="角色变更组")
    user = UserMirror.objects.create(authentik_user_id="teams-role-user")
    member = TeamMember.objects.create(team=team, user=user, role="member")

    # When: 提升为 leader 后再移除。
    promoted = client.patch(
        f"/console/api/v1/teams/{team.id}/members/{member.id}",
        data=dumps({"role": "leader"}),
        content_type="application/json",
    )
    removed = client.delete(f"/console/api/v1/teams/{team.id}/members/{member.id}")

    # Then: 角色更新与移除生效, 审计留痕。
    assert promoted.status_code == HTTPStatus.OK
    assert removed.status_code == HTTPStatus.OK
    assert not TeamMember.objects.filter(id=member.id).exists()
    assert AuditLog.objects.filter(event_type="team_member_role_updated").exists()
    assert AuditLog.objects.filter(event_type="team_member_removed").exists()


def test_superuser_deactivates_team() -> None:
    # Given
    client = _logged_in_superuser("teams-deactivate-admin")
    team = Team.objects.create(name="停用组")

    # When
    response = client.patch(
        f"/console/api/v1/teams/{team.id}",
        data=dumps({"is_active": False}),
        content_type="application/json",
    )

    # Then
    body = _response_json(response)
    team.refresh_from_db()
    assert response.status_code == HTTPStatus.OK
    assert team.is_active is False
    team_payload = body["team"]
    assert isinstance(team_payload, dict)
    assert team_payload["is_active"] is False


def test_superuser_deletes_team_and_cascades_members() -> None:
    # Given: 一个带成员的团队。
    client = _logged_in_superuser("teams-delete-admin")
    team = Team.objects.create(name="删除组")
    user = UserMirror.objects.create(authentik_user_id="teams-delete-user")
    member = TeamMember.objects.create(team=team, user=user, role="member")

    # When: 从表格操作列删除团队。
    response = client.delete(f"/console/api/v1/teams/{team.id}")

    # Then: 团队与成员关系一并移除(CASCADE), 审计留痕。
    body = _response_json(response)
    assert response.status_code == HTTPStatus.OK
    assert body["deleted"] is True
    assert not Team.objects.filter(id=team.id).exists()
    assert not TeamMember.objects.filter(id=member.id).exists()
    assert AuditLog.objects.filter(event_type="team_deleted").exists()


def test_team_write_rejects_duplicate_name_member_and_departed_user() -> None:
    # Given
    client = _logged_in_superuser("teams-validation-admin")
    team = Team.objects.create(name="校验组")
    user = UserMirror.objects.create(authentik_user_id="teams-validation-user")
    _ = TeamMember.objects.create(team=team, user=user, role="member")
    departed = UserMirror.objects.create(
        authentik_user_id="teams-validation-departed",
        status=USER_STATUS_DEPARTED,
    )

    # When
    duplicate_name = client.post(
        "/console/api/v1/teams",
        data=dumps({"name": "校验组"}),
        content_type="application/json",
    )
    duplicate_member = client.post(
        f"/console/api/v1/teams/{team.id}/members",
        data=dumps({"user_id": user.authentik_user_id, "role": "member"}),
        content_type="application/json",
    )
    departed_member = client.post(
        f"/console/api/v1/teams/{team.id}/members",
        data=dumps({"user_id": departed.authentik_user_id, "role": "member"}),
        content_type="application/json",
    )

    # Then
    assert duplicate_name.status_code == HTTPStatus.BAD_REQUEST
    assert duplicate_member.status_code == HTTPStatus.BAD_REQUEST
    assert departed_member.status_code == HTTPStatus.BAD_REQUEST
    assert TeamMember.objects.filter(team=team).count() == 1


def test_non_superuser_cannot_access_teams() -> None:
    # Given: 普通控制台用户(非超级管理员)。
    client = _logged_in_user("teams-plain-user")
    team = Team.objects.create(name="越权组")

    # When
    listed = client.get("/console/api/v1/teams")
    created = client.post(
        "/console/api/v1/teams",
        data=dumps({"name": "越权新建组"}),
        content_type="application/json",
    )
    detail = client.get(f"/console/api/v1/teams/{team.id}")

    # Then: 团队是组织架构 oracle, 读写一律 403。
    assert listed.status_code == HTTPStatus.FORBIDDEN
    assert created.status_code == HTTPStatus.FORBIDDEN
    assert detail.status_code == HTTPStatus.FORBIDDEN
    assert not Team.objects.filter(name="越权新建组").exists()


def _logged_in_superuser(username: str) -> Client:
    _ = User.objects.create_superuser(username=username, password=LOGIN_VALUE)
    client = Client(HTTP_HOST="localhost")
    assert client.login(username=username, password=LOGIN_VALUE) is True
    return client


def _logged_in_user(username: str) -> Client:
    _ = User.objects.create_user(username=username, password=LOGIN_VALUE)
    client = Client(HTTP_HOST="localhost")
    assert client.login(username=username, password=LOGIN_VALUE) is True
    return client


def _team_id(response: HttpResponseLike) -> int:
    body = _response_json(response)
    team = body["team"]
    assert isinstance(team, dict)
    team_id = team["id"]
    assert isinstance(team_id, int)
    return team_id


def _response_json(response: HttpResponseLike) -> dict[str, JsonValue]:
    parsed = JSON_VALUE_ADAPTER.validate_json(response.content)
    assert isinstance(parsed, dict), response.content.decode()
    return parsed
