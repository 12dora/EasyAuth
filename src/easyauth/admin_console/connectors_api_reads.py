from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, ClassVar, Final, cast

from django.http import HttpRequest, JsonResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from easyauth.admin_console.api_payloads import list_payload, paginated_list_payload
from easyauth.admin_console.api_responses import json_response, method_not_allowed_response
from easyauth.admin_console.connector_api_presenters import (
    connector_type_item,
    connector_types,
    instance_item,
    mapping_item,
    mapping_revision,
    merge_secret_fields,
    sync_run_item,
)
from easyauth.admin_console.connector_mapping_service import replace_mappings
from easyauth.admin_console.connectors_api_writes import (
    CONNECTOR_TYPE_UNKNOWN_MESSAGE,
    app_context,
    config_problems_response,
    create_instance,
    instance_context,
    record_event,
    request_reconcile,
    superuser_required,
    validation_error,
)
from easyauth.admin_console.operation_filters import (
    OperationFilterValidationError,
    operation_filter_error_response,
    paginate_queryset,
)
from easyauth.api.errors import JsonValue
from easyauth.api.ordering import parse_ordering
from easyauth.api.pagination import pagination_item
from easyauth.applications.models import App
from easyauth.applications.ownership import ConsoleActor
from easyauth.connectors.base import BaseConnector, ConnectorError
from easyauth.connectors.models import (
    ConnectorExternalGroup,
    ConnectorInstance,
    ConnectorMapping,
    ConnectorSyncRun,
)
from easyauth.connectors.registry import get_connector
from easyauth.outbox.services import enqueue_task
from easyauth.tasks.connectors import REFRESH_EXTERNAL_GROUPS_TASK_NAME

if TYPE_CHECKING:
    from easyauth.api.pagination import Pagination
    from easyauth.connectors.base import ConnectorProbe

type JsonObject = dict[str, JsonValue]

SYNC_RUN_ORDERING: Final[dict[str, str]] = {
    "started_at": "started_at",
    "trigger": "trigger",
    "status": "status",
}
SYNC_RUN_DEFAULT_ORDER: Final[tuple[str, ...]] = ("-started_at", "-id")


class ConnectorTestPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    connector_key: str = Field(max_length=64)
    config: dict[str, JsonValue] = Field(default_factory=dict)


def console_app_connectors(request: HttpRequest, app_key: str) -> JsonResponse:
    match app_context(request, app_key):
        case (App() as app, ConsoleActor() as actor):
            pass
        case JsonResponse() as response:
            return response
    if request.method == "GET":
        instances = ConnectorInstance.objects.filter(app=app, tombstoned=False).order_by(
            "connector_key"
        )
        payload: JsonObject = {
            "connector_types": [connector_type_item(item) for item in connector_types()],
            "data": [instance_item(instance) for instance in instances],
        }
        return json_response(payload)
    if request.method == "POST":
        return create_instance(request, app, actor)
    return method_not_allowed_response()


def console_app_connector_test(request: HttpRequest, app_key: str) -> JsonResponse:
    # 测试连接不落库(方案 §3.7): 候选配置来自请求体; 密文字段留空时回填已存值,
    # 支持"改了地址想复用旧 token"的常见动线。
    match app_context(request, app_key):
        case (App() as app, ConsoleActor() as actor):
            pass
        case JsonResponse() as response:
            return response
    if request.method != "POST":
        return method_not_allowed_response()
    if response := superuser_required(actor):
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
    record_event(
        app,
        actor,
        "connector_test_executed",
        {"connector_key": connector_key, "ok": probe_ok},
    )
    return json_response({"ok": probe_ok, "message": probe_message})


def console_app_connector_external_groups(  # noqa: PLR0911 - HTTP 权限与方法分支显式返回。
    request: HttpRequest,
    app_key: str,
    instance_id: int,
) -> JsonResponse:
    match instance_context(request, app_key, instance_id):
        case (ConnectorInstance() as instance, ConsoleActor() as actor):
            pass
        case JsonResponse() as response:
            return response
    if request.method == "POST":
        if response := superuser_required(actor):
            return response
        _ = enqueue_task(
            event_key=f"connector-external-groups-refresh:{instance.id}:{instance.updated_at.isoformat()}",
            task_name=REFRESH_EXTERNAL_GROUPS_TASK_NAME,
            args=[instance.id],
            countdown=0,
        )
        record_event(
            instance.app,
            actor,
            "connector_external_groups_refresh_requested",
            {"connector_key": instance.connector_key, "instance_id": instance.id},
        )
        return json_response({"queued": True}, status=HTTPStatus.ACCEPTED)
    if request.method != "GET":
        return method_not_allowed_response()
    if response := superuser_required(actor):
        return response
    try:
        page = paginate_queryset(
            ConnectorExternalGroup.objects.filter(
                instance=instance,
                is_active=True,
            ).order_by("external_name", "external_ref"),
            request.GET,
        )
    except OperationFilterValidationError as exc:
        return operation_filter_error_response(exc)
    items: list[JsonValue] = [
        {"ref": group.external_ref, "name": group.external_name} for group in page.items
    ]
    return json_response(
        paginated_list_payload(items=items, pagination=pagination_item(page)),
    )


def console_app_connector_mappings(
    request: HttpRequest,
    app_key: str,
    instance_id: int,
) -> JsonResponse:
    match instance_context(request, app_key, instance_id):
        case (ConnectorInstance() as instance, ConsoleActor() as actor):
            pass
        case JsonResponse() as response:
            return response
    if request.method == "GET":
        mappings = list(
            ConnectorMapping.objects.filter(
                instance=instance,
                tombstoned=False,
                authorization_group__isnull=False,
            ).select_related("authorization_group")
        )
        items: list[JsonValue] = [mapping_item(mapping) for mapping in mappings]
        payload = list_payload(items)
        payload["revision"] = mapping_revision(mappings)
        return json_response(payload)
    if request.method == "PUT":
        if response := superuser_required(actor):
            return response
        return replace_mappings(
            request,
            instance,
            actor,
            request_reconcile,
            record_event,
        )
    return method_not_allowed_response()


def console_app_connector_sync_runs(
    request: HttpRequest,
    app_key: str,
    instance_id: int,
) -> JsonResponse:
    match instance_context(request, app_key, instance_id):
        case (ConnectorInstance() as instance, ConsoleActor()):
            pass
        case JsonResponse() as response:
            return response
    if request.method != "GET":
        return method_not_allowed_response()
    match parse_ordering(request, SYNC_RUN_ORDERING, SYNC_RUN_DEFAULT_ORDER):
        case JsonResponse() as response:
            return response
        case tuple() as ordering:
            pass
    try:
        page = paginate_queryset(
            ConnectorSyncRun.objects.filter(instance=instance).order_by(*ordering),
            request.GET,
        )
    except OperationFilterValidationError as exc:
        return operation_filter_error_response(exc)
    items: list[JsonValue] = [sync_run_item(run) for run in page.items]
    return json_response(
        paginated_list_payload(
            items=items,
            pagination=pagination_item(cast("Pagination", cast("object", page))),
        )
    )


def _resolve_test_candidate(
    request: HttpRequest,
    app: App,
) -> tuple[BaseConnector, str, dict[str, JsonValue]] | JsonResponse:
    try:
        payload = ConnectorTestPayload.model_validate_json(request.body)
    except ValidationError as exc:
        return validation_error("测试参数无效。", {"errors": str(exc)})
    connector = get_connector(payload.connector_key)
    if connector is None:
        return validation_error(CONNECTOR_TYPE_UNKNOWN_MESSAGE)
    stored = ConnectorInstance.objects.filter(
        app=app,
        connector_key=payload.connector_key,
    ).first()
    config = merge_secret_fields(connector, dict(payload.config), stored)
    problems = connector.validate_config(config)
    if problems:
        return config_problems_response(problems)
    return connector, payload.connector_key, config
