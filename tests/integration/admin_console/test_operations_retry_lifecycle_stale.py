from __future__ import annotations

from datetime import timedelta
from http import HTTPStatus
from json import dumps
from typing import ClassVar, Final

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.utils import timezone
from pydantic import BaseModel, ConfigDict

from easyauth.access_requests.models import (
    REQUEST_STATUS_GRANT_FAILED,
    REQUEST_TYPE_RENEW,
    REQUEST_TYPE_REVOKE,
    AccessRequest,
    AccessRequestRole,
)
from easyauth.accounts.models import UserMirror
from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.applications.models import App, ApprovalRule, Role
from easyauth.audit.models import AuditLog
from easyauth.grants.models import (
    GRANT_STATUS_ACTIVE,
    GRANT_TYPE_PERMANENT,
    GRANT_TYPE_TIMED,
    AccessGrant,
    AccessGrantRole,
)

pytestmark = pytest.mark.django_db

LOGIN_VALUE: Final = "console-ops4-retry-lifecycle-stale"
ACCESS_REQUESTS_API_URL: Final = "/console/api/v1/operations/access-requests"
EXISTING_GRANT_VERSION: Final = 4
TARGET_CONFIGURATION_ERROR: Final = "target configuration is no longer valid"


class ErrorItem(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    code: ErrorCode
    message: str
    details: dict[str, JsonValue]


class ErrorEnvelope(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    error: ErrorItem


def test_retry_failed_renew_rejects_inactive_role_target_without_mutating_grant() -> None:
    # Given: grant_failed renew 申请重试前, 当前 Role 已被停用。
    client = _logged_in_superuser("ops4-retry-renew-inactive-role-admin")
    target_user = UserMirror.objects.create(authentik_user_id="ops4-retry-renew-inactive-target")
    app = App.objects.create(app_key="ops4-retry-renew-inactive-app", name="Retry Renew Stale")
    role = Role.objects.create(app=app, key="reader", name="Reader")
    _ = ApprovalRule.objects.create(app=app, role=role, approver_userids=["manager-001"])
    current_expires_at = timezone.now() + timedelta(days=3)
    grant = AccessGrant.objects.create(
        user=target_user,
        app=app,
        grant_type=GRANT_TYPE_TIMED,
        grant_expires_at=current_expires_at,
        version=EXISTING_GRANT_VERSION,
    )
    _ = AccessGrantRole.objects.create(grant=grant, role=role)
    access_request = AccessRequest.objects.create(
        user=target_user,
        app=app,
        request_type=REQUEST_TYPE_RENEW,
        status=REQUEST_STATUS_GRANT_FAILED,
        grant_type=GRANT_TYPE_TIMED,
        grant_expires_at=timezone.now() + timedelta(days=10),
        reason="续期授权写入失败",
    )
    _ = AccessRequestRole.objects.create(access_request=access_request, role=role)
    role.is_active = False
    role.save(update_fields=["is_active"])

    # When: 管理员通过 retry API 重试该过期 renew 申请。
    response = client.post(
        f"{ACCESS_REQUESTS_API_URL}/{access_request.id}/retry-grant",
        data=dumps({"reason": "修复后重试"}),
        content_type="application/json",
    )

    # Then: API 返回语义错误, 且当前授权期限和申请状态不变。
    grant.refresh_from_db()
    access_request.refresh_from_db()
    body = ErrorEnvelope.model_validate_json(response.content)
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert body.error.code == ErrorCode.SEMANTIC_VALIDATION_ERROR
    assert body.error.details["request_id"] == access_request.id
    assert body.error.details["error"] == TARGET_CONFIGURATION_ERROR
    assert grant.status == GRANT_STATUS_ACTIVE
    assert grant.version == EXISTING_GRANT_VERSION
    assert grant.grant_expires_at == current_expires_at
    assert access_request.status == REQUEST_STATUS_GRANT_FAILED
    assert access_request.applied_at is None
    assert AuditLog.objects.count() == 0


def test_retry_failed_revoke_rejects_inactive_retained_role_without_mutating_grant() -> None:
    # Given: grant_failed partial revoke 申请重试前, 保留目标 Role 已被停用。
    client = _logged_in_superuser("ops4-retry-revoke-inactive-role-admin")
    target_user = UserMirror.objects.create(authentik_user_id="ops4-retry-revoke-inactive-target")
    app = App.objects.create(app_key="ops4-retry-revoke-inactive-app", name="Retry Revoke Stale")
    keep_role = Role.objects.create(app=app, key="viewer", name="Viewer")
    remove_role = Role.objects.create(app=app, key="operator", name="Operator")
    _ = ApprovalRule.objects.create(app=app, role=keep_role, approver_userids=["manager-001"])
    grant = AccessGrant.objects.create(
        user=target_user,
        app=app,
        grant_type=GRANT_TYPE_PERMANENT,
        version=EXISTING_GRANT_VERSION,
    )
    _ = AccessGrantRole.objects.create(grant=grant, role=keep_role)
    _ = AccessGrantRole.objects.create(grant=grant, role=remove_role)
    access_request = AccessRequest.objects.create(
        user=target_user,
        app=app,
        request_type=REQUEST_TYPE_REVOKE,
        status=REQUEST_STATUS_GRANT_FAILED,
        reason="撤权授权写入失败",
    )
    _ = AccessRequestRole.objects.create(access_request=access_request, role=keep_role)
    keep_role.is_active = False
    keep_role.save(update_fields=["is_active"])

    # When: 管理员通过 retry API 重试该过期 partial revoke 申请。
    response = client.post(
        f"{ACCESS_REQUESTS_API_URL}/{access_request.id}/retry-grant",
        data=dumps({"reason": "修复后重试"}),
        content_type="application/json",
    )

    # Then: API 返回语义错误, 且当前授权成员和申请状态不变。
    grant.refresh_from_db()
    access_request.refresh_from_db()
    body = ErrorEnvelope.model_validate_json(response.content)
    role_keys = tuple(
        AccessGrantRole.objects.filter(grant=grant)
        .order_by("role__key")
        .values_list("role__key", flat=True),
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert body.error.code == ErrorCode.SEMANTIC_VALIDATION_ERROR
    assert body.error.details["request_id"] == access_request.id
    assert body.error.details["error"] == TARGET_CONFIGURATION_ERROR
    assert role_keys == ("operator", "viewer")
    assert grant.status == GRANT_STATUS_ACTIVE
    assert grant.version == EXISTING_GRANT_VERSION
    assert access_request.status == REQUEST_STATUS_GRANT_FAILED
    assert access_request.applied_at is None
    assert AuditLog.objects.count() == 0


def _logged_in_superuser(username: str) -> Client:
    _ = User.objects.create_superuser(username=username, password=LOGIN_VALUE)
    client = Client(HTTP_HOST="localhost", raise_request_exception=False)
    assert client.login(username=username, password=LOGIN_VALUE) is True
    return client
