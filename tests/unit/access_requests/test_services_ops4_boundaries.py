from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from easyauth.access_requests.models import (
    GRANT_TYPE_PERMANENT,
    GRANT_TYPE_TIMED,
    REQUEST_TYPE_RENEW,
    REQUEST_TYPE_REVOKE,
    AccessRequest,
)
from easyauth.access_requests.services import (
    AccessRequestService,
    AccessRequestSubmission,
    AccessRequestSubmissionError,
)
from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App, AuthorizationGroup
from easyauth.grants.models import AccessGrant, AccessGrantGroup

pytestmark = pytest.mark.django_db


def test_ops4_revoke_request_rejects_non_reducing_role_target() -> None:
    # Given: 员工当前授权只有一个授权组。
    user = UserMirror.objects.create(authentik_user_id="ops4-revoke-equal-user")
    app = App.objects.create(app_key="ops4-revoke-equal-app", name="OPS4 Revoke Equal")
    group = AuthorizationGroup.objects.create(app=app, key="reader", kind="role", name="Reader")
    grant = AccessGrant.objects.create(user=user, app=app, grant_type=GRANT_TYPE_PERMANENT)
    _ = AccessGrantGroup.objects.create(grant=grant, authorization_group=group)

    # When / Then: 撤销申请目标完全等于当前授权组集合时被拒绝。
    with pytest.raises(AccessRequestSubmissionError) as exc_info:
        _ = AccessRequestService.submit_access_request(
            AccessRequestSubmission(
                user=user,
                app=app,
                authorization_groups=(group,),
                grant_type=GRANT_TYPE_PERMANENT,
                grant_expires_at=None,
                reason="没有减少权限",
                actor_type="user",
                actor_id=user.authentik_user_id,
                request_type=REQUEST_TYPE_REVOKE,
            ),
        )

    assert "reduce" in str(exc_info.value)
    assert AccessRequest.objects.count() == 0


def test_ops4_renew_request_rejects_changed_role_target() -> None:
    # Given: 员工当前限时授权包含 reader 和 writer 两个授权组。
    user = UserMirror.objects.create(authentik_user_id="ops4-renew-changed-user")
    app = App.objects.create(app_key="ops4-renew-changed-app", name="OPS4 Renew Changed")
    reader = AuthorizationGroup.objects.create(app=app, key="reader", kind="role", name="Reader")
    writer = AuthorizationGroup.objects.create(app=app, key="writer", kind="role", name="Writer")
    grant = AccessGrant.objects.create(
        user=user,
        app=app,
        grant_type=GRANT_TYPE_TIMED,
        grant_expires_at=timezone.now() + timedelta(days=3),
    )
    _ = AccessGrantGroup.objects.create(grant=grant, authorization_group=reader)
    _ = AccessGrantGroup.objects.create(grant=grant, authorization_group=writer)

    # When / Then: 续期申请不能借机改变授权组集合。
    with pytest.raises(AccessRequestSubmissionError) as exc_info:
        _ = AccessRequestService.submit_access_request(
            AccessRequestSubmission(
                user=user,
                app=app,
                authorization_groups=(reader,),
                grant_type=GRANT_TYPE_TIMED,
                grant_expires_at=timezone.now() + timedelta(days=10),
                reason="续期不能减角色",
                actor_type="user",
                actor_id=user.authentik_user_id,
                request_type=REQUEST_TYPE_RENEW,
            ),
        )

    assert "keep current groups" in str(exc_info.value)
    assert AccessRequest.objects.count() == 0
