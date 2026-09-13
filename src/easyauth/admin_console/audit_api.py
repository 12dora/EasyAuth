from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

from django.db.models import QuerySet
from django.http import HttpRequest, JsonResponse

from easyauth.accounts.department_paths import department_path_labels
from easyauth.accounts.models import UserMirror
from easyauth.admin_console.api_responses import (
    error_response as _error_response,
)
from easyauth.admin_console.api_responses import (
    json_response as _json_response,
)
from easyauth.admin_console.operation_filters import (
    OperationFilterValidationError,
    Page,
    filter_audit_logs,
    operation_filter_error_response,
    paginate_queryset,
)
from easyauth.admin_console.operations_payloads import person_ref_or_none
from easyauth.admin_console.request_guards import require_console_actor
from easyauth.api.datetime_json import datetime_value
from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.api.ordering import apply_ordering
from easyauth.api.pagination import paginated_list_payload, pagination_item
from easyauth.applications.models import App
from easyauth.applications.ownership import ConsoleActor, can_manage_app
from easyauth.audit.models import AuditLog

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

type AuditQuerysetResult = QuerySet[AuditLog] | JsonResponse


AUDIT_LOG_ORDERING = {
    "event_type": "event_type",
    "actor": ("actor_type", "actor_id"),
    "target": ("target_type", "target_id"),
    "app": "metadata__app_key",
    "created_at": "created_at",
}


def console_audit_logs(request: HttpRequest) -> JsonResponse:
    match require_console_actor(request):
        case ConsoleActor() as actor:
            pass
        case JsonResponse() as response:
            return response

    match _audit_queryset_for_actor(request, actor):
        case JsonResponse() as response:
            return response
        case queryset:
            pass

    try:
        queryset = apply_ordering(
            request,
            filter_audit_logs(queryset, request.GET),
            AUDIT_LOG_ORDERING,
            ("-created_at", "-id"),
        )
        if isinstance(queryset, JsonResponse):
            return queryset
        return _page_response(paginate_queryset(queryset, request.GET))
    except OperationFilterValidationError as exc:
        return operation_filter_error_response(exc)


def _audit_item(
    audit_log: AuditLog,
    *,
    users: Mapping[str, UserMirror],
    department_labels: Mapping[str, str],
) -> dict[str, JsonValue]:
    return {
        "actor_type": audit_log.actor_type,
        "actor_id": audit_log.actor_id,
        "actor_person": person_ref_or_none(
            audit_log.actor_id,
            users=users,
            department_labels=department_labels,
        ),
        "event_type": audit_log.event_type,
        "target_type": audit_log.target_type,
        "target_id": audit_log.target_id,
        "metadata": audit_log.metadata,
        "created_at": datetime_value(audit_log.created_at),
    }


def _audit_queryset_for_actor(request: HttpRequest, actor: ConsoleActor) -> AuditQuerysetResult:
    if actor.is_superuser:
        return AuditLog.objects.all()

    app_key = request.GET.get("app_key", "")
    app = App.objects.filter(app_key=app_key).first()
    if app_key == "" or app is None or not can_manage_app(actor, app):
        return _error_response(
            ErrorCode.PERMISSION_DENIED,
            "只有 App owner 可以查看该 App 审计日志。",
            status=HTTPStatus.FORBIDDEN,
        )
    return AuditLog.objects.filter(metadata__app_key=app.app_key)


def _page_response(page: Page[AuditLog]) -> JsonResponse:
    users = _users_by_ids(audit_log.actor_id for audit_log in page.items)
    department_labels = department_path_labels(users.values())
    result: list[JsonValue] = [
        _audit_item(audit_log, users=users, department_labels=department_labels)
        for audit_log in page.items
    ]
    return _json_response(
        paginated_list_payload(items=result, pagination=pagination_item(page)),
    )


def _users_by_ids(user_ids: Iterable[str]) -> dict[str, UserMirror]:
    unique_ids = tuple(dict.fromkeys(user_id for user_id in user_ids if user_id))
    if not unique_ids:
        return {}
    return {
        user.authentik_user_id: user
        for user in UserMirror.objects.filter(authentik_user_id__in=unique_ids)
    }
