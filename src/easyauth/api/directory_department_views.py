from __future__ import annotations

from typing import TYPE_CHECKING

from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_http_methods

from easyauth.accounts.directory_references import (
    AmbiguousDirectoryReferenceError,
    InvalidDirectoryReferenceError,
    resolve_department_scope,
)
from easyauth.accounts.models import DingTalkDepartmentMirror
from easyauth.api.directory_auth import authenticate_capability_and_throttle
from easyauth.api.directory_payloads import department_item
from easyauth.api.directory_responses import (
    directory_response,
    record_directory_audit,
    reference_error_response,
)
from easyauth.applications.services import AppPrincipal

if TYPE_CHECKING:
    from easyauth.api.errors import JsonValue


@require_http_methods(["GET"])
def directory_departments(request: HttpRequest, app_key: str) -> JsonResponse:
    match authenticate_capability_and_throttle(request, app_key):
        case AppPrincipal() as principal:
            pass
        case JsonResponse() as response:
            return response

    queryset = DingTalkDepartmentMirror.objects.order_by(
        "order",
        "source_slug",
        "corp_id",
        "dept_id",
    )
    if "parent_id" in request.GET:
        parent_ref = request.GET.get("parent_id", "")
        if parent_ref == "":
            queryset = queryset.filter(parent_id="")
        else:
            try:
                scope = resolve_department_scope(parent_ref)
            except (AmbiguousDirectoryReferenceError, InvalidDirectoryReferenceError) as error:
                return reference_error_response(error)
            if scope is None:
                queryset = DingTalkDepartmentMirror.objects.none()
            else:
                source_slug, corp_id, parent_id = scope
                queryset = queryset.filter(
                    source_slug=source_slug,
                    corp_id=corp_id,
                    parent_id=parent_id,
                )
    rows = list(queryset)
    department_items: list[JsonValue] = [department_item(row) for row in rows]
    payload: dict[str, JsonValue] = {"data": department_items}
    record_directory_audit(
        principal=principal,
        endpoint="departments",
        result_count=len(rows),
        q_present=False,
        aggregated=True,
    )
    return directory_response(payload)
