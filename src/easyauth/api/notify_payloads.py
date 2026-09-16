from __future__ import annotations

from http import HTTPStatus
from typing import Final, TypedDict, cast

from django.http import JsonResponse

from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.api.responses import error_response
from easyauth.notify.contracts import (
    FIELDS_INVALID_MESSAGE,
    FIELDS_TOO_MANY_MESSAGE,
    NOTIFY_FORM_FIELD_MAX_ITEMS,
)

_INVALID_JSON_FIELD: Final = "body"

# 旧 SDK(46cd486 之前) 每次 POST 都带 template, 可选 deeplink_title。
# 这些字段以及其它未知键一律忽略, 不得 422; 工作通知只发 OA。
# 移除条件: EasyLearning 等下游升级到不再发送旧字段的 SDK 之后, 再考虑收紧。


class NotifyFormFieldPayload(TypedDict):
    key: str
    value: str


class NotifyCreatePayload(TypedDict):
    recipients: list[str]
    title: str
    content: str
    deeplink_url: str
    dedup_key: str
    biz_tag: str
    fields: list[NotifyFormFieldPayload]
    app_display_name: str
    author: str


def notify_create_payload(body: dict[str, object]) -> NotifyCreatePayload | JsonResponse:
    try:
        recipients = as_string_list(body.get("recipients"))
    except TypeError:
        return validation_error("recipients 必须为 1~500 个用户引用。", "recipients")
    fields = parse_notify_fields(body.get("fields"))
    if isinstance(fields, JsonResponse):
        return fields
    payload: NotifyCreatePayload = {
        "recipients": recipients,
        "title": "",
        "content": "",
        "deeplink_url": "",
        "dedup_key": "",
        "biz_tag": "",
        "fields": fields,
        "app_display_name": "",
        "author": "",
    }
    return _fill_string_fields(body, payload)


def parse_notify_fields(raw: object) -> list[NotifyFormFieldPayload] | JsonResponse:
    if raw is None:
        return []
    if not isinstance(raw, list):
        return validation_error(FIELDS_INVALID_MESSAGE, "fields")
    if len(cast("list[object]", raw)) > NOTIFY_FORM_FIELD_MAX_ITEMS:
        return validation_error(FIELDS_TOO_MANY_MESSAGE, "fields")
    result: list[NotifyFormFieldPayload] = []
    for item in cast("list[object]", raw):
        parsed = _parse_field_item(item)
        if isinstance(parsed, JsonResponse):
            return parsed
        result.append(parsed)
    return result


def optional_string_field(body: dict[str, object], field_name: str) -> str | JsonResponse:
    value = body.get(field_name)
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return validation_error(f"{field_name} 必须为字符串。", field_name)


def validation_error(
    message: str,
    field: str,
    extra_details: dict[str, JsonValue] | None = None,
) -> JsonResponse:
    details: dict[str, JsonValue] = {"field": field}
    if extra_details is not None:
        details.update(extra_details)
    return error_response(
        ErrorCode.VALIDATION_ERROR,
        message,
        details,
        status=HTTPStatus.UNPROCESSABLE_ENTITY,
    )


def as_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        message = "recipients 必须为 1~500 个用户引用。"
        raise TypeError(message)
    result: list[str] = []
    for item in cast("list[object]", value):
        if not isinstance(item, str):
            message = "recipients 必须为 1~500 个用户引用。"
            raise TypeError(message)
        result.append(item)
    return result


def _fill_string_fields(
    body: dict[str, object],
    payload: NotifyCreatePayload,
) -> NotifyCreatePayload | JsonResponse:
    for field_name in (
        "title",
        "content",
        "deeplink_url",
        "dedup_key",
        "biz_tag",
        "app_display_name",
        "author",
    ):
        parsed = optional_string_field(body, field_name)
        if isinstance(parsed, JsonResponse):
            return parsed
        payload[field_name] = parsed
    return payload


def _parse_field_item(item: object) -> NotifyFormFieldPayload | JsonResponse:
    if not isinstance(item, dict):
        return validation_error(FIELDS_INVALID_MESSAGE, "fields")
    raw = cast("dict[str, object]", item)
    if set(raw) - {"key", "value"}:
        return validation_error(FIELDS_INVALID_MESSAGE, "fields")
    key = raw.get("key")
    value = raw.get("value")
    if not isinstance(key, str) or not isinstance(value, str):
        return validation_error(FIELDS_INVALID_MESSAGE, "fields")
    return {"key": key, "value": value}
