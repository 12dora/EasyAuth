from __future__ import annotations

import pytest

from easyauth.access_requests.inbound_callbacks import (
    ApprovalCallbackError,
    apply_approval_callback,
)
from easyauth.access_requests.models import (
    GRANT_TYPE_PERMANENT,
    REQUEST_STATUS_GRANT_FAILED,
    REQUEST_STATUS_REJECTED,
    REQUEST_STATUS_SUBMITTED,
    REQUEST_TYPE_CHANGE,
    AccessRequest,
    AccessRequestGroup,
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
from easyauth.grants.models import AccessGrant
from easyauth.grants.query import resolve_user_permissions

pytestmark = pytest.mark.django_db


def test_apply_approval_callback_rejects_submitted_request_without_creating_grant() -> None:
    # Given: submitted grant 申请绑定 DingTalk process instance id。
    access_request = _submitted_grant_request(
        user_key="callback-rejected-user",
        app_key="callback-rejected-app",
        role_key="reader",
        process_instance_id="proc-rejected",
    )

    # When: 入站审批回调拒绝该申请。
    rejected = apply_approval_callback(
        process_instance_id="proc-rejected",
        status="rejected",
        approver_user_id="manager-001",
        raw_payload=b'{"status":"rejected"}',
    )

    # Then: 申请进入 rejected, 记录审批审计, 授权事实保持为空。
    access_request.refresh_from_db()
    snapshot = resolve_user_permissions(user=access_request.user, app=access_request.app)
    audit_log = AuditLog.objects.get(event_type="dingtalk_approval_rejected")
    assert rejected.id == access_request.id
    assert access_request.status == REQUEST_STATUS_REJECTED
    assert audit_log.actor_type == "dingtalk"
    assert audit_log.actor_id == "manager-001"
    assert audit_log.target_type == "access_request"
    assert audit_log.target_id == str(access_request.id)
    assert audit_log.metadata == {
        "process_instance_id": "proc-rejected",
        "user_id": "callback-rejected-user",
        "app_key": "callback-rejected-app",
        "approver_user_id": "manager-001",
    }
    assert AccessGrant.objects.count() == 0
    assert snapshot.grant_version == 0
    assert snapshot.groups == ()
    assert snapshot.grants == ()


def test_apply_approval_callback_returns_not_found_for_unknown_process_with_audit() -> None:
    with pytest.raises(ApprovalCallbackError) as exc_info:
        _ = apply_approval_callback(
            process_instance_id="proc-unknown",
            status="approved",
            approver_user_id="manager-001",
            raw_payload=b'{"status":"approved"}',
        )

    audit_log = AuditLog.objects.get(event_type="dingtalk_callback_unknown_process")
    assert exc_info.value.kind == "not_found"
    assert exc_info.value.details == {"process_instance_id": "proc-unknown"}
    assert audit_log.actor_type == "dingtalk"
    assert audit_log.actor_id == "callback"
    assert audit_log.target_type == "dingtalk_callback"
    assert audit_log.target_id == "proc-unknown"
    assert audit_log.metadata == {"process_instance_id": "proc-unknown"}


def test_apply_approval_callback_returns_application_error_when_apply_fails() -> None:
    # Given: submitted change 申请审批通过后找不到当前授权, 应用授权会失败。
    user = UserMirror.objects.create(authentik_user_id="callback-apply-error-user")
    app = App.objects.create(app_key="callback-apply-error-app", name="Callback Apply Error")
    group = AuthorizationGroup.objects.create(app=app, key="writer", kind="role", name="Writer")
    access_request = AccessRequest.objects.create(
        user=user,
        app=app,
        request_type=REQUEST_TYPE_CHANGE,
        dingtalk_process_instance_id="proc-apply-error",
    )
    _ = AccessRequestGroup.objects.create(access_request=access_request, authorization_group=group)

    # When: 入站审批回调批准该申请。
    with pytest.raises(ApprovalCallbackError) as exc_info:
        _ = apply_approval_callback(
            process_instance_id="proc-apply-error",
            status="approved",
            approver_user_id="manager-001",
            raw_payload=b'{"status":"approved"}',
        )

    # Then: 回调错误分类为 application_error, 申请进入 grant_failed 且授权事实不变。
    access_request.refresh_from_db()
    assert exc_info.value.kind == "application_error"
    assert exc_info.value.details == {"process_instance_id": "proc-apply-error"}
    assert access_request.status == REQUEST_STATUS_GRANT_FAILED
    assert AccessGrant.objects.count() == 0
    assert AuditLog.objects.filter(event_type="dingtalk_approval_approved").count() == 1
    assert AuditLog.objects.filter(event_type="grant_apply_failed").count() == 1


def test_apply_approval_callback_rejects_invalid_status_without_mutating_request_or_grant() -> None:
    # Given: submitted grant 申请绑定 DingTalk process instance id。
    access_request = _submitted_grant_request(
        user_key="callback-invalid-status-user",
        app_key="callback-invalid-status-app",
        role_key="reader",
        process_instance_id="proc-invalid-status",
    )

    # When: 入站审批回调传入服务层不支持的状态。
    with pytest.raises(ApprovalCallbackError) as exc_info:
        _ = apply_approval_callback(
            process_instance_id="proc-invalid-status",
            status="cancelled",
            approver_user_id="manager-001",
            raw_payload=b'{"status":"cancelled"}',
        )

    # Then: 服务返回 validation_error, 不修改申请和授权事实。
    access_request.refresh_from_db()
    assert exc_info.value.kind == "validation_error"
    assert exc_info.value.details == {
        "process_instance_id": "proc-invalid-status",
        "status": "cancelled",
    }
    assert access_request.status == REQUEST_STATUS_SUBMITTED
    assert AccessGrant.objects.count() == 0
    assert AuditLog.objects.count() == 0


def _submitted_grant_request(
    *,
    user_key: str,
    app_key: str,
    role_key: str,
    process_instance_id: str,
) -> AccessRequest:
    user = UserMirror.objects.create(authentik_user_id=user_key)
    app = App.objects.create(app_key=app_key, name=app_key)
    scope = AppScope.objects.create(app=app, key="GLOBAL", name="Global")
    group = AuthorizationGroup.objects.create(app=app, key=role_key, kind="role", name=role_key)
    permission = Permission.objects.create(
        app=app,
        key=f"{role_key}.view",
        name=f"{role_key} View",
        supported_scopes=[scope.key],
    )
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=group,
        permission=permission,
        scope_key=scope.key,
    )
    _ = ApprovalRule.objects.create(
        app=app,
        authorization_group=group,
        approver_userids=["manager-001"],
    )
    access_request = AccessRequest.objects.create(
        user=user,
        app=app,
        grant_type=GRANT_TYPE_PERMANENT,
        dingtalk_process_instance_id=process_instance_id,
    )
    _ = AccessRequestGroup.objects.create(access_request=access_request, authorization_group=group)
    return access_request
