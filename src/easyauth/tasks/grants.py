from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from celery import shared_task
from django.db.models import Q
from django.utils import timezone

from easyauth.grants.models import GRANT_STATUS_ACTIVE, AccessGrant
from easyauth.grants.services import GrantExpirationInput, GrantService

if TYPE_CHECKING:
    from datetime import datetime

GRANT_EXPIRATION_TASK_NAME: Final = "easyauth.grants.cleanup_expired_grants"
GRANT_EXPIRATION_REASON: Final = "grant_expiration_cleanup"


@dataclass(frozen=True, slots=True)
class ExpiredGrantCleanupResult:
    expired_grants: tuple[AccessGrant, ...]

    @property
    def expired_count(self) -> int:
        return len(self.expired_grants)


def cleanup_expired_grants(*, now: datetime | None = None) -> ExpiredGrantCleanupResult:
    cutoff = timezone.now() if now is None else now
    candidates = (
        AccessGrant.objects.select_related("user", "app")
        .filter(
            Q(grant_groups__expires_at__lte=cutoff) | Q(grant_permissions__expires_at__lte=cutoff),
            is_current=True,
            status=GRANT_STATUS_ACTIVE,
        )
        .distinct()
        .order_by("app__app_key", "user__authentik_user_id", "id")
    )
    expired: list[AccessGrant] = []
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


@shared_task(name=GRANT_EXPIRATION_TASK_NAME)
def cleanup_expired_grants_task() -> int:
    return cleanup_expired_grants().expired_count
