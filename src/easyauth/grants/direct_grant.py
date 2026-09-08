from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, override

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
DIRECT_GRANT_EMPTY_REPLACE_WITHOUT_CURRENT_MESSAGE = "至少选择一个授权组或权限。"


@dataclass(frozen=True, slots=True)
class DirectGrantEmptyReplaceError(Exception):
    message: str = DIRECT_GRANT_EMPTY_REPLACE_WITHOUT_CURRENT_MESSAGE

    @override
    def __str__(self) -> str:
        return self.message


def apply_admin_direct_grant(
    *,
    user: UserMirror,
    targets: ResolvedAdminGrantTargets,
    actor_id: str,
) -> AccessGrant:
    submitted_groups = tuple(
        AuthorizationGroupGrantInput(
            authorization_group=group,
            expires_at=targets.grant_expires_at,
            source=MEMBERSHIP_SOURCE_USER,
        )
        for group in targets.authorization_groups
    )
    submitted_directs = tuple(
        ScopedDirectGrantInput(
            permission=item.permission,
            scope_key=item.scope_key,
            expires_at=targets.grant_expires_at,
            source=MEMBERSHIP_SOURCE_USER,
        )
        for item in targets.direct_grants
    )
    with transaction.atomic():
        current = (
            AccessGrant.objects.select_for_update()
            .filter(user=user, app=targets.app, is_current=True)
            .first()
        )
        existing_groups, existing_directs = _live_user_memberships(current)
        removed_group_keys, removed_permission_keys = _removed_user_membership_keys(
            existing_groups=existing_groups,
            existing_directs=existing_directs,
            submitted_groups=submitted_groups,
            submitted_directs=submitted_directs,
        )
        if not submitted_groups and not submitted_directs:
            grant = _replace_with_empty_user_memberships(
                user=user,
                app=targets.app,
                actor_id=actor_id,
                reason=targets.reason,
                current=current,
            )
        else:
            term_changed = _term_changed(
                existing_groups=existing_groups,
                existing_directs=existing_directs,
                grant_type=targets.grant_type,
                grant_expires_at=targets.grant_expires_at,
            )
            desired_groups, desired_directs = _replaced_user_memberships(
                existing_groups=existing_groups,
                existing_directs=existing_directs,
                submitted_groups=submitted_groups,
                submitted_directs=submitted_directs,
                term_changed=term_changed,
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
            group_keys=tuple(item.authorization_group.key for item in submitted_groups),
            permission_keys=tuple(item.permission.key for item in submitted_directs),
            removed_group_keys=removed_group_keys,
            removed_permission_keys=removed_permission_keys,
            grant_type=targets.grant_type,
            expires_at=targets.grant_expires_at,
            reason=targets.reason,
        )
        return grant


def _replace_with_empty_user_memberships(
    *,
    user: UserMirror,
    app: App,
    actor_id: str,
    reason: str,
    current: AccessGrant | None,
) -> AccessGrant:
    if current is None:
        raise DirectGrantEmptyReplaceError
    grant = GrantService.revoke_user_memberships(
        user=user,
        app=app,
        actor_type="admin",
        actor_id=actor_id,
        reason=reason,
    )
    if grant is None:
        raise DirectGrantEmptyReplaceError
    return grant


def _replaced_user_memberships(
    *,
    existing_groups: dict[int, AuthorizationGroupGrantInput],
    existing_directs: dict[tuple[int, str], ScopedDirectGrantInput],
    submitted_groups: tuple[AuthorizationGroupGrantInput, ...],
    submitted_directs: tuple[ScopedDirectGrantInput, ...],
    term_changed: bool,
) -> tuple[tuple[AuthorizationGroupGrantInput, ...], tuple[ScopedDirectGrantInput, ...]]:
    groups = tuple(
        existing_groups[item.authorization_group.id]
        if item.authorization_group.id in existing_groups and not term_changed
        else item
        for item in submitted_groups
    )
    directs = tuple(
        existing_directs[(item.permission.id, item.scope_key)]
        if (item.permission.id, item.scope_key) in existing_directs and not term_changed
        else item
        for item in submitted_directs
    )
    return groups, directs


def _live_user_memberships(
    grant: AccessGrant | None,
) -> tuple[dict[int, AuthorizationGroupGrantInput], dict[tuple[int, str], ScopedDirectGrantInput]]:
    if grant is None:
        return {}, {}
    now = timezone.now()
    return _current_user_groups(grant, now=now), _current_user_directs(grant, now=now)


def _removed_user_membership_keys(
    *,
    existing_groups: dict[int, AuthorizationGroupGrantInput],
    existing_directs: dict[tuple[int, str], ScopedDirectGrantInput],
    submitted_groups: tuple[AuthorizationGroupGrantInput, ...],
    submitted_directs: tuple[ScopedDirectGrantInput, ...],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    submitted_group_ids = {item.authorization_group.id for item in submitted_groups}
    submitted_direct_identities = {
        (item.permission.id, item.scope_key) for item in submitted_directs
    }
    removed_groups = tuple(
        sorted(
            item.authorization_group.key
            for item in existing_groups.values()
            if item.authorization_group.id not in submitted_group_ids
        )
    )
    removed_permissions = tuple(
        sorted(
            item.permission.key
            for item in existing_directs.values()
            if (item.permission.id, item.scope_key) not in submitted_direct_identities
        )
    )
    return removed_groups, removed_permissions


def _term_changed(
    *,
    existing_groups: dict[int, AuthorizationGroupGrantInput],
    existing_directs: dict[tuple[int, str], ScopedDirectGrantInput],
    grant_type: str,
    grant_expires_at: datetime | None,
) -> bool:
    if not existing_groups and not existing_directs:
        return False
    current_type, current_expires_at = _user_sourced_term(existing_groups, existing_directs)
    return current_type != grant_type or current_expires_at != grant_expires_at


def _user_sourced_term(
    groups: dict[int, AuthorizationGroupGrantInput],
    directs: dict[tuple[int, str], ScopedDirectGrantInput],
) -> tuple[str, datetime | None]:
    expirations = [item.expires_at for item in groups.values()] + [
        item.expires_at for item in directs.values()
    ]
    timed = [item for item in expirations if item is not None]
    if not timed:
        return "permanent", None
    return "timed", min(timed)


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


def _record_direct_grant_applied(  # noqa: PLR0913 - 审计元数据必须完整记录授权目标、期限与被去掉的成员。
    *,
    grant: AccessGrant,
    actor_id: str,
    group_keys: tuple[str, ...],
    permission_keys: tuple[str, ...],
    removed_group_keys: tuple[str, ...],
    removed_permission_keys: tuple[str, ...],
    grant_type: str,
    expires_at: datetime | None,
    reason: str,
) -> None:
    metadata: dict[str, JsonValue] = {
        "user_id": grant.user.authentik_user_id,
        "app_key": grant.app.app_key,
        "authorization_group_keys": list(group_keys),
        "permission_keys": list(permission_keys),
        "removed_authorization_group_keys": list(removed_group_keys),
        "removed_permission_keys": list(removed_permission_keys),
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
