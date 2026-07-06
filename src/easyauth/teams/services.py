from __future__ import annotations

from typing import TYPE_CHECKING

from easyauth.accounts.models import USER_STATUS_ACTIVE
from easyauth.teams.models import TEAM_MEMBER_ROLE_LEADER, TeamMember

if TYPE_CHECKING:
    from easyauth.accounts.models import UserMirror


def team_managed_user_ids(user: UserMirror) -> tuple[str, ...]:
    # easyauth_team resolver 语义: 本人为 leader 的所有 active 团队的
    # active 成员并集, 去重并排除本人。纯本地表查询, 不依赖目录新鲜度。
    led_team_ids = TeamMember.objects.filter(
        user=user,
        role=TEAM_MEMBER_ROLE_LEADER,
        team__is_active=True,
    ).values_list("team_id", flat=True)
    member_user_ids = (
        TeamMember.objects.filter(
            team_id__in=led_team_ids,
            user__status=USER_STATUS_ACTIVE,
        )
        .exclude(user=user)
        # 清空模型默认排序: ORDER BY 列会被并入 DISTINCT 的判重键, 导致去重失效。
        .order_by()
        .values_list("user__authentik_user_id", flat=True)
        .distinct()
    )
    return tuple(sorted(member_user_ids))
