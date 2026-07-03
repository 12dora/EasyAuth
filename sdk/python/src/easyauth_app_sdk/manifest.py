"""EasyAuth App manifest 的轻量结构校验。

manifest 是下游应用权限目录的完整契约(schema_version 单调递增), 这里只做结构级校验,
业务级校验由 EasyAuth 导入管线负责。
"""

from __future__ import annotations

from typing import Any


class ManifestValidationError(ValueError):
    """manifest 结构不满足 EasyAuth 契约。"""


REQUIRED_SECTIONS = (
    "schema_version",
    "app",
    "scopes",
    "permission_groups",
    "permissions",
    "authorization_groups",
    "approval_rules",
)
LIST_SECTIONS = (
    "scopes",
    "permission_groups",
    "permissions",
    "authorization_groups",
    "approval_rules",
)
REQUIRED_APP_FIELDS = ("app_key", "name", "description", "is_active")


def validate_manifest(manifest: Any) -> dict[str, Any]:
    """校验 manifest 结构并原样返回; 不满足契约时抛 ManifestValidationError。"""
    if not isinstance(manifest, dict):
        raise ManifestValidationError("manifest 必须是 JSON object")
    missing = [section for section in REQUIRED_SECTIONS if section not in manifest]
    if missing:
        raise ManifestValidationError(f"manifest 缺少字段: {missing}")
    schema_version = manifest["schema_version"]
    version_invalid = (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version < 1
    )
    if version_invalid:
        raise ManifestValidationError("schema_version 必须是 >=1 的整数")
    _validate_app(manifest["app"])
    for section in LIST_SECTIONS:
        if not isinstance(manifest[section], list):
            raise ManifestValidationError(f"{section} 必须是 JSON array")
    for index, permission in enumerate(manifest["permissions"]):
        _validate_permission(permission, index)
    return manifest


def _validate_app(app: Any) -> None:
    if not isinstance(app, dict):
        raise ManifestValidationError("app 必须是 JSON object")
    for field in REQUIRED_APP_FIELDS:
        if field not in app:
            raise ManifestValidationError(f"app 缺少字段: {field}")
    if not isinstance(app["app_key"], str) or not app["app_key"]:
        raise ManifestValidationError("app.app_key 必须是非空字符串")


def _validate_permission(permission: Any, index: int) -> None:
    label = f"permissions[{index}]"
    if not isinstance(permission, dict):
        raise ManifestValidationError(f"{label} 必须是 JSON object")
    key = permission.get("key")
    if not isinstance(key, str) or not key:
        raise ManifestValidationError(f"{label}.key 必须是非空字符串")
    name = permission.get("name")
    if not isinstance(name, str) or not name:
        raise ManifestValidationError(f"{label}.name 必须是非空字符串(权限显示名由下游提供)")
    name_en = permission.get("name_en")
    if name_en is not None and (not isinstance(name_en, str) or not name_en):
        raise ManifestValidationError(f"{label}.name_en 存在时必须是非空字符串")
    supported_scopes = permission.get("supported_scopes")
    if not isinstance(supported_scopes, list) or not supported_scopes:
        raise ManifestValidationError(f"{label}.supported_scopes 必须是非空数组")
