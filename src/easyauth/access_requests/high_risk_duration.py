from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Final

from django.utils import timezone

from easyauth.applications.ops_models import AuthorizationGroupAccessPolicy

if TYPE_CHECKING:
    from datetime import datetime

    from easyauth.applications.models import AuthorizationGroup

HIGH_RISK_DURATION_MESSAGE: Final = "high-risk authorization group max duration exceeded"


def high_risk_duration_error(
    authorization_groups: tuple[AuthorizationGroup, ...],
    requested_expires_at: datetime | None,
) -> str:
    if requested_expires_at is None:
        return ""
    group_ids = tuple(group.id for group in authorization_groups)
    if not group_ids:
        return ""
    policies = AuthorizationGroupAccessPolicy.objects.select_related(
        "authorization_group",
    ).filter(
        authorization_group_id__in=group_ids,
        is_high_risk=True,
    )
    max_expires_at_base = timezone.now()
    for policy in policies:
        max_days = policy.max_grant_duration_days
        if max_days is None:
            return HIGH_RISK_DURATION_MESSAGE
        if requested_expires_at > max_expires_at_base + timedelta(days=max_days):
            return HIGH_RISK_DURATION_MESSAGE
    return ""
