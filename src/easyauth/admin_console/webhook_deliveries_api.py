from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, Final

from django.http import HttpRequest, JsonResponse

from easyauth.admin_console.api_responses import (
    error_response,
    json_response,
    method_not_allowed_response,
)
from easyauth.admin_console.operation_filters import (
    OperationFilterValidationError,
    operation_filter_error_response,
    paginate_queryset,
)
from easyauth.admin_console.request_guards import require_console_actor
from easyauth.api.errors import ErrorCode
from easyauth.api.pagination import pagination_item
from easyauth.applications.models import App
from easyauth.applications.ownership import ConsoleActor, can_manage_app
from easyauth.audit.services import AuditRecord, AuditService
from easyauth.webhooks.delivery import WebhookRedeliveryConflictError, redeliver
from easyauth.webhooks.models import DELIVERY_STATUS_VALUES, WebhookDelivery

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from django.http import QueryDict

    from easyauth.api.errors import JsonValue

type JsonObject = dict[str, "JsonValue"]
type AppContextResult = tuple[App, "ConsoleActor"] | JsonResponse

LAST_ERROR_SUMMARY_MAX_CHARS: Final = 200


def console_app_webhook_deliveries(request: HttpRequest, app_key: str) -> JsonResponse:
    """列出应用 webhook 投递记录(摘要默认不带 payload)。"""
    match _app_context(request, app_key):
        case (App() as app, ConsoleActor()):
            pass
        case JsonResponse() as response:
            return response
    if request.method != "GET":
        return method_not_allowed_response()
    include_payload = request.GET.get("include_payload", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    try:
        page = paginate_queryset(_filtered_deliveries(app, request.GET), request.GET)
    except OperationFilterValidationError as exc:
        return operation_filter_error_response(exc)
    items: list[JsonValue] = [
        _delivery_summary(delivery, include_payload=include_payload) for delivery in page.items
    ]
    return json_response({"data": items, "pagination": pagination_item(page)})


def console_app_webhook_delivery_redeliver(
    request: HttpRequest,
    app_key: str,
    delivery_pk: int,
) -> JsonResponse:
    """手动重投失败的 webhook 投递。"""
    match _app_context(request, app_key):
        case (App() as app, ConsoleActor() as actor):
            pass
        case JsonResponse() as response:
            return response
    if request.method != "POST":
        return method_not_allowed_response()
    delivery = WebhookDelivery.objects.filter(app=app, id=delivery_pk).first()
    if delivery is None:
        return error_response(
            ErrorCode.NOT_FOUND,
            "投递记录不存在。",
            status=HTTPStatus.NOT_FOUND,
        )
    try:
        delivery = redeliver(delivery)
    except WebhookRedeliveryConflictError as exc:
        return error_response(
            ErrorCode.SEMANTIC_VALIDATION_ERROR,
            str(exc),
            status=HTTPStatus.CONFLICT,
        )
    _ = AuditService.record(
        AuditRecord(
            actor_type="user",
            actor_id=actor.user_id,
            action="webhook_delivery_redelivered",
            target_type="webhook_delivery",
            target_id=delivery.delivery_id,
            metadata={
                "app_key": app.app_key,
                "delivery_pk": delivery.id,
                "event_type": delivery.event_type,
                "generation": delivery.generation,
            },
        ),
    )
    return json_response({"delivery": _delivery_summary(delivery, include_payload=False)})


def _filtered_deliveries(app: App, query: QueryDict) -> QuerySet[WebhookDelivery]:
    queryset = WebhookDelivery.objects.filter(app=app).order_by("-created_at", "-id")
    status = query.get("status", "").strip()
    if status:
        if status not in DELIVERY_STATUS_VALUES:
            raise OperationFilterValidationError(
                key="status",
                value=status,
                message="status 必须为 pending、delivered 或 failed。",
            )
        queryset = queryset.filter(status=status)
    event_type = query.get("event_type", "").strip()
    if event_type:
        queryset = queryset.filter(event_type=event_type)
    return queryset


def _delivery_summary(delivery: WebhookDelivery, *, include_payload: bool) -> JsonObject:
    last_error = delivery.last_error
    if len(last_error) > LAST_ERROR_SUMMARY_MAX_CHARS:
        last_error = f"{last_error[:LAST_ERROR_SUMMARY_MAX_CHARS]}…"
    item: JsonObject = {
        "id": delivery.id,
        "delivery_id": delivery.delivery_id,
        "event_type": delivery.event_type,
        "target_url": delivery.target_url,
        "status": delivery.status,
        "attempts": delivery.attempts,
        "generation": delivery.generation,
        "last_error": last_error,
        "created_at": delivery.created_at.isoformat(),
        "updated_at": delivery.updated_at.isoformat(),
    }
    if include_payload:
        item["payload"] = dict(delivery.payload)
    return item


def _app_context(request: HttpRequest, app_key: str) -> AppContextResult:
    match require_console_actor(request):
        case ConsoleActor() as actor:
            pass
        case JsonResponse() as response:
            return response
    app = App.objects.filter(app_key=app_key).first()
    if app is None:
        return error_response(ErrorCode.NOT_FOUND, "应用不存在。", status=HTTPStatus.NOT_FOUND)
    if not can_manage_app(actor, app):
        return error_response(
            ErrorCode.PERMISSION_DENIED,
            "只有 active App owner 可以管理 webhook 投递。",
            status=HTTPStatus.FORBIDDEN,
        )
    return app, actor
