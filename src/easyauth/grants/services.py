from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, final

from django.db import transaction

from easyauth.connectors.dispatch import notify_grant_mutation
from easyauth.grants.expiration import GrantExpirationInput, expire_current_grant
from easyauth.grants.inputs import ScopedDirectGrantInput
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
    from easyauth.applications.models import App, AuthorizationGroup

type GrantStatus = Literal["active", "revoked", "expired"]
type GrantType = Literal["permanent", "timed"]

__all__ = [
    "GrantExpirationInput",
    "GrantMutationInput",
    "GrantService",
    "ScopedDirectGrantInput",
]


@dataclass(frozen=True, slots=True)
class GrantMutationInput:
    user: UserMirror
    app: App
    grant_type: GrantType = GRANT_TYPE_PERMANENT
    grant_expires_at: datetime | None = None
    authorization_groups: Iterable[AuthorizationGroup] = ()
    direct_grants: Iterable[ScopedDirectGrantInput] = ()
    actor_type: str = "system"
    actor_id: str = "system"


@final
class GrantService:
    # 授权事实变更的唯一收口(F2): 每个方法在事务内经 notify_grant_mutation 显式埋点,
    # 提交成功后异步触发连接器对账; 连接器失败绝不回滚授权(方案 §3.5)。
    @staticmethod
    def create_grant(input_data: GrantMutationInput) -> AccessGrant:
        with transaction.atomic():
            grant = create_current_grant(input_data, action="grant_created")
            notify_grant_mutation(grant)
            return grant

    @staticmethod
    def change_grant(input_data: GrantMutationInput) -> AccessGrant:
        with transaction.atomic():
            grant = change_current_grant(input_data)
            notify_grant_mutation(grant)
            return grant

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
            grant = revoke_current_grant(
                user=user,
                app=app,
                actor_type=actor_type,
                actor_id=actor_id,
                reason=reason,
            )
            if grant is not None:
                notify_grant_mutation(grant)
            return grant

    @staticmethod
    def revoke_for_user(
        *,
        user: UserMirror,
        reason: str,
        actor_type: str,
        actor_id: str,
    ) -> list[AccessGrant]:
        with transaction.atomic():
            grants = revoke_current_grants_for_user(
                user=user,
                reason=reason,
                actor_type=actor_type,
                actor_id=actor_id,
            )
            for grant in grants:
                notify_grant_mutation(grant)
            return grants

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
            grant = expire_current_grant(input_data)
            if grant is not None:
                notify_grant_mutation(grant)
            return grant
