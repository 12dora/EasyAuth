from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, final, override

from django.db import transaction
from django.utils import timezone

from easyauth.connectors.dispatch import notify_grant_mutation
from easyauth.grants.expiration import GrantExpirationInput, expire_current_grant
from easyauth.grants.inputs import AuthorizationGroupGrantInput, ScopedDirectGrantInput
from easyauth.grants.lifecycle import (
    change_current_grant,
    create_current_grant,
    revoke_current_grant,
    revoke_current_grants_for_user,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from easyauth.accounts.models import UserMirror
    from easyauth.applications.models import App
    from easyauth.grants.models import AccessGrant

type GrantStatus = Literal["active", "revoked", "expired"]

__all__ = [
    "AuthorizationGroupGrantInput",
    "GrantExpirationInput",
    "GrantMutationExpiredError",
    "GrantMutationInput",
    "GrantService",
    "ScopedDirectGrantInput",
]


@dataclass(frozen=True, slots=True)
class GrantMutationExpiredError(Exception):
    message: str = "grant membership expiration must be in the future"

    @override
    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True, slots=True)
class GrantMutationInput:
    user: UserMirror
    app: App
    authorization_groups: Iterable[AuthorizationGroupGrantInput] = ()
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
            input_data = _validated_mutation_input(input_data)
            grant = create_current_grant(input_data, action="grant_created")
            notify_grant_mutation(grant)
            return grant

    @staticmethod
    def change_grant(input_data: GrantMutationInput) -> AccessGrant:
        with transaction.atomic():
            input_data = _validated_mutation_input(input_data)
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


def _validated_mutation_input(input_data: GrantMutationInput) -> GrantMutationInput:
    authorization_groups = tuple(input_data.authorization_groups)
    direct_grants = tuple(input_data.direct_grants)
    if not authorization_groups and not direct_grants:
        message = "grant mutation requires at least one membership"
        raise ValueError(message)

    group_ids = [item.authorization_group.id for item in authorization_groups]
    direct_identities = [(item.permission.id, item.scope_key) for item in direct_grants]
    if len(group_ids) != len(set(group_ids)):
        message = "grant mutation contains duplicate authorization groups"
        raise ValueError(message)
    if len(direct_identities) != len(set(direct_identities)):
        message = "grant mutation contains duplicate direct grants"
        raise ValueError(message)

    now = timezone.now()
    expirations = [
        *(item.expires_at for item in authorization_groups),
        *(item.expires_at for item in direct_grants),
    ]
    if any(expires_at is not None and expires_at <= now for expires_at in expirations):
        raise GrantMutationExpiredError

    return GrantMutationInput(
        user=input_data.user,
        app=input_data.app,
        authorization_groups=authorization_groups,
        direct_grants=direct_grants,
        actor_type=input_data.actor_type,
        actor_id=input_data.actor_id,
    )
