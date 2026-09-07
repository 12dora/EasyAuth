from __future__ import annotations

from typing import TYPE_CHECKING, cast

from django.db.models import Q
from django.utils import timezone

from easyauth.grants.effective_snapshot import EffectiveGrantSnapshot
from easyauth.grants.models import (
    MEMBERSHIP_SOURCE_USER,
    AccessGrant,
    AccessGrantGroup,
    AccessGrantPermission,
)

if TYPE_CHECKING:
    from datetime import datetime


def user_membership_snapshot(grant: AccessGrant) -> EffectiveGrantSnapshot:
    effective = Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())
    group_rows = cast(
        "tuple[tuple[int, datetime | None], ...]",
        tuple(
            AccessGrantGroup.objects.filter(
                effective, grant=grant, source=MEMBERSHIP_SOURCE_USER
            ).values_list(
                "authorization_group_id",
                "expires_at",
            ),
        ),
    )
    direct_rows = cast(
        "tuple[tuple[int, str, datetime | None], ...]",
        tuple(
            AccessGrantPermission.objects.filter(
                effective, grant=grant, source=MEMBERSHIP_SOURCE_USER
            ).values_list(
                "permission_id",
                "scope_key",
                "expires_at",
            ),
        ),
    )
    return EffectiveGrantSnapshot(
        grant=grant,
        group_ids=frozenset(group_id for group_id, _expires_at in group_rows),
        direct_grants=frozenset(
            (permission_id, scope_key) for permission_id, scope_key, _expires_at in direct_rows
        ),
        membership_expirations=(
            *(_expires_at for _group_id, _expires_at in group_rows),
            *(_expires_at for _permission_id, _scope_key, _expires_at in direct_rows),
        ),
    )
