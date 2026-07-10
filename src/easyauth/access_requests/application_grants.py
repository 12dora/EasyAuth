from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol, override

from django.db.models import Q
from django.utils import timezone

from easyauth.access_requests.application_target_validation import apply_target_errors
from easyauth.access_requests.models import (
    AccessRequest,
    AccessRequestGroup,
    AccessRequestPermission,
)
from easyauth.access_requests.submission_types import ScopedAccessRequestGrant
from easyauth.access_requests.submission_validation import validated_request_type
from easyauth.grants.models import AccessGrantGroup, AccessGrantPermission
from easyauth.grants.operations import current_grant
from easyauth.grants.services import (
    AuthorizationGroupGrantInput,
    GrantMutationExpiredError,
    GrantMutationInput,
    GrantService,
    ScopedDirectGrantInput,
)

if TYPE_CHECKING:
    from datetime import datetime

    from easyauth.access_requests.submission_types import AccessRequestType
    from easyauth.applications.models import AuthorizationGroup
    from easyauth.grants.models import AccessGrant

CURRENT_GRANT_REQUIRED_MESSAGE: Final = "current active grant is required"
TARGET_CONFIGURATION_REQUIRED_MESSAGE: Final = "target configuration is no longer valid"


@dataclass(frozen=True, slots=True)
class GrantApplyFailureError(Exception):
    message: str

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
    authorization_groups = _selected_authorization_groups(access_request)
    direct_grants = _selected_direct_grants(access_request)
    request_type = validated_request_type(access_request.request_type)
    if (
        request_type != "revoke"
        and access_request.grant_expires_at is not None
        and access_request.grant_expires_at <= timezone.now()
    ):
        raise GrantMutationExpiredError
    if apply_target_errors(access_request.app, request_type, authorization_groups, direct_grants):
        raise GrantApplyFailureError(TARGET_CONFIGURATION_REQUIRED_MESSAGE)
    return _apply_validated_grant_request(
        access_request=access_request,
        input_data=input_data,
        authorization_groups=authorization_groups,
        direct_grants=direct_grants,
        request_type=request_type,
    )


def _apply_validated_grant_request(
    *,
    access_request: AccessRequest,
    input_data: _GrantApplicationInput,
    authorization_groups: tuple[AuthorizationGroup, ...],
    direct_grants: tuple[ScopedAccessRequestGrant, ...],
    request_type: AccessRequestType,
) -> AccessGrant:
    match request_type:
        case "grant":
            return _create_request_grant(
                access_request,
                input_data,
                authorization_groups,
                direct_grants,
            )
        case "change":
            _ = _active_current_grant(access_request)
            return _change_request_grant(
                access_request,
                input_data,
                authorization_groups,
                direct_grants,
            )
        case "renew":
            return _apply_renew_request(
                access_request,
                input_data,
                authorization_groups,
                direct_grants,
            )
        case "revoke":
            return _apply_revoke_request(
                access_request,
                input_data,
                authorization_groups,
                direct_grants,
            )


def _create_request_grant(
    access_request: AccessRequest,
    input_data: _GrantApplicationInput,
    authorization_groups: tuple[AuthorizationGroup, ...],
    direct_grants: tuple[ScopedAccessRequestGrant, ...],
) -> AccessGrant:
    return GrantService.create_grant(
        _request_grant_mutation_input(
            access_request,
            input_data,
            authorization_groups,
            direct_grants,
        ),
    )


def _change_request_grant(
    access_request: AccessRequest,
    input_data: _GrantApplicationInput,
    authorization_groups: tuple[AuthorizationGroup, ...],
    direct_grants: tuple[ScopedAccessRequestGrant, ...],
) -> AccessGrant:
    return GrantService.change_grant(
        _request_grant_mutation_input(
            access_request,
            input_data,
            authorization_groups,
            direct_grants,
        ),
    )


def _apply_renew_request(
    access_request: AccessRequest,
    input_data: _GrantApplicationInput,
    authorization_groups: tuple[AuthorizationGroup, ...],
    direct_grants: tuple[ScopedAccessRequestGrant, ...],
) -> AccessGrant:
    current = _active_current_grant(access_request)
    _validate_renew_target(
        current,
        authorization_groups,
        direct_grants,
        access_request.grant_expires_at,
    )
    return _change_request_grant(access_request, input_data, authorization_groups, direct_grants)


def _validate_request_scope(access_request: AccessRequest) -> None:
    match access_request.user.status:
        case "active":
            pass
        case _:
            raise GrantApplyFailureError(CURRENT_GRANT_REQUIRED_MESSAGE)
    if not access_request.app.is_active:
        raise GrantApplyFailureError(CURRENT_GRANT_REQUIRED_MESSAGE)


def _apply_revoke_request(
    access_request: AccessRequest,
    input_data: _GrantApplicationInput,
    authorization_groups: tuple[AuthorizationGroup, ...],
    direct_grants: tuple[ScopedAccessRequestGrant, ...],
) -> AccessGrant:
    current = _active_current_grant(access_request)
    if authorization_groups or direct_grants:
        _validate_revoke_target(current, authorization_groups, direct_grants)
        return GrantService.change_grant(
            _current_membership_mutation_input(
                access_request,
                input_data,
                authorization_groups,
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
    authorization_groups: tuple[AuthorizationGroup, ...],
    direct_grants: tuple[ScopedAccessRequestGrant, ...],
) -> GrantMutationInput:
    return _grant_mutation_input(
        access_request,
        input_data,
        authorization_groups,
        direct_grants,
        _request_grant_lifecycle(access_request),
    )


def _request_grant_lifecycle(access_request: AccessRequest) -> _GrantLifecycle:
    return _GrantLifecycle(
        grant_expires_at=access_request.grant_expires_at,
    )


def _active_current_grant(access_request: AccessRequest) -> AccessGrant:
    grant = current_grant(access_request.user, access_request.app)
    if grant is None:
        raise GrantApplyFailureError(CURRENT_GRANT_REQUIRED_MESSAGE)
    match grant.status:
        case "active":
            pass
        case _:
            raise GrantApplyFailureError(CURRENT_GRANT_REQUIRED_MESSAGE)
    if not _grant_has_effective_membership(grant):
        raise GrantApplyFailureError(CURRENT_GRANT_REQUIRED_MESSAGE)
    return grant


def _validate_revoke_target(
    current: AccessGrant,
    authorization_groups: tuple[AuthorizationGroup, ...],
    direct_grants: tuple[ScopedAccessRequestGrant, ...],
) -> None:
    current_group_ids = _current_group_ids(current)
    target_group_ids = {group.id for group in authorization_groups}
    if not target_group_ids.issubset(current_group_ids):
        raise GrantApplyFailureError(CURRENT_GRANT_REQUIRED_MESSAGE)
    current_direct_grants = _current_direct_grants(current)
    target_direct_grants = _target_direct_grants(direct_grants)
    if not target_direct_grants.issubset(current_direct_grants):
        raise GrantApplyFailureError(CURRENT_GRANT_REQUIRED_MESSAGE)
    if target_group_ids == current_group_ids and target_direct_grants == current_direct_grants:
        raise GrantApplyFailureError(CURRENT_GRANT_REQUIRED_MESSAGE)


def _validate_renew_target(
    current: AccessGrant,
    authorization_groups: tuple[AuthorizationGroup, ...],
    direct_grants: tuple[ScopedAccessRequestGrant, ...],
    requested_expires_at: datetime | None,
) -> None:
    if {group.id for group in authorization_groups} != _current_group_ids(current):
        raise GrantApplyFailureError(CURRENT_GRANT_REQUIRED_MESSAGE)
    if _target_direct_grants(direct_grants) != _current_direct_grants(current):
        raise GrantApplyFailureError(CURRENT_GRANT_REQUIRED_MESSAGE)
    current_expirations = _current_membership_expirations(current)
    if not current_expirations or requested_expires_at is None:
        raise GrantApplyFailureError(CURRENT_GRANT_REQUIRED_MESSAGE)
    if any(expires_at is None for expires_at in current_expirations):
        raise GrantApplyFailureError(CURRENT_GRANT_REQUIRED_MESSAGE)
    if any(requested_expires_at <= expires_at for expires_at in current_expirations if expires_at):
        raise GrantApplyFailureError(CURRENT_GRANT_REQUIRED_MESSAGE)


def _current_group_ids(grant: AccessGrant) -> set[int]:
    effective = Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())
    return set(
        AccessGrantGroup.objects.filter(effective, grant=grant).values_list(
            "authorization_group_id",
            flat=True,
        ),
    )


def _current_direct_grants(grant: AccessGrant) -> set[tuple[int, str]]:
    effective = Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())
    return set(
        AccessGrantPermission.objects.filter(effective, grant=grant).values_list(
            "permission_id",
            "scope_key",
        ),
    )


def _target_direct_grants(
    direct_grants: tuple[ScopedAccessRequestGrant, ...],
) -> set[tuple[int, str]]:
    return {(grant.permission.id, grant.scope_key) for grant in direct_grants}


def _grant_mutation_input(
    access_request: AccessRequest,
    input_data: _GrantApplicationInput,
    authorization_groups: tuple[AuthorizationGroup, ...],
    direct_grants: tuple[ScopedAccessRequestGrant, ...],
    lifecycle: _GrantLifecycle,
) -> GrantMutationInput:
    return GrantMutationInput(
        user=access_request.user,
        app=access_request.app,
        authorization_groups=tuple(
            AuthorizationGroupGrantInput(
                authorization_group=authorization_group,
                expires_at=lifecycle.grant_expires_at,
            )
            for authorization_group in authorization_groups
        ),
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
    authorization_groups: tuple[AuthorizationGroup, ...],
    direct_grants: tuple[ScopedAccessRequestGrant, ...],
    current: AccessGrant,
) -> GrantMutationInput:
    group_expirations = dict(
        AccessGrantGroup.objects.filter(grant=current).values_list(
            "authorization_group_id",
            "expires_at",
        ),
    )
    direct_expirations = {
        (permission_id, scope_key): expires_at
        for permission_id, scope_key, expires_at in AccessGrantPermission.objects.filter(
            grant=current,
        ).values_list("permission_id", "scope_key", "expires_at")
    }
    return GrantMutationInput(
        user=access_request.user,
        app=access_request.app,
        authorization_groups=tuple(
            AuthorizationGroupGrantInput(group, group_expirations[group.id])
            for group in authorization_groups
        ),
        direct_grants=tuple(
            ScopedDirectGrantInput(
                direct_grant.permission,
                direct_grant.scope_key,
                direct_expirations[(direct_grant.permission.id, direct_grant.scope_key)],
            )
            for direct_grant in direct_grants
        ),
        actor_type=input_data.actor_type,
        actor_id=input_data.actor_id,
    )


def _grant_has_effective_membership(grant: AccessGrant) -> bool:
    effective = Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())
    return AccessGrantGroup.objects.filter(effective, grant=grant).exists() or (
        AccessGrantPermission.objects.filter(effective, grant=grant).exists()
    )


def _current_membership_expirations(grant: AccessGrant) -> tuple[datetime | None, ...]:
    effective = Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())
    group_expirations = AccessGrantGroup.objects.filter(effective, grant=grant).values_list(
        "expires_at",
        flat=True,
    )
    direct_expirations = AccessGrantPermission.objects.filter(effective, grant=grant).values_list(
        "expires_at",
        flat=True,
    )
    return (*group_expirations, *direct_expirations)


def _selected_authorization_groups(access_request: AccessRequest) -> tuple[AuthorizationGroup, ...]:
    return tuple(
        link.authorization_group
        for link in AccessRequestGroup.objects.select_related("authorization_group").filter(
            access_request=access_request,
        )
    )


def _selected_direct_grants(access_request: AccessRequest) -> tuple[ScopedAccessRequestGrant, ...]:
    return tuple(
        ScopedAccessRequestGrant(permission=link.permission, scope_key=link.scope_key)
        for link in AccessRequestPermission.objects.select_related("permission").filter(
            access_request=access_request,
        )
    )
