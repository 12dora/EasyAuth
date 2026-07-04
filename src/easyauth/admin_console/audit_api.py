from __future__ import annotations

from http import HTTPStatus

from django.db.models import QuerySet
from django.http import HttpRequest, JsonResponse

from easyauth.admin_console.api_responses import (
    error_response as _error_response,
)
from easyauth.admin_console.api_responses import (
    json_response as _json_response,
)
from easyauth.admin_console.operation_filters import Page, filter_audit_logs, paginate_queryset
from easyauth.admin_console.request_guards import require_console_actor
from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.api.pagination import pagination_item
from easyauth.applications.models import App
from easyauth.applications.ownership import ConsoleActor, can_manage_app
from easyauth.audit.models import AuditLog

type AuditQuerysetResult = QuerySet[AuditLog] | JsonResponse


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

    queryset = filter_audit_logs(queryset, request.GET)
    return _page_response(paginate_queryset(queryset, request.GET))


def _audit_item(audit_log: AuditLog) -> dict[str, JsonValue]:
    return {
        "actor_type": audit_log.actor_type,
        "actor_id": audit_log.actor_id,
        "event_type": audit_log.event_type,
        "target_type": audit_log.target_type,
        "target_id": audit_log.target_id,
        "metadata": audit_log.metadata,
        "created_at": audit_log.created_at.isoformat(),
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
    result: list[JsonValue] = []
    result.extend(_audit_item(audit_log) for audit_log in page.items)
    return _json_response({"data": result, "pagination": pagination_item(page)})
