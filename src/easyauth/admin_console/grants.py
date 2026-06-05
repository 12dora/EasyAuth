from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from easyauth.grants.services import GrantService

if TYPE_CHECKING:
    from easyauth.accounts.models import UserMirror
    from easyauth.grants.models import AccessGrant


@dataclass(frozen=True, slots=True)
class EmergencyRevokeResult:
    revoked_grants: tuple[AccessGrant, ...]

    @property
    def revoked_count(self) -> int:
        return len(self.revoked_grants)


def emergency_revoke_for_user(
    *,
    user: UserMirror,
    reason: str,
    actor_id: str,
) -> EmergencyRevokeResult:
    revoked_grants = GrantService.emergency_revoke_for_user(
        user=user,
        reason=reason,
        actor_type="admin",
        actor_id=actor_id,
    )
    return EmergencyRevokeResult(revoked_grants=tuple(revoked_grants))
