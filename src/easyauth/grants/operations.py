from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from django.core.exceptions import ValidationError

from easyauth.audit.services import AuditRecord, AuditService
from easyauth.grants.models import (
    GRANT_TYPE_PERMANENT,
    GRANT_TYPE_TIMED,
    AccessGrant,
    AccessGrantGroup,
    AccessGrantPermission,
)
from easyauth.grants.status import GrantStatus, parse_grant_status

if TYPE_CHECKING:
    from collections.abc import Iterable

    from easyauth.accounts.models import UserMirror
    from easyauth.applications.models import App, AuthorizationGroup
    from easyauth.grants.services import ScopedDirectGrantInput

type GrantType = Literal["permanent", "timed"]


def parse_status(status: str) -> GrantStatus:
    return parse_grant_status(status)


def parse_grant_type(grant_type: str) -> GrantType:
    match grant_type:
        case "permanent":
            return GRANT_TYPE_PERMANENT
        case "timed":
            return GRANT_TYPE_TIMED
        case unsupported:
            raise ValidationError({"grant_type": f"Unsupported grant type: {unsupported}"})


def current_grant(user: UserMirror, app: App) -> AccessGrant | None:
    return (
        AccessGrant.objects.select_for_update()
        .filter(user=user, app=app, is_current=True)
        .first()
    )


def next_version(user: UserMirror, app: App) -> int:
    # 锁定该用户在此 App 的最新授权行, 串行化并发 revoke(就地 +1)与新建授权;
    # (user, app, version) 唯一约束兜底, 并发冲突显式失败而非产生重复版本号。
    latest = (
        AccessGrant.objects.select_for_update()
        .filter(user=user, app=app)
        .order_by("-version", "-id")
        .first()
    )
    if latest is None:
        return 1
    return latest.version + 1


def replace_memberships(
    grant: AccessGrant,
    authorization_groups: Iterable[AuthorizationGroup],
    direct_grants: Iterable[ScopedDirectGrantInput],
) -> None:
    _ = AccessGrantGroup.objects.filter(grant=grant).delete()
    _ = AccessGrantPermission.objects.filter(grant=grant).delete()

    groups_by_id = {group.id: group for group in authorization_groups}
    for group in groups_by_id.values():
        link = AccessGrantGroup(grant=grant, authorization_group=group)
        link.full_clean()
        link.save()

    direct_grants_by_identity = {
        (direct_grant.permission.id, direct_grant.scope_key): direct_grant
        for direct_grant in direct_grants
    }
    for direct_grant in direct_grants_by_identity.values():
        link = AccessGrantPermission(
            grant=grant,
            permission=direct_grant.permission,
            scope_key=direct_grant.scope_key,
        )
        link.full_clean()
        link.save()


def record_grant_event(
    grant: AccessGrant,
    *,
    action: str,
    actor_type: str,
    actor_id: str,
    reason: str = "",
) -> None:
    _ = AuditService.record(
        AuditRecord(
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            target_type="grant",
            target_id=grant_target_id(grant),
            metadata=audit_metadata(grant, reason=reason),
        ),
    )


def audit_metadata(grant: AccessGrant, *, reason: str = "") -> dict[str, str | int]:
    metadata: dict[str, str | int] = {
        "user_id": grant.user.authentik_user_id,
        "app_key": grant.app.app_key,
        "version": grant.version,
    }
    if reason != "":
        metadata["reason"] = reason
    return metadata


def grant_target_id(grant: AccessGrant) -> str:
    return f"{grant.user.authentik_user_id}:{grant.app.app_key}"
