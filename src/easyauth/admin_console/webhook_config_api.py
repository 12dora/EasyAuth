from __future__ import annotations

import secrets
from http import HTTPStatus
from typing import TYPE_CHECKING, ClassVar

from django.http import HttpRequest, JsonResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from easyauth.admin_console.api_responses import (
    error_response,
    json_response,
    method_not_allowed_response,
)
from easyauth.admin_console.request_guards import require_console_actor
from easyauth.api.errors import ErrorCode
from easyauth.applications.models import App
from easyauth.applications.ownership import ConsoleActor, can_manage_app
from easyauth.audit.services import AuditRecord, AuditService
from easyauth.webhooks.delivery import WebhookNotConfiguredError, enqueue_delivery
from easyauth.webhooks.models import WEBHOOK_EVENT_TEST, AppWebhookConfig

if TYPE_CHECKING:
    from easyauth.api.errors import JsonValue

type JsonObject = dict[str, "JsonValue"]
type AppContextResult = tuple[App, "ConsoleActor"] | JsonResponse


class WebhookConfigPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    enabled: bool = True
    approval_callback_url: str = Field(default="", max_length=512)
    handover_url: str = Field(default="", max_length=512)
    onboard_url: str = Field(default="", max_length=512)
    # true 时生成并轮换密钥(明文只在本次响应返回一次)。
    rotate_secret: bool = False


class WebhookTestPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    # 事件的目标 URL 字段名: approval_callback_url / handover_url / onboard_url。
    target: str = Field(default="approval_callback_url", max_length=32)


def console_app_webhook_config(request: HttpRequest, app_key: str) -> JsonResponse:
    match _app_context(request, app_key):
        case (App() as app, ConsoleActor() as actor):
            pass
        case JsonResponse() as response:
            return response
    if request.method == "GET":
        config = AppWebhookConfig.objects.filter(app=app).first()
        return json_response({"webhook_config": _config_item(config)})
    if request.method == "PUT":
        return _update_config(request, app, actor)
    return method_not_allowed_response()


def console_app_webhook_test(request: HttpRequest, app_key: str) -> JsonResponse:
    match _app_context(request, app_key):
        case (App() as app, ConsoleActor() as actor):
            pass
        case JsonResponse() as response:
            return response
    if request.method != "POST":
        return method_not_allowed_response()
    try:
        payload = WebhookTestPayload.model_validate_json(request.body or b"{}")
    except ValidationError as exc:
        return _validation_error("测试参数无效。", {"errors": str(exc)})
    config = AppWebhookConfig.objects.filter(app=app).first()
    url = _target_url(config, payload.target)
    if url is None:
        return _validation_error(
            "target 必须为 approval_callback_url、handover_url 或 onboard_url。",
        )
    try:
        delivery = enqueue_delivery(
            app=app,
            event_type=WEBHOOK_EVENT_TEST,
            url=url,
            payload={"message": "EasyAuth webhook 测试事件", "app_key": app.app_key},
        )
    except WebhookNotConfiguredError as exc:
        return _validation_error(str(exc))
    _ = AuditService.record(
        AuditRecord(
            actor_type="user",
            actor_id=actor.user_id,
            action="webhook_test_sent",
            target_type="app",
            target_id=str(app.id),
            metadata={"app_key": app.app_key, "delivery_id": delivery.delivery_id},
        ),
    )
    return json_response({"delivery_id": delivery.delivery_id, "status": delivery.status})


def _update_config(request: HttpRequest, app: App, actor: ConsoleActor) -> JsonResponse:
    try:
        payload = WebhookConfigPayload.model_validate_json(request.body)
    except ValidationError as exc:
        return _validation_error("webhook 配置参数无效。", {"errors": str(exc)})
    config, _created = AppWebhookConfig.objects.get_or_create(app=app)
    config.enabled = payload.enabled
    config.approval_callback_url = payload.approval_callback_url
    config.handover_url = payload.handover_url
    config.onboard_url = payload.onboard_url
    config.updated_by = actor.user_id
    new_secret = ""
    if payload.rotate_secret or not config.secret:
        # 轮换后旧签名立即失效; 明文只在本次响应返回一次, 落库走 EncryptedCharField。
        new_secret = f"whsec_{secrets.token_urlsafe(32)}"
        config.secret = new_secret
    config.save()
    _ = AuditService.record(
        AuditRecord(
            actor_type="user",
            actor_id=actor.user_id,
            action="webhook_config_updated",
            target_type="app",
            target_id=str(app.id),
            metadata={
                "app_key": app.app_key,
                "enabled": config.enabled,
                "secret_rotated": bool(new_secret),
            },
        ),
    )
    item = _config_payload(config)
    if new_secret:
        item["secret"] = new_secret
    return json_response({"webhook_config": item})


def _config_item(config: AppWebhookConfig | None) -> JsonObject | None:
    if config is None:
        return None
    return _config_payload(config)


def _config_payload(config: AppWebhookConfig) -> JsonObject:
    return {
        "enabled": config.enabled,
        "secret_configured": bool(config.secret),
        "approval_callback_url": config.approval_callback_url,
        "handover_url": config.handover_url,
        "onboard_url": config.onboard_url,
        "updated_by": config.updated_by,
        "updated_at": config.updated_at.isoformat(),
    }


def _target_url(config: AppWebhookConfig | None, target: str) -> str | None:
    if config is None:
        return ""
    match target:
        case "approval_callback_url":
            return config.approval_callback_url
        case "handover_url":
            return config.handover_url
        case "onboard_url":
            return config.onboard_url
        case _:
            return None


def _app_context(request: HttpRequest, app_key: str) -> AppContextResult:
    match require_console_actor(request):
        case ConsoleActor() as actor:
            pass
        case JsonResponse() as response:
            return response
    app = App.objects.filter(app_key=app_key).first()
    if app is None:
        return error_response(ErrorCode.NOT_FOUND, "应用不存在。", status=HTTPStatus.NOT_FOUND)
    # webhook 密钥与回调地址是应用集成敏感配置: 收紧为 owner/superuser。
    if not can_manage_app(actor, app):
        return error_response(
            ErrorCode.PERMISSION_DENIED,
            "只有 active App owner 可以维护 webhook 配置。",
            status=HTTPStatus.FORBIDDEN,
        )
    return app, actor


def _validation_error(message: str, details: JsonObject | None = None) -> JsonResponse:
    return error_response(
        ErrorCode.VALIDATION_ERROR,
        message,
        details,
        status=HTTPStatus.BAD_REQUEST,
    )
