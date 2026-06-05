from __future__ import annotations

from dataclasses import dataclass
from typing import Final, final, override

from django.core.management.base import BaseCommand
from django.db import transaction

from easyauth.accounts.models import UserMirror
from easyauth.applications.models import (
    App,
    AppCredential,
    ApprovalRule,
    Permission,
    Role,
    RolePermission,
)
from easyauth.applications.services import APP_CREDENTIAL_TYPE_STATIC_TOKEN, StaticTokenService
from easyauth.grants.models import AccessGrant
from easyauth.grants.services import GrantMutationInput, GrantService

CRM_APP_KEY: Final = "crm"
CRM_CREDENTIAL_NAME: Final = "CRM pilot static credential"
CRM_PILOT_USER_ID: Final = "crm-pilot-user"
CRM_APPROVERS: Final[tuple[str, ...]] = ("manager-001",)


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
    app, _ = App.objects.get_or_create(
        app_key=CRM_APP_KEY,
        defaults={"name": "CRM"},
    )
    admin_role = _role(app=app, key="admin", name="CRM 管理员")
    auditor_role = _role(app=app, key="auditor", name="CRM 审计员")
    view_permission = _permission(
        app=app,
        key="customer:view:department",
        name="查看本部门客户",
    )
    export_permission = _permission(app=app, key="customer:export", name="导出客户")
    _ = _permission(app=app, key="customer:edit", name="编辑客户")
    _ = _role_permission(role=admin_role, permission=view_permission)
    _ = _role_permission(role=admin_role, permission=export_permission)
    _ = _role_permission(role=auditor_role, permission=view_permission)
    _ = _approval_rule(app=app, role=admin_role)
    _ = _approval_rule(app=app, role=auditor_role)
    plaintext_token = _ensure_static_token(app)
    _ensure_seed_grant(app=app, role=admin_role)
    return SeedResult(app=app, plaintext_token=plaintext_token)


def _role(*, app: App, key: str, name: str) -> Role:
    role, _ = Role.objects.get_or_create(
        app=app,
        key=key,
        defaults={"name": name, "requestable": True},
    )
    if not role.requestable:
        role.requestable = True
        role.save(update_fields=["requestable", "updated_at"])
    return role


def _permission(*, app: App, key: str, name: str) -> Permission:
    permission, _ = Permission.objects.get_or_create(
        app=app,
        key=key,
        defaults={"name": name},
    )
    return permission


def _approval_rule(*, app: App, role: Role) -> ApprovalRule:
    approval_rule, _ = ApprovalRule.objects.get_or_create(
        app=app,
        role=role,
        defaults={"approver_userids": list(CRM_APPROVERS)},
    )
    return approval_rule


def _role_permission(*, role: Role, permission: Permission) -> RolePermission:
    role_permission, _ = RolePermission.objects.get_or_create(role=role, permission=permission)
    return role_permission


def _ensure_static_token(app: App) -> str | None:
    credential = AppCredential.objects.filter(
        app=app,
        credential_type=APP_CREDENTIAL_TYPE_STATIC_TOKEN,
        is_active=True,
    ).first()
    if credential is not None:
        return None
    return StaticTokenService.create_token(app=app, name=CRM_CREDENTIAL_NAME).plaintext_token


def _ensure_seed_grant(*, app: App, role: Role) -> None:
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
            roles=(role,),
            actor_type="system",
            actor_id="seed_crm_pilot",
        ),
    )
