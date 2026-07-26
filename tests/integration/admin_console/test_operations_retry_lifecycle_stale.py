from __future__ import annotations

from datetime import timedelta
from http import HTTPStatus
from json import dumps
from typing import Final

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.utils import timezone

from easyauth.access_requests.models import (
    DECISION_ACTOR_CONSOLE_ADMIN,
    GRANT_TYPE_PERMANENT,
    GRANT_TYPE_TIMED,
    REQUEST_STATUS_GRANT_APPLIED,
    REQUEST_STATUS_GRANT_FAILED,
    REQUEST_TYPE_RENEW,
    REQUEST_TYPE_REVOKE,
    AccessRequest,
    AccessRequestGroup,
    AccessRequestGroupGrantSnapshot,
)
from easyauth.accounts.models import UserMirror
from easyauth.applications.models import (
    App,
    ApprovalRule,
    AppScope,
    AuthorizationGroup,
    AuthorizationGroupGrant,
    Permission,
)
from easyauth.audit.models import AuditLog
from easyauth.grants.models import (
    GRANT_STATUS_ACTIVE,
    AccessGrant,
    AccessGrantGroup,
    AccessGrantPermission,
)
from tests.integration.admin_console.auth_helpers import authenticate_console_admin

pytestmark = pytest.mark.django_db

LOGIN_VALUE: Final = "console-ops4-retry-lifecycle-stale"
ACCESS_REQUESTS_API_URL: Final = "/console/api/v1/operations/access-requests"
EXISTING_GRANT_VERSION: Final = 4


def test_retry_failed_renew_applies_snapshot_when_group_is_inactive() -> None:
    # Given: grant_failed renew 申请重试前, 当前授权组已被停用。
    client = _logged_in_superuser("ops4-retry-renew-inactive-role-admin")
    target_user = UserMirror.objects.create(authentik_user_id="ops4-retry-renew-inactive-target")
    app = App.objects.create(app_key="ops4-retry-renew-inactive-app", name="Retry Renew Stale")
    group = AuthorizationGroup.objects.create(app=app, key="reader", kind="role", name="Reader")
    _ = ApprovalRule.objects.create(
        app=app,
        authorization_group=group,
        approver_userids=["manager-001"],
    )
    grant = AccessGrant.objects.create(
        user=target_user,
        app=app,
        version=EXISTING_GRANT_VERSION,
    )
    _ = AccessGrantGroup.objects.create(
        grant=grant,
        authorization_group=group,
        expires_at=timezone.now() + timedelta(days=3),
    )
    access_request = AccessRequest.objects.create(
        user=target_user,
        app=app,
        request_type=REQUEST_TYPE_RENEW,
        status=REQUEST_STATUS_GRANT_FAILED,
        base_grant=grant,
        base_grant_revision=EXISTING_GRANT_VERSION,
        grant_type=GRANT_TYPE_TIMED,
        grant_expires_at=timezone.now() + timedelta(days=10),
        reason="续期授权写入失败",
        idempotency_key="retry-renew-inactive-group",
        payload_digest="a" * 64,
        approved_at=timezone.now(),
        decided_at=timezone.now(),
        decided_by="ops4-retry-renew-inactive-role-admin",
        decision_actor_type=DECISION_ACTOR_CONSOLE_ADMIN,
    )
    _ = AccessRequestGroup.objects.create(access_request=access_request, authorization_group=group)
    _attach_group_snapshot(access_request, group)
    group.is_active = False
    group.save(update_fields=["is_active"])

    # When: 管理员通过 retry API 重试该过期 renew 申请。
    response = client.post(
        f"{ACCESS_REQUESTS_API_URL}/{access_request.id}/retry-grant",
        data=dumps({"reason": "修复后重试"}),
        content_type="application/json",
    )

    # Then: retry 使用提交时冻结的授权组展开事实, 不再依赖当前授权组状态。
    grant.refresh_from_db()
    access_request.refresh_from_db()
    group_count = AccessGrantGroup.objects.filter(grant=grant).count()
    direct_grant = AccessGrantPermission.objects.get(
        grant=grant,
        permission__key="reader.read",
        scope_key="reader-scope",
    )
    assert response.status_code == HTTPStatus.OK
    assert response.json()["status"] == REQUEST_STATUS_GRANT_APPLIED
    assert group_count == 0
    assert direct_grant.expires_at == access_request.grant_expires_at
    assert grant.status == GRANT_STATUS_ACTIVE
    assert grant.version == EXISTING_GRANT_VERSION + 1
    assert access_request.status == REQUEST_STATUS_GRANT_APPLIED
    assert AuditLog.objects.filter(event_type="access_request_grant_retry_applied").count() == 1


def test_retry_failed_revoke_applies_snapshot_when_retained_group_is_inactive() -> None:
    # Given: grant_failed partial revoke 申请重试前, 保留目标授权组已被停用。
    client = _logged_in_superuser("ops4-retry-revoke-inactive-role-admin")
    target_user = UserMirror.objects.create(authentik_user_id="ops4-retry-revoke-inactive-target")
    app = App.objects.create(app_key="ops4-retry-revoke-inactive-app", name="Retry Revoke Stale")
    keep_group = AuthorizationGroup.objects.create(
        app=app,
        key="viewer",
        kind="role",
        name="Viewer",
    )
    remove_group = AuthorizationGroup.objects.create(
        app=app,
        key="operator",
        kind="role",
        name="Operator",
    )
    _ = ApprovalRule.objects.create(
        app=app,
        authorization_group=keep_group,
        approver_userids=["manager-001"],
    )
    grant = AccessGrant.objects.create(
        user=target_user,
        app=app,
        version=EXISTING_GRANT_VERSION,
    )
    _ = AccessGrantGroup.objects.create(
        grant=grant,
        authorization_group=keep_group,
        expires_at=None,
    )
    _ = AccessGrantGroup.objects.create(
        grant=grant,
        authorization_group=remove_group,
        expires_at=None,
    )
    access_request = AccessRequest.objects.create(
        user=target_user,
        app=app,
        request_type=REQUEST_TYPE_REVOKE,
        status=REQUEST_STATUS_GRANT_FAILED,
        base_grant=grant,
        base_grant_revision=EXISTING_GRANT_VERSION,
        grant_type=GRANT_TYPE_PERMANENT,
        reason="撤权授权写入失败",
        idempotency_key="retry-revoke-inactive-group",
        payload_digest="b" * 64,
        approved_at=timezone.now(),
        decided_at=timezone.now(),
        decided_by="ops4-retry-revoke-inactive-role-admin",
        decision_actor_type=DECISION_ACTOR_CONSOLE_ADMIN,
    )
    _ = AccessRequestGroup.objects.create(
        access_request=access_request,
        authorization_group=keep_group,
    )
    _attach_group_snapshot(access_request, keep_group)
    keep_group.is_active = False
    keep_group.save(update_fields=["is_active"])

    # When: 管理员通过 retry API 重试该过期 partial revoke 申请。
    response = client.post(
        f"{ACCESS_REQUESTS_API_URL}/{access_request.id}/retry-grant",
        data=dumps({"reason": "修复后重试"}),
        content_type="application/json",
    )

    # Then: retry 使用提交时冻结的授权组展开事实, 不再依赖当前授权组状态。
    grant.refresh_from_db()
    access_request.refresh_from_db()
    group_count = AccessGrantGroup.objects.filter(grant=grant).count()
    direct_grants = tuple(
        AccessGrantPermission.objects.filter(grant=grant).values_list(
            "permission__key",
            "scope_key",
        ),
    )
    assert response.status_code == HTTPStatus.OK
    assert response.json()["status"] == REQUEST_STATUS_GRANT_APPLIED
    assert group_count == 0
    assert direct_grants == (("viewer.read", "viewer-scope"),)
    assert grant.status == GRANT_STATUS_ACTIVE
    assert grant.version == EXISTING_GRANT_VERSION + 1
    assert access_request.status == REQUEST_STATUS_GRANT_APPLIED
    assert AuditLog.objects.filter(event_type="access_request_grant_retry_applied").count() == 1


def _logged_in_superuser(username: str) -> Client:
    _ = User.objects.create_superuser(username=username, password=LOGIN_VALUE)
    client = Client(HTTP_HOST="localhost", raise_request_exception=False)
    _ = authenticate_console_admin(client, username)
    return client


def _attach_group_snapshot(access_request: AccessRequest, group: AuthorizationGroup) -> None:
    scope = AppScope.objects.create(app=access_request.app, key=f"{group.key}-scope", name="Scope")
    permission = Permission.objects.create(
        app=access_request.app,
        key=f"{group.key}.read",
        name=f"{group.name} Read",
        supported_scopes=[scope.key],
    )
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=group,
        permission=permission,
        scope_key=scope.key,
    )
    _ = AccessRequestGroupGrantSnapshot.objects.create(
        access_request=access_request,
        authorization_group_id_snapshot=group.id,
        authorization_group_key=group.key,
        authorization_group_kind=group.kind,
        authorization_group_name=group.name,
        permission_key=permission.key,
        permission_name=permission.name,
        scope_key=scope.key,
    )
