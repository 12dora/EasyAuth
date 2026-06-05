from __future__ import annotations

from datetime import datetime
from typing import Final

from easyauth.api.errors import ErrorCode, build_error_response
from easyauth.api.serializers import PermissionQueryResponseSerializer

EXPECTED_ERROR_CODES: Final = {
    "VALIDATION_ERROR",
    "AUTHENTICATION_FAILED",
    "PERMISSION_DENIED",
    "NOT_FOUND",
    "CONFLICT",
    "SEMANTIC_VALIDATION_ERROR",
    "INTERNAL_ERROR",
}
EXPECTED_VERSION: Final = 7


def test_error_code_contains_api_v1_contract_values() -> None:
    # Given: `/api/v1` 错误码契约已定义。
    expected_codes = EXPECTED_ERROR_CODES

    # When: 读取公开枚举值。
    actual_codes = {code.value for code in ErrorCode}

    # Then: 枚举值完整且没有额外错误码。
    assert actual_codes == expected_codes


def test_build_error_response_returns_api_v1_error_shape() -> None:
    # Given: 调用方提供错误码、消息和结构化详情。
    details = {"field": "user_id", "reason": "required"}

    # When: 构造统一错误响应。
    response = build_error_response(
        ErrorCode.VALIDATION_ERROR,
        "请求参数无效",
        details,
    )

    # Then: 响应符合固定的 `/api/v1` 错误 envelope。
    assert response == {
        "error": {
            "code": "VALIDATION_ERROR",
            "message": "请求参数无效",
            "details": details,
        },
    }


def test_build_error_response_defaults_details_to_empty_object() -> None:
    # Given: 调用方没有提供错误详情。
    message = "未找到资源"

    # When: 构造统一错误响应。
    response = build_error_response(ErrorCode.NOT_FOUND, message)

    # Then: details 缺省为空对象。
    assert response["error"]["details"] == {}


def test_permission_query_response_serializer_accepts_contract_payload() -> None:
    # Given: 权限查询成功响应包含 `/api/v1` 契约字段。
    payload = {
        "user_id": "user-001",
        "app_key": "crm",
        "roles": ["admin", "auditor"],
        "permissions": ["account.read", "account.write"],
        "version": EXPECTED_VERSION,
        "expires_at": "2026-06-05T10:20:30Z",
    }

    # When: serializer 校验并序列化响应。
    serializer = PermissionQueryResponseSerializer(data=payload)

    # Then: 字符串列表、整数版本和 ISO datetime 字符串都保留在契约输出中。
    assert serializer.is_valid(), serializer.errors
    assert serializer.data["user_id"] == "user-001"
    assert serializer.data["app_key"] == "crm"
    assert serializer.data["roles"] == ["admin", "auditor"]
    assert serializer.data["permissions"] == ["account.read", "account.write"]
    assert serializer.data["version"] == EXPECTED_VERSION
    expires_at = serializer.data["expires_at"]
    assert isinstance(expires_at, str)
    parsed_expires_at = datetime.fromisoformat(expires_at)
    assert parsed_expires_at.tzinfo is not None


def test_permission_query_response_serializer_rejects_missing_version() -> None:
    # Given: 权限查询响应缺少必填 version。
    payload = {
        "user_id": "user-001",
        "app_key": "crm",
        "roles": ["admin"],
        "permissions": ["account.read"],
        "expires_at": "2026-06-05T10:20:30Z",
    }

    # When: serializer 校验输入。
    serializer = PermissionQueryResponseSerializer(data=payload)

    # Then: 契约校验失败并指出 version 问题。
    assert serializer.is_valid() is False
    assert "version" in serializer.errors


def test_permission_query_response_serializer_rejects_non_list_roles() -> None:
    # Given: roles 使用字符串而不是字符串列表。
    payload = {
        "user_id": "user-001",
        "app_key": "crm",
        "roles": "admin",
        "permissions": ["account.read"],
        "version": EXPECTED_VERSION,
        "expires_at": "2026-06-05T10:20:30Z",
    }

    # When: serializer 校验输入。
    serializer = PermissionQueryResponseSerializer(data=payload)

    # Then: 契约校验失败并指出 roles 问题。
    assert serializer.is_valid() is False
    assert "roles" in serializer.errors
