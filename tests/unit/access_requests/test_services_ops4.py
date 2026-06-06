from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from easyauth.access_requests.models import (
    GRANT_TYPE_PERMANENT,
    GRANT_TYPE_TIMED,
    REQUEST_STATUS_SUBMITTED,
    REQUEST_TYPE_CHANGE,
    REQUEST_TYPE_RENEW,
    REQUEST_TYPE_REVOKE,
    AccessRequest,
    AccessRequestPermission,
    AccessRequestRole,
)
from easyauth.access_requests.services import (
    AccessRequestService,
    AccessRequestSubmission,
    AccessRequestSubmissionError,
)
from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App, ApprovalRule, Permission, Role
from easyauth.audit.models import AuditLog
from easyauth.grants.models import (
    GRANT_STATUS_REVOKED,
    AccessGrant,
    AccessGrantPermission,
    AccessGrantRole,
)
from easyauth.grants.models import (
    GRANT_TYPE_TIMED as GRANT_RECORD_TYPE_TIMED,
)

pytestmark = pytest.mark.django_db


def test_ops4_submit_change_request_requires_current_active_grant() -> None:
    # Given: 员工在目标 App 下还没有 active 授权。
    user = UserMirror.objects.create(authentik_user_id="ops4-change-no-grant-user")
    app = App.objects.create(app_key="ops4-change-no-grant-app", name="OPS4 Change Missing")
    role = Role.objects.create(app=app, key="writer", name="Writer")
    _ = ApprovalRule.objects.create(app=app, role=role, approver_userids=["manager-001"])

    # When / Then: 变更申请被拒绝, 不落库申请或审计。
    with pytest.raises(AccessRequestSubmissionError) as exc_info:
        _ = AccessRequestService.submit_access_request(
            AccessRequestSubmission(
                user=user,
                app=app,
                roles=(role,),
                grant_type=GRANT_TYPE_PERMANENT,
                grant_expires_at=None,
                reason="需要变更为写权限",
                actor_type="user",
                actor_id=user.authentik_user_id,
                request_type=REQUEST_TYPE_CHANGE,
            ),
        )

    assert "active grant" in str(exc_info.value)
    assert AccessRequest.objects.count() == 0
    assert AuditLog.objects.count() == 0


def test_ops4_submit_change_request_creates_submitted_lifecycle_request_only() -> None:
    # Given: 员工已有目标 App 的 active 授权。
    user = UserMirror.objects.create(authentik_user_id="ops4-change-user")
    app = App.objects.create(app_key="ops4-change-app", name="OPS4 Change")
    old_role = Role.objects.create(app=app, key="reader", name="Reader")
    new_role = Role.objects.create(app=app, key="writer", name="Writer")
    grant = AccessGrant.objects.create(user=user, app=app, grant_type=GRANT_TYPE_PERMANENT)
    _ = AccessGrantRole.objects.create(grant=grant, role=old_role)
    _ = ApprovalRule.objects.create(app=app, role=new_role, approver_userids=["manager-001"])

    # When: 员工提交角色变更申请。
    access_request = AccessRequestService.submit_access_request(
        AccessRequestSubmission(
            user=user,
            app=app,
            roles=(new_role,),
            grant_type=GRANT_TYPE_PERMANENT,
            grant_expires_at=None,
            reason="需要处理发票",
            actor_type="user",
            actor_id=user.authentik_user_id,
            request_type=REQUEST_TYPE_CHANGE,
        ),
    )

    # Then: 服务只写 submitted 申请, 不直接改变当前授权事实。
    grant.refresh_from_db()
    assert access_request.request_type == REQUEST_TYPE_CHANGE
    assert access_request.status == REQUEST_STATUS_SUBMITTED
    assert AccessRequestRole.objects.get(access_request=access_request).role == new_role
    assert grant.version == 1
    assert AccessGrantRole.objects.get(grant=grant).role == old_role


def test_ops4_submit_change_request_accepts_direct_permission_only_target() -> None:
    # Given: 员工已有 active 授权, 目标 direct Permission 有 active 审批规则。
    user = UserMirror.objects.create(authentik_user_id="ops4-change-permission-user")
    app = App.objects.create(app_key="ops4-change-permission-app", name="OPS4 Change Permission")
    old_permission = Permission.objects.create(app=app, key="invoice.read", name="Invoice Read")
    new_permission = Permission.objects.create(app=app, key="invoice.write", name="Invoice Write")
    grant = AccessGrant.objects.create(user=user, app=app, grant_type=GRANT_TYPE_PERMANENT)
    _ = AccessGrantPermission.objects.create(grant=grant, permission=old_permission)
    _ = ApprovalRule.objects.create(
        app=app,
        permission=new_permission,
        approver_userids=["manager-001"],
    )

    # When: 员工只提交 direct Permission 目标的 change 申请。
    access_request = AccessRequestService.submit_access_request(
        AccessRequestSubmission(
            user=user,
            app=app,
            roles=(),
            permissions=(new_permission,),
            grant_type=GRANT_TYPE_PERMANENT,
            grant_expires_at=None,
            reason="需要发票写权限",
            actor_type="user",
            actor_id=user.authentik_user_id,
            request_type=REQUEST_TYPE_CHANGE,
        ),
    )

    # Then: 服务创建 direct Permission 目标申请, 不要求角色目标。
    grant.refresh_from_db()
    assert access_request.request_type == REQUEST_TYPE_CHANGE
    assert access_request.status == REQUEST_STATUS_SUBMITTED
    request_permission = AccessRequestPermission.objects.get(access_request=access_request)
    assert request_permission.permission == new_permission
    assert AccessRequestRole.objects.filter(access_request=access_request).count() == 0
    assert grant.version == 1


def test_ops4_submit_revoke_request_accepts_empty_target_for_full_revoke() -> None:
    # Given: 员工已有目标 App 的 active 授权。
    user = UserMirror.objects.create(authentik_user_id="ops4-revoke-empty-user")
    app = App.objects.create(app_key="ops4-revoke-empty-app", name="OPS4 Revoke Empty")
    role = Role.objects.create(app=app, key="reader", name="Reader")
    grant = AccessGrant.objects.create(user=user, app=app, grant_type=GRANT_TYPE_PERMANENT)
    _ = AccessGrantRole.objects.create(grant=grant, role=role)

    # When: 员工提交空目标撤销申请。
    access_request = AccessRequestService.submit_access_request(
        AccessRequestSubmission(
            user=user,
            app=app,
            roles=(),
            grant_type=GRANT_TYPE_PERMANENT,
            grant_expires_at=None,
            reason="不再需要访问",
            actor_type="user",
            actor_id=user.authentik_user_id,
            request_type=REQUEST_TYPE_REVOKE,
        ),
    )

    # Then: 申请进入审批, 当前授权暂不变化。
    grant.refresh_from_db()
    assert access_request.request_type == REQUEST_TYPE_REVOKE
    assert AccessRequestRole.objects.filter(access_request=access_request).count() == 0
    assert grant.is_current is True
    assert grant.version == 1


def test_ops4_submit_revoke_request_rejects_role_outside_current_grant() -> None:
    # Given: 员工当前授权只有 reader 角色。
    user = UserMirror.objects.create(authentik_user_id="ops4-revoke-superset-user")
    app = App.objects.create(app_key="ops4-revoke-superset-app", name="OPS4 Revoke Superset")
    current_role = Role.objects.create(app=app, key="reader", name="Reader")
    outside_role = Role.objects.create(app=app, key="admin", name="Admin")
    grant = AccessGrant.objects.create(user=user, app=app, grant_type=GRANT_TYPE_PERMANENT)
    _ = AccessGrantRole.objects.create(grant=grant, role=current_role)

    # When / Then: 撤销申请不能把当前授权外的角色放入目标集合。
    with pytest.raises(AccessRequestSubmissionError) as exc_info:
        _ = AccessRequestService.submit_access_request(
            AccessRequestSubmission(
                user=user,
                app=app,
                roles=(outside_role,),
                grant_type=GRANT_TYPE_PERMANENT,
                grant_expires_at=None,
                reason="撤销不能扩大权限",
                actor_type="user",
                actor_id=user.authentik_user_id,
                request_type=REQUEST_TYPE_REVOKE,
            ),
        )

    assert "current grant" in str(exc_info.value)
    assert AccessRequest.objects.count() == 0


def test_ops4_submit_renew_request_preserves_timed_lifecycle_target() -> None:
    # Given: 员工已有未过期的限时授权。
    user = UserMirror.objects.create(authentik_user_id="ops4-renew-user")
    app = App.objects.create(app_key="ops4-renew-app", name="OPS4 Renew")
    role = Role.objects.create(app=app, key="reader", name="Reader")
    now = timezone.now()
    grant = AccessGrant.objects.create(
        user=user,
        app=app,
        grant_type=GRANT_RECORD_TYPE_TIMED,
        grant_expires_at=now + timedelta(days=3),
    )
    _ = AccessGrantRole.objects.create(grant=grant, role=role)
    renewed_until = now + timedelta(days=10)

    # When: 员工提交续期申请。
    access_request = AccessRequestService.submit_access_request(
        AccessRequestSubmission(
            user=user,
            app=app,
            roles=(role,),
            grant_type=GRANT_TYPE_TIMED,
            grant_expires_at=renewed_until,
            reason="项目延期",
            actor_type="user",
            actor_id=user.authentik_user_id,
            request_type=REQUEST_TYPE_RENEW,
        ),
    )

    # Then: 续期申请保留新期限, 当前授权等待审批后再变更。
    grant.refresh_from_db()
    assert access_request.request_type == REQUEST_TYPE_RENEW
    assert access_request.grant_expires_at == renewed_until
    assert grant.grant_expires_at == now + timedelta(days=3)


def test_ops4_submit_renew_request_rejects_permanent_conversion() -> None:
    # Given: 员工已有未过期的限时授权。
    user = UserMirror.objects.create(authentik_user_id="ops4-renew-permanent-user")
    app = App.objects.create(app_key="ops4-renew-permanent-app", name="OPS4 Renew Permanent")
    grant = AccessGrant.objects.create(
        user=user,
        app=app,
        grant_type=GRANT_RECORD_TYPE_TIMED,
        grant_expires_at=timezone.now() + timedelta(days=3),
    )

    # When / Then: 续期不能把限时授权转换成永久授权。
    with pytest.raises(AccessRequestSubmissionError) as exc_info:
        _ = AccessRequestService.submit_access_request(
            AccessRequestSubmission(
                user=user,
                app=app,
                roles=(),
                grant_type=GRANT_TYPE_PERMANENT,
                grant_expires_at=None,
                reason="希望转永久",
                actor_type="user",
                actor_id=user.authentik_user_id,
                request_type=REQUEST_TYPE_RENEW,
            ),
        )

    grant.refresh_from_db()
    assert "timed grant" in str(exc_info.value)
    assert grant.version == 1


def test_ops4_submit_lifecycle_request_rejects_revoked_current_grant() -> None:
    # Given: 员工目标 App 下只有 revoked 授权。
    user = UserMirror.objects.create(authentik_user_id="ops4-revoked-user")
    app = App.objects.create(app_key="ops4-revoked-app", name="OPS4 Revoked")
    role = Role.objects.create(app=app, key="reader", name="Reader")
    _ = AccessGrant.objects.create(
        user=user,
        app=app,
        grant_type=GRANT_TYPE_PERMANENT,
        status=GRANT_STATUS_REVOKED,
        is_current=False,
    )
    _ = ApprovalRule.objects.create(app=app, role=role, approver_userids=["manager-001"])

    # When / Then: 生命周期申请被拒绝。
    with pytest.raises(AccessRequestSubmissionError) as exc_info:
        _ = AccessRequestService.submit_access_request(
            AccessRequestSubmission(
                user=user,
                app=app,
                roles=(role,),
                grant_type=GRANT_TYPE_PERMANENT,
                grant_expires_at=None,
                reason="已撤销授权不能变更",
                actor_type="user",
                actor_id=user.authentik_user_id,
                request_type=REQUEST_TYPE_CHANGE,
            ),
        )

    assert "active grant" in str(exc_info.value)
    assert AccessRequest.objects.count() == 0
