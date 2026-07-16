from __future__ import annotations

from http import HTTPStatus
from typing import ClassVar, Final

from django.http import HttpRequest, JsonResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from easyauth.admin_console.api_responses import (
    error_response,
    json_response,
    method_not_allowed_response,
)
from easyauth.admin_console.authz import require_superuser
from easyauth.admin_console.request_guards import require_console_actor
from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.applications.models import (
    CAPABILITY_CHOICES,
    CAPABILITY_VALUES,
    App,
    AppCapability,
)
from easyauth.applications.ownership import ConsoleActor, can_view_app
from easyauth.audit.services import AuditRecord, AuditService

type CapabilityPayload = dict[str, JsonValue]

ACTION_ENABLED: Final = "app_capability_enabled"
ACTION_DISABLED: Final = "app_capability_disabled"
UNKNOWN_CAPABILITY_MESSAGE: Final = "capability 必须为 directory 或 notify。"


class CapabilityUpdatePayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    enabled: bool
    config: dict[str, JsonValue] = Field(default_factory=dict)


def console_app_capabilities(request: HttpRequest, app_key: str) -> JsonResponse:
    # GET: 列出该 app 全部已知平台能力(含未建行的默认关闭态)。
    match _read_context(request, app_key):
        case (App() as app, ConsoleActor() as actor):
            pass
        case JsonResponse() as response:
            return response
    if request.method != "GET":
        return method_not_allowed_response()
    payload: CapabilityPayload = {
        "capabilities": _capability_list(app),
        "can_manage": actor.is_superuser,
    }
    return json_response(payload)


def console_app_capability_detail(
    request: HttpRequest,
    app_key: str,
    capability: str,
) -> JsonResponse:
    if request.method == "GET":
        return _get_capability(request, app_key=app_key, capability=capability)
    if request.method == "PUT":
        return _put_capability_for_superuser(request, app_key=app_key, capability=capability)
    return method_not_allowed_response()


def _get_capability(request: HttpRequest, *, app_key: str, capability: str) -> JsonResponse:
    match _read_context(request, app_key):
        case (App() as app, ConsoleActor() as actor):
            pass
        case JsonResponse() as response:
            return response
    if capability not in CAPABILITY_VALUES:
        return _unknown_capability_response()
    row = AppCapability.objects.filter(app=app, capability=capability).first()
    payload: CapabilityPayload = {
        "capability": _capability_item(capability, row),
        "can_manage": actor.is_superuser,
    }
    return json_response(payload)


def _put_capability_for_superuser(
    request: HttpRequest,
    *,
    app_key: str,
    capability: str,
) -> JsonResponse:
    # PUT: 只有系统超管可开关/改配置; 普通 App owner/developer 只读。
    match require_superuser(request):
        case str() as actor_id:
            pass
        case JsonResponse() as response:
            return response
    if capability not in CAPABILITY_VALUES:
        return _unknown_capability_response()
    app = App.objects.filter(app_key=app_key).first()
    if app is None:
        return error_response(ErrorCode.NOT_FOUND, "应用不存在。", status=HTTPStatus.NOT_FOUND)
    return _put_capability(request, app=app, capability=capability, actor_id=actor_id)


def _put_capability(
    request: HttpRequest,
    *,
    app: App,
    capability: str,
    actor_id: str,
) -> JsonResponse:
    try:
        payload = CapabilityUpdatePayload.model_validate_json(request.body or b"{}")
    except ValidationError as exc:
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            "能力开关参数无效。",
            {"errors": str(exc)},
            status=HTTPStatus.BAD_REQUEST,
        )

    previous = AppCapability.objects.filter(app=app, capability=capability).first()
    previous_enabled = previous.enabled if previous is not None else False
    row, _created = AppCapability.objects.update_or_create(
        app=app,
        capability=capability,
        defaults={
            "enabled": payload.enabled,
            "config": payload.config,
            "updated_by": actor_id,
        },
    )
    if previous_enabled != payload.enabled:
        _record_capability_toggle(
            app=app,
            capability=capability,
            enabled=payload.enabled,
            actor_id=actor_id,
        )
    response_payload: CapabilityPayload = {
        "capability": _capability_item(capability, row),
        "can_manage": True,
    }
    return json_response(response_payload)


def _capability_list(app: App) -> list[JsonValue]:
    rows = {
        row.capability: row
        for row in AppCapability.objects.filter(app=app, capability__in=CAPABILITY_VALUES)
    }
    items: list[JsonValue] = [
        _capability_item(capability_key, rows.get(capability_key))
        for capability_key, _label in CAPABILITY_CHOICES
    ]
    return items


def _capability_item(capability: str, row: AppCapability | None) -> CapabilityPayload:
    if row is None:
        return {
            "capability": capability,
            "enabled": False,
            "config": {},
            "updated_by": "",
            "updated_at": None,
            "created_at": None,
        }
    config: CapabilityPayload = dict(row.config)
    return {
        "capability": row.capability,
        "enabled": row.enabled,
        "config": config,
        "updated_by": row.updated_by,
        "updated_at": row.updated_at.isoformat(),
        "created_at": row.created_at.isoformat(),
    }


def _record_capability_toggle(
    *,
    app: App,
    capability: str,
    enabled: bool,
    actor_id: str,
) -> None:
    _ = AuditService.record(
        AuditRecord(
            actor_type="user",
            actor_id=actor_id,
            action=ACTION_ENABLED if enabled else ACTION_DISABLED,
            target_type="app",
            target_id=str(app.id),
            metadata={
                "app_key": app.app_key,
                "capability": capability,
                "updated_by": actor_id,
            },
        ),
    )


def _read_context(request: HttpRequest, app_key: str) -> tuple[App, ConsoleActor] | JsonResponse:
    match require_console_actor(request):
        case ConsoleActor() as actor:
            pass
        case JsonResponse() as response:
            return response
    app = App.objects.filter(app_key=app_key).first()
    if app is None:
        return error_response(ErrorCode.NOT_FOUND, "应用不存在。", status=HTTPStatus.NOT_FOUND)
    if not can_view_app(actor, app):
        return error_response(
            ErrorCode.PERMISSION_DENIED,
            "只有 active App owner/developer 可以查看能力配置。",
            status=HTTPStatus.FORBIDDEN,
        )
    return app, actor


def _unknown_capability_response() -> JsonResponse:
    return error_response(
        ErrorCode.VALIDATION_ERROR,
        UNKNOWN_CAPABILITY_MESSAGE,
        status=HTTPStatus.BAD_REQUEST,
    )
