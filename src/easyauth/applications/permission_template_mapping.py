from __future__ import annotations

from typing import TYPE_CHECKING

from easyauth.applications.permission_template_types import (
    AppManifestAppInput,
    AppManifestApprovalRuleInput,
    AppManifestAuthorizationGroupInput,
    AppManifestGrantInput,
    AppManifestHandoverAssetTypeInput,
    AppManifestInput,
    AppManifestLifecycleInput,
    AppManifestPermissionGroupInput,
    AppManifestPermissionInput,
    AppManifestScopeInput,
)

if TYPE_CHECKING:
    from easyauth.applications.permission_template_payloads import (
        AppManifestPayload,
        AppPayload,
        ApprovalRulePayload,
        AuthorizationGroupPayload,
        GrantPayload,
        HandoverAssetTypePayload,
        LifecyclePayload,
        PermissionGroupPayload,
        PermissionPayload,
        ScopePayload,
    )


def build_manifest_input(
    *,
    payload: AppManifestPayload,
    raw_template: str,
    imported_by: str,
) -> AppManifestInput:
    return AppManifestInput(
        schema_version=payload.schema_version,
        source="paste",
        imported_by=imported_by,
        raw_template=raw_template,
        app=_app_input(payload.app),
        scopes=tuple(_scope_input(scope) for scope in payload.scopes),
        permission_groups=tuple(
            _permission_group_input(group) for group in payload.permission_groups
        ),
        permissions=tuple(_permission_input(permission) for permission in payload.permissions),
        authorization_groups=tuple(
            _authorization_group_input(group) for group in payload.authorization_groups
        ),
        approval_rules=tuple(_approval_rule_input(rule) for rule in payload.approval_rules),
        lifecycle=_lifecycle_input(payload.lifecycle),
        capabilities=payload.capabilities,
    )


def _app_input(app: AppPayload) -> AppManifestAppInput:
    return AppManifestAppInput(
        app_key=app.app_key,
        name=app.name,
        description=app.description,
        is_active=app.is_active,
    )


def _scope_input(scope: ScopePayload) -> AppManifestScopeInput:
    return AppManifestScopeInput(
        key=scope.key,
        name=scope.name,
        name_en=scope.name_en,
        description=scope.description,
        description_en=scope.description_en,
        is_active=scope.is_active,
        display_order=scope.display_order,
    )


def _permission_group_input(
    group: PermissionGroupPayload,
) -> AppManifestPermissionGroupInput:
    return AppManifestPermissionGroupInput(
        key=group.key,
        name=group.name,
        name_en=group.name_en,
        description=group.description,
        description_en=group.description_en,
        parent_key=group.parent_key,
        display_order=group.display_order,
        is_active=group.is_active,
    )


def _permission_input(permission: PermissionPayload) -> AppManifestPermissionInput:
    return AppManifestPermissionInput(
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


def _authorization_group_input(
    group: AuthorizationGroupPayload,
) -> AppManifestAuthorizationGroupInput:
    return AppManifestAuthorizationGroupInput(
        key=group.key,
        kind=group.kind,
        name=group.name,
        name_en=group.name_en,
        description=group.description,
        description_en=group.description_en,
        requestable=group.requestable,
        is_active=group.is_active,
        grants=tuple(_grant_input(grant) for grant in group.grants),
    )


def _grant_input(grant: GrantPayload) -> AppManifestGrantInput:
    return AppManifestGrantInput(
        permission=grant.permission,
        scope=grant.scope,
        is_active=grant.is_active,
    )


def _approval_rule_input(rule: ApprovalRulePayload) -> AppManifestApprovalRuleInput:
    return AppManifestApprovalRuleInput(
        target_type=rule.target_type,
        target_key=rule.target_key,
        approver_userids=rule.approver_userids,
        is_active=rule.is_active,
    )


def _lifecycle_input(lifecycle: LifecyclePayload | None) -> AppManifestLifecycleInput | None:
    if lifecycle is None:
        return None
    return AppManifestLifecycleInput(
        handover_url=lifecycle.handover_url or "",
        onboard_url=lifecycle.onboard_url or "",
        capabilities=lifecycle.capabilities,
        handover_asset_types=tuple(
            _handover_asset_type_input(item) for item in lifecycle.handover_asset_types
        ),
    )


def _handover_asset_type_input(
    item: HandoverAssetTypePayload,
) -> AppManifestHandoverAssetTypeInput:
    return AppManifestHandoverAssetTypeInput(
        type=item.type,
        label=item.label,
        detail_supported=item.detail_supported,
        releasable=item.releasable,
    )
