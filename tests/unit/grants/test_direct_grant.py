from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from django.utils import timezone

from easyauth.access_requests.submission_types import ScopedAccessRequestGrant
from easyauth.accounts.models import UserMirror
from easyauth.admin_console.grant_write_common import AdminGrantType, ResolvedAdminGrantTargets
from easyauth.applications.models import App, AppScope, AuthorizationGroup, Permission
from easyauth.audit.models import AuditLog
from easyauth.grants.direct_grant import (
    DIRECT_GRANT_APPLIED_ACTION,
    DirectGrantEmptyReplaceError,
    apply_admin_direct_grant,
)
from easyauth.grants.inputs import AuthorizationGroupGrantInput, ScopedDirectGrantInput
from easyauth.grants.models import (
    GRANT_STATUS_REVOKED,
    MEMBERSHIP_SOURCE_DEPARTMENT,
    MEMBERSHIP_SOURCE_USER,
    AccessGrant,
    AccessGrantGroup,
    AccessGrantPermission,
)
from easyauth.grants.services import GrantMutationInput, GrantService

pytestmark = pytest.mark.django_db

DEFAULT_SCOPE_KEY = "GLOBAL"
ACTOR_ID = "admin-direct-grant"


def test_apply_admin_direct_grant_replaces_user_memberships_and_keeps_department_rows() -> None:
    user, app, sales, finance, permission = _catalog("replace")
    first = apply_admin_direct_grant(
        user=user,
        targets=_targets(app, groups=(sales, finance), permission=permission),
        actor_id=ACTOR_ID,
    )
    department_group = AccessGrantGroup.objects.create(
        grant=first,
        authorization_group=finance,
        source=MEMBERSHIP_SOURCE_DEPARTMENT,
    )
    department_direct = AccessGrantPermission.objects.create(
        grant=first,
        permission=permission,
        scope_key=DEFAULT_SCOPE_KEY,
        source=MEMBERSHIP_SOURCE_DEPARTMENT,
    )

    replaced = apply_admin_direct_grant(
        user=user,
        targets=_targets(app, groups=(sales,)),
        actor_id=ACTOR_ID,
    )

    assert replaced.id == first.id
    assert replaced.is_current is True
    user_group_keys = set(
        AccessGrantGroup.objects.filter(grant=replaced, source=MEMBERSHIP_SOURCE_USER).values_list(
            "authorization_group__key",
            flat=True,
        )
    )
    assert user_group_keys == {sales.key}
    assert not AccessGrantPermission.objects.filter(
        grant=replaced, source=MEMBERSHIP_SOURCE_USER
    ).exists()
    assert AccessGrantGroup.objects.filter(pk=department_group.pk).exists()
    assert AccessGrantPermission.objects.filter(pk=department_direct.pk).exists()
    audit = AuditLog.objects.filter(
        event_type=DIRECT_GRANT_APPLIED_ACTION, target_id=str(replaced.id)
    ).latest("id")
    assert audit.metadata["authorization_group_keys"] == [sales.key]
    assert audit.metadata["permission_keys"] == []
    assert audit.metadata["removed_authorization_group_keys"] == [finance.key]
    assert audit.metadata["removed_permission_keys"] == [permission.key]


def test_apply_admin_direct_grant_keeps_existing_expiry_unless_submission_changes_term() -> None:
    user, app, sales, finance, permission = _catalog("expiry")
    first_expiry = (timezone.now() + timedelta(days=10)).replace(microsecond=0)
    _ = GrantService.create_grant(
        GrantMutationInput(
            user=user,
            app=app,
            authorization_groups=(AuthorizationGroupGrantInput(sales, first_expiry),),
            direct_grants=(ScopedDirectGrantInput(permission, DEFAULT_SCOPE_KEY, None),),
            actor_type="admin",
            actor_id=ACTOR_ID,
        ),
    )
    sales_row = AccessGrantGroup.objects.get(
        authorization_group=sales, source=MEMBERSHIP_SOURCE_USER
    )
    permission_row = AccessGrantPermission.objects.get(
        permission=permission, source=MEMBERSHIP_SOURCE_USER
    )

    kept_expires_at = sales_row.expires_at
    kept = apply_admin_direct_grant(
        user=user,
        targets=_targets(
            app,
            groups=(sales, finance),
            permission=permission,
            grant_type="timed",
            grant_expires_at=kept_expires_at,
        ),
        actor_id=ACTOR_ID,
    )
    sales_row = AccessGrantGroup.objects.get(
        grant=kept, authorization_group=sales, source=MEMBERSHIP_SOURCE_USER
    )
    permission_row = AccessGrantPermission.objects.get(
        grant=kept, permission=permission, source=MEMBERSHIP_SOURCE_USER
    )
    finance_row = AccessGrantGroup.objects.get(
        grant=kept, authorization_group=finance, source=MEMBERSHIP_SOURCE_USER
    )
    assert sales_row.expires_at == first_expiry
    assert permission_row.expires_at is None
    assert finance_row.expires_at == first_expiry

    second_expiry = (timezone.now() + timedelta(days=40)).replace(microsecond=0)
    changed = apply_admin_direct_grant(
        user=user,
        targets=_targets(
            app,
            groups=(sales, finance),
            permission=permission,
            grant_type="timed",
            grant_expires_at=second_expiry,
        ),
        actor_id=ACTOR_ID,
    )
    sales_row = AccessGrantGroup.objects.get(
        grant=changed, authorization_group=sales, source=MEMBERSHIP_SOURCE_USER
    )
    permission_row = AccessGrantPermission.objects.get(
        grant=changed, permission=permission, source=MEMBERSHIP_SOURCE_USER
    )
    finance_row = AccessGrantGroup.objects.get(
        grant=changed, authorization_group=finance, source=MEMBERSHIP_SOURCE_USER
    )
    assert sales_row.expires_at == second_expiry
    assert permission_row.expires_at == second_expiry
    assert finance_row.expires_at == second_expiry


def test_apply_admin_direct_grant_empty_replace_keeps_department_rows() -> None:
    user, app, sales, _finance, permission = _catalog("empty-dept")
    grant = apply_admin_direct_grant(
        user=user,
        targets=_targets(app, groups=(sales,), permission=permission),
        actor_id=ACTOR_ID,
    )
    department_group = AccessGrantGroup.objects.create(
        grant=grant,
        authorization_group=sales,
        source=MEMBERSHIP_SOURCE_DEPARTMENT,
    )

    replaced = apply_admin_direct_grant(
        user=user,
        targets=_targets(app),
        actor_id=ACTOR_ID,
    )

    replaced.refresh_from_db()
    assert replaced.is_current is True
    assert replaced.status != GRANT_STATUS_REVOKED
    assert not AccessGrantGroup.objects.filter(
        grant=replaced, source=MEMBERSHIP_SOURCE_USER
    ).exists()
    assert not AccessGrantPermission.objects.filter(
        grant=replaced, source=MEMBERSHIP_SOURCE_USER
    ).exists()
    assert AccessGrantGroup.objects.filter(pk=department_group.pk).exists()
    audit = AuditLog.objects.filter(
        event_type=DIRECT_GRANT_APPLIED_ACTION, target_id=str(replaced.id)
    ).latest("id")
    assert audit.metadata["authorization_group_keys"] == []
    assert audit.metadata["permission_keys"] == []
    assert audit.metadata["removed_authorization_group_keys"] == [sales.key]
    assert audit.metadata["removed_permission_keys"] == [permission.key]


def test_apply_admin_direct_grant_empty_replace_revokes_grant_when_only_user_rows() -> None:
    user, app, sales, _finance, permission = _catalog("empty-revoke")
    grant = apply_admin_direct_grant(
        user=user,
        targets=_targets(app, groups=(sales,), permission=permission),
        actor_id=ACTOR_ID,
    )

    revoked = apply_admin_direct_grant(
        user=user,
        targets=_targets(app, reason="收回全部直接授权"),
        actor_id=ACTOR_ID,
    )

    revoked.refresh_from_db()
    assert revoked.id == grant.id
    assert revoked.is_current is False
    assert revoked.status == GRANT_STATUS_REVOKED
    assert AccessGrant.objects.filter(user=user, app=app, is_current=True).count() == 0
    audit = AuditLog.objects.filter(
        event_type=DIRECT_GRANT_APPLIED_ACTION, target_id=str(revoked.id)
    ).latest("id")
    assert audit.metadata["reason"] == "收回全部直接授权"
    assert audit.metadata["authorization_group_keys"] == []
    assert audit.metadata["permission_keys"] == []
    assert audit.metadata["removed_authorization_group_keys"] == [sales.key]
    assert audit.metadata["removed_permission_keys"] == [permission.key]


def test_apply_admin_direct_grant_empty_replace_without_current_grant_fails() -> None:
    user, app, _sales, _finance, _permission = _catalog("empty-missing")

    with pytest.raises(DirectGrantEmptyReplaceError, match="至少选择一个授权组或权限"):
        apply_admin_direct_grant(user=user, targets=_targets(app), actor_id=ACTOR_ID)

    assert AccessGrant.objects.filter(user=user, app=app).count() == 0
    assert AuditLog.objects.filter(event_type=DIRECT_GRANT_APPLIED_ACTION).count() == 0


def _catalog(
    prefix: str,
) -> tuple[UserMirror, App, AuthorizationGroup, AuthorizationGroup, Permission]:
    user = UserMirror.objects.create(authentik_user_id=f"{prefix}-user")
    app = App.objects.create(app_key=f"{prefix}-app", name=prefix)
    _ = AppScope.objects.create(app=app, key=DEFAULT_SCOPE_KEY, name="全局")
    permission = Permission.objects.create(
        app=app,
        key="order.order.view",
        name="查看订单",
        supported_scopes=[DEFAULT_SCOPE_KEY],
    )
    sales = AuthorizationGroup.objects.create(
        app=app,
        key="sales",
        kind="role",
        name="销售",
        requestable=False,
    )
    finance = AuthorizationGroup.objects.create(
        app=app,
        key="finance",
        kind="role",
        name="财务",
        requestable=False,
    )
    return user, app, sales, finance, permission


def _targets(  # noqa: PLR0913 - 测试目标构造需要显式覆盖各字段。
    app: App,
    *,
    groups: tuple[AuthorizationGroup, ...] = (),
    permission: Permission | None = None,
    grant_type: AdminGrantType = "permanent",
    grant_expires_at: datetime | None = None,
    reason: str = "管理员直接授权",
) -> ResolvedAdminGrantTargets:
    directs: tuple[ScopedAccessRequestGrant, ...] = (
        () if permission is None else (ScopedAccessRequestGrant(permission, DEFAULT_SCOPE_KEY),)
    )
    return ResolvedAdminGrantTargets(
        app=app,
        authorization_groups=groups,
        direct_grants=directs,
        grant_type=grant_type,
        grant_expires_at=grant_expires_at,
        reason=reason,
    )
