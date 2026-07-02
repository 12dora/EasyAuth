from __future__ import annotations

from typing import TYPE_CHECKING

from easyauth.access_requests.target_validation import (
    AccessRequestTargetValidationError,
    validate_request_targets,
)
from easyauth.applications.models import ApprovalRule

if TYPE_CHECKING:
    from easyauth.access_requests.submission_types import (
        AccessRequestType,
        ScopedAccessRequestGrant,
    )
    from easyauth.applications.models import App, AuthorizationGroup


def apply_target_errors(
    app: App,
    request_type: AccessRequestType,
    authorization_groups: tuple[AuthorizationGroup, ...],
    direct_grants: tuple[ScopedAccessRequestGrant, ...],
) -> tuple[str, ...]:
    match request_type:
        case "grant" | "change" | "revoke" | "renew":
            errors: list[str] = []
            try:
                validate_request_targets(app, authorization_groups, direct_grants)
            except AccessRequestTargetValidationError as exc:
                errors.extend(exc.messages)
            errors.extend(_approval_rule_errors(app, authorization_groups, direct_grants))
            return tuple(errors)


def _approval_rule_errors(
    app: App,
    authorization_groups: tuple[AuthorizationGroup, ...],
    direct_grants: tuple[ScopedAccessRequestGrant, ...],
) -> tuple[str, ...]:
    _ = direct_grants
    errors: list[str] = []
    errors.extend(
        f"{group.key}: Active approval rule is required."
        for group in authorization_groups
        if not ApprovalRule.objects.filter(
            app=app,
            authorization_group=group,
            is_active=True,
        ).exists()
    )
    return tuple(errors)
