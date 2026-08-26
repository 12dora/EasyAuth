from __future__ import annotations

import hashlib
from http import HTTPStatus
from typing import TYPE_CHECKING, ClassVar, Final

from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from easyauth.admin_console.api_responses import (
    error_response,
    json_response,
    method_not_allowed_response,
)
from easyauth.admin_console.connector_api_presenters import (
    instance_audit_metadata,
    instance_item,
    merge_secret_fields,
)
from easyauth.admin_console.request_guards import require_console_actor
from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.applications.models import App
from easyauth.applications.ownership import ConsoleActor, can_manage_app
from easyauth.audit.services import AuditRecord, AuditService
from easyauth.connectors.base import ConnectorError
from easyauth.connectors.dispatch import request_instance_reconcile
from easyauth.connectors.models import SYNC_TRIGGER_MANUAL, ConnectorInstance
from easyauth.connectors.registry import get_connector

if TYPE_CHECKING:
    from easyauth.connectors.base import BaseConnector


type JsonObject = dict[str, JsonValue]
type AppContextResult = tuple[App, "ConsoleActor"] | JsonResponse
type InstanceContextResult = tuple[ConnectorInstance, "ConsoleActor"] | JsonResponse

APP_NOT_FOUND_MESSAGE: Final = "应用不存在。"
INSTANCE_NOT_FOUND_MESSAGE: Final = "连接器实例不存在。"
CONNECTOR_TYPE_UNKNOWN_MESSAGE: Final = "连接器类型未注册。"
CONNECTOR_EXISTS_MESSAGE: Final = "该应用已配置此类型的连接器。"
EXTERNAL_ACCOUNT_CONFLICT_MESSAGE: Final = "该外部账户已绑定到另一个 EasyAuth App。"
EXTERNAL_ACCOUNT_CHANGED_MESSAGE: Final = "连接器不可重新绑定到另一个外部账户。"
SUPERUSER_REQUIRED_MESSAGE: Final = "只有系统管理员可以维护连接器配置。"
MANAGE_REQUIRED_MESSAGE: Final = "只有 active App owner 可以查看连接器状态。"
INSTANCE_DISABLED_MESSAGE: Final = "连接器实例未启用, 无法触发对账。"
RECONCILE_THROTTLED_MESSAGE: Final = "手动对账请求过于频繁, 请稍后再试。"
MANUAL_RECONCILE_RATE_SECONDS: Final = 10

MIN_RECONCILE_INTERVAL_SECONDS: Final = 60
MAX_RECONCILE_INTERVAL_SECONDS: Final = 86400


class ConnectorCreatePayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    connector_key: str = Field(max_length=64)
    enabled: bool = False
    reconcile_interval_seconds: int = Field(
        default=300,
        ge=MIN_RECONCILE_INTERVAL_SECONDS,
        le=MAX_RECONCILE_INTERVAL_SECONDS,
    )
    config: dict[str, JsonValue] = Field(default_factory=dict)


class ConnectorUpdatePayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    enabled: bool | None = None
    reconcile_interval_seconds: int | None = Field(
        default=None,
        ge=MIN_RECONCILE_INTERVAL_SECONDS,
        le=MAX_RECONCILE_INTERVAL_SECONDS,
    )
    # 密文字段传空串表示保持现有值不变(读接口从不回显密文)。
    config: dict[str, JsonValue] | None = None


def request_reconcile(instance_id: int, *, trigger: str, countdown: int) -> bool:
    """按调用时的模块级名字解析对账投递, 测试补丁打在本模块的 request_instance_reconcile。"""
    return request_instance_reconcile(instance_id, trigger=trigger, countdown=countdown)


def console_app_connector_detail(
    request: HttpRequest,
    app_key: str,
    instance_id: int,
) -> JsonResponse | HttpResponse:
    match instance_context(request, app_key, instance_id):
        case (ConnectorInstance() as instance, ConsoleActor() as actor):
            pass
        case JsonResponse() as response:
            return response
    if request.method == "PUT":
        if response := superuser_required(actor):
            return response
        return _update_instance(request, instance, actor)
    if request.method == "DELETE":
        if response := superuser_required(actor):
            return response
        return _delete_instance(instance, actor)
    return method_not_allowed_response()


def console_app_connector_reconcile(
    request: HttpRequest,
    app_key: str,
    instance_id: int,
) -> JsonResponse:
    match instance_context(request, app_key, instance_id):
        case (ConnectorInstance() as instance, ConsoleActor() as actor):
            pass
        case JsonResponse() as response:
            return response
    if request.method != "POST":
        return method_not_allowed_response()
    if response := superuser_required(actor):
        return response
    if not instance.enabled:
        return validation_error(INSTANCE_DISABLED_MESSAGE)
    actor_hash = hashlib.sha256(actor.user_id.encode()).hexdigest()
    rate_key = f"easyauth:connectors:manual:{instance.id}:{actor_hash}"
    if not cache.add(rate_key, "1", timeout=MANUAL_RECONCILE_RATE_SECONDS):
        return error_response(
            ErrorCode.PERMISSION_DENIED,
            RECONCILE_THROTTLED_MESSAGE,
            status=HTTPStatus.TOO_MANY_REQUESTS,
        )
    queued = request_reconcile(
        instance.id,
        trigger=SYNC_TRIGGER_MANUAL,
        countdown=0,
    )
    record_event(
        instance.app,
        actor,
        "connector_reconcile_requested",
        {"connector_key": instance.connector_key, "instance_id": instance.id},
    )
    return json_response({"queued": queued}, status=HTTPStatus.ACCEPTED)


def create_instance(
    request: HttpRequest,
    app: App,
    actor: ConsoleActor,
) -> JsonResponse:
    if response := superuser_required(actor):
        return response
    match _resolve_create_candidate(request, app):
        case (ConnectorCreatePayload() as payload, dict() as config, str() as external_account_id):
            pass
        case JsonResponse() as response:
            return response
    instance = ConnectorInstance(
        app=app,
        connector_key=payload.connector_key,
        enabled=payload.enabled,
        reconcile_interval_seconds=payload.reconcile_interval_seconds,
        updated_by=actor.user_id,
        external_account_id=external_account_id,
    )
    instance.set_config(config)
    try:
        with transaction.atomic():
            instance.save()
            record_event(
                app,
                actor,
                "connector_instance_created",
                instance_audit_metadata(instance),
            )
    except IntegrityError:
        return error_response(
            ErrorCode.CONFLICT,
            EXTERNAL_ACCOUNT_CONFLICT_MESSAGE,
            status=HTTPStatus.CONFLICT,
        )
    return json_response({"connector": instance_item(instance)}, status=HTTPStatus.CREATED)


def record_event(app: App, actor: ConsoleActor, action: str, metadata: JsonObject) -> None:
    _ = AuditService.record(
        AuditRecord(
            actor_type="user",
            actor_id=actor.user_id,
            action=action,
            target_type="app",
            target_id=str(app.id),
            metadata=metadata,
        ),
    )


def config_problems_response(problems: list[str]) -> JsonResponse:
    details: JsonObject = {"problems": list(problems)}
    return validation_error("连接器配置无效。", details)


def superuser_required(actor: ConsoleActor) -> JsonResponse | None:
    if actor.is_superuser:
        return None
    return error_response(
        ErrorCode.PERMISSION_DENIED,
        SUPERUSER_REQUIRED_MESSAGE,
        status=HTTPStatus.FORBIDDEN,
    )


def app_context(request: HttpRequest, app_key: str) -> AppContextResult:
    match require_console_actor(request):
        case ConsoleActor() as actor:
            pass
        case JsonResponse() as response:
            return response
    app = App.objects.filter(app_key=app_key).first()
    if app is None:
        return error_response(
            ErrorCode.NOT_FOUND,
            APP_NOT_FOUND_MESSAGE,
            status=HTTPStatus.NOT_FOUND,
        )
    # 连接器凭据是基础设施敏感配置: 读收紧为 owner/superuser, 写另行要求 superuser。
    if not can_manage_app(actor, app):
        return error_response(
            ErrorCode.PERMISSION_DENIED,
            MANAGE_REQUIRED_MESSAGE,
            status=HTTPStatus.FORBIDDEN,
        )
    return app, actor


def instance_context(
    request: HttpRequest,
    app_key: str,
    instance_id: int,
) -> InstanceContextResult:
    match app_context(request, app_key):
        case (App() as app, ConsoleActor() as actor):
            pass
        case JsonResponse() as response:
            return response
    instance = (
        ConnectorInstance.objects.select_related("app")
        .filter(
            app=app,
            id=instance_id,
            tombstoned=False,
        )
        .first()
    )
    if instance is None:
        return error_response(
            ErrorCode.NOT_FOUND,
            INSTANCE_NOT_FOUND_MESSAGE,
            status=HTTPStatus.NOT_FOUND,
        )
    return instance, actor


def validation_error(message: str, details: JsonObject | None = None) -> JsonResponse:
    return error_response(
        ErrorCode.VALIDATION_ERROR,
        message,
        details,
        status=HTTPStatus.BAD_REQUEST,
    )


def _resolve_create_candidate(
    request: HttpRequest,
    app: App,
) -> tuple[ConnectorCreatePayload, dict[str, JsonValue], str] | JsonResponse:
    try:
        payload = ConnectorCreatePayload.model_validate_json(request.body)
    except ValidationError as exc:
        return validation_error("连接器参数无效。", {"errors": str(exc)})
    connector = get_connector(payload.connector_key)
    if connector is None:
        return validation_error(CONNECTOR_TYPE_UNKNOWN_MESSAGE)
    if ConnectorInstance.objects.filter(app=app, connector_key=payload.connector_key).exists():
        return error_response(
            ErrorCode.CONFLICT,
            CONNECTOR_EXISTS_MESSAGE,
            status=HTTPStatus.CONFLICT,
        )
    config = dict(payload.config)
    problems = connector.validate_config(config)
    if problems:
        return config_problems_response(problems)
    try:
        external_account_id = connector.external_account_id(config)
    except ConnectorError as error:
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            str(error),
            status=HTTPStatus.BAD_GATEWAY,
        )
    return payload, config, external_account_id


def _update_instance(
    request: HttpRequest,
    instance: ConnectorInstance,
    actor: ConsoleActor,
) -> JsonResponse:
    try:
        payload = ConnectorUpdatePayload.model_validate_json(request.body)
    except ValidationError as exc:
        return validation_error("连接器参数无效。", {"errors": str(exc)})
    connector = get_connector(instance.connector_key)
    if connector is None:
        return validation_error(CONNECTOR_TYPE_UNKNOWN_MESSAGE)
    if response := _apply_config_update(payload, connector, instance):
        return response
    if payload.enabled is not None:
        instance.enabled = payload.enabled
    if payload.reconcile_interval_seconds is not None:
        instance.reconcile_interval_seconds = payload.reconcile_interval_seconds
    instance.updated_by = actor.user_id
    try:
        with transaction.atomic():
            instance.save()
            record_event(
                instance.app,
                actor,
                "connector_instance_updated",
                instance_audit_metadata(instance),
            )
    except IntegrityError:
        return error_response(
            ErrorCode.CONFLICT,
            EXTERNAL_ACCOUNT_CONFLICT_MESSAGE,
            status=HTTPStatus.CONFLICT,
        )
    return json_response({"connector": instance_item(instance)})


def _apply_config_update(
    payload: ConnectorUpdatePayload,
    connector: BaseConnector,
    instance: ConnectorInstance,
) -> JsonResponse | None:
    if payload.config is None:
        return None
    config = merge_secret_fields(connector, dict(payload.config), instance)
    problems = connector.validate_config(config)
    if problems:
        return config_problems_response(problems)
    try:
        external_account_id = connector.external_account_id(config)
    except ConnectorError as error:
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            str(error),
            status=HTTPStatus.BAD_GATEWAY,
        )
    if instance.external_account_id and instance.external_account_id != external_account_id:
        return error_response(
            ErrorCode.CONFLICT,
            EXTERNAL_ACCOUNT_CHANGED_MESSAGE,
            status=HTTPStatus.CONFLICT,
        )
    instance.external_account_id = external_account_id
    instance.set_config(config)
    return None


def _delete_instance(instance: ConnectorInstance, actor: ConsoleActor) -> HttpResponse:
    metadata = instance_audit_metadata(instance)
    with transaction.atomic():
        record_event(instance.app, actor, "connector_instance_deleted", metadata)
        instance.tombstoned = True
        instance.enabled = False
        instance.save(update_fields=["tombstoned", "enabled", "updated_at"])
    _ = request_reconcile(instance.id, trigger=SYNC_TRIGGER_MANUAL, countdown=0)
    return HttpResponse(status=HTTPStatus.NO_CONTENT)
