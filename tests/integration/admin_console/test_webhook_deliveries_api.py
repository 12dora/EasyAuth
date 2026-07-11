from __future__ import annotations

from http import HTTPStatus
from typing import Final, Protocol

import pytest
from django.contrib.auth.models import User
from django.test import Client
from pydantic import TypeAdapter

from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.applications.models import App
from easyauth.audit.models import AuditLog
from easyauth.webhooks.models import WebhookDelivery

pytestmark = pytest.mark.django_db

LOGIN_VALUE: Final = "console-webhook-deliveries"
JSON_VALUE_ADAPTER: Final[TypeAdapter[JsonValue]] = TypeAdapter(JsonValue)


class HttpResponseLike(Protocol):
    content: bytes


def test_list_webhook_deliveries_summary_and_redeliver() -> None:
    # Given: 应用 owner 与两条投递(含失败行)。
    client = _logged_in_superuser("webhook-deliveries-admin")
    app = App.objects.create(app_key="webhook-deliveries-app", name="Deliveries")
    other = App.objects.create(app_key="webhook-deliveries-other", name="Other")
    failed = WebhookDelivery.objects.create(
        app=app,
        delivery_id="del-failed-1",
        event_type="approval.completed",
        target_url="https://app.example.com/hook",
        payload={"secret": "should-not-leak-by-default"},
        status="failed",
        attempts=5,
        last_error="x" * 250,
    )
    _ = WebhookDelivery.objects.create(
        app=app,
        delivery_id="del-ok-1",
        event_type="webhook.test",
        target_url="https://app.example.com/hook",
        payload={"ok": True},
        status="delivered",
        attempts=1,
    )
    _ = WebhookDelivery.objects.create(
        app=other,
        delivery_id="del-other",
        event_type="approval.completed",
        target_url="https://other.example.com/hook",
        payload={},
        status="failed",
    )

    list_url = f"/console/api/v1/apps/{app.app_key}/webhook-deliveries"

    # When
    listed = client.get(list_url)
    filtered = client.get(list_url, data={"status": "failed", "event_type": "approval.completed"})
    with_payload = client.get(list_url, data={"include_payload": "true"})
    redeliver_url = f"/console/api/v1/apps/{app.app_key}/webhook-deliveries/{failed.id}/redeliver"
    first = client.post(redeliver_url, data="{}", content_type="application/json")
    second = client.post(redeliver_url, data="{}", content_type="application/json")

    # Then
    body = _response_json(listed)
    assert listed.status_code == HTTPStatus.OK
    assert body["pagination"]["total_items"] == 2
    items = body["data"]
    assert isinstance(items, list)
    assert len(items) == 2
    for item in items:
        assert isinstance(item, dict)
        assert "payload" not in item
        assert "secret" not in str(item)
        assert set(item) >= {
            "id",
            "delivery_id",
            "event_type",
            "target_url",
            "status",
            "attempts",
            "generation",
            "last_error",
            "created_at",
            "updated_at",
        }
    failed_item = next(item for item in items if item["delivery_id"] == "del-failed-1")
    assert isinstance(failed_item["last_error"], str)
    assert len(failed_item["last_error"]) <= 201

    filtered_body = _response_json(filtered)
    assert filtered.status_code == HTTPStatus.OK
    assert filtered_body["pagination"]["total_items"] == 1
    assert filtered_body["data"][0]["delivery_id"] == "del-failed-1"

    payload_body = _response_json(with_payload)
    assert with_payload.status_code == HTTPStatus.OK
    payload_item = next(
        item for item in payload_body["data"] if item["delivery_id"] == "del-failed-1"
    )
    assert payload_item["payload"] == {"secret": "should-not-leak-by-default"}

    failed.refresh_from_db()
    assert first.status_code == HTTPStatus.OK
    assert failed.status == "pending"
    assert failed.attempts == 0
    assert second.status_code == HTTPStatus.CONFLICT
    second_error = _response_json(second)["error"]
    assert isinstance(second_error, dict)
    assert second_error["code"] == ErrorCode.SEMANTIC_VALIDATION_ERROR
    assert AuditLog.objects.filter(event_type="webhook_delivery_redelivered").count() == 1


def test_webhook_deliveries_require_auth_and_known_app() -> None:
    client = Client(HTTP_HOST="localhost")
    response = client.get("/console/api/v1/apps/missing/webhook-deliveries")
    assert response.status_code == HTTPStatus.UNAUTHORIZED

    authed = _logged_in_superuser("webhook-deliveries-missing-admin")
    missing = authed.get("/console/api/v1/apps/no-such-app/webhook-deliveries")
    assert missing.status_code == HTTPStatus.NOT_FOUND


def _logged_in_superuser(username: str) -> Client:
    _ = User.objects.create_superuser(username=username, password=LOGIN_VALUE)
    client = Client(HTTP_HOST="localhost")
    assert client.login(username=username, password=LOGIN_VALUE) is True
    return client


def _response_json(response: HttpResponseLike) -> dict[str, JsonValue]:
    parsed = JSON_VALUE_ADAPTER.validate_json(response.content)
    assert isinstance(parsed, dict), response.content.decode()
    return parsed
