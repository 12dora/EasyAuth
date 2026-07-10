from __future__ import annotations

from datetime import datetime, timedelta
from typing import Final

import pytest
from django.utils import timezone

from easyauth.access_requests.models import (
    GRANT_TYPE_PERMANENT,
    GRANT_TYPE_TIMED,
    REQUEST_STATUS_APPROVED,
    REQUEST_STATUS_GRANT_FAILED,
    REQUEST_TYPE_CHANGE,
    REQUEST_TYPE_GRANT,
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
from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App, AuthorizationGroup
from easyauth.audit.models import AuditLog
from easyauth.grants.models import GRANT_STATUS_ACTIVE, AccessGrant, AccessGrantGroup

pytestmark = pytest.mark.django_db

INITIAL_VERSION: Final = 1


@pytest.mark.parametrize(
    ("request_type", "stale_scope"),
    [
        (REQUEST_TYPE_GRANT, "user_disabled"),
        (REQUEST_TYPE_CHANGE, "user_disabled"),
        (REQUEST_TYPE_REVOKE, "user_disabled"),
        (REQUEST_TYPE_RENEW, "user_disabled"),
        (REQUEST_TYPE_GRANT, "app_inactive"),
        (REQUEST_TYPE_CHANGE, "app_inactive"),
        (REQUEST_TYPE_REVOKE, "app_inactive"),
        (REQUEST_TYPE_RENEW, "app_inactive"),
    ],
)
def test_ops4_apply_approved_request_fails_when_scope_becomes_stale(
    request_type: str,
    stale_scope: str,
) -> None:
    # Given: 审批通过后, 用户或 App 状态在回调前变为不可用。
    user = UserMirror.objects.create(authentik_user_id=f"ops4-stale-scope-{request_type}-user")
    app = App.objects.create(
        app_key=f"ops4-stale-scope-{request_type}-{stale_scope}-app",
        name="OPS4 Stale Scope",
    )
    access_request = _approved_request_for_type(user=user, app=app, request_type=request_type)
    _make_scope_stale(user=user, app=app, stale_scope=stale_scope)

    # When: 审批回调尝试应用该 stale 申请。
    with pytest.raises(AccessRequestApplicationError):
        _ = AccessRequestService.apply_approved_access_request(
            AccessRequestApplication(
                request_id=access_request.id,
                actor_type="approval",
                actor_id="dingtalk-callback",
            ),
        )

    # Then: 授权事实不被创建或变更, 申请进入 grant_failed。
    access_request.refresh_from_db()
    assert access_request.status == REQUEST_STATUS_GRANT_FAILED
    assert AuditLog.objects.filter(event_type="grant_apply_failed").count() == 1
    grants = tuple(AccessGrant.objects.filter(user=user, app=app).order_by("id"))
    if request_type == REQUEST_TYPE_GRANT:
        assert grants == ()
        return
    assert len(grants) == 1
    assert grants[0].version == INITIAL_VERSION
    assert grants[0].status == GRANT_STATUS_ACTIVE


def _approved_request_for_type(
    *,
    user: UserMirror,
    app: App,
    request_type: str,
) -> AccessRequest:
    group = AuthorizationGroup.objects.create(
        app=app,
        key=f"{request_type}-group",
        kind="role",
        name="Authorization group",
    )
    match request_type:
        case "grant" | "change":
            access_request = _approved_request(user=user, app=app, request_type=request_type)
            _ = AccessRequestGroup.objects.create(
                access_request=access_request,
                authorization_group=group,
            )
            if request_type == REQUEST_TYPE_CHANGE:
                _ = AccessGrant.objects.create(
                    user=user,
                    app=app,
                )
            return access_request
        case "revoke":
            grant = AccessGrant.objects.create(
                user=user,
                app=app,
            )
            _ = AccessGrantGroup.objects.create(
                grant=grant,
                authorization_group=group,
                expires_at=None,
            )
            return _approved_request(user=user, app=app, request_type=request_type)
        case "renew":
            grant = AccessGrant.objects.create(
                user=user,
                app=app,
            )
            _ = AccessGrantGroup.objects.create(
                grant=grant,
                authorization_group=group,
                expires_at=timezone.now() + timedelta(days=3),
            )
            access_request = _approved_request(
                user=user,
                app=app,
                request_type=request_type,
                grant_type=GRANT_TYPE_TIMED,
                grant_expires_at=timezone.now() + timedelta(days=10),
            )
            _ = AccessRequestGroup.objects.create(
                access_request=access_request,
                authorization_group=group,
            )
            return access_request
        case unsupported:
            raise AssertionError(unsupported)


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
        idempotency_key=f"{app.app_key}-approved-{request_type}",
        payload_digest="1" * 64,
        approved_at=timezone.now(),
    )


def _make_scope_stale(*, user: UserMirror, app: App, stale_scope: str) -> None:
    match stale_scope:
        case "user_disabled":
            user.status = "disabled"
            user.save(update_fields=["status"])
        case "app_inactive":
            app.is_active = False
            app.save(update_fields=["is_active"])
        case unsupported:
            raise AssertionError(unsupported)
