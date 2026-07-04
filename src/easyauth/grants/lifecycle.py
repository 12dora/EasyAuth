from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Protocol

from easyauth.grants.models import GRANT_STATUS_ACTIVE, GRANT_STATUS_REVOKED, AccessGrant
from easyauth.grants.operations import (
    current_grant,
    next_version,
    parse_status,
    record_grant_event,
    replace_memberships,
)

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime

    from easyauth.accounts.models import UserMirror
    from easyauth.applications.models import App, AuthorizationGroup
    from easyauth.grants.inputs import ScopedDirectGrantInput
type GrantType = Literal["permanent", "timed"]


class GrantMutationData(Protocol):
    @property
    def user(self) -> UserMirror: ...

    @property
    def app(self) -> App: ...

    @property
    def grant_type(self) -> GrantType: ...

    @property
    def grant_expires_at(self) -> datetime | None: ...

    @property
    def authorization_groups(self) -> Iterable[AuthorizationGroup]: ...

    @property
    def direct_grants(self) -> Iterable[ScopedDirectGrantInput]: ...

    @property
    def actor_type(self) -> str: ...

    @property
    def actor_id(self) -> str: ...


def create_current_grant(input_data: GrantMutationData, *, action: str) -> AccessGrant:
    grant = AccessGrant(
        user=input_data.user,
        app=input_data.app,
        grant_type=input_data.grant_type,
        grant_expires_at=input_data.grant_expires_at,
        status=GRANT_STATUS_ACTIVE,
        is_current=True,
        version=next_version(input_data.user, input_data.app),
    )
    grant.full_clean()
    grant.save()
    replace_memberships(grant, input_data.authorization_groups, input_data.direct_grants)
    record_grant_event(
        grant,
        action=action,
        actor_type=input_data.actor_type,
        actor_id=input_data.actor_id,
    )
    return grant


def change_current_grant(input_data: GrantMutationData) -> AccessGrant:
    grant = current_grant(input_data.user, input_data.app)
    if grant is None:
        return create_current_grant(input_data, action="grant_changed")

    grant.grant_type = input_data.grant_type
    grant.grant_expires_at = input_data.grant_expires_at
    grant.status = GRANT_STATUS_ACTIVE
    grant.is_current = True
    grant.version += 1
    grant.full_clean()
    grant.save(
        update_fields=[
            "grant_type",
            "grant_expires_at",
            "status",
            "is_current",
            "version",
            "updated_at",
        ],
    )
    replace_memberships(grant, input_data.authorization_groups, input_data.direct_grants)
    record_grant_event(
        grant,
        action="grant_changed",
        actor_type=input_data.actor_type,
        actor_id=input_data.actor_id,
    )
    return grant


def revoke_current_grant(
    *,
    user: UserMirror,
    app: App,
    actor_type: str,
    actor_id: str,
    reason: str = "",
) -> AccessGrant | None:
    grant = current_grant(user, app)
    if grant is None or not can_revoke(grant):
        return None

    revoke_grant(grant, actor_type=actor_type, actor_id=actor_id, reason=reason)
    return grant


def revoke_current_grants_for_user(
    *,
    user: UserMirror,
    reason: str,
    actor_type: str,
    actor_id: str,
) -> list[AccessGrant]:
    revoked: list[AccessGrant] = []
    current_grants = (
        AccessGrant.objects.select_for_update()
        .select_related("app")
        .filter(user=user, is_current=True, status=GRANT_STATUS_ACTIVE)
        .order_by("app__app_key", "id")
    )
    for grant in current_grants:
        revoke_grant(grant, actor_type=actor_type, actor_id=actor_id, reason=reason)
        revoked.append(grant)
    return revoked


def can_revoke(grant: AccessGrant) -> bool:
    match parse_status(grant.status):
        case "active":
            return True
        case "revoked" | "expired":
            return False


def revoke_grant(
    grant: AccessGrant,
    *,
    actor_type: str,
    actor_id: str,
    reason: str = "",
) -> None:
    grant.status = GRANT_STATUS_REVOKED
    grant.is_current = False
    grant.version += 1
    grant.full_clean()
    grant.save(update_fields=["status", "is_current", "version", "updated_at"])
    record_grant_event(
        grant,
        action="grant_revoked",
        actor_type=actor_type,
        actor_id=actor_id,
        reason=reason,
    )
