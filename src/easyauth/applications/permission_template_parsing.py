from __future__ import annotations

from typing import Literal

from pydantic import ValidationError
from yaml import YAMLError, safe_load

from easyauth.applications.permission_template_flattening import (
    PERMISSION_TEMPLATE_MAX_RAW_LENGTH,
)
from easyauth.applications.permission_template_mapping import build_manifest_input
from easyauth.applications.permission_template_payloads import AppManifestPayload
from easyauth.applications.permission_template_types import (
    AppManifestInput,
    PermissionTemplateImportError,
)

type TemplateFormat = Literal["json", "yaml"]


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
    return build_manifest_input(
        payload=payload,
        raw_template=raw_template,
        imported_by=imported_by,
    )


def _parse_payload(
    *,
    raw_template: str,
    template_format: TemplateFormat,
) -> AppManifestPayload:
    if len(raw_template) > PERMISSION_TEMPLATE_MAX_RAW_LENGTH:
        raise PermissionTemplateImportError(
            code="permission_template_too_large",
            message="App manifest 不符合导入约束。",
            subject=str(len(raw_template)),
        )
    match template_format:
        case "json":
            return AppManifestPayload.model_validate_json(raw_template)
        case "yaml":
            return AppManifestPayload.model_validate(safe_load(raw_template))


def _validate_manifest_payload(*, app_key: str, payload: AppManifestPayload) -> None:
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
    payload: AppManifestPayload,
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
    payload: AppManifestPayload,
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
    payload: AppManifestPayload,
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


def _raise_manifest_error(code: str, subject: str) -> None:
    raise PermissionTemplateImportError(
        code=code,
        message="App manifest 引用关系无效。",
        subject=subject,
    )
