from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final, final, override

from django.core.management.base import BaseCommand
from django.db import models, transaction

from easyauth.accounts.models import UserMirror
from easyauth.applications.catalog_version import bump_catalog_version
from easyauth.applications.models import (
    App,
    AppCredential,
    AppMembership,
    ApprovalRule,
    AppScope,
    AuthorizationGroup,
    AuthorizationGroupGrant,
    Permission,
    PermissionGroup,
)
from easyauth.applications.services import APP_CREDENTIAL_TYPE_STATIC_TOKEN, StaticTokenService
from easyauth.grants.models import AccessGrant
from easyauth.grants.services import (
    AuthorizationGroupGrantInput,
    GrantMutationInput,
    GrantService,
    ScopedDirectGrantInput,
)

CRM_APP_KEY: Final = "crm"
CRM_CREDENTIAL_NAME: Final = "CRM pilot static credential"
CRM_PILOT_USER_ID: Final = "crm-pilot-user"
CRM_OWNER_USER_ID: Final = "crm-owner"
CRM_DEVELOPER_USER_ID: Final = "crm-developer"
CRM_MANIFEST_PATH: Final = Path(__file__).with_name("fixtures") / "crm_pilot_manifest.json"


@dataclass(frozen=True, slots=True)
class SeedResult:
    app: App
    plaintext_token: str | None


@final
class Command(BaseCommand):
    help: str = "创建 CRM 试点配置和一次性静态凭据。"

    @override
    def handle(self, *_args: str, **_options: str) -> None:
        result = seed_crm_pilot()
        self.stdout.write(f"CRM app: {result.app.app_key}")
        match result.plaintext_token:
            case str() as token:
                self.stdout.write(f"static token: {token}")
            case None:
                self.stdout.write("static token: 已存在, 未重新输出明文")


@transaction.atomic
def seed_crm_pilot() -> SeedResult:
    manifest = _load_manifest()
    app = _upsert_manifest_app(manifest)
    _ensure_memberships(app)
    _upsert_manifest_scopes(app, manifest)
    group_by_key = _upsert_manifest_permission_groups(app, manifest)
    permission_by_key = _upsert_manifest_permissions(app, manifest, group_by_key)
    group_models = _upsert_manifest_authorization_groups(app, manifest, permission_by_key)
    _upsert_manifest_approval_rules(app, manifest, group_models)
    _ = bump_catalog_version(
        app,
        actor_id="seed_crm_pilot",
        reason="seed_crm_pilot_applied",
    )
    plaintext_token = _ensure_static_token(app)
    _ensure_seed_grant(
        app=app,
        authorization_group=group_models["admin"],
        direct_permission=permission_by_key["customer.profile.view"],
    )
    return SeedResult(app=app, plaintext_token=plaintext_token)


def _validated_upsert[ModelT: models.Model](
    model: type[ModelT],
    lookup: dict[str, object],
    defaults: dict[str, object],
) -> ModelT:
    # seed 数据也必须走 full_clean, 不允许绕过模型校验落库。
    instance = model.objects.filter(**lookup).first()
    if instance is None:
        instance = model(**lookup)
    for field, value in defaults.items():
        setattr(instance, field, value)
    instance.full_clean()
    instance.save()
    return instance


def _load_manifest() -> dict[str, object]:
    return json.loads(CRM_MANIFEST_PATH.read_text(encoding="utf-8"))


def _upsert_manifest_app(manifest: dict[str, object]) -> App:
    app_payload = _dict(manifest["app"])
    app_key = str(app_payload["app_key"])
    if app_key != CRM_APP_KEY:
        message = "CRM manifest app_key 与 seed 目标不一致。"
        raise ValueError(message)
    return _validated_upsert(
        App,
        {"app_key": app_key},
        {
            "name": str(app_payload["name"]),
            "description": str(app_payload.get("description", "")),
        },
    )


def _ensure_memberships(app: App) -> None:
    _owner, _created = AppMembership.objects.get_or_create(
        app=app,
        user_id=CRM_OWNER_USER_ID,
        role="owner",
    )
    _developer, _created = AppMembership.objects.get_or_create(
        app=app,
        user_id=CRM_DEVELOPER_USER_ID,
        role="developer",
    )


def _upsert_manifest_scopes(app: App, manifest: dict[str, object]) -> None:
    for payload in _list(manifest["scopes"]):
        scope_payload = _dict(payload)
        _ = _validated_upsert(
            AppScope,
            {"app": app, "key": str(scope_payload["key"])},
            {
                "name": str(scope_payload["name"]),
                "description": str(scope_payload.get("description", "")),
                "is_active": bool(scope_payload.get("is_active", True)),
                "display_order": int(scope_payload.get("display_order", 0)),
            },
        )


def _upsert_manifest_permission_groups(
    app: App,
    manifest: dict[str, object],
) -> dict[str, PermissionGroup]:
    group_by_key = {group.key: group for group in PermissionGroup.objects.filter(app=app)}
    for payload in _list(manifest["permission_groups"]):
        group_payload = _dict(payload)
        parent_key = str(group_payload.get("parent_key", ""))
        parent = group_by_key.get(parent_key) if parent_key else None
        group = _validated_upsert(
            PermissionGroup,
            {"app": app, "key": str(group_payload["key"])},
            {
                "name": str(group_payload["name"]),
                "description": str(group_payload.get("description", "")),
                "parent": parent,
                "depth": 1 if parent is None else parent.depth + 1,
                "display_order": int(group_payload.get("display_order", 0)),
                "is_active": bool(group_payload.get("is_active", True)),
            },
        )
        group_by_key[group.key] = group
    return group_by_key


def _upsert_manifest_permissions(
    app: App,
    manifest: dict[str, object],
    group_by_key: dict[str, PermissionGroup],
) -> dict[str, Permission]:
    permission_by_key = {
        permission.key: permission for permission in Permission.objects.filter(app=app)
    }
    for payload in _list(manifest["permissions"]):
        permission_payload = _dict(payload)
        permission = _validated_upsert(
            Permission,
            {"app": app, "key": str(permission_payload["key"])},
            {
                "name": str(permission_payload["name"]),
                "description": str(permission_payload.get("description", "")),
                "group": group_by_key[str(permission_payload.get("group_key", ""))],
                "supported_scopes": [
                    str(scope) for scope in _list(permission_payload["supported_scopes"])
                ],
                "risk_level": str(permission_payload.get("risk_level", "standard")),
                "is_active": bool(permission_payload.get("is_active", True)),
                "deprecated_at": None,
                "deprecated_reason": "",
            },
        )
        permission_by_key[permission.key] = permission
    return permission_by_key


def _upsert_manifest_authorization_groups(
    app: App,
    manifest: dict[str, object],
    permission_by_key: dict[str, Permission],
) -> dict[str, AuthorizationGroup]:
    group_by_key: dict[str, AuthorizationGroup] = {}
    for payload in _list(manifest["authorization_groups"]):
        group_payload = _dict(payload)
        group = _validated_upsert(
            AuthorizationGroup,
            {"app": app, "key": str(group_payload["key"])},
            {
                "kind": str(group_payload.get("kind", "role")),
                "name": str(group_payload["name"]),
                "description": str(group_payload.get("description", "")),
                "requestable": bool(group_payload.get("requestable", True)),
                "is_active": bool(group_payload.get("is_active", True)),
            },
        )
        group_by_key[group.key] = group
        for grant_payload in _list(group_payload.get("grants", [])):
            grant = _dict(grant_payload)
            _ = _validated_upsert(
                AuthorizationGroupGrant,
                {
                    "authorization_group": group,
                    "permission": permission_by_key[str(grant["permission"])],
                    "scope_key": str(grant["scope"]),
                },
                {"is_active": True},
            )
    return group_by_key


def _upsert_manifest_approval_rules(
    app: App,
    manifest: dict[str, object],
    groups: dict[str, AuthorizationGroup],
) -> None:
    for payload in _list(manifest["approval_rules"]):
        rule_payload = _dict(payload)
        target_key = str(rule_payload["target_key"])
        group = groups[target_key]
        _ = _validated_upsert(
            ApprovalRule,
            {"app": app, "authorization_group": group},
            {
                "approver_userids": [
                    str(user_id) for user_id in _list(rule_payload["approver_userids"])
                ],
                "is_active": bool(rule_payload.get("is_active", True)),
            },
        )


def _ensure_static_token(app: App) -> str | None:
    credential = AppCredential.objects.filter(
        app=app,
        credential_type=APP_CREDENTIAL_TYPE_STATIC_TOKEN,
        is_active=True,
    ).first()
    if credential is not None:
        return None
    return StaticTokenService.create_token(app=app, name=CRM_CREDENTIAL_NAME).plaintext_token


def _ensure_seed_grant(
    *,
    app: App,
    authorization_group: AuthorizationGroup,
    direct_permission: Permission,
) -> None:
    user, _ = UserMirror.objects.get_or_create(
        authentik_user_id=CRM_PILOT_USER_ID,
        defaults={
            "name": "CRM 试点用户",
            "email": "crm-pilot@example.internal",
            "department": "试点部门",
        },
    )
    existing_grant = AccessGrant.objects.filter(user=user, app=app, is_current=True).first()
    if existing_grant is not None:
        return
    _ = GrantService.create_grant(
        GrantMutationInput(
            user=user,
            app=app,
            authorization_groups=(
                AuthorizationGroupGrantInput(
                    authorization_group=authorization_group,
                    expires_at=None,
                ),
            ),
            direct_grants=(
                ScopedDirectGrantInput(
                    permission=direct_permission,
                    scope_key="SELF",
                    expires_at=None,
                ),
            ),
            actor_type="system",
            actor_id="seed_crm_pilot",
        ),
    )


def _dict(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        message = "manifest 节点必须是对象。"
        raise TypeError(message)
    return value


def _list(value: object) -> list[object]:
    if not isinstance(value, list):
        message = "manifest 节点必须是列表。"
        raise TypeError(message)
    return value
