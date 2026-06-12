from __future__ import annotations

from dataclasses import dataclass
from typing import Final, final

from django.db import transaction

from easyauth.accounts.models import UserMirror
from easyauth.accounts.status import is_non_active_status
from easyauth.audit.services import AuditRecord, AuditService
from easyauth.grants.services import GrantService
from easyauth.integrations.authentik.payloads import (
    AuthentikPayloadInput,
    AuthentikUserProfile,
    parse_authentik_payload,
)

AUTHENTIK_DEPARTURE_REASON: Final = "authentik_departure"


@dataclass(frozen=True, slots=True)
class AuthentikSyncResult:
    user: UserMirror
    created: bool
    revoked_count: int


@dataclass(frozen=True, slots=True)
class _UserUpsertResult:
    user: UserMirror
    created: bool
    was_non_active: bool


@final
class AuthentikSyncService:
    @staticmethod
    def sync_payload(payload: AuthentikPayloadInput) -> AuthentikSyncResult:
        profile = parse_authentik_payload(payload)
        with transaction.atomic():
            upsert = _upsert_user(profile)
            revoked_count = _revoke_current_grants_for_departed_user(upsert.user)
            if _should_record_departure_event(upsert=upsert, revoked_count=revoked_count):
                _record_departure_event(upsert.user, revoked_count=revoked_count)
            return AuthentikSyncResult(
                user=upsert.user,
                created=upsert.created,
                revoked_count=revoked_count,
            )


def _upsert_user(profile: AuthentikUserProfile) -> _UserUpsertResult:
    user, created = UserMirror.objects.select_for_update().get_or_create(
        authentik_user_id=profile.authentik_user_id,
        defaults={
            "name": profile.name,
            "email": profile.email,
            "department": profile.department,
            "status": profile.status,
        },
    )
    if created:
        return _UserUpsertResult(user=user, created=True, was_non_active=False)

    was_non_active = is_non_active_status(user.status)
    user.name = profile.name
    user.email = profile.email
    user.department = profile.department
    user.status = profile.status
    user.full_clean()
    user.save(update_fields=["name", "email", "department", "status", "updated_at"])
    return _UserUpsertResult(user=user, created=False, was_non_active=was_non_active)


def _revoke_current_grants_for_departed_user(user: UserMirror) -> int:
    if not is_non_active_status(user.status):
        return 0

    revoked_grants = GrantService.revoke_for_user(
        user=user,
        reason=AUTHENTIK_DEPARTURE_REASON,
        actor_type="authentik",
        actor_id=user.authentik_user_id,
    )
    return len(revoked_grants)


def _should_record_departure_event(*, upsert: _UserUpsertResult, revoked_count: int) -> bool:
    if not is_non_active_status(upsert.user.status):
        return False
    return revoked_count > 0 or not upsert.was_non_active


def _record_departure_event(user: UserMirror, *, revoked_count: int) -> None:
    _ = AuditService.record(
        AuditRecord(
            actor_type="authentik",
            actor_id=user.authentik_user_id,
            action="user_departure_detected",
            target_type="user",
            target_id=user.authentik_user_id,
            metadata={
                "user_id": user.authentik_user_id,
                "status": user.status,
                "revoked_count": revoked_count,
            },
        ),
    )
