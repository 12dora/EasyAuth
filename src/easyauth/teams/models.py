from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Final, override

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from easyauth.accounts.models import UserMirror

if TYPE_CHECKING:
    from datetime import date, datetime

TEAM_MEMBER_ROLE_LEADER: Final = "leader"
TEAM_MEMBER_ROLE_MEMBER: Final = "member"
TEAM_MEMBER_ROLE_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    (TEAM_MEMBER_ROLE_LEADER, "leader"),
    (TEAM_MEMBER_ROLE_MEMBER, "member"),
)
TEAM_MEMBER_ROLE_VALUES: Final[tuple[str, ...]] = (
    TEAM_MEMBER_ROLE_LEADER,
    TEAM_MEMBER_ROLE_MEMBER,
)


class Team(models.Model):
    # 团队是跨 App 的组织事实, 服务 MANAGED_USERS 的 easyauth_team resolver;
    # 第一版刻意扁平(无嵌套)、全局(不按 App 隔离), 允许多 leader、一人多团队。
    if TYPE_CHECKING:
        id: ClassVar[int]

    name: models.CharField[str, str] = models.CharField(max_length=128, unique=True)
    description: models.TextField[str, str] = models.TextField(blank=True)
    is_active: models.BooleanField[bool, bool] = models.BooleanField(default=True)
    created_by: models.CharField[str, str] = models.CharField(max_length=128, blank=True)
    created_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )
    updated_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering: ClassVar[list[str]] = ["name"]

    @override
    def __str__(self) -> str:
        return self.name


class TeamMember(models.Model):
    if TYPE_CHECKING:
        id: ClassVar[int]
        team_id: ClassVar[int]
        user_id: ClassVar[int]

    team: models.ForeignKey[Team, Team] = models.ForeignKey(
        Team,
        on_delete=models.CASCADE,
        related_name="members",
    )
    user: models.ForeignKey[UserMirror, UserMirror] = models.ForeignKey(
        UserMirror,
        on_delete=models.CASCADE,
        related_name="team_memberships",
    )
    role: models.CharField[str, str] = models.CharField(
        max_length=16,
        choices=TEAM_MEMBER_ROLE_CHOICES,
        default=TEAM_MEMBER_ROLE_MEMBER,
    )
    added_by: models.CharField[str, str] = models.CharField(max_length=128, blank=True)
    added_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["team", "user"],
                name="teams_team_member_unique",
            ),
            models.CheckConstraint(
                condition=Q(role__in=TEAM_MEMBER_ROLE_VALUES),
                name="teams_team_member_role_supported",
            ),
        ]
        ordering: ClassVar[list[str]] = ["team__name", "role", "user__authentik_user_id"]

    @override
    def __str__(self) -> str:
        return f"{self.team.name}:{self.user.authentik_user_id}:{self.role}"

    @override
    def clean(self) -> None:
        super().clean()
        if self.role not in TEAM_MEMBER_ROLE_VALUES:
            raise ValidationError({"role": "Team member role must be leader or member."})
