from __future__ import annotations

from http import HTTPStatus
from typing import Final, Protocol

import pytest
from django.contrib.auth.models import User
from django.test import Client
from pydantic import TypeAdapter

from easyauth.accounts.models import UserMirror
from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.applications.models import App
from easyauth.audit.models import AuditLog
from easyauth.webhooks.models import WebhookDelivery
from easyauth.workflows.models import ApprovalInstance, ApprovalTemplate

pytestmark = pytest.mark.django_db

LOGIN_VALUE: Final = "console-operations-approval-instances"
JSON_VALUE_ADAPTER: Final[TypeAdapter[JsonValue]] = TypeAdapter(JsonValue)


class HttpResponseLike(Protocol):
    content: bytes


def test_redeliver_uses_atomic_failed_to_pending_transition() -> None:
    # Given: 两个请求都针对同一条失败的审批结果投递。
    client = _logged_in_superuser("ops-approval-redeliver-admin")
    app = App.objects.create(app_key="ops-approval-redeliver", name="Redeliver")
    template = ApprovalTemplate.objects.create(
        app=app,
        key="approval",
        name="审批",
        dingtalk_process_code="PROC-APPROVAL",
    )
    originator = UserMirror.objects.create(authentik_user_id="ops-redeliver-originator")
    delivery = WebhookDelivery.objects.create(
        app=app,
        delivery_id="ops-approval-redeliver-1",
        event_type="approval.completed",
        target_url="https://app.example.com/approval-callback",
        payload={},
        status="failed",
        attempts=5,
        last_error="HTTP 500",
    )
    instance = ApprovalInstance.objects.create(
        app=app,
        template=template,
        biz_key="ops-redeliver-biz",
        originator_user=originator,
        status="approved",
        submission_state="submitted",
        payload_hash="0" * 64,
        completion_delivery=delivery,
    )
    url = f"/console/api/v1/operations/approval-instances/{instance.id}/redeliver"

    # When: 第一次重投成功, 随后重复请求。
    first = client.post(url, data="{}", content_type="application/json")
    second = client.post(url, data="{}", content_type="application/json")

    # Then: 只有第一次能推进并记录审计, 重复请求明确返回冲突。
    delivery.refresh_from_db()
    first_body = _response_json(first)
    first_instance = first_body["approval_instance"]
    assert isinstance(first_instance, dict)
    assert first.status_code == HTTPStatus.OK
    assert first_instance["delivery_state"] == "pending"
    assert delivery.status == "pending"
    assert delivery.attempts == 0
    assert delivery.last_error == ""
    assert second.status_code == HTTPStatus.CONFLICT
    second_error = _response_json(second)["error"]
    assert isinstance(second_error, dict)
    assert second_error["code"] == ErrorCode.SEMANTIC_VALIDATION_ERROR
    assert AuditLog.objects.filter(event_type="approval_delivery_redelivered").count() == 1


def _logged_in_superuser(username: str) -> Client:
    _ = User.objects.create_superuser(username=username, password=LOGIN_VALUE)
    client = Client(HTTP_HOST="localhost")
    assert client.login(username=username, password=LOGIN_VALUE) is True
    return client


def _response_json(response: HttpResponseLike) -> dict[str, JsonValue]:
    parsed = JSON_VALUE_ADAPTER.validate_json(response.content)
    assert isinstance(parsed, dict), response.content.decode()
    return parsed
