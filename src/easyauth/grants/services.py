from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, final

from django.db import transaction
from django.utils import timezone

from easyauth.grants.models import (
    GRANT_STATUS_ACTIVE,
    GRANT_STATUS_EXPIRED,
    GRANT_STATUS_REVOKED,
    GRANT_TYPE_PERMANENT,
    AccessGrant,
)
from easyauth.grants.operations import (
    current_grant,
    next_version,
    parse_grant_type,
    parse_status,
    record_grant_event,
    replace_memberships,
)

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime

    from easyauth.accounts.models import UserMirror
    from easyauth.applications.models import App, Permission, Role

type GrantStatus = Literal["active", "revoked", "expired"]
type GrantType = Literal["permanent", "timed"]


@dataclass(frozen=True, slots=True)
class GrantMutationInput:
    user: UserMirror
    app: App
    grant_type: GrantType = GRANT_TYPE_PERMANENT
    grant_expires_at: datetime | None = None
    roles: Iterable[Role] = ()
    permissions: Iterable[Permission] = ()
    actor_type: str = "system"
    actor_id: str = "system"


@dataclass(frozen=True, slots=True)
class GrantExpirationInput:
    user: UserMirror
    app: App
    actor_type: str
    actor_id: str
    expires_at_or_before: datetime | None = None
    reason: str = ""


def _create_current_grant(input_data: GrantMutationInput, *, action: str) -> AccessGrant:
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
    replace_memberships(grant, input_data.roles, input_data.permissions)
    record_grant_event(
        grant,
        action=action,
        actor_type=input_data.actor_type,
        actor_id=input_data.actor_id,
    )
    return grant


@final
class GrantService:
    @staticmethod
    def create_grant(input_data: GrantMutationInput) -> AccessGrant:
        with transaction.atomic():
            return _create_current_grant(input_data, action="grant_created")

    @staticmethod
    def change_grant(input_data: GrantMutationInput) -> AccessGrant:
        with transaction.atomic():
            grant = current_grant(input_data.user, input_data.app)
            if grant is None:
                return _create_current_grant(input_data, action="grant_changed")

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
            replace_memberships(grant, input_data.roles, input_data.permissions)
            record_grant_event(
                grant,
                action="grant_changed",
                actor_type=input_data.actor_type,
                actor_id=input_data.actor_id,
            )
            return grant

    @staticmethod
    def revoke_grant(
        *,
        user: UserMirror,
        app: App,
        actor_type: str,
        actor_id: str,
    ) -> AccessGrant | None:
        with transaction.atomic():
            grant = current_grant(user, app)
            if grant is None:
                return None

            match parse_status(grant.status):
                case "active":
                    grant.status = GRANT_STATUS_REVOKED
                case "revoked" | "expired":
                    return None

            grant.is_current = False
            grant.version += 1
            grant.full_clean()
            grant.save(update_fields=["status", "is_current", "version", "updated_at"])
            record_grant_event(
                grant,
                action="grant_revoked",
                actor_type=actor_type,
                actor_id=actor_id,
            )
            return grant

    @staticmethod
    def revoke_for_user(
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
        with transaction.atomic():
            for grant in current_grants:
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
                revoked.append(grant)
        return revoked

    @staticmethod
    def emergency_revoke_for_user(
        *,
        user: UserMirror,
        reason: str,
        actor_type: str,
        actor_id: str,
    ) -> list[AccessGrant]:
        return GrantService.revoke_for_user(
            user=user,
            reason=reason,
            actor_type=actor_type,
            actor_id=actor_id,
        )

    @staticmethod
    def expire_grant(input_data: GrantExpirationInput) -> AccessGrant | None:
        with transaction.atomic():
            grant = current_grant(input_data.user, input_data.app)
            if grant is None:
                return None

            match parse_status(grant.status):
                case "active":
                    pass
                case "revoked" | "expired":
                    return None

            match parse_grant_type(grant.grant_type):
                case "timed":
                    cutoff = (
                        timezone.now()
                        if input_data.expires_at_or_before is None
                        else input_data.expires_at_or_before
                    )
                    grant_expires_at = grant.grant_expires_at
                    if grant_expires_at is None or grant_expires_at > cutoff:
                        return None
                    grant.status = GRANT_STATUS_EXPIRED
                case "permanent":
                    return None

            grant.is_current = False
            grant.version += 1
            grant.full_clean()
            grant.save(update_fields=["status", "is_current", "version", "updated_at"])
            record_grant_event(
                grant,
                action="grant_expired",
                actor_type=input_data.actor_type,
                actor_id=input_data.actor_id,
                reason=input_data.reason,
            )
            return grant
