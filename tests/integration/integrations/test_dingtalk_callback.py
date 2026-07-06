from __future__ import annotations

import hmac
import json
from hashlib import sha256
from http import HTTPStatus
from time import time
from typing import TYPE_CHECKING, Final, Protocol

import pytest
from django.test import Client, override_settings

from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App
from easyauth.audit.models import AuditLog
from easyauth.webhooks.models import AppWebhookConfig, WebhookDelivery
from easyauth.workflows.models import (
    APPROVAL_STATUS_APPROVED,
    APPROVAL_STATUS_REJECTED,
    APPROVAL_STATUS_SUBMITTED,
    ApprovalInstance,
    ApprovalTemplate,
)

if TYPE_CHECKING:
    from easyauth.api.errors import JsonValue

pytestmark = pytest.mark.django_db

CALLBACK_URL: Final = "/integrations/dingtalk/callback"
CALLBACK_KEY: Final = "integration-callback-key"


class _CallbackResponse(Protocol):
    status_code: int

    def json(self) -> dict[str, JsonValue]: ...


@override_settings(EASYAUTH_DINGTALK_CALLBACK_SECRET=CALLBACK_KEY)
def test_callback_rejects_invalid_signature_without_mutating_instance() -> None:
    # Given: 一条 submitted 审批实例。
    instance = _submitted_instance("cb-sig-app", "proc-invalid-signature")
    body = _callback_body("proc-invalid-signature", "approved")

    # When: 使用错误签名回调。
    response = _post(body, timestamp=_current_timestamp(), signature="bad-signature")

    # Then: 403, 实例状态不变, 有签名拒绝审计。
    instance.refresh_from_db()
    assert response.status_code == HTTPStatus.FORBIDDEN
    assert instance.status == APPROVAL_STATUS_SUBMITTED
    assert AuditLog.objects.filter(
        event_type="dingtalk_callback_signature_rejected",
    ).exists()


@override_settings(EASYAUTH_DINGTALK_CALLBACK_SECRET=CALLBACK_KEY)
def test_callback_approves_instance_and_enqueues_webhook() -> None:
    # Given: submitted 实例, 且 APP 配置了审批结果回调 webhook。
    instance = _submitted_instance("cb-approve-app", "proc-approve")
    _ = AppWebhookConfig.objects.create(
        app=instance.app,
        secret="whsec-test",  # noqa: S106 - 测试用密钥。
        approval_callback_url="https://app.example.com/easyauth/approvals",
    )
    body = _callback_body("proc-approve", "approved")

    # When
    response = _signed_post(body)

    # Then: 实例进入 approved, 结果投递已入列(pending), 审计成链。
    payload = response.json()
    instance.refresh_from_db()
    delivery = WebhookDelivery.objects.get(app=instance.app)
    assert response.status_code == HTTPStatus.OK
    assert payload["status"] == APPROVAL_STATUS_APPROVED
    assert payload["instance_id"] == str(instance.id)
    assert instance.status == APPROVAL_STATUS_APPROVED
    assert instance.completed_at is not None
    assert instance.completion_delivery is not None
    assert instance.completion_delivery.id == delivery.id
    assert delivery.event_type == "approval.completed"
    assert delivery.payload["biz_key"] == instance.biz_key
    assert delivery.payload["status"] == APPROVAL_STATUS_APPROVED
    assert AuditLog.objects.filter(event_type="approval_instance_approved").exists()


@override_settings(EASYAUTH_DINGTALK_CALLBACK_SECRET=CALLBACK_KEY)
def test_callback_without_webhook_config_marks_delivery_skipped() -> None:
    # Given: submitted 实例, APP 未配置 webhook。
    instance = _submitted_instance("cb-skip-app", "proc-skip")
    body = _callback_body("proc-skip", "rejected")

    # When
    response = _signed_post(body)

    # Then: 状态推进但投递为 skipped(APP 侧轮询兜底)。
    instance.refresh_from_db()
    assert response.status_code == HTTPStatus.OK
    assert instance.status == APPROVAL_STATUS_REJECTED
    assert instance.completion_delivery is None
    assert instance.delivery_state() == "skipped"
    assert WebhookDelivery.objects.count() == 0


@override_settings(EASYAUTH_DINGTALK_CALLBACK_SECRET=CALLBACK_KEY)
def test_callback_is_idempotent_and_conflicts_on_terminal_change() -> None:
    # Given: 已 approved 的实例。
    instance = _submitted_instance("cb-idem-app", "proc-idem")
    approve_body = _callback_body("proc-idem", "approved")
    _ = _signed_post(approve_body)

    # When: 重复同态回调与终态翻转回调。
    repeat = _signed_post(approve_body)
    reject_body = _callback_body("proc-idem", "rejected")
    conflict = _signed_post(reject_body)

    # Then: 同态幂等 200; 终态翻转 409 且留冲突审计。
    instance.refresh_from_db()
    assert repeat.status_code == HTTPStatus.OK
    assert conflict.status_code == HTTPStatus.CONFLICT
    assert instance.status == APPROVAL_STATUS_APPROVED
    assert AuditLog.objects.filter(event_type="dingtalk_callback_status_conflict").exists()


@override_settings(EASYAUTH_DINGTALK_CALLBACK_SECRET=CALLBACK_KEY)
def test_callback_unknown_process_returns_not_found_with_audit() -> None:
    # Given: 不存在的审批实例号。
    body = _callback_body("proc-unknown", "approved")

    # When
    response = _signed_post(body)

    # Then
    assert response.status_code == HTTPStatus.NOT_FOUND
    audit_log = AuditLog.objects.get(event_type="dingtalk_callback_unknown_process")
    assert audit_log.target_id == "proc-unknown"


@override_settings(EASYAUTH_DINGTALK_CALLBACK_SECRET=CALLBACK_KEY)
def test_callback_rejects_unknown_status_payload() -> None:
    # Given
    _ = _submitted_instance("cb-status-app", "proc-status")
    body = json.dumps(
        {"process_instance_id": "proc-status", "status": "revoked"},
    ).encode("utf-8")

    # When
    response = _signed_post(body)

    # Then: 未支持状态 422, 有载荷拒绝审计。
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert AuditLog.objects.filter(event_type="dingtalk_callback_payload_rejected").exists()


def _submitted_instance(app_key: str, process_instance_id: str) -> ApprovalInstance:
    app = App.objects.create(app_key=app_key, name=app_key)
    template = ApprovalTemplate.objects.create(
        app=app,
        key="expense",
        name="费用审批",
        dingtalk_process_code="PROC-TEST",
    )
    originator = UserMirror.objects.create(
        authentik_user_id=f"{app_key}-originator",
        dingtalk_userid=f"{app_key}-dt",
    )
    return ApprovalInstance.objects.create(
        app=app,
        template=template,
        biz_key=f"{app_key}-biz-1",
        originator_user=originator,
        dingtalk_process_instance_id=process_instance_id,
        status=APPROVAL_STATUS_SUBMITTED,
    )


def _callback_body(process_instance_id: str, status: str) -> bytes:
    return json.dumps(
        {"process_instance_id": process_instance_id, "status": status},
    ).encode("utf-8")


def _current_timestamp() -> str:
    return str(int(time() * 1000))


def _signed_post(body: bytes) -> _CallbackResponse:
    timestamp = _current_timestamp()
    message = timestamp.encode("utf-8") + b"." + body
    signature = hmac.new(CALLBACK_KEY.encode("utf-8"), message, sha256).hexdigest()
    return _post(body, timestamp=timestamp, signature=signature)


def _post(body: bytes, *, timestamp: str, signature: str) -> _CallbackResponse:
    client = Client()
    return client.post(
        CALLBACK_URL,
        data=body,
        content_type="application/json",
        HTTP_X_EASYAUTH_DINGTALK_TIMESTAMP=timestamp,
        HTTP_X_EASYAUTH_DINGTALK_SIGNATURE=signature,
    )
