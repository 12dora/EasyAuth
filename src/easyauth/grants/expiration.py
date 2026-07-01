from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.utils import timezone

from easyauth.grants.models import GRANT_STATUS_EXPIRED, AccessGrant
from easyauth.grants.operations import (
    current_grant,
    parse_grant_type,
    parse_status,
    record_grant_event,
)

if TYPE_CHECKING:
    from datetime import datetime

    from easyauth.accounts.models import UserMirror
    from easyauth.applications.models import App


@dataclass(frozen=True, slots=True)
class GrantExpirationInput:
    user: UserMirror
    app: App
    actor_type: str
    actor_id: str
    expires_at_or_before: datetime | None = None
    reason: str = ""


def expire_current_grant(input_data: GrantExpirationInput) -> AccessGrant | None:
    grant = current_grant(input_data.user, input_data.app)
    if grant is None or not can_expire(
        grant,
        expires_at_or_before=input_data.expires_at_or_before,
    ):
        return None

    expire_grant(
        grant,
        actor_type=input_data.actor_type,
        actor_id=input_data.actor_id,
        reason=input_data.reason,
    )
    return grant


def can_expire(
    grant: AccessGrant,
    *,
    expires_at_or_before: datetime | None = None,
) -> bool:
    match parse_status(grant.status):
        case "active":
            pass
        case "revoked" | "expired":
            return False

    match parse_grant_type(grant.grant_type):
        case "timed":
            cutoff = timezone.now() if expires_at_or_before is None else expires_at_or_before
            grant_expires_at = grant.grant_expires_at
            return grant_expires_at is not None and grant_expires_at <= cutoff
        case "permanent":
            return False


def expire_grant(
    grant: AccessGrant,
    *,
    actor_type: str,
    actor_id: str,
    reason: str = "",
) -> None:
    grant.status = GRANT_STATUS_EXPIRED
    grant.is_current = False
    grant.version += 1
    grant.full_clean()
    grant.save(update_fields=["status", "is_current", "version", "updated_at"])
    record_grant_event(
        grant,
        action="grant_expired",
        actor_type=actor_type,
        actor_id=actor_id,
        reason=reason,
    )
