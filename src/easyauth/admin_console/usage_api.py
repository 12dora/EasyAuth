from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, ClassVar, Final, cast

from django.db import transaction
from django.http import HttpRequest, JsonResponse
from django.utils import timezone
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from easyauth.admin_console.api_responses import (
    error_response,
    json_response,
    method_not_allowed_response,
    require_method,
)
from easyauth.admin_console.authz import require_superuser
from easyauth.admin_console.usage_payloads import (
    USAGE_SINGLETON_ID,
    parse_alert_limit,
    parse_usage_range,
    stream_payload,
    summary_payload,
    timeseries_payload,
)
from easyauth.api.datetime_json import datetime_value
from easyauth.api.errors import ErrorCode
from easyauth.audit.services import AuditRecord, AuditService
from easyauth.usage.config import (
    UsageConfig,
)
from easyauth.usage.config import (
    load as load_usage_config,
)
from easyauth.usage.config import (
    save as save_usage_config,
)
from easyauth.usage.enforcement import StreamNotPausedError, resume_stream
from easyauth.usage.models import UsageAlertEvent, UsageRuntimeState, UsageSettings

if TYPE_CHECKING:
    from easyauth.api.errors import JsonValue

REQUEST_INVALID_MESSAGE: Final = "请求参数无效。"
VERSION_CONFLICT_MESSAGE: Final = "用量设置已被他人更新, 请刷新后重试。"
STREAM_NOT_PAUSED_MESSAGE: Final = "用量 Stream 当前未暂停, 无法恢复。"
CONFIG_JSON_OBJECT_MESSAGE: Final = "用量配置序列化结果必须是对象。"
CONFIG_JSON_TYPE_MESSAGE: Final = "用量配置含有无法序列化的值。"


class UsageSettingsWritePayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    config: UsageConfig
    version: int = Field(ge=0)


def usage_summary(request: HttpRequest) -> JsonResponse:
    match _superuser_get(request):
        case str():
            return json_response(summary_payload(now=timezone.now()))
        case JsonResponse() as response:
            return response


def usage_timeseries(request: HttpRequest) -> JsonResponse:
    match _superuser_get(request):
        case str():
            parsed = parse_usage_range(request.GET)
            if isinstance(parsed, JsonResponse):
                return parsed
            return json_response(timeseries_payload(parsed))
        case JsonResponse() as response:
            return response


def usage_settings(request: HttpRequest) -> JsonResponse:
    match require_superuser(request):
        case str() as actor_id:
            pass
        case JsonResponse() as response:
            return response
    if request.method == "GET":
        return json_response(settings_payload())
    if request.method == "PUT":
        return _put_settings(request, actor_id=actor_id)
    return method_not_allowed_response()


def usage_alerts(request: HttpRequest) -> JsonResponse:
    match _superuser_get(request):
        case str():
            limit = parse_alert_limit(request.GET)
            if isinstance(limit, JsonResponse):
                return limit
            return json_response(alerts_payload(limit))
        case JsonResponse() as response:
            return response


def usage_stream_resume(request: HttpRequest) -> JsonResponse:
    match require_superuser(request):
        case str() as actor_id:
            pass
        case JsonResponse() as response:
            return response
    if blocked := require_method(request, "POST"):
        return blocked
    return _resume_stream(actor_id)


def _put_settings(request: HttpRequest, *, actor_id: str) -> JsonResponse:
    try:
        payload = UsageSettingsWritePayload.model_validate_json(request.body)
    except ValidationError as exc:
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            REQUEST_INVALID_MESSAGE,
            validation_fields(exc),
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    with transaction.atomic():
        conflict = _reject_stale_version(payload.version)
        if conflict is not None:
            return conflict
        before = config_document(load_usage_config())
        _ = save_usage_config(payload.config, updated_by=actor_id)
        _record_settings_updated(
            actor_id,
            config_changed_keys(before, config_document(payload.config)),
        )
    return json_response(settings_payload())


def _reject_stale_version(expected: int) -> JsonResponse | None:
    current = settings_version()
    if current == expected:
        return None
    details: dict[str, JsonValue] = {"reason": "version_conflict", "current_version": current}
    return error_response(
        ErrorCode.CONFLICT,
        VERSION_CONFLICT_MESSAGE,
        details,
        status=HTTPStatus.CONFLICT,
    )


def _resume_stream(actor_id: str) -> JsonResponse:
    runtime = UsageRuntimeState.objects.filter(pk=USAGE_SINGLETON_ID).first()
    if runtime is None or not runtime.stream_paused:
        return _stream_not_paused_response()
    try:
        resume_stream(actor_id)
    except StreamNotPausedError:
        return _stream_not_paused_response()
    _record_stream_resumed(actor_id)
    refreshed = UsageRuntimeState.objects.filter(pk=USAGE_SINGLETON_ID).first()
    return json_response({"stream": stream_payload(refreshed)})


def _stream_not_paused_response() -> JsonResponse:
    details: dict[str, JsonValue] = {"reason": "stream_not_paused"}
    return error_response(
        ErrorCode.CONFLICT,
        STREAM_NOT_PAUSED_MESSAGE,
        details,
        status=HTTPStatus.CONFLICT,
    )


def _superuser_get(request: HttpRequest) -> str | JsonResponse:
    match require_superuser(request):
        case str() as actor_id:
            pass
        case JsonResponse() as response:
            return response
    if blocked := require_method(request, "GET"):
        return blocked
    return actor_id


def _record_settings_updated(actor_id: str, changed_keys: list[str]) -> None:
    keys: list[JsonValue] = list(changed_keys)
    _ = AuditService.record(
        AuditRecord(
            actor_type="admin",
            actor_id=actor_id,
            action="usage_settings_updated",
            target_type="usage_settings",
            target_id="singleton",
            metadata={"changed_keys": keys},
        ),
    )


def _record_stream_resumed(actor_id: str) -> None:
    _ = AuditService.record(
        AuditRecord(
            actor_type="admin",
            actor_id=actor_id,
            action="usage_stream_resumed",
            target_type="usage_stream",
            target_id="singleton",
            metadata={},
        ),
    )


def settings_payload() -> dict[str, JsonValue]:
    row = UsageSettings.objects.filter(pk=USAGE_SINGLETON_ID).first()
    updated_at = "" if row is None else datetime_value(row.updated_at)
    return {
        "config": config_document(load_usage_config()),
        "version": 0 if row is None else row.version,
        "updated_at": updated_at,
        "updated_by": "" if row is None else row.updated_by,
    }


def settings_version() -> int:
    row = UsageSettings.objects.select_for_update().filter(pk=USAGE_SINGLETON_ID).first()
    return 0 if row is None else row.version


def alerts_payload(limit: int) -> dict[str, JsonValue]:
    rows = UsageAlertEvent.objects.order_by("-created_at", "-id")[:limit]
    return {"data": json_document([_alert_item(row) for row in rows])}


def config_document(config: UsageConfig) -> dict[str, JsonValue]:
    dumped = json_document(cast("object", config.model_dump(mode="json")))
    if not isinstance(dumped, dict):
        raise TypeError(CONFIG_JSON_OBJECT_MESSAGE)
    return cast("dict[str, JsonValue]", dumped)


def json_document(value: object) -> JsonValue:
    if value is None or isinstance(value, bool | str):
        return value
    if isinstance(value, int | float):
        return value
    if isinstance(value, list):
        return [json_document(item) for item in cast("list[object]", value)]
    if isinstance(value, dict):
        raw = cast("dict[str, object]", value)
        return {key: json_document(item) for key, item in raw.items()}
    raise TypeError(CONFIG_JSON_TYPE_MESSAGE)


def config_changed_keys(before: dict[str, JsonValue], after: dict[str, JsonValue]) -> list[str]:
    changed: list[str] = []
    _collect_changed(changed, prefix="", left=before, right=after)
    return changed


def validation_fields(error: ValidationError) -> dict[str, JsonValue]:
    raw_errors = cast(
        "list[dict[str, object]]",
        error.errors(include_url=False, include_context=False, include_input=False),
    )
    fields: list[str] = []
    for item in raw_errors:
        location = item.get("loc")
        if not isinstance(location, tuple):
            continue
        path = ".".join(str(component) for component in cast("tuple[str | int, ...]", location))
        if path and path not in fields:
            fields.append(path)
    return {"fields": cast("list[JsonValue]", fields.copy()), "errors": str(error)}


def _alert_item(row: UsageAlertEvent) -> dict[str, JsonValue]:
    return {
        "id": row.id,
        "kind": row.kind,
        "metric": row.metric,
        "scope": row.scope,
        "period_key": row.period_key,
        "threshold_percent": row.threshold_percent,
        "status": row.status,
        "title": row.title,
        "detail": row.detail,
        "failure_reason": row.failure_reason,
        "created_at": datetime_value(row.created_at),
    }


def _collect_changed(out: list[str], *, prefix: str, left: object, right: object) -> None:
    if left == right:
        return
    if not isinstance(left, dict) or not isinstance(right, dict):
        out.append(prefix)
        return
    left_map = cast("dict[str, object]", left)
    right_map = cast("dict[str, object]", right)
    for key in sorted(set(left_map) | set(right_map)):
        child = key if prefix == "" else f"{prefix}.{key}"
        _collect_changed(out, prefix=child, left=left_map.get(key), right=right_map.get(key))

