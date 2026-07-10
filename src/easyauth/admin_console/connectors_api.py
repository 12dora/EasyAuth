from __future__ import annotations

import hashlib
import json
from http import HTTPStatus
from typing import TYPE_CHECKING, ClassVar, Final, cast

from celery import current_app
from django.db import transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from easyauth.admin_console.api_payloads import list_payload, paginated_list_payload
from easyauth.admin_console.api_responses import (
    error_response,
    json_response,
    method_not_allowed_response,
)
from easyauth.admin_console.operation_filters import paginate_queryset
from easyauth.admin_console.request_guards import require_console_actor
from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.api.pagination import pagination_item
from easyauth.applications.models import App, AuthorizationGroup
from easyauth.applications.ownership import ConsoleActor, can_manage_app
from easyauth.audit.services import AuditRecord, AuditService
from easyauth.connectors.base import BaseConnector, ConnectorError, secret_field_names
from easyauth.connectors.dispatch import RECONCILE_TASK_NAME
from easyauth.connectors.models import (
    SYNC_TRIGGER_MANUAL,
    ConnectorInstance,
    ConnectorMapping,
    ConnectorSyncRun,
)
from easyauth.connectors.registry import available_connectors, get_connector

if TYPE_CHECKING:
    from easyauth.api.pagination import Pagination
    from easyauth.connectors.base import ConnectorProbe

type JsonObject = dict[str, JsonValue]
type AppContextResult = tuple[App, "ConsoleActor"] | JsonResponse
type InstanceContextResult = tuple[ConnectorInstance, "ConsoleActor"] | JsonResponse

APP_NOT_FOUND_MESSAGE: Final = "应用不存在。"
INSTANCE_NOT_FOUND_MESSAGE: Final = "连接器实例不存在。"
CONNECTOR_TYPE_UNKNOWN_MESSAGE: Final = "连接器类型未注册。"
CONNECTOR_EXISTS_MESSAGE: Final = "该应用已配置此类型的连接器。"
MAPPINGS_CHANGED_MESSAGE: Final = "授权组映射已被其他请求更新, 请重新加载后再保存。"
SUPERUSER_REQUIRED_MESSAGE: Final = "只有系统管理员可以维护连接器配置。"
MANAGE_REQUIRED_MESSAGE: Final = "只有 active App owner 可以查看连接器状态。"
INSTANCE_DISABLED_MESSAGE: Final = "连接器实例未启用, 无法触发对账。"
AUTHORIZATION_GROUP_UNKNOWN_TEMPLATE: Final = "授权组 {key} 不存在或不属于该应用。"

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


class ConnectorTestPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    connector_key: str = Field(max_length=64)
    config: dict[str, JsonValue] = Field(default_factory=dict)


class MappingEntryPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    authorization_group_key: str = Field(max_length=64)
    external_ref: str = Field(min_length=1, max_length=255)
    auto_create: bool = False


class MappingsPutPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    revision: str = Field(min_length=64, max_length=64)
    mappings: list[MappingEntryPayload] = Field(default_factory=list)


def console_app_connectors(request: HttpRequest, app_key: str) -> JsonResponse:
    match _app_context(request, app_key):
        case (App() as app, ConsoleActor() as actor):
            pass
        case JsonResponse() as response:
            return response
    if request.method == "GET":
        instances = ConnectorInstance.objects.filter(app=app).order_by("connector_key")
        payload: JsonObject = {
            "connector_types": [_connector_type_item(item) for item in _connector_types()],
            "data": [_instance_item(instance) for instance in instances],
        }
        return json_response(payload)
    if request.method == "POST":
        return _create_instance(request, app, actor)
    return method_not_allowed_response()


def console_app_connector_detail(
    request: HttpRequest,
    app_key: str,
    instance_id: int,
) -> JsonResponse | HttpResponse:
    match _instance_context(request, app_key, instance_id):
        case (ConnectorInstance() as instance, ConsoleActor() as actor):
            pass
        case JsonResponse() as response:
            return response
    if request.method == "PUT":
        if response := _superuser_required(actor):
            return response
        return _update_instance(request, instance, actor)
    if request.method == "DELETE":
        if response := _superuser_required(actor):
            return response
        return _delete_instance(instance, actor)
    return method_not_allowed_response()


def console_app_connector_test(request: HttpRequest, app_key: str) -> JsonResponse:
    # 测试连接不落库(方案 §3.7): 候选配置来自请求体; 密文字段留空时回填已存值,
    # 支持"改了地址想复用旧 token"的常见动线。
    match _app_context(request, app_key):
        case (App() as app, ConsoleActor() as actor):
            pass
        case JsonResponse() as response:
            return response
    if request.method != "POST":
        return method_not_allowed_response()
    if response := _superuser_required(actor):
        return response
    match _resolve_test_candidate(request, app):
        case (BaseConnector() as connector, str() as connector_key, dict() as config):
            pass
        case JsonResponse() as response:
            return response
    try:
        probe: ConnectorProbe = connector.test_connection(config)
    except ConnectorError as error:
        probe_ok, probe_message = False, str(error)
    else:
        probe_ok, probe_message = probe.ok, probe.message
    _record_event(
        app,
        actor,
        "connector_test_executed",
        {"connector_key": connector_key, "ok": probe_ok},
    )
    return json_response({"ok": probe_ok, "message": probe_message})


def _resolve_test_candidate(
    request: HttpRequest,
    app: App,
) -> tuple[BaseConnector, str, dict[str, JsonValue]] | JsonResponse:
    try:
        payload = ConnectorTestPayload.model_validate_json(request.body)
    except ValidationError as exc:
        return _validation_error("测试参数无效。", {"errors": str(exc)})
    connector = get_connector(payload.connector_key)
    if connector is None:
        return _validation_error(CONNECTOR_TYPE_UNKNOWN_MESSAGE)
    stored = ConnectorInstance.objects.filter(
        app=app,
        connector_key=payload.connector_key,
    ).first()
    config = _merge_secret_fields(connector, dict(payload.config), stored)
    problems = connector.validate_config(config)
    if problems:
        return _config_problems_response(problems)
    return connector, payload.connector_key, config


def console_app_connector_external_groups(
    request: HttpRequest,
    app_key: str,
    instance_id: int,
) -> JsonResponse:
    match _instance_context(request, app_key, instance_id):
        case (ConnectorInstance() as instance, ConsoleActor() as actor):
            pass
        case JsonResponse() as response:
            return response
    if request.method != "GET":
        return method_not_allowed_response()
    if response := _superuser_required(actor):
        return response
    connector = get_connector(instance.connector_key)
    if connector is None:
        return _validation_error(CONNECTOR_TYPE_UNKNOWN_MESSAGE)
    try:
        groups = connector.list_external_groups(instance.config)
    except ConnectorError as error:
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            str(error),
            status=HTTPStatus.BAD_GATEWAY,
        )
    items: list[JsonValue] = [{"ref": group.ref, "name": group.name} for group in groups]
    return json_response(list_payload(items))


def console_app_connector_mappings(
    request: HttpRequest,
    app_key: str,
    instance_id: int,
) -> JsonResponse:
    match _instance_context(request, app_key, instance_id):
        case (ConnectorInstance() as instance, ConsoleActor() as actor):
            pass
        case JsonResponse() as response:
            return response
    if request.method == "GET":
        mappings = list(
            ConnectorMapping.objects.filter(instance=instance).select_related(
                "authorization_group",
            )
        )
        items: list[JsonValue] = [_mapping_item(mapping) for mapping in mappings]
        payload = list_payload(items)
        payload["revision"] = _mapping_revision(mappings)
        return json_response(payload)
    if request.method == "PUT":
        if response := _superuser_required(actor):
            return response
        return _replace_mappings(request, instance, actor)
    return method_not_allowed_response()


def console_app_connector_reconcile(
    request: HttpRequest,
    app_key: str,
    instance_id: int,
) -> JsonResponse:
    match _instance_context(request, app_key, instance_id):
        case (ConnectorInstance() as instance, ConsoleActor() as actor):
            pass
        case JsonResponse() as response:
            return response
    if request.method != "POST":
        return method_not_allowed_response()
    if not instance.enabled:
        return _validation_error(INSTANCE_DISABLED_MESSAGE)
    # 手动触发绕过去抖直接入队(任务开始时会自行清理 pending 标记), 按钮永远即刻生效。
    _ = current_app.send_task(RECONCILE_TASK_NAME, args=[instance.id, SYNC_TRIGGER_MANUAL])
    _record_event(
        instance.app,
        actor,
        "connector_reconcile_requested",
        {"connector_key": instance.connector_key, "instance_id": instance.id},
    )
    return json_response({"queued": True}, status=HTTPStatus.ACCEPTED)


def console_app_connector_sync_runs(
    request: HttpRequest,
    app_key: str,
    instance_id: int,
) -> JsonResponse:
    match _instance_context(request, app_key, instance_id):
        case (ConnectorInstance() as instance, ConsoleActor()):
            pass
        case JsonResponse() as response:
            return response
    if request.method != "GET":
        return method_not_allowed_response()
    page = paginate_queryset(
        ConnectorSyncRun.objects.filter(instance=instance),
        request.GET,
    )
    items: list[JsonValue] = [_sync_run_item(run) for run in page.items]
    return json_response(
        paginated_list_payload(
            items=items,
            pagination=pagination_item(cast("Pagination", cast("object", page))),
        )
    )


def _create_instance(request: HttpRequest, app: App, actor: ConsoleActor) -> JsonResponse:
    if response := _superuser_required(actor):
        return response
    try:
        payload = ConnectorCreatePayload.model_validate_json(request.body)
    except ValidationError as exc:
        return _validation_error("连接器参数无效。", {"errors": str(exc)})
    connector = get_connector(payload.connector_key)
    if connector is None:
        return _validation_error(CONNECTOR_TYPE_UNKNOWN_MESSAGE)
    if ConnectorInstance.objects.filter(app=app, connector_key=payload.connector_key).exists():
        return error_response(
            ErrorCode.CONFLICT,
            CONNECTOR_EXISTS_MESSAGE,
            status=HTTPStatus.CONFLICT,
        )
    config = dict(payload.config)
    problems = connector.validate_config(config)
    if problems:
        return _config_problems_response(problems)
    instance = ConnectorInstance(
        app=app,
        connector_key=payload.connector_key,
        enabled=payload.enabled,
        reconcile_interval_seconds=payload.reconcile_interval_seconds,
        updated_by=actor.user_id,
    )
    instance.set_config(config)
    with transaction.atomic():
        instance.save()
        _record_event(
            app,
            actor,
            "connector_instance_created",
            _instance_audit_metadata(instance),
        )
    return json_response({"connector": _instance_item(instance)}, status=HTTPStatus.CREATED)


def _update_instance(
    request: HttpRequest,
    instance: ConnectorInstance,
    actor: ConsoleActor,
) -> JsonResponse:
    try:
        payload = ConnectorUpdatePayload.model_validate_json(request.body)
    except ValidationError as exc:
        return _validation_error("连接器参数无效。", {"errors": str(exc)})
    connector = get_connector(instance.connector_key)
    if connector is None:
        return _validation_error(CONNECTOR_TYPE_UNKNOWN_MESSAGE)
    if payload.config is not None:
        config = _merge_secret_fields(connector, dict(payload.config), instance)
        problems = connector.validate_config(config)
        if problems:
            return _config_problems_response(problems)
        instance.set_config(config)
    if payload.enabled is not None:
        instance.enabled = payload.enabled
    if payload.reconcile_interval_seconds is not None:
        instance.reconcile_interval_seconds = payload.reconcile_interval_seconds
    instance.updated_by = actor.user_id
    with transaction.atomic():
        instance.save()
        _record_event(
            instance.app,
            actor,
            "connector_instance_updated",
            _instance_audit_metadata(instance),
        )
    return json_response({"connector": _instance_item(instance)})


def _delete_instance(instance: ConnectorInstance, actor: ConsoleActor) -> HttpResponse:
    metadata = _instance_audit_metadata(instance)
    with transaction.atomic():
        _record_event(instance.app, actor, "connector_instance_deleted", metadata)
        _ = instance.delete()
    return HttpResponse(status=HTTPStatus.NO_CONTENT)


def _replace_mappings(
    request: HttpRequest,
    instance: ConnectorInstance,
    actor: ConsoleActor,
) -> JsonResponse:
    try:
        payload = MappingsPutPayload.model_validate_json(request.body)
    except ValidationError as exc:
        return _validation_error("映射参数无效。", {"errors": str(exc)})
    groups_by_key = {
        group.key: group
        for group in AuthorizationGroup.objects.filter(app_id=instance.app_id)
    }
    resolved: list[tuple[AuthorizationGroup, MappingEntryPayload]] = []
    seen_keys: set[str] = set()
    for entry in payload.mappings:
        group = groups_by_key.get(entry.authorization_group_key)
        if group is None:
            return _validation_error(
                AUTHORIZATION_GROUP_UNKNOWN_TEMPLATE.format(key=entry.authorization_group_key),
            )
        if entry.authorization_group_key in seen_keys:
            continue
        seen_keys.add(entry.authorization_group_key)
        resolved.append((group, entry))
    with transaction.atomic():
        _ = ConnectorInstance.objects.select_for_update().get(id=instance.id)
        current_mappings = list(
            ConnectorMapping.objects.filter(instance=instance).select_related(
                "authorization_group",
            )
        )
        if payload.revision != _mapping_revision(current_mappings):
            return error_response(
                ErrorCode.CONFLICT,
                MAPPINGS_CHANGED_MESSAGE,
                status=HTTPStatus.CONFLICT,
            )
        _ = ConnectorMapping.objects.filter(instance=instance).delete()
        _ = ConnectorMapping.objects.bulk_create(
            ConnectorMapping(
                instance=instance,
                authorization_group=group,
                external_ref=entry.external_ref,
                auto_create=entry.auto_create,
            )
            for group, entry in resolved
        )
        _record_event(
            instance.app,
            actor,
            "connector_mappings_updated",
            {
                "connector_key": instance.connector_key,
                "instance_id": instance.id,
                "mapping_count": len(resolved),
            },
        )
    mappings = list(
        ConnectorMapping.objects.filter(instance=instance).select_related(
            "authorization_group",
        )
    )
    items: list[JsonValue] = [_mapping_item(mapping) for mapping in mappings]
    response_payload = list_payload(items)
    response_payload["revision"] = _mapping_revision(mappings)
    return json_response(response_payload)


def _connector_types() -> list[BaseConnector]:
    return list(available_connectors().values())


def _connector_type_item(connector: BaseConnector) -> JsonObject:
    return {
        "key": connector.key,
        "display_name": connector.display_name,
        "config_schema": dict(connector.config_schema),
    }


def _instance_item(instance: ConnectorInstance) -> JsonObject:
    connector = get_connector(instance.connector_key)
    secrets: frozenset[str] = (
        secret_field_names(connector.config_schema) if connector else frozenset()
    )
    config = instance.config
    redacted: JsonObject = {
        key: ("" if key in secrets else value) for key, value in config.items()
    }
    configured_secrets: list[JsonValue] = []
    configured_secrets.extend(sorted(key for key in secrets if config.get(key)))
    return {
        "id": instance.id,
        "connector_key": instance.connector_key,
        "display_name": connector.display_name if connector else instance.connector_key,
        "enabled": instance.enabled,
        "config": redacted,
        "configured_secrets": configured_secrets,
        "reconcile_interval_seconds": instance.reconcile_interval_seconds,
        "last_reconcile_at": (
            instance.last_reconcile_at.isoformat() if instance.last_reconcile_at else None
        ),
        "last_status": instance.last_status,
        "last_error": instance.last_error,
        "consecutive_failures": instance.consecutive_failures,
        "updated_by": instance.updated_by,
        "updated_at": instance.updated_at.isoformat(),
    }


def _mapping_item(mapping: ConnectorMapping) -> JsonObject:
    return {
        "authorization_group_key": mapping.authorization_group.key,
        "authorization_group_name": mapping.authorization_group.name,
        "external_ref": mapping.external_ref,
        "auto_create": mapping.auto_create,
    }


def _mapping_revision(mappings: list[ConnectorMapping]) -> str:
    canonical = [
        {
            "authorization_group_key": mapping.authorization_group.key,
            "external_ref": mapping.external_ref,
            "auto_create": mapping.auto_create,
        }
        for mapping in mappings
    ]
    serialized = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode()).hexdigest()


def _sync_run_item(run: ConnectorSyncRun) -> JsonObject:
    return {
        "id": run.id,
        "trigger": run.trigger,
        "status": run.status,
        "started_at": run.started_at.isoformat(),
        "finished_at": run.finished_at.isoformat(),
        "stats": dict(run.stats),
        "error": run.error,
    }


def _merge_secret_fields(
    connector: BaseConnector,
    config: dict[str, JsonValue],
    stored: ConnectorInstance | None,
) -> dict[str, JsonValue]:
    # 读接口不回显密文, 表单原样提交会带回空串; 空值密文回填已存值。
    if stored is None:
        return config
    stored_config = stored.config
    for name in secret_field_names(connector.config_schema):
        incoming = config.get(name)
        if (incoming is None or incoming == "") and stored_config.get(name):
            config[name] = stored_config[name]
    return config


def _instance_audit_metadata(instance: ConnectorInstance) -> JsonObject:
    # 审计记录不得包含 token/secret 明文。
    return {
        "app_key": instance.app.app_key,
        "connector_key": instance.connector_key,
        "instance_id": instance.id,
        "enabled": instance.enabled,
        "reconcile_interval_seconds": instance.reconcile_interval_seconds,
    }


def _record_event(app: App, actor: ConsoleActor, action: str, metadata: JsonObject) -> None:
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


def _config_problems_response(problems: list[str]) -> JsonResponse:
    details: JsonObject = {"problems": list(problems)}
    return _validation_error("连接器配置无效。", details)


def _superuser_required(actor: ConsoleActor) -> JsonResponse | None:
    if actor.is_superuser:
        return None
    return error_response(
        ErrorCode.PERMISSION_DENIED,
        SUPERUSER_REQUIRED_MESSAGE,
        status=HTTPStatus.FORBIDDEN,
    )


def _app_context(request: HttpRequest, app_key: str) -> AppContextResult:
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


def _instance_context(
    request: HttpRequest,
    app_key: str,
    instance_id: int,
) -> InstanceContextResult:
    match _app_context(request, app_key):
        case (App() as app, ConsoleActor() as actor):
            pass
        case JsonResponse() as response:
            return response
    instance = (
        ConnectorInstance.objects.select_related("app").filter(app=app, id=instance_id).first()
    )
    if instance is None:
        return error_response(
            ErrorCode.NOT_FOUND,
            INSTANCE_NOT_FOUND_MESSAGE,
            status=HTTPStatus.NOT_FOUND,
        )
    return instance, actor


def _validation_error(message: str, details: JsonObject | None = None) -> JsonResponse:
    return error_response(
        ErrorCode.VALIDATION_ERROR,
        message,
        details,
        status=HTTPStatus.BAD_REQUEST,
    )
