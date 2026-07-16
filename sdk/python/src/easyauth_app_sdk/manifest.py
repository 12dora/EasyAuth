"""EasyAuth App manifest 的结构校验(对齐服务端权威契约子集)。

manifest 是下游应用权限目录的完整契约(schema_version 单调递增)。
此处做结构级 + 交叉引用校验, 避免 CI/启动“合法”但接入时才 422。
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
ALLOWED_AUTH_GROUP_KINDS = frozenset({"role", "bundle"})
ALLOWED_APPROVAL_TARGET_TYPES = frozenset({"authorization_group", "permission"})
ALLOWED_RISK_LEVELS = frozenset({"standard", "high"})
ALLOWED_WEBHOOK_SIGNING = frozenset({"hmac-sha256"})
# 顶层 capabilities 节: 平台能力申明(申明 ≠ 开通)。
ALLOWED_PLATFORM_CAPABILITIES = frozenset({"directory", "notify"})
OPTIONAL_TOP_SECTIONS = frozenset({"lifecycle", "webhook", "capabilities"})


def validate_manifest(manifest: Any) -> dict[str, Any]:
    """校验 manifest 结构并原样返回; 不满足契约时抛 ManifestValidationError。"""
    if not isinstance(manifest, dict):
        raise ManifestValidationError("manifest 必须是 JSON object")
    unknown_top = sorted(set(manifest) - set(REQUIRED_SECTIONS) - OPTIONAL_TOP_SECTIONS)
    if unknown_top:
        raise ManifestValidationError(f"manifest 含未知顶层字段: {unknown_top}")
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
    scope_keys = _validate_scopes(manifest["scopes"])
    group_keys = _validate_permission_groups(manifest["permission_groups"])
    permission_keys = _validate_permissions(manifest["permissions"], scope_keys, group_keys)
    auth_group_keys = _validate_authorization_groups(
        manifest["authorization_groups"],
        permission_keys,
        scope_keys,
    )
    _validate_approval_rules(
        manifest["approval_rules"],
        permission_keys=permission_keys,
        authorization_group_keys=auth_group_keys,
    )
    if "lifecycle" in manifest:
        _validate_lifecycle(manifest["lifecycle"])
    if "webhook" in manifest:
        _validate_webhook(manifest["webhook"])
    if "capabilities" in manifest:
        _validate_capabilities(manifest["capabilities"])
    return manifest


def _validate_capabilities(capabilities: Any) -> None:
    """校验顶层 capabilities 节: 非空字符串、白名单、去重。"""
    if not isinstance(capabilities, list):
        raise ManifestValidationError("capabilities 必须是字符串数组")
    seen: set[str] = set()
    for index, item in enumerate(capabilities):
        label = f"capabilities[{index}]"
        if not isinstance(item, str) or not item:
            raise ManifestValidationError(f"{label} 必须是非空字符串")
        if item not in ALLOWED_PLATFORM_CAPABILITIES:
            raise ManifestValidationError(
                f"{label} 取值必须是 {sorted(ALLOWED_PLATFORM_CAPABILITIES)} 之一",
            )
        if item in seen:
            raise ManifestValidationError(f"capabilities 存在重复值: {item}")
        seen.add(item)


def _validate_lifecycle(lifecycle: Any) -> None:
    if not isinstance(lifecycle, dict):
        raise ManifestValidationError("lifecycle 必须是 JSON object")
    allowed = {"handover_url", "onboard_url", "capabilities"}
    unknown = sorted(set(lifecycle) - allowed)
    if unknown:
        raise ManifestValidationError(f"lifecycle 含未知字段: {unknown}")
    for field in ("handover_url", "onboard_url"):
        value = lifecycle.get(field)
        if value is not None and not isinstance(value, str):
            raise ManifestValidationError(f"lifecycle.{field} 必须是字符串或 null")
    capabilities = lifecycle.get("capabilities")
    if capabilities is None:
        return
    if not isinstance(capabilities, list) or any(
        not isinstance(capability, str) for capability in capabilities
    ):
        raise ManifestValidationError("lifecycle.capabilities 必须是字符串数组")


def _validate_webhook(webhook: Any) -> None:
    if not isinstance(webhook, dict):
        raise ManifestValidationError("webhook 必须是 JSON object")
    unknown = sorted(set(webhook) - {"signing"})
    if unknown:
        raise ManifestValidationError(f"webhook 含未知字段: {unknown}")
    signing = webhook.get("signing")
    if signing is None:
        return
    if not isinstance(signing, str) or signing not in ALLOWED_WEBHOOK_SIGNING:
        raise ManifestValidationError(
            f"webhook.signing 必须是 {sorted(ALLOWED_WEBHOOK_SIGNING)} 之一",
        )


def _validate_scopes(scopes: list[Any]) -> set[str]:
    if not scopes:
        raise ManifestValidationError("scopes 必须是非空数组(至少声明一个 scope)")
    scope_keys: set[str] = set()
    for index, scope in enumerate(scopes):
        label = f"scopes[{index}]"
        if not isinstance(scope, dict):
            raise ManifestValidationError(f"{label} 必须是 JSON object")
        key = scope.get("key")
        if not isinstance(key, str) or not key:
            raise ManifestValidationError(f"{label}.key 必须是非空字符串")
        if key in scope_keys:
            raise ManifestValidationError(f"scopes 存在重复 key: {key}")
        scope_keys.add(key)
    return scope_keys


def _validate_permission_groups(groups: list[Any]) -> set[str]:
    group_keys: set[str] = set()
    for index, group in enumerate(groups):
        label = f"permission_groups[{index}]"
        if not isinstance(group, dict):
            raise ManifestValidationError(f"{label} 必须是 JSON object")
        key = group.get("key")
        if not isinstance(key, str) or not key:
            raise ManifestValidationError(f"{label}.key 必须是非空字符串")
        if key in group_keys:
            raise ManifestValidationError(f"permission_groups 存在重复 key: {key}")
        group_keys.add(key)
        parent_key = group.get("parent_key")
        if parent_key is not None and not isinstance(parent_key, str):
            raise ManifestValidationError(f"{label}.parent_key 必须是字符串")
    for index, group in enumerate(groups):
        parent_key = group.get("parent_key") or ""
        if parent_key and parent_key not in group_keys:
            raise ManifestValidationError(
                f"permission_groups[{index}].parent_key 引用了未知组: {parent_key}",
            )
    return group_keys


def _validate_app(app: Any) -> None:
    if not isinstance(app, dict):
        raise ManifestValidationError("app 必须是 JSON object")
    for field in REQUIRED_APP_FIELDS:
        if field not in app:
            raise ManifestValidationError(f"app 缺少字段: {field}")
    if not isinstance(app["app_key"], str) or not app["app_key"]:
        raise ManifestValidationError("app.app_key 必须是非空字符串")


def _validate_permissions(  # noqa: C901, PLR0912 - 字段校验分支与契约字段一一对应
    permissions: list[Any],
    scope_keys: set[str],
    group_keys: set[str],
) -> set[str]:
    permission_keys: set[str] = set()
    for index, permission in enumerate(permissions):
        label = f"permissions[{index}]"
        if not isinstance(permission, dict):
            raise ManifestValidationError(f"{label} 必须是 JSON object")
        key = permission.get("key")
        if not isinstance(key, str) or not key:
            raise ManifestValidationError(f"{label}.key 必须是非空字符串")
        if key in permission_keys:
            raise ManifestValidationError(f"permissions 存在重复 key: {key}")
        permission_keys.add(key)
        name = permission.get("name")
        if not isinstance(name, str) or not name:
            raise ManifestValidationError(
                f"{label}.name 必须是非空字符串(权限显示名由下游提供)",
            )
        name_en = permission.get("name_en")
        if name_en is not None and (not isinstance(name_en, str) or not name_en):
            raise ManifestValidationError(f"{label}.name_en 存在时必须是非空字符串")
        group_key = permission.get("group_key")
        if group_key is not None:
            if not isinstance(group_key, str) or not group_key:
                raise ManifestValidationError(f"{label}.group_key 必须是非空字符串")
            if group_keys and group_key not in group_keys:
                raise ManifestValidationError(
                    f"{label}.group_key 引用了未知组: {group_key}",
                )
        supported_scopes = permission.get("supported_scopes")
        if not isinstance(supported_scopes, list) or not supported_scopes:
            raise ManifestValidationError(f"{label}.supported_scopes 必须是非空数组")
        if len(supported_scopes) != len(set(supported_scopes)):
            raise ManifestValidationError(f"{label}.supported_scopes 存在重复值")
        unknown_scopes = [scope for scope in supported_scopes if scope not in scope_keys]
        if unknown_scopes:
            raise ManifestValidationError(
                f"{label}.supported_scopes 引用了未声明的 scope: {unknown_scopes}",
            )
        risk_level = permission.get("risk_level")
        if risk_level is not None and risk_level not in ALLOWED_RISK_LEVELS:
            raise ManifestValidationError(
                f"{label}.risk_level 必须是 {sorted(ALLOWED_RISK_LEVELS)} 之一",
            )
    return permission_keys


def _validate_authorization_groups(  # noqa: C901, PLR0912 - 字段校验分支与契约字段一一对应
    groups: list[Any],
    permission_keys: set[str],
    scope_keys: set[str],
) -> set[str]:
    auth_group_keys: set[str] = set()
    for index, group in enumerate(groups):
        label = f"authorization_groups[{index}]"
        if not isinstance(group, dict):
            raise ManifestValidationError(f"{label} 必须是 JSON object")
        key = group.get("key")
        if not isinstance(key, str) or not key:
            raise ManifestValidationError(f"{label}.key 必须是非空字符串")
        if key in auth_group_keys:
            raise ManifestValidationError(f"authorization_groups 存在重复 key: {key}")
        auth_group_keys.add(key)
        kind = group.get("kind")
        if kind is not None and kind not in ALLOWED_AUTH_GROUP_KINDS:
            raise ManifestValidationError(
                f"{label}.kind 必须是 {sorted(ALLOWED_AUTH_GROUP_KINDS)} 之一",
            )
        grants = group.get("grants", [])
        if not isinstance(grants, list):
            raise ManifestValidationError(f"{label}.grants 必须是数组")
        seen_grants: set[tuple[str, str]] = set()
        for grant_index, grant in enumerate(grants):
            grant_label = f"{label}.grants[{grant_index}]"
            if not isinstance(grant, dict):
                raise ManifestValidationError(f"{grant_label} 必须是 JSON object")
            permission = grant.get("permission")
            scope = grant.get("scope")
            if not isinstance(permission, str) or not permission:
                raise ManifestValidationError(
                    f"{grant_label}.permission 必须是非空字符串",
                )
            if not isinstance(scope, str) or not scope:
                raise ManifestValidationError(f"{grant_label}.scope 必须是非空字符串")
            if permission_keys and permission not in permission_keys:
                raise ManifestValidationError(
                    f"{grant_label}.permission 引用了未知权限: {permission}",
                )
            if scope not in scope_keys:
                raise ManifestValidationError(
                    f"{grant_label}.scope 引用了未知 scope: {scope}",
                )
            grant_key = (permission, scope)
            if grant_key in seen_grants:
                raise ManifestValidationError(
                    f"{label} 存在重复 grant: {permission}/{scope}",
                )
            seen_grants.add(grant_key)
    return auth_group_keys


def _validate_approval_rules(
    rules: list[Any],
    *,
    permission_keys: set[str],
    authorization_group_keys: set[str],
) -> None:
    seen_targets: set[tuple[str, str]] = set()
    for index, rule in enumerate(rules):
        label = f"approval_rules[{index}]"
        if not isinstance(rule, dict):
            raise ManifestValidationError(f"{label} 必须是 JSON object")
        target_type = rule.get("target_type")
        target_key = rule.get("target_key")
        if target_type not in ALLOWED_APPROVAL_TARGET_TYPES:
            raise ManifestValidationError(
                f"{label}.target_type 必须是 {sorted(ALLOWED_APPROVAL_TARGET_TYPES)} 之一",
            )
        if not isinstance(target_key, str) or not target_key:
            raise ManifestValidationError(f"{label}.target_key 必须是非空字符串")
        target = (str(target_type), target_key)
        if target in seen_targets:
            raise ManifestValidationError(
                f"approval_rules 存在重复 target: {target_type}/{target_key}",
            )
        seen_targets.add(target)
        if target_type == "permission" and permission_keys and target_key not in permission_keys:
            raise ManifestValidationError(f"{label}.target_key 引用了未知权限: {target_key}")
        if (
            target_type == "authorization_group"
            and authorization_group_keys
            and target_key not in authorization_group_keys
        ):
            raise ManifestValidationError(f"{label}.target_key 引用了未知授权组: {target_key}")
        approvers = rule.get("approver_userids")
        if not isinstance(approvers, list) or not approvers:
            raise ManifestValidationError(f"{label}.approver_userids 必须是非空数组")
        if any(not isinstance(item, str) or not item for item in approvers):
            raise ManifestValidationError(f"{label}.approver_userids 只能包含非空字符串")
