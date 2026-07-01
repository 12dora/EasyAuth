from __future__ import annotations

import json
from http import HTTPStatus
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from django.http import HttpResponse

from easyauth.admin_console.api_responses import error_response as admin_error_response
from easyauth.admin_console.api_responses import json_response as admin_json_response
from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.api.responses import error_response, json_response

type JsonObject = dict[str, JsonValue]


def test_json_response_keeps_chinese_text_unescaped_in_response_bytes() -> None:
    payload: JsonObject = {"message": "请求成功", "nested": {"label": "中文"}}

    response = json_response(payload)

    assert _json_object(response) == payload
    assert b"\\u8bf7" not in response.content
    assert b"\\u4e2d" not in response.content
    assert "请求成功".encode() in response.content


def test_error_response_defaults_details_to_empty_object_when_details_is_none() -> None:
    # Given: 调用方显式传入 details=None。
    message = "未找到资源"

    # When: 生成错误响应。
    response = error_response(
        ErrorCode.NOT_FOUND,
        message,
        details=None,
        status=HTTPStatus.NOT_FOUND,
    )

    # Then: details 输出为空对象。
    error = _error_object(response)
    assert error["details"] == {}


def test_error_response_accepts_http_status_values() -> None:
    # Given: status 使用 HTTPStatus。
    status = HTTPStatus.CONFLICT

    # When: 生成错误响应。
    response = error_response(
        ErrorCode.CONFLICT,
        "资源冲突",
        {"field": "name"},
        status=status,
    )

    # Then: HTTP 状态码写入响应。
    assert response.status_code == status


def test_error_response_accepts_integer_status_values() -> None:
    # Given: status 使用 int。
    status = 422

    # When: 生成错误响应。
    response = error_response(
        ErrorCode.SEMANTIC_VALIDATION_ERROR,
        "语义校验失败",
        {"field": "permission"},
        status=status,
    )

    # Then: HTTP 状态码写入响应。
    assert response.status_code == status


def test_admin_console_reexports_json_response_with_public_helper_behavior() -> None:
    # Given: admin console 重新导出的 json_response。
    payload: JsonObject = {"message": "控制台成功"}

    # When: 通过重新导出函数生成响应。
    response = admin_json_response(payload, status=HTTPStatus.CREATED)

    # Then: 行为与公共 helper 契约一致。
    assert _json_object(response) == payload
    assert response.status_code == HTTPStatus.CREATED
    assert b"\\u63a7" not in response.content


def test_admin_console_reexports_error_response_with_public_helper_behavior() -> None:
    # Given: admin console 重新导出的 error_response。
    message = "禁止访问"

    # When: 通过重新导出函数生成响应。
    response = admin_error_response(
        ErrorCode.PERMISSION_DENIED,
        message,
        details=None,
        status=HTTPStatus.FORBIDDEN,
    )

    # Then: 行为与公共 helper 契约一致。
    payload = _json_object(response)
    assert response.status_code == HTTPStatus.FORBIDDEN
    assert payload == {
        "error": {
            "code": "PERMISSION_DENIED",
            "message": message,
            "details": {},
        },
    }


def _json_object(response: HttpResponse) -> JsonObject:
    payload: JsonObject = cast("JsonObject", json.loads(response.content.decode()))
    assert isinstance(payload, dict)
    return payload


def _error_object(response: HttpResponse) -> JsonObject:
    payload = _json_object(response)
    error = payload["error"]
    assert isinstance(error, dict)
    return cast("JsonObject", error)
