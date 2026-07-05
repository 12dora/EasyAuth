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
    REQUEST_STATUS_REJECTED,
    REQUEST_STATUS_SUBMITTED,
    REQUEST_TYPE_CHANGE,
    AccessRequest,
    AccessRequestGroup,
)
from easyauth.accounts.models import UserMirror
from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.applications.models import App, ApprovalRule, AuthorizationGroup
from easyauth.audit.models import AuditLog
from easyauth.grants.models import AccessGrant, AccessGrantGroup
from easyauth.grants.query import resolve_user_permissions

pytestmark = pytest.mark.django_db

CALLBACK_URL: Final = "/integrations/dingtalk/callback"
CALLBACK_KEY: Final = "integration-callback-key"
TIMESTAMP: Final = "1764986400000"
INITIAL_VERSION: Final = 1
APPLIED_VERSION: Final = 2


class _CallbackResponse(Protocol):
    status_code: int

    def json(self) -> dict[str, JsonValue]: ...


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
def test_dingtalk_callback_rejects_malformed_json_with_payload_audit_event() -> None:
    # Given: 一条 submitted 申请存在, 但 DingTalk 回调 body 不是合法 JSON。
    access_request = _submitted_grant_request(
        user_key="dingtalk-malformed-json-user",
        app_key="dingtalk-malformed-json-app",
        role_key="reader",
        process_instance_id="proc-malformed-json",
    )
    body = b'{"process_instance_id":"proc-malformed-json","status":'

    # When: DingTalk 使用有效签名投递 malformed JSON。
    response = _post_callback(body)

    # Then: 接口拒绝 payload, 写入 payload_rejected 审计且不创建授权。
    access_request.refresh_from_db()
    audit_log = AuditLog.objects.get(event_type="dingtalk_callback_payload_rejected")
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert access_request.status == REQUEST_STATUS_SUBMITTED
    assert audit_log.target_type == "dingtalk_callback"
    assert AccessGrant.objects.count() == 0


@override_settings(EASYAUTH_DINGTALK_CALLBACK_SECRET=CALLBACK_KEY)
def test_dingtalk_callback_rejects_missing_process_instance_id_with_standard_error() -> None:
    # Given: DingTalk 回调 body 缺少 process_instance_id。
    body = json.dumps(
        {"status": "approved", "approver_user_id": "manager-001"},
        separators=(",", ":"),
    ).encode()

    # When: DingTalk 使用有效签名请求接口。
    response = _post_callback(body)

    # Then: 接口返回 EasyAuth 标准错误结构。
    payload = response.json()
    error = payload["error"]
    assert isinstance(error, dict)
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert set(payload) == {"error"}
    assert set(error) == {"code", "message", "details"}
    assert error["code"] == ErrorCode.VALIDATION_ERROR


@override_settings(EASYAUTH_DINGTALK_CALLBACK_SECRET=CALLBACK_KEY)
def test_dingtalk_callback_rejects_unsupported_status_with_raw_payload_summary() -> None:
    # Given: DingTalk 回调 body 使用 EasyAuth 不支持的状态。
    body = _callback_body("proc-unsupported-status", "cancelled")

    # When: DingTalk 使用有效签名请求接口。
    response = _post_callback(body)

    # Then: 接口拒绝 payload, 审计 metadata 保留原始 payload 摘要。
    audit_log = AuditLog.objects.get(event_type="dingtalk_callback_payload_rejected")
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert audit_log.metadata["payload_summary"] == {
        "process_instance_id": "proc-unsupported-status",
        "status": "cancelled",
    }


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
    # Given: submitted change 申请将当前授权组替换为新授权组。
    user = UserMirror.objects.create(authentik_user_id="dingtalk-repeat-user")
    app = App.objects.create(app_key="dingtalk-repeat-app", name="DingTalk Repeat")
    old_group = _authorization_group(app, "reader")
    new_group = _authorization_group(app, "writer")
    _ = ApprovalRule.objects.create(
        app=app,
        authorization_group=new_group,
        approver_userids=["manager-001"],
    )
    grant = AccessGrant.objects.create(user=user, app=app, grant_type=GRANT_TYPE_PERMANENT)
    _ = AccessGrantGroup.objects.create(grant=grant, authorization_group=old_group)
    access_request = AccessRequest.objects.create(
        user=user,
        app=app,
        request_type=REQUEST_TYPE_CHANGE,
        dingtalk_process_instance_id="proc-repeat",
        approver_user_ids=["manager-001"],
    )
    _ = AccessRequestGroup.objects.create(
        access_request=access_request,
        authorization_group=new_group,
    )
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
    group = _authorization_group(app, "reader")
    grant = AccessGrant.objects.create(user=user, app=app, grant_type=GRANT_TYPE_PERMANENT)
    _ = AccessGrantGroup.objects.create(grant=grant, authorization_group=group)
    access_request = AccessRequest.objects.create(
        user=user,
        app=app,
        status=REQUEST_STATUS_GRANT_APPLIED,
        applied_at=timezone.now() - timedelta(minutes=1),
        dingtalk_process_instance_id="proc-rejected-applied",
        approver_user_ids=["manager-001"],
    )
    body = _callback_body("proc-rejected-applied", "rejected")

    # When: DingTalk 延迟投递 rejected 回调。
    response = _post_callback(body)

    # Then: 已应用申请和现有授权不被拒绝状态覆盖, 冲突显式报错并留审计。
    access_request.refresh_from_db()
    grant.refresh_from_db()
    assert response.status_code == HTTPStatus.CONFLICT
    assert access_request.status == REQUEST_STATUS_GRANT_APPLIED
    assert grant.version == INITIAL_VERSION
    assert AuditLog.objects.filter(event_type="dingtalk_callback_status_conflict").exists()


@override_settings(EASYAUTH_DINGTALK_CALLBACK_SECRET=CALLBACK_KEY)
def test_dingtalk_callback_rejected_request_does_not_override_approved_request() -> None:
    # Given: 申请已经进入 approved, 授权应用尚未改变当前授权事实。
    user = UserMirror.objects.create(authentik_user_id="dingtalk-reject-approved-user")
    app = App.objects.create(
        app_key="dingtalk-reject-approved-app",
        name="DingTalk Reject Approved",
    )
    group = _authorization_group(app, "reader")
    _ = AccessGrant.objects.create(user=user, app=app, grant_type=GRANT_TYPE_PERMANENT)
    access_request = AccessRequest.objects.create(
        user=user,
        app=app,
        status=REQUEST_STATUS_APPROVED,
        approved_at=timezone.now() - timedelta(minutes=1),
        dingtalk_process_instance_id="proc-rejected-approved",
        approver_user_ids=["manager-001"],
    )
    _ = AccessRequestGroup.objects.create(access_request=access_request, authorization_group=group)
    body = _callback_body("proc-rejected-approved", "rejected")

    # When: DingTalk 延迟投递 rejected 回调。
    response = _post_callback(body)

    # Then: 已批准申请不被拒绝状态覆盖, 冲突显式报错。
    access_request.refresh_from_db()
    assert response.status_code == HTTPStatus.CONFLICT
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
        approver_user_ids=["manager-001"],
    )
    body = _callback_body("proc-rejected-failed", "rejected")

    # When: DingTalk 延迟投递 rejected 回调。
    response = _post_callback(body)

    # Then: 授权失败终态不被拒绝状态覆盖, 冲突显式报错。
    access_request.refresh_from_db()
    assert response.status_code == HTTPStatus.CONFLICT
    assert access_request.status == REQUEST_STATUS_GRANT_FAILED


@pytest.mark.parametrize(
    ("current_status", "process_instance_id"),
    [
        (REQUEST_STATUS_REJECTED, "proc-approved-rejected"),
        (REQUEST_STATUS_GRANT_FAILED, "proc-approved-failed"),
    ],
)
@override_settings(EASYAUTH_DINGTALK_CALLBACK_SECRET=CALLBACK_KEY)
def test_dingtalk_callback_rejects_approved_callback_for_conflicting_terminal_status(
    current_status: str,
    process_instance_id: str,
) -> None:
    # Given: 申请已经进入与 approved 回调冲突的终态。
    user = UserMirror.objects.create(authentik_user_id=f"dingtalk-{process_instance_id}-user")
    app = App.objects.create(
        app_key=f"dingtalk-{process_instance_id}-app",
        name=process_instance_id,
    )
    access_request = AccessRequest.objects.create(
        user=user,
        app=app,
        status=current_status,
        dingtalk_process_instance_id=process_instance_id,
        approver_user_ids=["manager-001"],
    )
    body = _callback_body(process_instance_id, "approved")

    # When: DingTalk 延迟投递 approved 回调。
    response = _post_callback(body)

    # Then: 接口返回冲突, 不创建或修改授权。
    access_request.refresh_from_db()
    assert response.status_code == HTTPStatus.CONFLICT
    assert access_request.status == current_status
    assert AccessGrant.objects.count() == 0


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
            approver_user_ids=["manager-001"],
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
    group = _authorization_group(app, role_key)
    _ = ApprovalRule.objects.create(
        app=app,
        authorization_group=group,
        approver_userids=["manager-001"],
    )
    access_request = AccessRequest.objects.create(
        user=user,
        app=app,
        dingtalk_process_instance_id=process_instance_id,
        approver_user_ids=["manager-001"],
    )
    _ = AccessRequestGroup.objects.create(access_request=access_request, authorization_group=group)
    return access_request


def _authorization_group(app: App, key: str) -> AuthorizationGroup:
    return AuthorizationGroup.objects.create(app=app, key=key, kind="role", name=key)


def _callback_body(
    process_instance_id: str,
    status: str,
    approver_user_id: str = "manager-001",
) -> bytes:
    payload = {
        "process_instance_id": process_instance_id,
        "status": status,
        "approver_user_id": approver_user_id,
    }
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



@override_settings(EASYAUTH_DINGTALK_CALLBACK_SECRET=CALLBACK_KEY)
def test_dingtalk_callback_rejects_approver_outside_request_approver_list() -> None:
    # Given: 申请显式限定了审批人列表。
    access_request = _submitted_grant_request(
        user_key="dingtalk-approver-check-user",
        app_key="dingtalk-approver-check-app",
        role_key="reader",
        process_instance_id="proc-approver-check",
    )
    access_request.approver_user_ids = ["manager-001"]
    access_request.save(update_fields=["approver_user_ids"])
    body = _callback_body("proc-approver-check", "approved", approver_user_id="intruder-007")

    # When: 持有共享密钥者以列表外身份投递批准回调。
    response = _post_callback(body)

    # Then: 回调被拒绝, 申请状态不变, 写入安全审计。
    access_request.refresh_from_db()
    assert response.status_code == HTTPStatus.FORBIDDEN
    assert access_request.status == REQUEST_STATUS_SUBMITTED
    assert AccessGrant.objects.count() == 0
    audit_log = AuditLog.objects.get(event_type="dingtalk_callback_approver_rejected")
    assert audit_log.metadata["approver_user_id"] == "intruder-007"


@override_settings(EASYAUTH_DINGTALK_CALLBACK_SECRET=CALLBACK_KEY)
def test_dingtalk_callback_records_final_approver_in_audit() -> None:
    # Given: submitted 申请限定审批人 manager-001。
    access_request = _submitted_grant_request(
        user_key="dingtalk-final-approver-user",
        app_key="dingtalk-final-approver-app",
        role_key="reader",
        process_instance_id="proc-final-approver",
    )
    access_request.approver_user_ids = ["manager-001"]
    access_request.save(update_fields=["approver_user_ids"])
    body = _callback_body("proc-final-approver", "approved", approver_user_id="manager-001")

    # When: manager-001 批准该申请。
    response = _post_callback(body)

    # Then: 审计记录最终审批人。
    audit_log = AuditLog.objects.get(event_type="dingtalk_approval_approved")
    assert response.status_code == HTTPStatus.OK
    assert audit_log.actor_id == "manager-001"
    assert audit_log.metadata["approver_user_id"] == "manager-001"


@override_settings(EASYAUTH_DINGTALK_CALLBACK_SECRET=CALLBACK_KEY)
def test_dingtalk_callback_fails_closed_when_approver_list_empty() -> None:
    # Given: 一条审批人列表为空的申请 (不变量被破坏, 只能经非门户路径产生)。
    access_request = _submitted_grant_request(
        user_key="dingtalk-empty-approver-user",
        app_key="dingtalk-empty-approver-app",
        role_key="reader",
        process_instance_id="proc-empty-approver",
    )
    access_request.approver_user_ids = []
    access_request.save(update_fields=["approver_user_ids"])
    body = _callback_body("proc-empty-approver", "approved", approver_user_id="manager-001")

    # When: 持有共享密钥者投递批准回调。
    response = _post_callback(body)

    # Then: fail-closed 拒绝, 申请状态不变, 不产生授权。
    access_request.refresh_from_db()
    assert response.status_code == HTTPStatus.FORBIDDEN
    assert access_request.status == REQUEST_STATUS_SUBMITTED
    assert AccessGrant.objects.count() == 0


@override_settings(EASYAUTH_DINGTALK_CALLBACK_SECRET=CALLBACK_KEY)
def test_dingtalk_callback_rejects_applicant_self_approval() -> None:
    # Given: 申请人本人恰好也在审批人列表里 (自审自批)。
    access_request = _submitted_grant_request(
        user_key="dingtalk-self-approver-user",
        app_key="dingtalk-self-approver-app",
        role_key="reader",
        process_instance_id="proc-self-approver",
    )
    access_request.approver_user_ids = ["dingtalk-self-approver-user"]
    access_request.save(update_fields=["approver_user_ids"])
    body = _callback_body(
        "proc-self-approver",
        "approved",
        approver_user_id="dingtalk-self-approver-user",
    )

    # When: 申请人以自己身份投递批准回调。
    response = _post_callback(body)

    # Then: 回调被拒绝, 申请状态不变, 不产生授权。
    access_request.refresh_from_db()
    assert response.status_code == HTTPStatus.FORBIDDEN
    assert access_request.status == REQUEST_STATUS_SUBMITTED
    assert AccessGrant.objects.count() == 0
