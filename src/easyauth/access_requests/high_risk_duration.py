from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Final

from django.utils import timezone

from easyauth.applications.models import RoleAccessPolicy

if TYPE_CHECKING:
    from datetime import datetime

    from easyauth.applications.models import Role

HIGH_RISK_DURATION_MESSAGE: Final = "high-risk role max duration exceeded"


def high_risk_duration_error(
    roles: tuple[Role, ...],
    requested_expires_at: datetime | None,
) -> str:
    if requested_expires_at is None:
        return ""
    role_ids = tuple(role.id for role in roles)
    if not role_ids:
        return ""
    policies = RoleAccessPolicy.objects.select_related("role").filter(
        role_id__in=role_ids,
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
