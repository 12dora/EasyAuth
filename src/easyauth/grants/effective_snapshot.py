from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from django.db.models import Q
from django.utils import timezone

from easyauth.grants.models import (
    GRANT_STATUS_ACTIVE,
    AccessGrant,
    AccessGrantGroup,
    AccessGrantPermission,
)

if TYPE_CHECKING:
    from datetime import datetime

    from easyauth.accounts.models import UserMirror
    from easyauth.applications.models import App


@dataclass(frozen=True, slots=True)
class EffectiveGrantSnapshot:
    grant: AccessGrant
    group_ids: frozenset[int]
    direct_grants: frozenset[tuple[int, str]]
    membership_expirations: tuple[datetime | None, ...]

    def has_membership(self) -> bool:
        return bool(self.group_ids or self.direct_grants)


def current_effective_grant_snapshot(
    *,
    user: UserMirror,
    app: App,
    for_update: bool = False,
) -> EffectiveGrantSnapshot | None:
    queryset = AccessGrant.objects.filter(
        user=user,
        app=app,
        is_current=True,
        status=GRANT_STATUS_ACTIVE,
    )
    if for_update:
        queryset = queryset.select_for_update()
    grant = queryset.first()
    if grant is None:
        return None
    return effective_grant_snapshot(grant)


def effective_grant_snapshot(grant: AccessGrant) -> EffectiveGrantSnapshot:
    effective = Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())
    group_rows = cast(
        "tuple[tuple[int, datetime | None], ...]",
        tuple(
            AccessGrantGroup.objects.filter(effective, grant=grant).values_list(
                "authorization_group_id",
                "expires_at",
            ),
        ),
    )
    direct_rows = cast(
        "tuple[tuple[int, str, datetime | None], ...]",
        tuple(
            AccessGrantPermission.objects.filter(effective, grant=grant).values_list(
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
            (permission_id, scope_key)
            for permission_id, scope_key, _expires_at in direct_rows
        ),
        membership_expirations=(
            *(_expires_at for _group_id, _expires_at in group_rows),
            *(_expires_at for _permission_id, _scope_key, _expires_at in direct_rows),
        ),
    )
