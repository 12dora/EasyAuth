from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import transaction
from django.utils import timezone

from easyauth.api.datetime_json import datetime_value
from easyauth.audit.services import AuditRecord, AuditService
from easyauth.grants.inputs import AuthorizationGroupGrantInput, ScopedDirectGrantInput
from easyauth.grants.models import (
    MEMBERSHIP_SOURCE_USER,
    AccessGrant,
    AccessGrantGroup,
    AccessGrantPermission,
)
from easyauth.grants.services import GrantMutationInput, GrantService

if TYPE_CHECKING:
    from datetime import datetime

    from easyauth.accounts.models import UserMirror
    from easyauth.admin_console.grant_write_common import ResolvedAdminGrantTargets
    from easyauth.api.errors import JsonValue
    from easyauth.applications.models import App

DIRECT_GRANT_APPLIED_ACTION = "direct_grant_applied"


def apply_admin_direct_grant(
    *,
    user: UserMirror,
    targets: ResolvedAdminGrantTargets,
    actor_id: str,
) -> AccessGrant:
    new_groups = tuple(
        AuthorizationGroupGrantInput(
            authorization_group=group,
            expires_at=targets.grant_expires_at,
            source=MEMBERSHIP_SOURCE_USER,
        )
        for group in targets.authorization_groups
    )
    new_directs = tuple(
        ScopedDirectGrantInput(
            permission=item.permission,
            scope_key=item.scope_key,
            expires_at=targets.grant_expires_at,
            source=MEMBERSHIP_SOURCE_USER,
        )
        for item in targets.direct_grants
    )
    with transaction.atomic():
        desired_groups, desired_directs = _merged_user_memberships(
            user=user,
            app=targets.app,
            new_groups=new_groups,
            new_directs=new_directs,
        )
        grant = GrantService.change_grant(
            GrantMutationInput(
                user=user,
                app=targets.app,
                authorization_groups=desired_groups,
                direct_grants=desired_directs,
                actor_type="admin",
                actor_id=actor_id,
            ),
        )
        _record_direct_grant_applied(
            grant=grant,
            actor_id=actor_id,
            group_keys=tuple(item.authorization_group.key for item in new_groups),
            permission_keys=tuple(item.permission.key for item in new_directs),
            grant_type=targets.grant_type,
            expires_at=targets.grant_expires_at,
            reason=targets.reason,
        )
        return grant


def _merged_user_memberships(
    *,
    user: UserMirror,
    app: App,
    new_groups: tuple[AuthorizationGroupGrantInput, ...],
    new_directs: tuple[ScopedDirectGrantInput, ...],
) -> tuple[tuple[AuthorizationGroupGrantInput, ...], tuple[ScopedDirectGrantInput, ...]]:
    grant = (
        AccessGrant.objects.select_for_update().filter(user=user, app=app, is_current=True).first()
    )
    if grant is None:
        return new_groups, new_directs
    now = timezone.now()
    groups_by_id = _current_user_groups(grant, now=now)
    directs_by_identity = _current_user_directs(grant, now=now)
    for item in new_groups:
        groups_by_id[item.authorization_group.id] = item
    for item in new_directs:
        directs_by_identity[(item.permission.id, item.scope_key)] = item
    return tuple(groups_by_id.values()), tuple(directs_by_identity.values())


def _current_user_groups(
    grant: AccessGrant,
    *,
    now: datetime,
) -> dict[int, AuthorizationGroupGrantInput]:
    groups_by_id: dict[int, AuthorizationGroupGrantInput] = {}
    rows = AccessGrantGroup.objects.filter(
        grant=grant, source=MEMBERSHIP_SOURCE_USER
    ).select_related(
        "authorization_group",
    )
    for row in rows:
        if row.expires_at is not None and row.expires_at <= now:
            continue
        groups_by_id[row.authorization_group_id] = AuthorizationGroupGrantInput(
            authorization_group=row.authorization_group,
            expires_at=row.expires_at,
            source=MEMBERSHIP_SOURCE_USER,
        )
    return groups_by_id


def _current_user_directs(
    grant: AccessGrant,
    *,
    now: datetime,
) -> dict[tuple[int, str], ScopedDirectGrantInput]:
    directs_by_identity: dict[tuple[int, str], ScopedDirectGrantInput] = {}
    rows = AccessGrantPermission.objects.filter(
        grant=grant,
        source=MEMBERSHIP_SOURCE_USER,
    ).select_related("permission")
    for row in rows:
        if row.expires_at is not None and row.expires_at <= now:
            continue
        directs_by_identity[(row.permission_id, row.scope_key)] = ScopedDirectGrantInput(
            permission=row.permission,
            scope_key=row.scope_key,
            expires_at=row.expires_at,
            source=MEMBERSHIP_SOURCE_USER,
        )
    return directs_by_identity


def _record_direct_grant_applied(  # noqa: PLR0913 - 审计元数据必须完整记录授权目标和期限。
    *,
    grant: AccessGrant,
    actor_id: str,
    group_keys: tuple[str, ...],
    permission_keys: tuple[str, ...],
    grant_type: str,
    expires_at: datetime | None,
    reason: str,
) -> None:
    metadata: dict[str, JsonValue] = {
        "user_id": grant.user.authentik_user_id,
        "app_key": grant.app.app_key,
        "authorization_group_keys": list(group_keys),
        "permission_keys": list(permission_keys),
        "grant_type": grant_type,
        "expires_at": datetime_value(expires_at),
        "reason": reason,
    }
    _ = AuditService.record(
        AuditRecord(
            actor_type="admin",
            actor_id=actor_id,
            action=DIRECT_GRANT_APPLIED_ACTION,
            target_type="grant",
            target_id=str(grant.id),
            metadata=metadata,
        ),
    )
