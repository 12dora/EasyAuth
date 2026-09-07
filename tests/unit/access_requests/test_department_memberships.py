from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from easyauth.access_requests.models import AccessRequestPermission
from easyauth.access_requests.services import (
    AccessRequestApplication,
    AccessRequestApplicationError,
    AccessRequestService,
    AccessRequestSubmission,
    AccessRequestSubmissionError,
)
from easyauth.accounts.models import UserMirror
from easyauth.applications.models import (
    App,
    ApprovalRule,
    AuthorizationGroup,
    AuthorizationGroupGrant,
)
from easyauth.grants.models import AccessGrant, AccessGrantGroup, AccessGrantPermission
from tests.unit.access_requests.test_services_ops4_application import (
    _approved_request,
    _scoped_permission,
)

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("request_type", ["change", "renew", "revoke"])
def test_approved_request_changes_only_personal_source(request_type: str) -> None:
    user = UserMirror.objects.create(
        authentik_user_id=f"department-{request_type}", status="active"
    )
    app = App.objects.create(app_key=f"department-{request_type}", name="组织授权申请")
    personal = _scoped_permission(app, key="personal", name="个人权限")
    department = _scoped_permission(app, key="department", name="部门权限")
    grant = AccessGrant.objects.create(user=user, app=app)
    expiry = timezone.now() + timedelta(days=1)
    AccessGrantPermission.objects.create(
        grant=grant, permission=personal, source="user", expires_at=expiry
    )
    department_row = AccessGrantPermission.objects.create(
        grant=grant, permission=department, source="department"
    )
    overlap = AccessGrantPermission.objects.create(
        grant=grant, permission=personal, source="department"
    )
    renewed_expiry = expiry + timedelta(days=1)
    request = _approved_request(
        user=user,
        app=app,
        request_type=request_type,
        grant_type="timed",
        grant_expires_at=renewed_expiry,
        base_grant=grant,
    )
    if request_type != "revoke":
        AccessRequestPermission.objects.create(
            access_request=request, permission=personal, scope_key="GLOBAL"
        )
    applied = AccessRequestService.apply_approved_access_request(
        AccessRequestApplication(request_id=request.id, actor_type="approval", actor_id="approver")
    )
    assert applied.status == "grant_applied"
    grant.refresh_from_db()
    assert grant.is_current
    assert grant.status == "active"
    assert grant.version == 2
    assert AccessGrantPermission.objects.filter(pk=department_row.pk).exists()
    assert AccessGrantPermission.objects.filter(pk=overlap.pk).exists()
    personal_rows = AccessGrantPermission.objects.filter(grant=grant, source="user")
    if request_type == "revoke":
        assert not personal_rows.exists()
    else:
        assert personal_rows.get().permission == personal
        assert personal_rows.get().expires_at == renewed_expiry


def test_partial_revoke_preserves_personal_expiry_without_copying_department_rows() -> None:
    user = UserMirror.objects.create(authentik_user_id="department-partial", status="active")
    app = App.objects.create(app_key="department-partial", name="部分撤销")
    kept = _scoped_permission(app, key="kept", name="保留")
    removed = _scoped_permission(app, key="removed", name="移除")
    grant = AccessGrant.objects.create(user=user, app=app)
    expiry = timezone.now() + timedelta(days=1)
    AccessGrantPermission.objects.create(
        grant=grant, permission=kept, source="user", expires_at=expiry
    )
    AccessGrantPermission.objects.create(grant=grant, permission=removed, source="user")
    department_row = AccessGrantPermission.objects.create(
        grant=grant, permission=kept, source="department"
    )
    request = _approved_request(user=user, app=app, request_type="revoke", base_grant=grant)
    AccessRequestPermission.objects.create(
        access_request=request, permission=kept, scope_key="GLOBAL"
    )
    applied = AccessRequestService.apply_approved_access_request(
        AccessRequestApplication(request_id=request.id, actor_type="approval", actor_id="approver")
    )
    assert applied.status == "grant_applied"
    assert AccessGrantPermission.objects.get(grant=grant, source="user").expires_at == expiry
    assert not AccessGrantPermission.objects.filter(
        grant=grant, source="user", permission=removed
    ).exists()
    assert AccessGrantPermission.objects.filter(pk=department_row.pk).exists()


@pytest.mark.parametrize("personal_kind", [None, "group", "permission"])
def test_plain_grant_submission_only_conflicts_with_personal_rows(
    personal_kind: str | None,
) -> None:
    user = UserMirror.objects.create(authentik_user_id="plain-submit", status="active")
    approver = UserMirror.objects.create(authentik_user_id="approver", status="active")
    app = App.objects.create(app_key="plain-submit", name="普通授权申请")
    permission = _scoped_permission(app, key="read", name="读取")
    group = AuthorizationGroup.objects.create(app=app, key="reader", name="读取", kind="role")
    ApprovalRule.objects.create(app=app, authorization_group=group, approver_userids=["approver"])
    AuthorizationGroupGrant.objects.create(
        authorization_group=group, permission=permission, scope_key="GLOBAL"
    )
    grant = AccessGrant.objects.create(user=user, app=app)
    AccessGrantPermission.objects.create(grant=grant, permission=permission, source="department")
    if personal_kind == "group":
        AccessGrantGroup.objects.create(grant=grant, authorization_group=group, source="user")
    elif personal_kind == "permission":
        AccessGrantPermission.objects.create(grant=grant, permission=permission, source="user")
    submission = AccessRequestSubmission(
        user=user,
        app=app,
        authorization_groups=(group,),
        grant_type="permanent",
        grant_expires_at=None,
        reason="个人授权",
        actor_type="user",
        actor_id=user.authentik_user_id,
        idempotency_key="plain-submit",
        approver_user_ids=(approver.authentik_user_id,),
    )
    if personal_kind:
        with pytest.raises(AccessRequestSubmissionError, match="current grant already exists"):
            AccessRequestService.submit_access_request(submission)
    else:
        request = AccessRequestService.submit_access_request(submission)
        assert request.status == "submitted"
        assert request.base_grant_id is None


@pytest.mark.parametrize("personal_kind", [None, "group", "permission"])
def test_plain_grant_apply_after_department_grant_created(personal_kind: str | None) -> None:
    user = UserMirror.objects.create(authentik_user_id="plain-apply", status="active")
    app = App.objects.create(app_key="plain-apply", name="普通授权落地")
    permission = _scoped_permission(app, key="read", name="读取")
    request = _approved_request(user=user, app=app, request_type="grant")
    AccessRequestPermission.objects.create(access_request=request, permission=permission)
    # 申请获批后, 部门对账先创建 current 授权。
    grant = AccessGrant.objects.create(user=user, app=app)
    group = AuthorizationGroup.objects.create(app=app, key="reader", name="读取", kind="role")
    department_group = AccessGrantGroup.objects.create(
        grant=grant, authorization_group=group, source="department"
    )
    department_permission = AccessGrantPermission.objects.create(
        grant=grant, permission=permission, source="department"
    )
    if personal_kind == "group":
        AccessGrantGroup.objects.create(grant=grant, authorization_group=group, source="user")
    elif personal_kind == "permission":
        AccessGrantPermission.objects.create(grant=grant, permission=permission, source="user")
    application = AccessRequestApplication(
        request_id=request.id, actor_type="approval", actor_id="approver"
    )
    if personal_kind:
        with pytest.raises(AccessRequestApplicationError, match="grant apply failed"):
            AccessRequestService.apply_approved_access_request(application)
        request.refresh_from_db()
        assert request.status == "grant_failed"
    else:
        applied = AccessRequestService.apply_approved_access_request(application)
        assert applied.status == "grant_applied"
        assert (
            AccessGrantPermission.objects.get(grant=grant, source="user").permission == permission
        )
    grant.refresh_from_db()
    assert grant.version == (1 if personal_kind else 2)
    assert AccessGrant.objects.filter(user=user, app=app, is_current=True).count() == 1
    assert AccessGrantGroup.objects.filter(pk=department_group.pk).exists()
    assert AccessGrantPermission.objects.filter(pk=department_permission.pk).exists()
