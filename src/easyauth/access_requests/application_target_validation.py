from __future__ import annotations

from typing import TYPE_CHECKING

from easyauth.access_requests.target_validation import (
    AccessRequestTargetValidationError,
    validate_request_targets,
)

if TYPE_CHECKING:
    from easyauth.access_requests.submission_types import AccessRequestType
    from easyauth.applications.models import App, Permission, Role


def apply_target_errors(
    app: App,
    request_type: AccessRequestType,
    roles: tuple[Role, ...],
    permissions: tuple[Permission, ...],
) -> tuple[str, ...]:
    match request_type:
        case "grant" | "change" | "revoke" | "renew":
            try:
                validate_request_targets(app, roles, permissions)
            except AccessRequestTargetValidationError as exc:
                return exc.messages
            return ()
