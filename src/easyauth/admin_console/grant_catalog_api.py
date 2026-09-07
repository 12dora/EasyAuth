from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

from django.http import HttpRequest, JsonResponse

from easyauth.admin_console.api_responses import error_response, json_response
from easyauth.admin_console.authz import require_superuser
from easyauth.api.errors import ErrorCode
from easyauth.portal.request_catalog_approvers import ApproverResolution, RequestCatalogApprovers
from easyauth.portal.request_catalog_data import (
    CONSOLE_CATALOG_SCOPE,
    load_request_catalog_data,
    serialize_request_catalog,
)

if TYPE_CHECKING:
    from easyauth.portal.request_catalog_data import RequestCatalogData

CONSOLE_APPROVER_RESOLUTION_NOT_REQUIRED = "not_required"
_NOT_REQUIRED_APPROVER = ApproverResolution(
    user_ids=(),
    status=CONSOLE_APPROVER_RESOLUTION_NOT_REQUIRED,
)


def console_grant_catalog(request: HttpRequest) -> JsonResponse:
    match require_superuser(request):
        case JsonResponse() as response:
            return response
        case str():
            pass
    if request.method != "GET":
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            "请求方法无效。",
            status=HTTPStatus.METHOD_NOT_ALLOWED,
        )
    catalog = load_request_catalog_data(scope=CONSOLE_CATALOG_SCOPE)
    return json_response(serialize_request_catalog(catalog, _console_catalog_approvers(catalog)))


def _console_catalog_approvers(catalog: RequestCatalogData) -> RequestCatalogApprovers:
    return RequestCatalogApprovers(
        default_approver_by_app_id={app.id: _NOT_REQUIRED_APPROVER for app in catalog.apps},
        default_approver_by_group_id={
            group.id: _NOT_REQUIRED_APPROVER for group in catalog.authorization_groups
        },
        default_approver_by_permission_id={
            permission.id: _NOT_REQUIRED_APPROVER for permission in catalog.permissions
        },
        approver_candidates=(),
    )
