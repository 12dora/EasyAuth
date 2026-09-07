from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from easyauth.access_requests.models import AccessRequestPermission
from easyauth.access_requests.services import AccessRequestApplication, AccessRequestService
from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App
from easyauth.grants.models import AccessGrant, AccessGrantPermission
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
