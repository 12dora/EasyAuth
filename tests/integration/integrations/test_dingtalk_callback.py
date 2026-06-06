from __future__ import annotations

import hmac
import json
from datetime import timedelta
from hashlib import sha256
from http import HTTPStatus
from typing import Final, Protocol

import pytest
from django.db import IntegrityError
from django.test import Client, override_settings
from django.utils import timezone

from easyauth.access_requests.models import (
    GRANT_TYPE_PERMANENT,
    REQUEST_STATUS_APPROVED,
    REQUEST_STATUS_GRANT_APPLIED,
    REQUEST_STATUS_GRANT_FAILED,
    REQUEST_STATUS_SUBMITTED,
    REQUEST_TYPE_CHANGE,
    AccessRequest,
    AccessRequestRole,
)
from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App, ApprovalRule, Permission, Role, RolePermission
from easyauth.grants.models import AccessGrant, AccessGrantRole
from easyauth.grants.query import resolve_user_permissions

pytestmark = pytest.mark.django_db

CALLBACK_URL: Final = "/integrations/dingtalk/callback"
CALLBACK_KEY: Final = "integration-callback-key"
TIMESTAMP: Final = "1764986400000"
INITIAL_VERSION: Final = 1
APPLIED_VERSION: Final = 2


class _CallbackResponse(Protocol):
    status_code: int


@override_settings(EASYAUTH_DINGTALK_CALLBACK_SECRET=CALLBACK_KEY)
def test_dingtalk_callback_rejects_invalid_signature_without_mutating_request() -> None:
    # Given: 一条 submitted 申请绑定了 DingTalk process instance id。
    access_request = _submitted_grant_request(
        user_key="dingtalk-invalid-user",
        app_key="dingtalk-invalid-app",
        role_key="reader",
        process_instance_id="proc-invalid-signature",
    )
    body = _callback_body("proc-invalid-signature", "approved")

    # When: DingTalk 回调使用错误签名请求接口。
    response = _post_callback(body, signature="bad-signature")

    # Then: 接口拒绝请求, 申请状态不变且不创建授权。
    access_request.refresh_from_db()
    assert response.status_code == HTTPStatus.FORBIDDEN
    assert access_request.status == REQUEST_STATUS_SUBMITTED
    assert AccessGrant.objects.count() == 0


@override_settings(EASYAUTH_DINGTALK_CALLBACK_SECRET=CALLBACK_KEY)
def test_dingtalk_callback_rejects_expired_signature_without_mutating_request() -> None:
    # Given: 一条 submitted 申请收到超过允许窗口的旧时间戳签名回调。
    access_request = _submitted_grant_request(
        user_key="dingtalk-expired-user",
        app_key="dingtalk-expired-app",
        role_key="reader",
        process_instance_id="proc-expired-signature",
    )
    body = _callback_body("proc-expired-signature", "approved")
    timestamp = str(_current_timestamp_ms() - 300_001)

    # When: DingTalk 使用旧时间戳和匹配 HMAC 请求接口。
    response = _post_callback(body, timestamp=timestamp)

    # Then: 接口拒绝请求, 申请状态不变且不创建授权。
    access_request.refresh_from_db()
    assert response.status_code == HTTPStatus.FORBIDDEN
    assert access_request.status == REQUEST_STATUS_SUBMITTED
    assert AccessGrant.objects.count() == 0


@override_settings(EASYAUTH_DINGTALK_CALLBACK_SECRET=CALLBACK_KEY)
def test_dingtalk_callback_returns_not_found_for_unknown_process() -> None:
    # Given: 回调 body 指向不存在的 process instance id。
    body = _callback_body("proc-unknown", "approved")

    # When: DingTalk 使用有效签名请求接口。
    response = _post_callback(body)

    # Then: 接口返回 404, 不创建申请或授权。
    assert response.status_code == HTTPStatus.NOT_FOUND
    assert AccessRequest.objects.count() == 0
    assert AccessGrant.objects.count() == 0


@override_settings(EASYAUTH_DINGTALK_CALLBACK_SECRET=CALLBACK_KEY)
def test_dingtalk_callback_applies_submitted_approved_request() -> None:
    # Given: submitted grant 申请绑定 DingTalk process instance id 和一个目标角色。
    access_request = _submitted_grant_request(
        user_key="dingtalk-approved-user",
        app_key="dingtalk-approved-app",
        role_key="reader",
        process_instance_id="proc-approved",
    )
    body = _callback_body("proc-approved", "approved")

    # When: DingTalk 回调批准该申请。
    response = _post_callback(body)

    # Then: 申请应用为授权事实, 权限查询可见新授权。
    access_request.refresh_from_db()
    snapshot = resolve_user_permissions(user=access_request.user, app=access_request.app)
    assert response.status_code == HTTPStatus.OK
    assert access_request.status == REQUEST_STATUS_GRANT_APPLIED
    assert access_request.approved_at is not None
    assert snapshot.version == 1
    assert snapshot.roles == ("reader",)


@override_settings(EASYAUTH_DINGTALK_CALLBACK_SECRET=CALLBACK_KEY)
def test_dingtalk_callback_repeated_approved_request_does_not_increment_version() -> None:
    # Given: submitted change 申请将当前角色替换为新角色。
    user = UserMirror.objects.create(authentik_user_id="dingtalk-repeat-user")
    app = App.objects.create(app_key="dingtalk-repeat-app", name="DingTalk Repeat")
    old_role = Role.objects.create(app=app, key="reader", name="Reader")
    new_role = Role.objects.create(app=app, key="writer", name="Writer")
    permission = Permission.objects.create(app=app, key="invoice.write", name="Invoice Write")
    _ = RolePermission.objects.create(role=new_role, permission=permission)
    _ = ApprovalRule.objects.create(app=app, role=new_role, approver_userids=["manager-001"])
    grant = AccessGrant.objects.create(user=user, app=app, grant_type=GRANT_TYPE_PERMANENT)
    _ = AccessGrantRole.objects.create(grant=grant, role=old_role)
    access_request = AccessRequest.objects.create(
        user=user,
        app=app,
        request_type=REQUEST_TYPE_CHANGE,
        dingtalk_process_instance_id="proc-repeat",
    )
    _ = AccessRequestRole.objects.create(access_request=access_request, role=new_role)
    body = _callback_body("proc-repeat", "approved")

    # When: DingTalk 重复投递同一个批准回调。
    first = _post_callback(body)
    second = _post_callback(body)

    # Then: 第一次替换授权, 第二次保持幂等, version 不重复递增。
    grant.refresh_from_db()
    snapshot = resolve_user_permissions(user=user, app=app)
    assert first.status_code == HTTPStatus.OK
    assert second.status_code == HTTPStatus.OK
    assert grant.version == APPLIED_VERSION
    assert snapshot.version == APPLIED_VERSION
    assert snapshot.roles == ("writer",)


@override_settings(EASYAUTH_DINGTALK_CALLBACK_SECRET=CALLBACK_KEY)
def test_dingtalk_callback_rejected_request_does_not_override_applied_grant() -> None:
    # Given: 申请已经完成授权应用。
    user = UserMirror.objects.create(authentik_user_id="dingtalk-reject-applied-user")
    app = App.objects.create(app_key="dingtalk-reject-applied-app", name="DingTalk Reject Applied")
    role = Role.objects.create(app=app, key="reader", name="Reader")
    grant = AccessGrant.objects.create(user=user, app=app, grant_type=GRANT_TYPE_PERMANENT)
    _ = AccessGrantRole.objects.create(grant=grant, role=role)
    access_request = AccessRequest.objects.create(
        user=user,
        app=app,
        status=REQUEST_STATUS_GRANT_APPLIED,
        applied_at=timezone.now() - timedelta(minutes=1),
        dingtalk_process_instance_id="proc-rejected-applied",
    )
    body = _callback_body("proc-rejected-applied", "rejected")

    # When: DingTalk 延迟投递 rejected 回调。
    response = _post_callback(body)

    # Then: 已应用申请和现有授权不被拒绝状态覆盖。
    access_request.refresh_from_db()
    grant.refresh_from_db()
    assert response.status_code == HTTPStatus.OK
    assert access_request.status == REQUEST_STATUS_GRANT_APPLIED
    assert grant.version == INITIAL_VERSION


@override_settings(EASYAUTH_DINGTALK_CALLBACK_SECRET=CALLBACK_KEY)
def test_dingtalk_callback_rejected_request_does_not_override_approved_request() -> None:
    # Given: 申请已经进入 approved, 授权应用尚未改变当前授权事实。
    user = UserMirror.objects.create(authentik_user_id="dingtalk-reject-approved-user")
    app = App.objects.create(
        app_key="dingtalk-reject-approved-app",
        name="DingTalk Reject Approved",
    )
    role = Role.objects.create(app=app, key="reader", name="Reader")
    _ = AccessGrant.objects.create(user=user, app=app, grant_type=GRANT_TYPE_PERMANENT)
    access_request = AccessRequest.objects.create(
        user=user,
        app=app,
        status=REQUEST_STATUS_APPROVED,
        approved_at=timezone.now() - timedelta(minutes=1),
        dingtalk_process_instance_id="proc-rejected-approved",
    )
    _ = AccessRequestRole.objects.create(access_request=access_request, role=role)
    body = _callback_body("proc-rejected-approved", "rejected")

    # When: DingTalk 延迟投递 rejected 回调。
    response = _post_callback(body)

    # Then: 已批准申请不被拒绝状态覆盖。
    access_request.refresh_from_db()
    assert response.status_code == HTTPStatus.OK
    assert access_request.status == REQUEST_STATUS_APPROVED


@override_settings(EASYAUTH_DINGTALK_CALLBACK_SECRET=CALLBACK_KEY)
def test_dingtalk_callback_rejected_request_does_not_override_failed_grant() -> None:
    # Given: 申请已经进入 grant_failed 终态。
    user = UserMirror.objects.create(authentik_user_id="dingtalk-reject-failed-user")
    app = App.objects.create(app_key="dingtalk-reject-failed-app", name="DingTalk Reject Failed")
    access_request = AccessRequest.objects.create(
        user=user,
        app=app,
        status=REQUEST_STATUS_GRANT_FAILED,
        approved_at=timezone.now() - timedelta(minutes=1),
        dingtalk_process_instance_id="proc-rejected-failed",
    )
    body = _callback_body("proc-rejected-failed", "rejected")

    # When: DingTalk 延迟投递 rejected 回调。
    response = _post_callback(body)

    # Then: 授权失败终态不被拒绝状态覆盖。
    access_request.refresh_from_db()
    assert response.status_code == HTTPStatus.OK
    assert access_request.status == REQUEST_STATUS_GRANT_FAILED


def test_dingtalk_process_instance_id_is_unique_when_present() -> None:
    # Given: 一条申请已经绑定 DingTalk process instance id。
    access_request = _submitted_grant_request(
        user_key="dingtalk-unique-user",
        app_key="dingtalk-unique-app",
        role_key="reader",
        process_instance_id="proc-unique",
    )

    # When / Then: 另一条申请不能复用同一个 process instance id。
    with pytest.raises(IntegrityError):
        _ = AccessRequest.objects.create(
            user=access_request.user,
            app=access_request.app,
            dingtalk_process_instance_id="proc-unique",
        )


def _submitted_grant_request(
    *,
    user_key: str,
    app_key: str,
    role_key: str,
    process_instance_id: str,
) -> AccessRequest:
    user = UserMirror.objects.create(authentik_user_id=user_key)
    app = App.objects.create(app_key=app_key, name=app_key)
    role = Role.objects.create(app=app, key=role_key, name=role_key)
    _ = ApprovalRule.objects.create(app=app, role=role, approver_userids=["manager-001"])
    access_request = AccessRequest.objects.create(
        user=user,
        app=app,
        dingtalk_process_instance_id=process_instance_id,
    )
    _ = AccessRequestRole.objects.create(access_request=access_request, role=role)
    return access_request


def _callback_body(process_instance_id: str, status: str) -> bytes:
    payload = {"process_instance_id": process_instance_id, "status": status}
    return json.dumps(payload, separators=(",", ":")).encode()


def _post_callback(
    body: bytes,
    *,
    signature: str | None = None,
    timestamp: str | None = None,
) -> _CallbackResponse:
    return Client().post(
        CALLBACK_URL,
        data=body,
        content_type="application/json",
        headers=_headers(body, signature=signature, timestamp=timestamp),
    )


def _headers(
    body: bytes,
    *,
    signature: str | None = None,
    timestamp: str | None = None,
) -> dict[str, str]:
    signed_timestamp = timestamp or str(_current_timestamp_ms())
    signed = hmac.new(
        CALLBACK_KEY.encode(),
        signed_timestamp.encode() + b"." + body,
        sha256,
    ).hexdigest()
    return {
        "X-EasyAuth-DingTalk-Timestamp": signed_timestamp,
        "X-EasyAuth-DingTalk-Signature": signature or signed,
    }


def _current_timestamp_ms() -> int:
    return int(timezone.now().timestamp() * 1000)
