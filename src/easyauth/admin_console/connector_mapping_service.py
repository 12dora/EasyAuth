from __future__ import annotations

from collections.abc import Callable
from http import HTTPStatus
from typing import TYPE_CHECKING, ClassVar, Final

from django.db import transaction
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from easyauth.admin_console.api_payloads import list_payload
from easyauth.admin_console.api_responses import error_response, json_response
from easyauth.admin_console.connector_api_presenters import mapping_item, mapping_revision
from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.applications.models import AuthorizationGroup
from easyauth.connectors.models import (
    SYNC_TRIGGER_MANUAL,
    ConnectorInstance,
    ConnectorMapping,
)

if TYPE_CHECKING:
    from django.http import HttpRequest, JsonResponse

    from easyauth.applications.models import App
    from easyauth.applications.ownership import ConsoleActor

type JsonObject = dict[str, JsonValue]
type EventRecorder = Callable[[App, ConsoleActor, str, JsonObject], None]

AUTHORIZATION_GROUP_UNKNOWN_TEMPLATE: Final = "授权组 {key} 不存在或不属于该应用。"
AUTHORIZATION_GROUP_DUPLICATE_TEMPLATE: Final = "授权组 {key} 在映射中重复。"
MAPPINGS_CHANGED_MESSAGE: Final = "授权组映射已被其他请求更新, 请重新加载后再保存。"


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


class _MappingRejectedError(Exception):
    """内部信号: 携带映射解析阶段的失败响应, 仅在事务外抛出。"""

    response: JsonResponse

    def __init__(self, response: JsonResponse) -> None:
        super().__init__("mapping rejected")
        self.response = response


def _resolve_mapping_entries(
    payload: MappingsPutPayload,
    instance: ConnectorInstance,
) -> list[tuple[AuthorizationGroup, MappingEntryPayload]]:
    groups_by_key = {
        group.key: group
        for group in AuthorizationGroup.objects.filter(app_id=instance.app_id)
    }
    resolved: list[tuple[AuthorizationGroup, MappingEntryPayload]] = []
    seen_keys: set[str] = set()
    for entry in payload.mappings:
        group = groups_by_key.get(entry.authorization_group_key)
        if group is None:
            raise _MappingRejectedError(
                _validation_error(
                    AUTHORIZATION_GROUP_UNKNOWN_TEMPLATE.format(key=entry.authorization_group_key),
                ),
            )
        if entry.authorization_group_key in seen_keys:
            raise _MappingRejectedError(
                _validation_error(
                    AUTHORIZATION_GROUP_DUPLICATE_TEMPLATE.format(
                        key=entry.authorization_group_key,
                    ),
                    {"authorization_group_key": entry.authorization_group_key},
                ),
            )
        seen_keys.add(entry.authorization_group_key)
        resolved.append((group, entry))
    return resolved


def _live_mappings_by_group_id(
    current_mappings: list[ConnectorMapping],
) -> dict[int | None, ConnectorMapping]:
    return {
        mapping.authorization_group_id: mapping
        for mapping in current_mappings
        if mapping.authorization_group is not None and not mapping.tombstoned
    }


def _plan_mapping_changes(
    instance: ConnectorInstance,
    *,
    resolved: list[tuple[AuthorizationGroup, MappingEntryPayload]],
    current_by_group_id: dict[int | None, ConnectorMapping],
) -> tuple[list[ConnectorMapping], list[ConnectorMapping]]:
    """就地更新可复用的映射, 并返回待墓碑 / 待新建两批(顺序与原实现一致)。"""
    next_group_ids = {group.id for group, _entry in resolved}
    tombstones: list[ConnectorMapping] = []
    creates: list[ConnectorMapping] = []
    for group, entry in resolved:
        existing = current_by_group_id.get(group.id)
        if existing is not None and existing.external_ref == entry.external_ref:
            existing.auto_create = entry.auto_create
            existing.external_name = existing.external_name or entry.external_ref
            existing.save(update_fields=["auto_create", "external_name", "updated_at"])
            continue
        if existing is not None:
            existing.authorization_group = None
            existing.tombstoned = True
            tombstones.append(existing)
        creates.append(
            ConnectorMapping(
                instance=instance,
                authorization_group=group,
                external_ref=entry.external_ref,
                external_name=entry.external_ref,
                auto_create=entry.auto_create,
            )
        )
    for group_id, existing in current_by_group_id.items():
        if group_id in next_group_ids:
            continue
        existing.authorization_group = None
        existing.tombstoned = True
        tombstones.append(existing)
    return tombstones, creates


def replace_mappings(
    request: HttpRequest,
    instance: ConnectorInstance,
    actor: ConsoleActor,
    request_reconcile: Callable[..., bool],
    record_event: EventRecorder,
) -> JsonResponse:
    try:
        payload = MappingsPutPayload.model_validate_json(request.body)
    except ValidationError as exc:
        return _validation_error("映射参数无效。", {"errors": str(exc)})
    try:
        resolved = _resolve_mapping_entries(payload, instance)
    except _MappingRejectedError as rejected:
        return rejected.response
    with transaction.atomic():
        _ = ConnectorInstance.objects.select_for_update().get(id=instance.id)
        current_mappings = list(
            ConnectorMapping.objects.filter(instance=instance).select_related(
                "authorization_group",
            )
        )
        if payload.revision != mapping_revision(current_mappings):
            return error_response(
                ErrorCode.CONFLICT,
                MAPPINGS_CHANGED_MESSAGE,
                status=HTTPStatus.CONFLICT,
            )
        tombstones, creates = _plan_mapping_changes(
            instance,
            resolved=resolved,
            current_by_group_id=_live_mappings_by_group_id(current_mappings),
        )
        if tombstones:
            _ = ConnectorMapping.objects.bulk_update(
                tombstones,
                ["authorization_group", "tombstoned", "updated_at"],
            )
        _ = ConnectorMapping.objects.bulk_create(creates)
        record_event(
            instance.app,
            actor,
            "connector_mappings_updated",
            {
                "connector_key": instance.connector_key,
                "instance_id": instance.id,
                "mapping_count": len(resolved),
            },
        )
    if instance.enabled:
        _ = request_reconcile(instance.id, trigger=SYNC_TRIGGER_MANUAL, countdown=0)
    return _mapping_response(instance)


def _mapping_response(instance: ConnectorInstance) -> JsonResponse:
    mappings = list(
        ConnectorMapping.objects.filter(
            instance=instance,
            tombstoned=False,
            authorization_group__isnull=False,
        ).select_related("authorization_group")
    )
    items: list[JsonValue] = [mapping_item(mapping) for mapping in mappings]
    response_payload = list_payload(items)
    response_payload["revision"] = mapping_revision(mappings)
    return json_response(response_payload)


def _validation_error(message: str, details: JsonObject | None = None) -> JsonResponse:
    return error_response(
        ErrorCode.VALIDATION_ERROR,
        message,
        details,
        status=HTTPStatus.BAD_REQUEST,
    )
