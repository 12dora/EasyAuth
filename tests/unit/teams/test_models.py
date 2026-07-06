from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from easyauth.accounts.models import UserMirror
from easyauth.teams.models import (
    TEAM_MEMBER_ROLE_LEADER,
    TEAM_MEMBER_ROLE_MEMBER,
    Team,
    TeamMember,
)

pytestmark = pytest.mark.django_db


def test_team_member_accepts_supported_roles() -> None:
    # Given
    team = Team.objects.create(name="华东销售组")
    leader = UserMirror.objects.create(authentik_user_id="team-role-leader")
    member = UserMirror.objects.create(authentik_user_id="team-role-member")

    # When
    leader_row = TeamMember(team=team, user=leader, role=TEAM_MEMBER_ROLE_LEADER)
    member_row = TeamMember(team=team, user=member, role=TEAM_MEMBER_ROLE_MEMBER)
    leader_row.full_clean()
    member_row.full_clean()

    # Then
    assert leader_row.role == TEAM_MEMBER_ROLE_LEADER
    assert member_row.role == TEAM_MEMBER_ROLE_MEMBER


def test_team_member_rejects_unsupported_role() -> None:
    # Given
    team = Team.objects.create(name="角色校验组")
    user = UserMirror.objects.create(authentik_user_id="team-role-invalid")

    # When / Then
    with pytest.raises(ValidationError):
        TeamMember(team=team, user=user, role="manager").full_clean()


def test_team_member_unique_per_team_and_user() -> None:
    # Given
    team = Team.objects.create(name="去重组")
    user = UserMirror.objects.create(authentik_user_id="team-unique-user")
    _ = TeamMember.objects.create(team=team, user=user, role=TEAM_MEMBER_ROLE_MEMBER)

    # When / Then
    with pytest.raises(IntegrityError):
        _ = TeamMember.objects.create(team=team, user=user, role=TEAM_MEMBER_ROLE_LEADER)


def test_team_name_unique() -> None:
    # Given
    _ = Team.objects.create(name="同名组")

    # When / Then
    with pytest.raises(IntegrityError):
        _ = Team.objects.create(name="同名组")
