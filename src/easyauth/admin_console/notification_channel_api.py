from __future__ import annotations

from http import HTTPStatus
from typing import ClassVar, cast

from django.conf import settings
from django.db import transaction
from django.db.models import Max
from django.http import HttpRequest, JsonResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from easyauth.accounts.directory_snapshot import directory_scope_keys
from easyauth.admin_console.api_responses import (
    error_response,
    json_response,
    method_not_allowed_response,
)
from easyauth.admin_console.request_guards import require_console_actor
from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.applications.models import App, AppNotificationChannel
from easyauth.applications.ownership import ConsoleActor, can_manage_app, can_view_app
from easyauth.audit.services import AuditRecord, AuditService
from easyauth.integrations.dingtalk.api_client import DingTalkApiClient, DingTalkApiError


class NotificationChannelPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    name: str = Field(min_length=1, max_length=128)
    dingtalk_app_key: str = Field(min_length=1, max_length=128)
    dingtalk_app_secret: str | None = Field(default=None, max_length=512)
    agent_id: str = Field(min_length=1, max_length=64)
    directory_source_slug: str = Field(min_length=1, max_length=128)
    corp_id: str = Field(min_length=1, max_length=128)


class NotificationChannelSecretRequiredError(Exception):
    pass


class NotificationChannelDirectoryScopeError(Exception):
    pass


def console_app_notification_channel(request: HttpRequest, app_key: str) -> JsonResponse:
    match _read_context(request, app_key):
        case (App() as app, ConsoleActor() as actor):
            pass
        case JsonResponse() as response:
            return response
    if request.method == "GET":
        channel = _active_channel(app)
        return json_response(
            {
                "notification_channel": _channel_payload(channel),
                "available_directory_scopes": _available_directory_scope_payload(),
            },
        )
    if request.method == "PUT":
        return _update_channel(request, app=app, actor=actor)
    return method_not_allowed_response()


def _update_channel(request: HttpRequest, *, app: App, actor: ConsoleActor) -> JsonResponse:
    if not can_manage_app(actor, app):
        return _write_denied()
    try:
        payload = NotificationChannelPayload.model_validate_json(request.body)
    except ValidationError as error:
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            "通知通道参数无效。",
            _validation_details(error),
            status=HTTPStatus.BAD_REQUEST,
        )
    try:
        channel = _replace_channel(app=app, actor=actor, payload=payload)
    except NotificationChannelSecretRequiredError:
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            "首次创建通知通道必须提供 dingtalk_app_secret。",
            {"field": "dingtalk_app_secret"},
            status=HTTPStatus.BAD_REQUEST,
        )
    except NotificationChannelDirectoryScopeError:
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            "通知通道目录作用域不存在。",
            {"fields": ["directory_source_slug", "corp_id"]},
            status=HTTPStatus.BAD_REQUEST,
        )
    return json_response(
        {"notification_channel": _channel_payload(channel)},
        status=HTTPStatus.CREATED,
    )


def console_app_notification_channel_test(request: HttpRequest, app_key: str) -> JsonResponse:
    match _read_context(request, app_key):
        case (App() as app, ConsoleActor() as actor):
            pass
        case JsonResponse() as response:
            return response
    if request.method != "POST":
        return method_not_allowed_response()
    if not can_manage_app(actor, app):
        return _write_denied()
    channel = _active_channel(app)
    if channel is None:
        return error_response(
            ErrorCode.DEPENDENCY_UNAVAILABLE,
            "应用未配置可用的钉钉通知通道。",
            status=HTTPStatus.SERVICE_UNAVAILABLE,
        )
    client = DingTalkApiClient(
        app_key=channel.dingtalk_app_key,
        app_secret=channel.dingtalk_app_secret,
        timeout_seconds=float(getattr(settings, "EASYAUTH_DINGTALK_HTTP_TIMEOUT_SECONDS", 5)),
    )
    try:
        _ = client.get_access_token(force_refresh=True)
    except DingTalkApiError:
        return error_response(
            ErrorCode.DEPENDENCY_UNAVAILABLE,
            "钉钉通知通道连通性测试失败。",
            status=HTTPStatus.SERVICE_UNAVAILABLE,
        )
    _ = AuditService.record(
        AuditRecord(
            actor_type="user",
            actor_id=actor.user_id,
            action="notification_channel_connectivity_tested",
            target_type="app_notification_channel",
            target_id=str(channel.id),
            metadata={"app_key": app.app_key, "version": channel.version},
        ),
    )
    return json_response({"ok": True, "version": channel.version})


@transaction.atomic
def _replace_channel(
    *,
    app: App,
    actor: ConsoleActor,
    payload: NotificationChannelPayload,
) -> AppNotificationChannel:
    _ = App.objects.select_for_update().get(id=app.id)
    if (payload.directory_source_slug, payload.corp_id) not in set(directory_scope_keys()):
        raise NotificationChannelDirectoryScopeError
    previous = AppNotificationChannel.objects.filter(app=app, is_active=True).first()
    app_secret = payload.dingtalk_app_secret or (
        previous.dingtalk_app_secret if previous is not None else ""
    )
    if not app_secret:
        raise NotificationChannelSecretRequiredError
    max_version = (
        AppNotificationChannel.objects.filter(app=app).aggregate(value=Max("version"))["value"] or 0
    )
    _ = AppNotificationChannel.objects.filter(app=app, is_active=True).update(is_active=False)
    channel = AppNotificationChannel(
        app=app,
        name=payload.name,
        dingtalk_app_key=payload.dingtalk_app_key,
        dingtalk_app_secret=app_secret,
        agent_id=payload.agent_id,
        directory_source_slug=payload.directory_source_slug,
        corp_id=payload.corp_id,
        version=max_version + 1,
        is_active=True,
        created_by=actor.user_id,
    )
    channel.full_clean()
    channel.save()
    _ = AuditService.record(
        AuditRecord(
            actor_type="user",
            actor_id=actor.user_id,
            action="notification_channel_updated",
            target_type="app_notification_channel",
            target_id=str(channel.id),
            metadata={
                "app_key": app.app_key,
                "name": channel.name,
                "version": channel.version,
                "agent_id": channel.agent_id,
                "directory_source_slug": channel.directory_source_slug,
                "corp_id": channel.corp_id,
                "secret_reused": not bool(payload.dingtalk_app_secret),
            },
        ),
    )
    return channel


def _active_channel(app: App) -> AppNotificationChannel | None:
    return AppNotificationChannel.objects.filter(app=app, is_active=True).first()


def _channel_payload(channel: AppNotificationChannel | None) -> dict[str, JsonValue] | None:
    if channel is None:
        return None
    return {
        "id": channel.id,
        "name": channel.name,
        "dingtalk_app_key": channel.dingtalk_app_key,
        "app_secret_configured": bool(channel.dingtalk_app_secret),
        "agent_id": channel.agent_id,
        "directory_source_slug": channel.directory_source_slug,
        "corp_id": channel.corp_id,
        "version": channel.version,
        "is_active": channel.is_active,
        "created_by": channel.created_by,
        "created_at": channel.created_at.isoformat(),
    }


def _available_directory_scope_payload() -> list[JsonValue]:
    return [
        {"directory_source_slug": source_slug, "corp_id": corp_id}
        for source_slug, corp_id in directory_scope_keys()
    ]


def _read_context(request: HttpRequest, app_key: str) -> tuple[App, ConsoleActor] | JsonResponse:
    match require_console_actor(request):
        case ConsoleActor() as actor:
            pass
        case JsonResponse() as response:
            return response
    app = App.objects.filter(app_key=app_key).first()
    if app is None:
        return error_response(
            ErrorCode.NOT_FOUND,
            "应用不存在。",
            status=HTTPStatus.NOT_FOUND,
        )
    if not can_view_app(actor, app):
        return error_response(
            ErrorCode.PERMISSION_DENIED,
            "只有 active App owner/developer 可以查看通知通道。",
            status=HTTPStatus.FORBIDDEN,
        )
    return app, actor


def _write_denied() -> JsonResponse:
    return error_response(
        ErrorCode.PERMISSION_DENIED,
        "只有 App owner 可以维护通知通道。",
        status=HTTPStatus.FORBIDDEN,
    )


def _validation_details(error: ValidationError) -> dict[str, JsonValue]:
    raw_errors = cast(
        "list[dict[str, object]]",
        error.errors(
            include_url=False,
            include_context=False,
            include_input=False,
        ),
    )
    fields: list[str] = []
    for item in raw_errors:
        location = item.get("loc")
        if not isinstance(location, tuple):
            continue
        typed_location = cast("tuple[str | int, ...]", location)
        field = ".".join(str(component) for component in typed_location)
        if field and field not in fields:
            fields.append(field)
    field_values = cast("list[JsonValue]", fields.copy())
    return {"fields": field_values}
