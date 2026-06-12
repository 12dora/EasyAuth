from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, final

from django.db import transaction

from easyauth.grants.expiration import GrantExpirationInput, expire_current_grant
from easyauth.grants.lifecycle import (
    change_current_grant,
    create_current_grant,
    revoke_current_grant,
    revoke_current_grants_for_user,
)
from easyauth.grants.models import GRANT_TYPE_PERMANENT, AccessGrant

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime

    from easyauth.accounts.models import UserMirror
    from easyauth.applications.models import App, Permission, Role

type GrantStatus = Literal["active", "revoked", "expired"]
type GrantType = Literal["permanent", "timed"]

__all__ = ["GrantExpirationInput", "GrantMutationInput", "GrantService"]


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


@final
class GrantService:
    @staticmethod
    def create_grant(input_data: GrantMutationInput) -> AccessGrant:
        with transaction.atomic():
            return create_current_grant(input_data, action="grant_created")

    @staticmethod
    def change_grant(input_data: GrantMutationInput) -> AccessGrant:
        with transaction.atomic():
            return change_current_grant(input_data)

    @staticmethod
    def revoke_grant(
        *,
        user: UserMirror,
        app: App,
        actor_type: str,
        actor_id: str,
        reason: str = "",
    ) -> AccessGrant | None:
        with transaction.atomic():
            return revoke_current_grant(
                user=user,
                app=app,
                actor_type=actor_type,
                actor_id=actor_id,
                reason=reason,
            )

    @staticmethod
    def revoke_for_user(
        *,
        user: UserMirror,
        reason: str,
        actor_type: str,
        actor_id: str,
    ) -> list[AccessGrant]:
        with transaction.atomic():
            return revoke_current_grants_for_user(
                user=user,
                reason=reason,
                actor_type=actor_type,
                actor_id=actor_id,
            )

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
            return expire_current_grant(input_data)
