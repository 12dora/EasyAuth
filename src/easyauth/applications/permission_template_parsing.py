from __future__ import annotations

import logging
from typing import TYPE_CHECKING, ClassVar, Final, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from yaml import YAMLError, safe_load

from easyauth.applications.models import CAPABILITY_VALUES
from easyauth.applications.permission_template_flattening import (
    PERMISSION_TEMPLATE_MAX_RAW_LENGTH,
)
from easyauth.applications.permission_template_types import (
    AppManifestAppInput,
    AppManifestApprovalRuleInput,
    AppManifestAuthorizationGroupInput,
    AppManifestGrantInput,
    AppManifestInput,
    AppManifestLifecycleInput,
    AppManifestPermissionGroupInput,
    AppManifestPermissionInput,
    AppManifestScopeInput,
    PermissionTemplateImportError,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

type TemplateFormat = Literal["json", "yaml"]

logger = logging.getLogger(__name__)

# 顶层 capabilities 节: 平台能力申明白名单; 未知值仅告警不拒绝(向前兼容新 SDK)。
_PLATFORM_CAPABILITY_EMPTY_MESSAGE: Final = "capabilities 元素必须是非空字符串。"


class _AppPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    app_key: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    description: str = ""
    is_active: bool = True


class _ScopePayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    name_en: str = Field(default="", max_length=128)
    description: str = ""
    description_en: str = ""
    is_active: bool = True
    display_order: int = 0


class _PermissionGroupPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=128)
    name_en: str = Field(default="", max_length=128)
    description: str = ""
    description_en: str = ""
    parent_key: str = ""
    display_order: int = 0
    is_active: bool = True


class _PermissionPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=128)
    name_en: str = Field(default="", max_length=128)
    description: str = ""
    description_en: str = ""
    group_key: str = Field(min_length=1, max_length=128)
    supported_scopes: tuple[str, ...] = Field(min_length=1)
    risk_level: str = "standard"
    is_active: bool = True


class _GrantPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    permission: str = Field(min_length=1, max_length=128)
    scope: str = Field(min_length=1, max_length=64)
    is_active: bool = True


class _AuthorizationGroupPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(min_length=1, max_length=64)
    kind: Literal["role", "bundle"]
    name: str = Field(min_length=1, max_length=128)
    name_en: str = Field(default="", max_length=128)
    description: str = ""
    description_en: str = ""
    requestable: bool = True
    is_active: bool = True
    grants: tuple[_GrantPayload, ...] = ()


class _ApprovalRulePayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    target_type: Literal["authorization_group", "permission"]
    target_key: str = Field(min_length=1, max_length=128)
    approver_userids: tuple[str, ...] = Field(min_length=1)
    is_active: bool = True


class _LifecyclePayload(BaseModel):
    # 下游生命周期交接声明(与 easyauth-app-sdk 描述符契约一致): URL 允许绝对地址
    # 或以 / 开头的站内路径(自动接入时用下游 base_url 补全)。
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    handover_url: str | None = Field(default=None, max_length=512)
    onboard_url: str | None = Field(default=None, max_length=512)
    capabilities: tuple[str, ...] = ()


class _WebhookPayload(BaseModel):
    # 下游 webhook 验签方式声明; 目前契约只支持 hmac-sha256。
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    signing: Literal["hmac-sha256"] = "hmac-sha256"


class _AppManifestPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = Field(ge=1)
    app: _AppPayload
    scopes: tuple[_ScopePayload, ...] = Field(min_length=1)
    permission_groups: tuple[_PermissionGroupPayload, ...] = ()
    permissions: tuple[_PermissionPayload, ...] = ()
    authorization_groups: tuple[_AuthorizationGroupPayload, ...] = ()
    approval_rules: tuple[_ApprovalRulePayload, ...] = ()
    lifecycle: _LifecyclePayload | None = None
    webhook: _WebhookPayload | None = None
    # 可选顶层节: 平台能力申明(directory/notify); 申明 ≠ 开通。
    capabilities: tuple[str, ...] = ()

    @field_validator("capabilities", mode="before")
    @classmethod
    def normalize_capabilities(cls, value: object) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, (list, tuple)):
            message = "capabilities 必须是字符串数组。"
            raise TypeError(message)
        raw_items = cast("Sequence[object]", value)
        normalized: list[str] = []
        seen: set[str] = set()
        for item in raw_items:
            if not isinstance(item, str) or not item.strip():
                raise ValueError(_PLATFORM_CAPABILITY_EMPTY_MESSAGE)
            capability = item.strip()
            if capability in seen:
                continue
            seen.add(capability)
            if capability not in CAPABILITY_VALUES:
                logger.warning(
                    "manifest capabilities 含未知平台能力值, 已记录但不拒绝: %s",
                    capability,
                )
            normalized.append(capability)
        return normalized


def parse_template_format(raw_format: str) -> TemplateFormat:
    match raw_format:
        case "json":
            return "json"
        case "yaml":
            return "yaml"
        case _:
            raise PermissionTemplateImportError(
                code="permission_template_format_invalid",
                message="App manifest 格式必须是 JSON 或 YAML。",
                subject=raw_format,
            )


def parse_permission_template(
    *,
    app_key: str,
    raw_template: str,
    template_format: TemplateFormat,
    imported_by: str,
) -> AppManifestInput:
    try:
        payload = _parse_payload(raw_template=raw_template, template_format=template_format)
        _validate_manifest_payload(app_key=app_key, payload=payload)
    except PermissionTemplateImportError:
        raise
    except (ValidationError, ValueError, YAMLError, TypeError) as exc:
        raise PermissionTemplateImportError(
            code="permission_template_parse_error",
            message="App manifest 无法解析。",
            subject=template_format,
        ) from exc
    return _manifest_input(payload=payload, raw_template=raw_template, imported_by=imported_by)


def _parse_payload(
    *,
    raw_template: str,
    template_format: TemplateFormat,
) -> _AppManifestPayload:
    if len(raw_template) > PERMISSION_TEMPLATE_MAX_RAW_LENGTH:
        raise PermissionTemplateImportError(
            code="permission_template_too_large",
            message="App manifest 不符合导入约束。",
            subject=str(len(raw_template)),
        )
    match template_format:
        case "json":
            return _AppManifestPayload.model_validate_json(raw_template)
        case "yaml":
            return _AppManifestPayload.model_validate(safe_load(raw_template))


def _validate_manifest_payload(*, app_key: str, payload: _AppManifestPayload) -> None:
    if payload.app.app_key != app_key:
        _raise_manifest_error("app_manifest_app_key_mismatch", payload.app.app_key)

    scope_keys = _unique_keys("scope", [scope.key for scope in payload.scopes])
    active_scope_keys = {scope.key for scope in payload.scopes if scope.is_active}
    group_keys = _unique_keys(
        "permission_group",
        [group.key for group in payload.permission_groups],
    )
    permission_keys = _unique_keys(
        "permission",
        [permission.key for permission in payload.permissions],
    )
    authorization_group_keys = _unique_keys(
        "authorization_group",
        [authorization_group.key for authorization_group in payload.authorization_groups],
    )
    permission_scope_map = _validate_permission_references(
        payload=payload,
        scope_keys=scope_keys,
        group_keys=group_keys,
    )
    _validate_authorization_group_references(
        payload=payload,
        scope_keys=scope_keys,
        active_scope_keys=active_scope_keys,
        permission_keys=permission_keys,
        permission_scope_map=permission_scope_map,
    )
    _validate_approval_rule_references(
        payload=payload,
        permission_keys=permission_keys,
        authorization_group_keys=authorization_group_keys,
    )


def _validate_permission_references(
    *,
    payload: _AppManifestPayload,
    scope_keys: set[str],
    group_keys: set[str],
) -> dict[str, set[str]]:
    for group in payload.permission_groups:
        if group.parent_key and group.parent_key not in group_keys:
            _raise_manifest_error("app_manifest_unknown_permission_group", group.parent_key)

    permission_scope_map: dict[str, set[str]] = {}
    for permission in payload.permissions:
        if permission.group_key not in group_keys:
            _raise_manifest_error("app_manifest_unknown_permission_group", permission.group_key)
        supported_scopes = set(permission.supported_scopes)
        unknown_scopes = sorted(supported_scopes - scope_keys)
        if unknown_scopes:
            _raise_manifest_error("app_manifest_unknown_scope", unknown_scopes[0])
        permission_scope_map[permission.key] = supported_scopes
    return permission_scope_map


def _validate_authorization_group_references(
    *,
    payload: _AppManifestPayload,
    scope_keys: set[str],
    active_scope_keys: set[str],
    permission_keys: set[str],
    permission_scope_map: dict[str, set[str]],
) -> None:
    for authorization_group in payload.authorization_groups:
        seen_grants: set[tuple[str, str]] = set()
        for grant in authorization_group.grants:
            if grant.permission not in permission_keys:
                _raise_manifest_error("app_manifest_unknown_permission", grant.permission)
            if grant.scope not in scope_keys:
                _raise_manifest_error("app_manifest_unknown_scope", grant.scope)
            if grant.is_active and grant.scope not in active_scope_keys:
                _raise_manifest_error("app_manifest_grant_scope_inactive", grant.scope)
            if grant.is_active and grant.scope not in permission_scope_map[grant.permission]:
                _raise_manifest_error("app_manifest_grant_scope_unsupported", grant.scope)
            grant_key = (grant.permission, grant.scope)
            if grant_key in seen_grants:
                _raise_manifest_error(
                    "app_manifest_duplicate_key",
                    f"{authorization_group.key}:{grant.permission}:{grant.scope}",
                )
            seen_grants.add(grant_key)


def _validate_approval_rule_references(
    *,
    payload: _AppManifestPayload,
    permission_keys: set[str],
    authorization_group_keys: set[str],
) -> None:
    seen_targets: set[tuple[str, str]] = set()
    for approval_rule in payload.approval_rules:
        target = (approval_rule.target_type, approval_rule.target_key)
        if target in seen_targets:
            _raise_manifest_error(
                "app_manifest_duplicate_key",
                f"approval_rule:{approval_rule.target_type}:{approval_rule.target_key}",
            )
        seen_targets.add(target)
        if approval_rule.target_type == "authorization_group":
            if approval_rule.target_key not in authorization_group_keys:
                _raise_manifest_error(
                    "app_manifest_unknown_approval_target",
                    approval_rule.target_key,
                )
        elif approval_rule.target_key not in permission_keys:
            _raise_manifest_error("app_manifest_unknown_approval_target", approval_rule.target_key)


def _unique_keys(kind: str, keys: list[str]) -> set[str]:
    seen: set[str] = set()
    for key in keys:
        if key in seen:
            _raise_manifest_error("app_manifest_duplicate_key", f"{kind}:{key}")
        seen.add(key)
    return seen


def _manifest_input(
    *,
    payload: _AppManifestPayload,
    raw_template: str,
    imported_by: str,
) -> AppManifestInput:
    return AppManifestInput(
        schema_version=payload.schema_version,
        source="paste",
        imported_by=imported_by,
        raw_template=raw_template,
        app=AppManifestAppInput(
            app_key=payload.app.app_key,
            name=payload.app.name,
            description=payload.app.description,
            is_active=payload.app.is_active,
        ),
        scopes=tuple(
            AppManifestScopeInput(
                key=scope.key,
                name=scope.name,
                name_en=scope.name_en,
                description=scope.description,
                description_en=scope.description_en,
                is_active=scope.is_active,
                display_order=scope.display_order,
            )
            for scope in payload.scopes
        ),
        permission_groups=tuple(
            AppManifestPermissionGroupInput(
                key=group.key,
                name=group.name,
                name_en=group.name_en,
                description=group.description,
                description_en=group.description_en,
                parent_key=group.parent_key,
                display_order=group.display_order,
                is_active=group.is_active,
            )
            for group in payload.permission_groups
        ),
        permissions=tuple(
            AppManifestPermissionInput(
                key=permission.key,
                name=permission.name,
                name_en=permission.name_en,
                description=permission.description,
                description_en=permission.description_en,
                group_key=permission.group_key,
                supported_scopes=permission.supported_scopes,
                risk_level=permission.risk_level,
                is_active=permission.is_active,
            )
            for permission in payload.permissions
        ),
        authorization_groups=tuple(
            AppManifestAuthorizationGroupInput(
                key=authorization_group.key,
                kind=authorization_group.kind,
                name=authorization_group.name,
                name_en=authorization_group.name_en,
                description=authorization_group.description,
                description_en=authorization_group.description_en,
                requestable=authorization_group.requestable,
                is_active=authorization_group.is_active,
                grants=tuple(
                    AppManifestGrantInput(
                        permission=grant.permission,
                        scope=grant.scope,
                        is_active=grant.is_active,
                    )
                    for grant in authorization_group.grants
                ),
            )
            for authorization_group in payload.authorization_groups
        ),
        approval_rules=tuple(
            AppManifestApprovalRuleInput(
                target_type=approval_rule.target_type,
                target_key=approval_rule.target_key,
                approver_userids=approval_rule.approver_userids,
                is_active=approval_rule.is_active,
            )
            for approval_rule in payload.approval_rules
        ),
        lifecycle=(
            AppManifestLifecycleInput(
                handover_url=payload.lifecycle.handover_url or "",
                onboard_url=payload.lifecycle.onboard_url or "",
                capabilities=payload.lifecycle.capabilities,
            )
            if payload.lifecycle is not None
            else None
        ),
        capabilities=payload.capabilities,
    )


def _raise_manifest_error(code: str, subject: str) -> None:
    raise PermissionTemplateImportError(
        code=code,
        message="App manifest 引用关系无效。",
        subject=subject,
    )
