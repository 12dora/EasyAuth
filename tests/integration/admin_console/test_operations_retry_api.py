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
    GRANT_TYPE_TIMED,
    REQUEST_STATUS_GRANT_APPLIED,
    REQUEST_STATUS_GRANT_FAILED,
    REQUEST_TYPE_CHANGE,
    REQUEST_TYPE_RENEW,
    REQUEST_TYPE_REVOKE,
    AccessRequest,
    AccessRequestGroup,
)
from easyauth.accounts.models import UserMirror
from easyauth.api.errors import ErrorCode
from easyauth.applications.models import App, ApprovalRule, AuthorizationGroup
from easyauth.audit.models import AuditLog
from easyauth.grants.models import (
    GRANT_STATUS_ACTIVE,
    AccessGrant,
    AccessGrantGroup,
)

pytestmark = pytest.mark.django_db

LOGIN_VALUE: Final = "console-ops3-retry"
ACCESS_REQUESTS_API_URL: Final = "/console/api/v1/operations/access-requests"
EXISTING_GRANT_VERSION: Final = 4


def test_retry_grant_rejects_existing_current_grant_without_mutating_state() -> None:
    # Given: 一条 grant_failed 申请的目标用户和 App 已经存在当前授权。
    client = _logged_in_superuser(
        "ops3-retry-current-admin",
        raise_request_exception=False,
    )
    target_user = UserMirror.objects.create(authentik_user_id="ops3-retry-current-target")
    app = App.objects.create(app_key="ops3-retry-current-app", name="Retry Current CRM")
    access_request = AccessRequest.objects.create(
        user=target_user,
        app=app,
        status=REQUEST_STATUS_GRANT_FAILED,
        reason="授权写入超时",
        idempotency_key="retry-current-grant",
        payload_digest="a" * 64,
    )
    existing_grant = AccessGrant.objects.create(
        user=target_user,
        app=app,
        status=GRANT_STATUS_ACTIVE,
        version=EXISTING_GRANT_VERSION,
    )

    # When: 管理员对该失败申请发起重试授权。
    response = client.post(
        f"{ACCESS_REQUESTS_API_URL}/{access_request.id}/retry-grant",
        data=dumps({"reason": "确认后重试"}),
        content_type="application/json",
    )

    # Then: API 返回受控语义错误, 且不新增授权、不递增版本、不改写申请。
    access_request.refresh_from_db()
    existing_grant.refresh_from_db()
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert response.json()["error"]["code"] == ErrorCode.SEMANTIC_VALIDATION_ERROR
    assert AccessGrant.objects.filter(user=target_user, app=app).count() == 1
    assert existing_grant.version == EXISTING_GRANT_VERSION
    assert existing_grant.status == GRANT_STATUS_ACTIVE
    assert existing_grant.is_current is True
    assert access_request.status == REQUEST_STATUS_GRANT_FAILED
    assert access_request.applied_at is None
    assert AuditLog.objects.count() == 0


def test_retry_failed_change_applies_original_lifecycle_with_current_grant() -> None:
    # Given: 一条 grant_failed change 申请仍有当前授权, 且目标规则仍有效。
    client = _logged_in_superuser("ops4-retry-change-admin")
    target_user = UserMirror.objects.create(authentik_user_id="ops4-retry-change-target")
    app = App.objects.create(app_key="ops4-retry-change-app", name="Retry Change CRM")
    old_group = AuthorizationGroup.objects.create(app=app, key="reader", kind="role", name="Reader")
    new_group = AuthorizationGroup.objects.create(app=app, key="writer", kind="role", name="Writer")
    _ = ApprovalRule.objects.create(
        app=app,
        authorization_group=new_group,
        approver_userids=["manager-001"],
    )
    grant = AccessGrant.objects.create(
        user=target_user,
        app=app,
        version=EXISTING_GRANT_VERSION,
    )
    _ = AccessGrantGroup.objects.create(
        grant=grant,
        authorization_group=old_group,
        expires_at=None,
    )
    access_request = AccessRequest.objects.create(
        user=target_user,
        app=app,
        request_type=REQUEST_TYPE_CHANGE,
        status=REQUEST_STATUS_GRANT_FAILED,
        reason="变更授权写入失败",
        idempotency_key="retry-failed-change",
        payload_digest="b" * 64,
    )
    _ = AccessRequestGroup.objects.create(
        access_request=access_request,
        authorization_group=new_group,
    )

    # When: 管理员重试该 change 申请, 随后重复提交已应用申请。
    response = client.post(
        f"{ACCESS_REQUESTS_API_URL}/{access_request.id}/retry-grant",
        data=dumps({"reason": "按原申请语义重试"}),
        content_type="application/json",
    )
    repeated = client.post(
        f"{ACCESS_REQUESTS_API_URL}/{access_request.id}/retry-grant",
        data=dumps({"reason": "重复提交"}),
        content_type="application/json",
    )

    # Then: API 复用 change 语义更新当前授权, 重复提交不会再次递增。
    grant.refresh_from_db()
    access_request.refresh_from_db()
    group_keys = tuple(
        AccessGrantGroup.objects.filter(grant=grant).values_list(
            "authorization_group__key",
            flat=True,
        ),
    )
    assert response.status_code == HTTPStatus.OK
    assert repeated.status_code == HTTPStatus.OK
    assert response.json()["request_id"] == access_request.id
    assert response.json()["status"] == REQUEST_STATUS_GRANT_APPLIED
    assert repeated.json()["request_id"] == access_request.id
    assert repeated.json()["version"] == EXISTING_GRANT_VERSION + 1
    assert group_keys == ("writer",)
    assert grant.version == EXISTING_GRANT_VERSION + 1
    assert access_request.status == REQUEST_STATUS_GRANT_APPLIED
    assert AuditLog.objects.filter(event_type="access_request_grant_retry_applied").count() == 1


def test_retry_failed_revoke_applies_original_lifecycle_with_current_grant() -> None:
    # Given: 一条 grant_failed revoke 申请仍有当前授权, 目标是保留部分角色。
    client = _logged_in_superuser("ops4-retry-revoke-admin")
    target_user = UserMirror.objects.create(authentik_user_id="ops4-retry-revoke-target")
    app = App.objects.create(app_key="ops4-retry-revoke-app", name="Retry Revoke CRM")
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
        reason="撤权授权写入失败",
        idempotency_key="retry-failed-revoke",
        payload_digest="c" * 64,
    )
    _ = AccessRequestGroup.objects.create(
        access_request=access_request,
        authorization_group=keep_group,
    )

    # When: 管理员重试该 revoke 申请, 随后重复提交已应用申请。
    response = client.post(
        f"{ACCESS_REQUESTS_API_URL}/{access_request.id}/retry-grant",
        data=dumps({"reason": "按撤权语义重试"}),
        content_type="application/json",
    )
    repeated = client.post(
        f"{ACCESS_REQUESTS_API_URL}/{access_request.id}/retry-grant",
        data=dumps({"reason": "重复提交"}),
        content_type="application/json",
    )

    # Then: API 缩减当前授权成员, 重复提交不会再次递增。
    grant.refresh_from_db()
    access_request.refresh_from_db()
    group_keys = tuple(
        AccessGrantGroup.objects.filter(grant=grant).values_list(
            "authorization_group__key",
            flat=True,
        ),
    )
    assert response.status_code == HTTPStatus.OK
    assert repeated.status_code == HTTPStatus.OK
    assert response.json()["request_id"] == access_request.id
    assert response.json()["status"] == REQUEST_STATUS_GRANT_APPLIED
    assert repeated.json()["request_id"] == access_request.id
    assert repeated.json()["version"] == EXISTING_GRANT_VERSION + 1
    assert group_keys == ("viewer",)
    assert grant.version == EXISTING_GRANT_VERSION + 1
    assert access_request.status == REQUEST_STATUS_GRANT_APPLIED


def test_retry_failed_renew_applies_original_lifecycle_with_current_grant() -> None:
    # Given: 一条 grant_failed renew 申请仍有当前限时授权。
    client = _logged_in_superuser("ops4-retry-renew-admin")
    target_user = UserMirror.objects.create(authentik_user_id="ops4-retry-renew-target")
    app = App.objects.create(app_key="ops4-retry-renew-app", name="Retry Renew CRM")
    group = AuthorizationGroup.objects.create(app=app, key="reader", kind="role", name="Reader")
    _ = ApprovalRule.objects.create(
        app=app,
        authorization_group=group,
        approver_userids=["manager-001"],
    )
    current_expires_at = timezone.now() + timedelta(days=3)
    renewed_expires_at = timezone.now() + timedelta(days=10)
    grant = AccessGrant.objects.create(
        user=target_user,
        app=app,
        version=EXISTING_GRANT_VERSION,
    )
    _ = AccessGrantGroup.objects.create(
        grant=grant,
        authorization_group=group,
        expires_at=current_expires_at,
    )
    access_request = AccessRequest.objects.create(
        user=target_user,
        app=app,
        request_type=REQUEST_TYPE_RENEW,
        status=REQUEST_STATUS_GRANT_FAILED,
        grant_type=GRANT_TYPE_TIMED,
        grant_expires_at=renewed_expires_at,
        reason="续期授权写入失败",
        idempotency_key="retry-failed-renew",
        payload_digest="d" * 64,
    )
    _ = AccessRequestGroup.objects.create(
        access_request=access_request,
        authorization_group=group,
    )

    # When: 管理员重试该 renew 申请, 随后重复提交已应用申请。
    response = client.post(
        f"{ACCESS_REQUESTS_API_URL}/{access_request.id}/retry-grant",
        data=dumps({"reason": "按续期语义重试"}),
        content_type="application/json",
    )
    repeated = client.post(
        f"{ACCESS_REQUESTS_API_URL}/{access_request.id}/retry-grant",
        data=dumps({"reason": "重复提交"}),
        content_type="application/json",
    )

    # Then: API 延长当前授权期限, 重复提交不会再次递增。
    grant.refresh_from_db()
    access_request.refresh_from_db()
    renewed_grant_group = AccessGrantGroup.objects.get(
        grant=grant,
        authorization_group=group,
    )
    assert response.status_code == HTTPStatus.OK
    assert repeated.status_code == HTTPStatus.OK
    assert response.json()["request_id"] == access_request.id
    assert response.json()["status"] == REQUEST_STATUS_GRANT_APPLIED
    assert repeated.json()["request_id"] == access_request.id
    assert repeated.json()["version"] == EXISTING_GRANT_VERSION + 1
    assert renewed_grant_group.expires_at == renewed_expires_at
    assert grant.version == EXISTING_GRANT_VERSION + 1
    assert access_request.status == REQUEST_STATUS_GRANT_APPLIED


def _logged_in_superuser(
    username: str,
    *,
    raise_request_exception: bool = True,
) -> Client:
    _ = User.objects.create_superuser(username=username, password=LOGIN_VALUE)
    client = Client(
        HTTP_HOST="localhost",
        raise_request_exception=raise_request_exception,
    )
    assert client.login(username=username, password=LOGIN_VALUE) is True
    return client
