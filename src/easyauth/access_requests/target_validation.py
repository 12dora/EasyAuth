from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, override

from easyauth.applications.models import ApprovalRule, AppScope

if TYPE_CHECKING:
    from easyauth.access_requests.submission_types import ScopedAccessRequestGrant
    from easyauth.applications.models import App, AuthorizationGroup


@dataclass(frozen=True, slots=True)
class AccessRequestTargetValidationError(Exception):
    messages: tuple[str, ...]

    @override
    def __str__(self) -> str:
        return "; ".join(self.messages)


def validate_request_targets(
    app: App,
    authorization_groups: tuple[AuthorizationGroup, ...],
    direct_grants: tuple[ScopedAccessRequestGrant, ...],
) -> None:
    errors = (
        *authorization_group_target_errors(app, authorization_groups),
        *direct_grant_target_errors(app, direct_grants),
    )
    if errors:
        raise AccessRequestTargetValidationError(errors)


def authorization_group_target_errors(
    app: App,
    authorization_groups: tuple[AuthorizationGroup, ...],
) -> tuple[str, ...]:
    errors: list[str] = []
    for group in authorization_groups:
        errors.extend(
            f"{group.key}: {message}"
            for message in _authorization_group_error_messages(app, group)
        )
    return tuple(errors)


def direct_grant_target_errors(
    app: App,
    direct_grants: tuple[ScopedAccessRequestGrant, ...],
) -> tuple[str, ...]:
    errors: list[str] = []
    for grant in direct_grants:
        errors.extend(
            f"{grant.permission.key}:{grant.scope_key}: {message}"
            for message in _direct_grant_error_messages(app, grant)
        )
    return tuple(errors)


def _authorization_group_error_messages(app: App, group: AuthorizationGroup) -> tuple[str, ...]:
    errors: list[str] = []
    if group.app_id != app.id:
        errors.append("Authorization group must belong to the access request app.")
    if not group.requestable:
        errors.append("Authorization group must be requestable.")
    if not group.is_active:
        errors.append("Authorization group must be active.")
    if errors:
        return tuple(errors)
    if not ApprovalRule.objects.filter(
        app=app,
        authorization_group=group,
        is_active=True,
    ).exists():
        errors.append("Authorization group must have an active approval rule.")
    return tuple(errors)


def _direct_grant_error_messages(
    app: App,
    direct_grant: ScopedAccessRequestGrant,
) -> tuple[str, ...]:
    permission = direct_grant.permission
    errors: list[str] = []
    if permission.app_id != app.id:
        errors.append("Permission must belong to the access request app.")
    if not permission.is_active:
        errors.append("Permission must be active.")
    if permission.deprecated_at is not None:
        errors.append("Permission must not be deprecated.")
    if direct_grant.scope_key not in permission.supported_scopes:
        errors.append("Scope must be supported by the permission.")
    if not AppScope.objects.filter(
        app_id=app.id,
        key=direct_grant.scope_key,
        is_active=True,
    ).exists():
        errors.append("Scope must belong to the access request app and be active.")
    return tuple(errors)
