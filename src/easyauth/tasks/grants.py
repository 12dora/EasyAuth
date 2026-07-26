from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from celery import shared_task
from django.db import connection, transaction
from django.utils import timezone

from easyauth.grants.models import (
    GRANT_STATUS_ACTIVE,
    AccessGrant,
    AccessGrantGroup,
    AccessGrantPermission,
)
from easyauth.grants.services import GrantExpirationInput, GrantService

if TYPE_CHECKING:
    from datetime import datetime

GRANT_EXPIRATION_TASK_NAME: Final = "easyauth.grants.cleanup_expired_grants"
GRANT_EXPIRATION_REASON: Final = "grant_expiration_cleanup"
GRANT_EXPIRATION_BATCH_SIZE: Final = 500


@dataclass(frozen=True, slots=True)
class ExpiredGrantCleanupResult:
    expired_grants: tuple[AccessGrant, ...]

    @property
    def expired_count(self) -> int:
        return len(self.expired_grants)


def cleanup_expired_grants(
    *,
    now: datetime | None = None,
    batch_size: int = GRANT_EXPIRATION_BATCH_SIZE,
) -> ExpiredGrantCleanupResult:
    cutoff = timezone.now() if now is None else now
    if batch_size <= 0:
        return ExpiredGrantCleanupResult(expired_grants=())
    expired: list[AccessGrant] = []
    with transaction.atomic():
        candidate_ids = _expired_candidate_grant_ids(cutoff=cutoff, batch_size=batch_size)
        if not candidate_ids:
            return ExpiredGrantCleanupResult(expired_grants=())
        candidates = (
            AccessGrant.objects.select_related("user", "app")
            .filter(id__in=candidate_ids, is_current=True, status=GRANT_STATUS_ACTIVE)
            .order_by("id")
        )
        if connection.features.has_select_for_update_skip_locked:
            candidates = candidates.select_for_update(skip_locked=True)
        else:
            candidates = candidates.select_for_update()
        for grant in candidates:
            result = GrantService.expire_grant(
                GrantExpirationInput(
                    user=grant.user,
                    app=grant.app,
                    actor_type="system",
                    actor_id="grant-expiration-cleanup",
                    expires_at_or_before=cutoff,
                    reason=GRANT_EXPIRATION_REASON,
                ),
            )
            if result is not None:
                expired.append(result)
    return ExpiredGrantCleanupResult(expired_grants=tuple(expired))


def _expired_candidate_grant_ids(*, cutoff: datetime, batch_size: int) -> tuple[int, ...]:
    group_ids = AccessGrantGroup.objects.filter(
        expires_at__isnull=False,
        expires_at__lte=cutoff,
        grant__is_current=True,
        grant__status=GRANT_STATUS_ACTIVE,
    ).values_list("grant_id", flat=True)[:batch_size]
    permission_ids = AccessGrantPermission.objects.filter(
        expires_at__isnull=False,
        expires_at__lte=cutoff,
        grant__is_current=True,
        grant__status=GRANT_STATUS_ACTIVE,
    ).values_list("grant_id", flat=True)[:batch_size]
    ids = sorted({*group_ids, *permission_ids})
    return tuple(ids[:batch_size])


@shared_task(name=GRANT_EXPIRATION_TASK_NAME)
def cleanup_expired_grants_task() -> int:
    return cleanup_expired_grants().expired_count
