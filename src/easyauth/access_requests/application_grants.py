from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol, cast, override

from django.utils import timezone

from easyauth.access_requests.application_target_validation import apply_target_errors
from easyauth.access_requests.models import (
    AccessRequest,
    AccessRequestGroup,
    AccessRequestGroupGrantSnapshot,
    AccessRequestPermission,
)
from easyauth.access_requests.submission_types import ScopedAccessRequestGrant
from easyauth.access_requests.submission_validation import validated_request_type
from easyauth.applications.models import Permission
from easyauth.grants.effective_snapshot import EffectiveGrantSnapshot, effective_grant_snapshot
from easyauth.grants.models import (
    GRANT_STATUS_ACTIVE,
    AccessGrant,
    AccessGrantGroup,
    AccessGrantPermission,
)
from easyauth.grants.services import (
    GrantMutationExpiredError,
    GrantMutationInput,
    GrantService,
    ScopedDirectGrantInput,
)

if TYPE_CHECKING:
    from datetime import datetime

    from easyauth.access_requests.submission_types import AccessRequestType

CURRENT_GRANT_REQUIRED_MESSAGE: Final = "current active grant is required"
BASE_GRANT_CONFLICT_MESSAGE: Final = "base grant revision conflict"
TARGET_CONFIGURATION_REQUIRED_MESSAGE: Final = "target configuration is no longer valid"


@dataclass(frozen=True, slots=True)
class GrantApplyFailureError(Exception):
    message: str

    @override
    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True, slots=True)
class GrantBaseRevisionConflictError(Exception):
    message: str = BASE_GRANT_CONFLICT_MESSAGE

    @override
    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True, slots=True)
class _GrantLifecycle:
    grant_expires_at: datetime | None


class _GrantApplicationInput(Protocol):
    @property
    def actor_type(self) -> str: ...

    @property
    def actor_id(self) -> str: ...

    @property
    def reason(self) -> str: ...


def apply_grant_fact(
    access_request: AccessRequest,
    input_data: _GrantApplicationInput,
) -> AccessGrant:
    _validate_request_scope(access_request)
    authorization_group_ids = _selected_authorization_group_ids(access_request)
    direct_grants = _selected_direct_grants(access_request)
    request_type = validated_request_type(access_request.request_type)
    if (
        request_type != "revoke"
        and access_request.grant_expires_at is not None
        and access_request.grant_expires_at <= timezone.now()
    ):
        raise GrantMutationExpiredError
    if apply_target_errors(access_request.app, request_type, (), direct_grants):
        raise GrantApplyFailureError(TARGET_CONFIGURATION_REQUIRED_MESSAGE)
    return _apply_validated_grant_request(
        access_request=access_request,
        input_data=input_data,
        authorization_group_ids=authorization_group_ids,
        direct_grants=direct_grants,
        request_type=request_type,
    )


def _apply_validated_grant_request(
    *,
    access_request: AccessRequest,
    input_data: _GrantApplicationInput,
    authorization_group_ids: tuple[int, ...],
    direct_grants: tuple[ScopedAccessRequestGrant, ...],
    request_type: AccessRequestType,
) -> AccessGrant:
    match request_type:
        case "grant":
            return _create_request_grant(
                access_request,
                input_data,
                authorization_group_ids,
                direct_grants,
            )
        case "change":
            _ = _base_current_snapshot(access_request)
            return _change_request_grant(
                access_request,
                input_data,
                authorization_group_ids,
                direct_grants,
            )
        case "renew":
            return _apply_renew_request(
                access_request,
                input_data,
                authorization_group_ids,
                direct_grants,
            )
        case "revoke":
            return _apply_revoke_request(
                access_request,
                input_data,
                authorization_group_ids,
                direct_grants,
            )


def _create_request_grant(
    access_request: AccessRequest,
    input_data: _GrantApplicationInput,
    authorization_group_ids: tuple[int, ...],
    direct_grants: tuple[ScopedAccessRequestGrant, ...],
) -> AccessGrant:
    return GrantService.create_grant(
        _request_grant_mutation_input(
            access_request,
            input_data,
            authorization_group_ids,
            direct_grants,
        ),
    )


def _change_request_grant(
    access_request: AccessRequest,
    input_data: _GrantApplicationInput,
    authorization_group_ids: tuple[int, ...],
    direct_grants: tuple[ScopedAccessRequestGrant, ...],
) -> AccessGrant:
    return GrantService.change_grant(
        _request_grant_mutation_input(
            access_request,
            input_data,
            authorization_group_ids,
            direct_grants,
        ),
    )


def _apply_renew_request(
    access_request: AccessRequest,
    input_data: _GrantApplicationInput,
    authorization_group_ids: tuple[int, ...],
    direct_grants: tuple[ScopedAccessRequestGrant, ...],
) -> AccessGrant:
    current = _base_current_snapshot(access_request)
    _validate_renew_target(
        current,
        authorization_group_ids,
        direct_grants,
        access_request.grant_expires_at,
    )
    return _change_request_grant(access_request, input_data, authorization_group_ids, direct_grants)


def _validate_request_scope(access_request: AccessRequest) -> None:
    match access_request.user.status:
        case "active":
            pass
        case _:
            raise GrantApplyFailureError(CURRENT_GRANT_REQUIRED_MESSAGE)
    if not access_request.app.is_active:
        raise GrantApplyFailureError(CURRENT_GRANT_REQUIRED_MESSAGE)


def _validate_group_snapshot_present(
    access_request: AccessRequest,
    authorization_group_ids: tuple[int, ...],
) -> None:
    target_group_ids = set(authorization_group_ids)
    if not target_group_ids:
        return
    snapshot_group_ids = set(
        AccessRequestGroupGrantSnapshot.objects.filter(
            access_request=access_request,
            authorization_group_id_snapshot__in=target_group_ids,
        ).values_list("authorization_group_id_snapshot", flat=True),
    )
    if target_group_ids == snapshot_group_ids:
        return
    raise GrantApplyFailureError(TARGET_CONFIGURATION_REQUIRED_MESSAGE)


def _apply_revoke_request(
    access_request: AccessRequest,
    input_data: _GrantApplicationInput,
    authorization_group_ids: tuple[int, ...],
    direct_grants: tuple[ScopedAccessRequestGrant, ...],
) -> AccessGrant:
    current = _base_current_snapshot(access_request)
    if authorization_group_ids or direct_grants:
        _validate_revoke_target(current, authorization_group_ids, direct_grants)
        return GrantService.change_grant(
            _current_membership_mutation_input(
                access_request,
                input_data,
                authorization_group_ids,
                direct_grants,
                current,
            ),
        )
    revoked = GrantService.revoke_grant(
        user=access_request.user,
        app=access_request.app,
        actor_type=input_data.actor_type,
        actor_id=input_data.actor_id,
        reason=input_data.reason,
    )
    if revoked is None:
        raise GrantApplyFailureError(CURRENT_GRANT_REQUIRED_MESSAGE)
    return revoked


def _request_grant_mutation_input(
    access_request: AccessRequest,
    input_data: _GrantApplicationInput,
    authorization_group_ids: tuple[int, ...],
    direct_grants: tuple[ScopedAccessRequestGrant, ...],
) -> GrantMutationInput:
    _validate_group_snapshot_present(access_request, authorization_group_ids)
    return _grant_mutation_input(
        access_request,
        input_data,
        _expanded_snapshot_direct_grants(access_request, direct_grants, authorization_group_ids),
        _request_grant_lifecycle(access_request),
    )


def _request_grant_lifecycle(access_request: AccessRequest) -> _GrantLifecycle:
    return _GrantLifecycle(
        grant_expires_at=access_request.grant_expires_at,
    )


def _base_current_snapshot(access_request: AccessRequest) -> EffectiveGrantSnapshot:
    if access_request.base_grant_id is None or access_request.base_grant_revision is None:
        raise GrantBaseRevisionConflictError
    grant = (
        AccessGrant.objects.select_for_update()
        .filter(id=access_request.base_grant_id, user=access_request.user, app=access_request.app)
        .first()
    )
    if grant is None:
        raise GrantBaseRevisionConflictError
    if not grant.is_current or grant.status != GRANT_STATUS_ACTIVE:
        raise GrantBaseRevisionConflictError
    if grant.version != access_request.base_grant_revision:
        raise GrantBaseRevisionConflictError
    snapshot = effective_grant_snapshot(grant)
    if not snapshot.has_membership():
        raise GrantBaseRevisionConflictError
    return snapshot


def _validate_revoke_target(
    current: EffectiveGrantSnapshot,
    authorization_group_ids: tuple[int, ...],
    direct_grants: tuple[ScopedAccessRequestGrant, ...],
) -> None:
    current_group_ids = set(current.group_ids)
    target_group_ids = set(authorization_group_ids)
    if not target_group_ids.issubset(current_group_ids):
        raise GrantBaseRevisionConflictError
    current_direct_grants = set(current.direct_grants)
    target_direct_grants = _target_direct_grants(direct_grants)
    if not target_direct_grants.issubset(current_direct_grants):
        raise GrantBaseRevisionConflictError
    if target_group_ids == current_group_ids and target_direct_grants == current_direct_grants:
        raise GrantApplyFailureError(CURRENT_GRANT_REQUIRED_MESSAGE)


def _validate_renew_target(
    current: EffectiveGrantSnapshot,
    authorization_group_ids: tuple[int, ...],
    direct_grants: tuple[ScopedAccessRequestGrant, ...],
    requested_expires_at: datetime | None,
) -> None:
    if set(authorization_group_ids) != set(current.group_ids):
        raise GrantBaseRevisionConflictError
    if _target_direct_grants(direct_grants) != set(current.direct_grants):
        raise GrantBaseRevisionConflictError
    current_expirations = current.membership_expirations
    if not current_expirations or requested_expires_at is None:
        raise GrantApplyFailureError(CURRENT_GRANT_REQUIRED_MESSAGE)
    if any(expires_at is None for expires_at in current_expirations):
        raise GrantApplyFailureError(CURRENT_GRANT_REQUIRED_MESSAGE)
    if any(requested_expires_at <= expires_at for expires_at in current_expirations if expires_at):
        raise GrantApplyFailureError(CURRENT_GRANT_REQUIRED_MESSAGE)


def _target_direct_grants(
    direct_grants: tuple[ScopedAccessRequestGrant, ...],
) -> set[tuple[int, str]]:
    return {(grant.permission.id, grant.scope_key) for grant in direct_grants}


def _grant_mutation_input(
    access_request: AccessRequest,
    input_data: _GrantApplicationInput,
    direct_grants: tuple[ScopedAccessRequestGrant, ...],
    lifecycle: _GrantLifecycle,
) -> GrantMutationInput:
    return GrantMutationInput(
        user=access_request.user,
        app=access_request.app,
        direct_grants=tuple(
            ScopedDirectGrantInput(
                permission=direct_grant.permission,
                scope_key=direct_grant.scope_key,
                expires_at=lifecycle.grant_expires_at,
            )
            for direct_grant in direct_grants
        ),
        actor_type=input_data.actor_type,
        actor_id=input_data.actor_id,
    )


def _current_membership_mutation_input(
    access_request: AccessRequest,
    input_data: _GrantApplicationInput,
    authorization_group_ids: tuple[int, ...],
    direct_grants: tuple[ScopedAccessRequestGrant, ...],
    current: EffectiveGrantSnapshot,
) -> GrantMutationInput:
    _validate_group_snapshot_present(access_request, authorization_group_ids)
    group_expiration_rows = cast(
        "tuple[tuple[int, datetime | None], ...]",
        tuple(
            AccessGrantGroup.objects.filter(grant=current.grant)
            .values_list(
                "authorization_group_id",
                "expires_at",
            )
        ),
    )
    group_expirations = dict(group_expiration_rows)
    direct_expiration_rows = cast(
        "tuple[tuple[int, str, datetime | None], ...]",
        tuple(
            AccessGrantPermission.objects.filter(grant=current.grant).values_list(
                "permission_id",
                "scope_key",
                "expires_at",
            ),
        ),
    )
    direct_expirations = {
        (permission_id, scope_key): expires_at
        for permission_id, scope_key, expires_at in direct_expiration_rows
    }
    snapshot_direct_grants = _snapshot_direct_grant_inputs(
        access_request,
        group_expirations,
        authorization_group_ids,
    )
    selected_direct_grants = tuple(
        ScopedDirectGrantInput(
            direct_grant.permission,
            direct_grant.scope_key,
            direct_expirations[(direct_grant.permission.id, direct_grant.scope_key)],
        )
        for direct_grant in direct_grants
    )
    direct_inputs = {
        (item.permission.id, item.scope_key): item
        for item in (*snapshot_direct_grants, *selected_direct_grants)
    }
    return GrantMutationInput(
        user=access_request.user,
        app=access_request.app,
        authorization_groups=(),
        direct_grants=tuple(direct_inputs.values()),
        actor_type=input_data.actor_type,
        actor_id=input_data.actor_id,
    )


def _selected_authorization_group_ids(access_request: AccessRequest) -> tuple[int, ...]:
    snapshot_group_ids = tuple(
        AccessRequestGroupGrantSnapshot.objects.filter(access_request=access_request)
        .order_by("authorization_group_id_snapshot")
        .values_list("authorization_group_id_snapshot", flat=True)
        .distinct()
    )
    if snapshot_group_ids:
        return snapshot_group_ids
    return tuple(
        AccessRequestGroup.objects.filter(access_request=access_request)
        .order_by("authorization_group_id")
        .values_list("authorization_group_id", flat=True)
    )


def _selected_direct_grants(access_request: AccessRequest) -> tuple[ScopedAccessRequestGrant, ...]:
    return tuple(
        ScopedAccessRequestGrant(permission=link.permission, scope_key=link.scope_key)
        for link in AccessRequestPermission.objects.select_related("permission").filter(
            access_request=access_request,
        )
    )


def _expanded_snapshot_direct_grants(
    access_request: AccessRequest,
    direct_grants: tuple[ScopedAccessRequestGrant, ...],
    authorization_group_ids: tuple[int, ...],
) -> tuple[ScopedAccessRequestGrant, ...]:
    direct_by_identity = {
        (direct_grant.permission.id, direct_grant.scope_key): direct_grant
        for direct_grant in direct_grants
    }
    target_group_ids = set(authorization_group_ids)
    snapshots = tuple(
        AccessRequestGroupGrantSnapshot.objects.filter(
            access_request=access_request,
            authorization_group_id_snapshot__in=target_group_ids,
        ).order_by("authorization_group_id_snapshot", "permission_key", "scope_key")
    )
    if not snapshots:
        return tuple(
            direct_by_identity[identity]
            for identity in sorted(
                direct_by_identity,
                key=lambda identity: (
                    direct_by_identity[identity].permission.key,
                    direct_by_identity[identity].scope_key,
                ),
            )
        )
    permissions = _snapshot_permissions_by_key(access_request, snapshots)
    for snapshot in snapshots:
        permission = permissions.get(snapshot.permission_key)
        if permission is None:
            raise GrantApplyFailureError(TARGET_CONFIGURATION_REQUIRED_MESSAGE)
        direct_by_identity[(permission.id, snapshot.scope_key)] = ScopedAccessRequestGrant(
            permission=permission,
            scope_key=snapshot.scope_key,
        )
    return tuple(
        direct_by_identity[identity]
        for identity in sorted(
            direct_by_identity,
            key=lambda identity: (
                direct_by_identity[identity].permission.key,
                direct_by_identity[identity].scope_key,
            ),
        )
    )


def _snapshot_permissions_by_key(
    access_request: AccessRequest,
    snapshots: tuple[AccessRequestGroupGrantSnapshot, ...],
) -> dict[str, Permission]:
    permission_keys = tuple({snapshot.permission_key for snapshot in snapshots})
    permissions = Permission.objects.filter(
        app=access_request.app,
        key__in=permission_keys,
    ).order_by("key")
    return {permission.key: permission for permission in permissions}


def _snapshot_direct_grant_inputs(
    access_request: AccessRequest,
    group_expirations: dict[int, datetime | None],
    authorization_group_ids: tuple[int, ...],
) -> tuple[ScopedDirectGrantInput, ...]:
    target_group_ids = set(authorization_group_ids)
    snapshots = tuple(
        AccessRequestGroupGrantSnapshot.objects.filter(
            access_request=access_request,
            authorization_group_id_snapshot__in=target_group_ids,
        ).order_by("authorization_group_id_snapshot", "permission_key", "scope_key")
    )
    permissions = _snapshot_permissions_by_key(access_request, snapshots)
    direct_inputs: dict[tuple[int, str], ScopedDirectGrantInput] = {}
    for snapshot in snapshots:
        permission = permissions.get(snapshot.permission_key)
        if permission is None or snapshot.authorization_group_id_snapshot not in group_expirations:
            raise GrantApplyFailureError(TARGET_CONFIGURATION_REQUIRED_MESSAGE)
        direct_inputs[(permission.id, snapshot.scope_key)] = ScopedDirectGrantInput(
            permission,
            snapshot.scope_key,
            group_expirations[snapshot.authorization_group_id_snapshot],
        )
    return tuple(direct_inputs.values())
