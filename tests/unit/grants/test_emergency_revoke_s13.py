from __future__ import annotations

from typing import Final

import pytest

from easyauth.accounts.models import UserMirror
from easyauth.admin_console.grants import emergency_revoke_for_user
from easyauth.applications.models import App, Permission
from easyauth.audit.models import AuditLog
from easyauth.grants.models import (
    GRANT_STATUS_REVOKED,
    GRANT_TYPE_PERMANENT,
    AccessGrant,
    AccessGrantPermission,
)
from easyauth.grants.services import GrantService

pytestmark = pytest.mark.django_db

REVOKED_VERSION: Final = 2
EMERGENCY_REASON: Final = "suspected_compromise"
EXPECTED_PERMISSION_LINKS: Final = 2
EXPECTED_REVOKED_GRANTS: Final = 2


def test_s13_emergency_revoke_for_user_revokes_current_grants_without_adding_permissions() -> None:
    # Given: 用户在两个应用中有当前授权和直接权限。
    user = UserMirror.objects.create(authentik_user_id="s13-emergency-user")
    crm = App.objects.create(app_key="s13-emergency-crm", name="S13 Emergency CRM")
    erp = App.objects.create(app_key="s13-emergency-erp", name="S13 Emergency ERP")
    crm_permission = Permission.objects.create(app=crm, key="invoice.read", name="Read invoices")
    erp_permission = Permission.objects.create(app=erp, key="order.read", name="Read orders")
    crm_grant = AccessGrant.objects.create(user=user, app=crm, grant_type=GRANT_TYPE_PERMANENT)
    erp_grant = AccessGrant.objects.create(user=user, app=erp, grant_type=GRANT_TYPE_PERMANENT)
    _ = AccessGrantPermission.objects.create(grant=crm_grant, permission=crm_permission)
    _ = AccessGrantPermission.objects.create(grant=erp_grant, permission=erp_permission)

    # When: 管理员执行紧急撤权并重复提交。
    first = GrantService.emergency_revoke_for_user(
        user=user,
        reason=EMERGENCY_REASON,
        actor_type="admin",
        actor_id="security-admin",
    )
    repeated = GrantService.emergency_revoke_for_user(
        user=user,
        reason=EMERGENCY_REASON,
        actor_type="admin",
        actor_id="security-admin",
    )

    # Then: 授权被撤销、权限链接没有新增, 且重复撤权不再递增版本或写审计。
    crm_grant.refresh_from_db()
    erp_grant.refresh_from_db()
    assert [grant.app.app_key for grant in first] == ["s13-emergency-crm", "s13-emergency-erp"]
    assert repeated == []
    assert crm_grant.status == GRANT_STATUS_REVOKED
    assert erp_grant.status == GRANT_STATUS_REVOKED
    assert crm_grant.version == REVOKED_VERSION
    assert erp_grant.version == REVOKED_VERSION
    permission_link_count = AccessGrantPermission.objects.filter(grant__user=user).count()
    assert permission_link_count == EXPECTED_PERMISSION_LINKS
    audit_logs = AuditLog.objects.filter(event_type="grant_revoked", actor_id="security-admin")
    assert audit_logs.count() == EXPECTED_REVOKED_GRANTS
    for audit_log in audit_logs:
        assert audit_log.metadata["reason"] == EMERGENCY_REASON


def test_s13_admin_console_emergency_revoke_uses_grant_write_boundary() -> None:
    # Given: 管理控制台需要通过受控入口执行用户级紧急撤权。
    user = UserMirror.objects.create(authentik_user_id="s13-admin-emergency-user")
    app = App.objects.create(app_key="s13-admin-emergency-app", name="S13 Admin Emergency")
    permission = Permission.objects.create(app=app, key="invoice.read", name="Read invoices")
    grant = AccessGrant.objects.create(user=user, app=app, grant_type=GRANT_TYPE_PERMANENT)
    _ = AccessGrantPermission.objects.create(grant=grant, permission=permission)

    # When: 管理员通过 admin_console 编排入口执行紧急撤权。
    result = emergency_revoke_for_user(
        user=user,
        reason=EMERGENCY_REASON,
        actor_id="security-admin-console",
    )

    # Then: 授权经 GrantService 写边界撤销, 并保留原因审计。
    grant.refresh_from_db()
    assert [revoked.app.app_key for revoked in result.revoked_grants] == [
        "s13-admin-emergency-app",
    ]
    assert result.revoked_count == 1
    assert grant.status == GRANT_STATUS_REVOKED
    audit_log = AuditLog.objects.get(
        event_type="grant_revoked",
        actor_id="security-admin-console",
    )
    assert audit_log.actor_type == "admin"
    assert audit_log.metadata["reason"] == EMERGENCY_REASON
