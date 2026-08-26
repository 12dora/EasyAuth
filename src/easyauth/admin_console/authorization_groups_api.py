from __future__ import annotations

from typing import TYPE_CHECKING

from easyauth.admin_console.authorization_groups_payloads import (
    AuthorizationGroupGrantPayload,
    AuthorizationGroupPayload,
    AuthorizationGroupQueryOptions,
    ManagedScopePolicyPayload,
    ResolvedAuthorizationGroupGrant,
)
from easyauth.admin_console.authorization_groups_read_api import (
    read_authorization_groups as _read_authorization_groups,
)
from easyauth.admin_console.authorization_groups_write_api import (
    AuthorizationGroupCreateInputs,
    AuthorizationGroupUpdateInputs,
)
from easyauth.admin_console.authorization_groups_write_api import (
    create_authorization_group as _create_authorization_group,
)
from easyauth.admin_console.authorization_groups_write_api import (
    update_authorization_group as _update_authorization_group,
)
from easyauth.admin_console.catalog_write_common import method_not_allowed_response

if TYPE_CHECKING:
    from django.http import HttpRequest, JsonResponse

__all__ = [
    "AuthorizationGroupCreateInputs",
    "AuthorizationGroupGrantPayload",
    "AuthorizationGroupPayload",
    "AuthorizationGroupQueryOptions",
    "AuthorizationGroupUpdateInputs",
    "ManagedScopePolicyPayload",
    "ResolvedAuthorizationGroupGrant",
    "console_authorization_group_detail",
    "console_authorization_groups",
]


def console_authorization_groups(request: HttpRequest, app_key: str) -> JsonResponse:
    if request.method == "GET":
        return _read_authorization_groups(request, app_key)
    if request.method == "POST":
        return _create_authorization_group(request, app_key)
    return method_not_allowed_response()


def console_authorization_group_detail(
    request: HttpRequest,
    app_key: str,
    authorization_group_key: str,
) -> JsonResponse:
    if request.method != "PATCH":
        return method_not_allowed_response()
    return _update_authorization_group(request, app_key, authorization_group_key)
