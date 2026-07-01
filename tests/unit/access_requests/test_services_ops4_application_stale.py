from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from django.utils import timezone

from easyauth.access_requests.models import (
    GRANT_TYPE_PERMANENT,
    GRANT_TYPE_TIMED,
    REQUEST_STATUS_APPROVED,
    REQUEST_STATUS_GRANT_FAILED,
    REQUEST_TYPE_CHANGE,
    REQUEST_TYPE_RENEW,
    REQUEST_TYPE_REVOKE,
    AccessRequest,
    AccessRequestGroup,
)
from easyauth.access_requests.services import (
    AccessRequestApplication,
    AccessRequestApplicationError,
    AccessRequestService,
)
from easyauth.accounts.models import USER_STATUS_DISABLED, UserMirror
from easyauth.applications.models import App, ApprovalRule, AuthorizationGroup
from easyauth.audit.models import AuditLog
from easyauth.grants.models import AccessGrant, AccessGrantGroup

pytestmark = pytest.mark.django_db


def test_ops4_apply_approved_request_rejects_disabled_user_without_mutating_grant() -> None:
    # Given: 审批通过后, 申请人被禁用。
    user = UserMirror.objects.create(
        authentik_user_id="ops4-apply-disabled-user",
        status=USER_STATUS_DISABLED,
    )
    app = App.objects.create(app_key="ops4-apply-disabled-app", name="OPS4 Disabled")
    group = _authorization_group(app, key="reader", name="Reader")
    grant = AccessGrant.objects.create(user=user, app=app, grant_type=GRANT_TYPE_PERMANENT)
    access_request = _approved_request(user=user, app=app, request_type=REQUEST_TYPE_CHANGE)
    _ = AccessRequestGroup.objects.create(access_request=access_request, authorization_group=group)

    # When: 审批回调尝试应用该申请。
    with pytest.raises(AccessRequestApplicationError):
        _ = AccessRequestService.apply_approved_access_request(_application(access_request))

    # Then: 授权事实不变, 申请进入 grant_failed。
    grant.refresh_from_db()
    access_request.refresh_from_db()
    assert grant.version == 1
    assert access_request.status == REQUEST_STATUS_GRANT_FAILED
    assert AuditLog.objects.filter(event_type="grant_apply_failed").count() == 1


def test_ops4_apply_approved_request_rejects_inactive_app_without_mutating_grant() -> None:
    # Given: 审批通过后, 目标 App 被停用。
    user = UserMirror.objects.create(authentik_user_id="ops4-apply-inactive-app-user")
    app = App.objects.create(
        app_key="ops4-apply-inactive-app",
        name="OPS4 Inactive App",
        is_active=False,
    )
    group = _authorization_group(app, key="reader", name="Reader")
    grant = AccessGrant.objects.create(user=user, app=app, grant_type=GRANT_TYPE_PERMANENT)
    access_request = _approved_request(user=user, app=app, request_type=REQUEST_TYPE_CHANGE)
    _ = AccessRequestGroup.objects.create(access_request=access_request, authorization_group=group)

    # When: 审批回调尝试应用该申请。
    with pytest.raises(AccessRequestApplicationError):
        _ = AccessRequestService.apply_approved_access_request(_application(access_request))

    # Then: 授权事实不变, 申请进入 grant_failed。
    grant.refresh_from_db()
    access_request.refresh_from_db()
    assert grant.version == 1
    assert access_request.status == REQUEST_STATUS_GRANT_FAILED
    assert AuditLog.objects.filter(event_type="grant_apply_failed").count() == 1


def test_ops4_apply_stale_partial_revoke_rejects_non_current_target() -> None:
    # Given: revoke 申请审批后, 当前授权组已变更。
    user = UserMirror.objects.create(authentik_user_id="ops4-apply-stale-revoke-user")
    app = App.objects.create(app_key="ops4-apply-stale-revoke-app", name="OPS4 Stale Revoke")
    old_group = _authorization_group(app, key="old", name="Old")
    new_group = _authorization_group(app, key="new", name="New")
    _ = ApprovalRule.objects.create(
        app=app,
        authorization_group=old_group,
        approver_userids=["manager-001"],
    )
    grant = AccessGrant.objects.create(user=user, app=app, grant_type=GRANT_TYPE_PERMANENT)
    _ = AccessGrantGroup.objects.create(grant=grant, authorization_group=new_group)
    access_request = _approved_request(user=user, app=app, request_type=REQUEST_TYPE_REVOKE)
    _ = AccessRequestGroup.objects.create(
        access_request=access_request,
        authorization_group=old_group,
    )

    # When: 审批回调尝试应用过期目标。
    with pytest.raises(AccessRequestApplicationError):
        _ = AccessRequestService.apply_approved_access_request(_application(access_request))

    # Then: 不会把旧授权组重新写回当前授权。
    grant.refresh_from_db()
    access_request.refresh_from_db()
    group_keys = tuple(
        AccessGrantGroup.objects.filter(grant=grant).values_list(
            "authorization_group__key",
            flat=True,
        ),
    )
    assert group_keys == ("new",)
    assert grant.version == 1
    assert access_request.status == REQUEST_STATUS_GRANT_FAILED


def test_ops4_apply_stale_renew_rejects_changed_membership() -> None:
    # Given: renew 申请审批后, 当前授权组已变更。
    user = UserMirror.objects.create(authentik_user_id="ops4-apply-stale-renew-user")
    app = App.objects.create(app_key="ops4-apply-stale-renew-app", name="OPS4 Stale Renew")
    old_group = _authorization_group(app, key="old", name="Old")
    new_group = _authorization_group(app, key="new", name="New")
    _ = ApprovalRule.objects.create(
        app=app,
        authorization_group=old_group,
        approver_userids=["manager-001"],
    )
    current_expires_at = timezone.now() + timedelta(days=3)
    grant = AccessGrant.objects.create(
        user=user,
        app=app,
        grant_type=GRANT_TYPE_TIMED,
        grant_expires_at=current_expires_at,
    )
    _ = AccessGrantGroup.objects.create(grant=grant, authorization_group=new_group)
    access_request = _approved_request(
        user=user,
        app=app,
        request_type=REQUEST_TYPE_RENEW,
        grant_type=GRANT_TYPE_TIMED,
        grant_expires_at=timezone.now() + timedelta(days=10),
    )
    _ = AccessRequestGroup.objects.create(
        access_request=access_request,
        authorization_group=old_group,
    )

    # When: 审批回调尝试应用过期续期目标。
    with pytest.raises(AccessRequestApplicationError):
        _ = AccessRequestService.apply_approved_access_request(_application(access_request))

    # Then: 授权成员和期限都保持当前事实。
    grant.refresh_from_db()
    access_request.refresh_from_db()
    group_keys = tuple(
        AccessGrantGroup.objects.filter(grant=grant).values_list(
            "authorization_group__key",
            flat=True,
        ),
    )
    assert group_keys == ("new",)
    assert grant.grant_expires_at == current_expires_at
    assert grant.version == 1
    assert access_request.status == REQUEST_STATUS_GRANT_FAILED


def _approved_request(
    *,
    user: UserMirror,
    app: App,
    request_type: str,
    grant_type: str = GRANT_TYPE_PERMANENT,
    grant_expires_at: datetime | None = None,
) -> AccessRequest:
    return AccessRequest.objects.create(
        user=user,
        app=app,
        request_type=request_type,
        status=REQUEST_STATUS_APPROVED,
        grant_type=grant_type,
        grant_expires_at=grant_expires_at,
        reason="审批已通过",
        approved_at=timezone.now(),
    )


def _authorization_group(app: App, *, key: str, name: str) -> AuthorizationGroup:
    return AuthorizationGroup.objects.create(app=app, key=key, kind="role", name=name)


def _application(access_request: AccessRequest) -> AccessRequestApplication:
    return AccessRequestApplication(
        request_id=access_request.id,
        actor_type="approval",
        actor_id="dingtalk-callback",
    )
