from __future__ import annotations

from http import HTTPStatus
from json import dumps, loads
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from django.core.cache import cache
from django.test import Client, RequestFactory
from django.utils import timezone

from easyauth.accounts.models import DingTalkUserMirror, UserMirror
from easyauth.api.notify_views import notify_message_detail, notify_messages_create
from easyauth.applications.models import (
    CAPABILITY_NOTIFY,
    App,
    AppCapability,
    AppNotificationChannel,
)
from easyauth.applications.services import AppPrincipal
from easyauth.audit.models import AuditLog
from easyauth.notify.models import (
    CREDENTIAL_TYPE_STATIC_TOKEN,
    NOTIFY_ERROR_USER_INACTIVE,
    NOTIFY_MESSAGE_STATUS_PARTIALLY_FAILED,
    NOTIFY_RECIPIENT_STATUS_DELIVERED,
    NOTIFY_RECIPIENT_STATUS_FAILED,
    NOTIFY_TEMPLATE_ACTION_CARD,
    NotifyMessage,
    NotifyRecipient,
)
from easyauth.notify.services import deliver_message

pytestmark = pytest.mark.django_db

_SAMPLES = Path(__file__).resolve().parents[2] / "contract_samples" / "notify"
_APP_KEY = "easyproject"
_AUTH_HEADER = "Bearer eat_notify_test"
_CORP = "corp-notify-api"
_SOURCE = "dingtalk"


def _load_sample(name: str) -> dict[str, Any]:
    return loads((_SAMPLES / name).read_text(encoding="utf-8"))


def _enable_notify(app: App, *, config: dict[str, Any] | None = None) -> None:
    _ = AppCapability.objects.create(
        app=app,
        capability=CAPABILITY_NOTIFY,
        enabled=True,
        config=config or {},
    )
    _ = _channel(app)


def _channel(app: App) -> AppNotificationChannel:
    return AppNotificationChannel.objects.create(
        app=app,
        name="API 测试通知通道",
        dingtalk_app_key="api-test-key",
        dingtalk_app_secret="api-test-secret",  # noqa: S106 - 测试专用固定值。
        agent_id="1001",
        version=1,
    )


def _auth(monkeypatch: pytest.MonkeyPatch, app: App) -> AppPrincipal:
    principal = AppPrincipal(
        app_id=app.id,
        app_key=app.app_key,
        credential_type="static_token",
        credential_id=202,
        capabilities=frozenset({CAPABILITY_NOTIFY}),
    )
    monkeypatch.setattr(
        "easyauth.api.notify_views.authenticate_permission_query_token",
        lambda _token: principal,
    )
    return principal


def _seed_user(*, authentik: str, dingtalk: str, status: str = "active") -> None:
    _ = DingTalkUserMirror.objects.create(
        source_slug=_SOURCE,
        corp_id=_CORP,
        user_id=dingtalk,
        name=dingtalk,
        status=status,
    )
    if authentik:
        _ = UserMirror.objects.create(
            authentik_user_id=authentik,
            dingtalk_userid=dingtalk,
            dingtalk_corp_id=_CORP,
            name=dingtalk,
        )


def _post(body: dict[str, Any]) -> object:
    return RequestFactory().post(
        f"/api/v1/apps/{_APP_KEY}/notify/messages",
        data=dumps(body),
        content_type="application/json",
        HTTP_AUTHORIZATION=_AUTH_HEADER,
    )


def test_post_202_new_accept(monkeypatch: pytest.MonkeyPatch) -> None:
    cache.clear()
    app = App.objects.create(app_key=_APP_KEY, name="EasyProject")
    _enable_notify(app)
    _auth(monkeypatch, app)
    _seed_user(authentik="f7c31a09e5b24f8d9a1c", dingtalk="user0123")
    # manager 仅需钉钉镜像(dt: 引用, 可无 UserMirror)。
    _ = DingTalkUserMirror.objects.create(
        source_slug=_SOURCE,
        corp_id=_CORP,
        user_id="manager8836",
        name="张主管",
        status="active",
    )
    body = _load_sample("message_create_request.json")
    response = notify_messages_create(_post(body), _APP_KEY)
    assert response.status_code == HTTPStatus.ACCEPTED
    payload = loads(response.content)
    sample = _load_sample("message_create_response.json")
    assert set(payload.keys()) == set(sample.keys())
    assert payload["accepted"] is True
    assert payload["status"] == "pending"
    assert payload["recipient_total"] == 2  # noqa: PLR2004
    assert payload["recipient_rejected"] == 0
    assert payload["message_id"]


def test_post_200_idempotent_replay(monkeypatch: pytest.MonkeyPatch) -> None:
    cache.clear()
    app = App.objects.create(app_key=_APP_KEY, name="EasyProject")
    _enable_notify(app)
    _auth(monkeypatch, app)
    _seed_user(authentik="u-idem", dingtalk="dt-idem")
    body = {
        "recipients": ["u-idem"],
        "template": "text",
        "content": "hello-idem",
        "dedup_key": "idem:1",
    }
    first = notify_messages_create(_post(body), _APP_KEY)
    second = notify_messages_create(_post(body), _APP_KEY)
    assert first.status_code == HTTPStatus.ACCEPTED
    assert second.status_code == HTTPStatus.OK
    p1 = loads(first.content)
    p2 = loads(second.content)
    assert p1["message_id"] == p2["message_id"]
    assert p2["accepted"] is False


def test_post_409_dedup_payload_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    cache.clear()
    app = App.objects.create(app_key=_APP_KEY, name="EasyProject")
    _enable_notify(app)
    _auth(monkeypatch, app)
    _seed_user(authentik="u-c", dingtalk="dt-c")
    base = {
        "recipients": ["u-c"],
        "template": "text",
        "content": "a",
        "dedup_key": "conflict:1",
    }
    assert notify_messages_create(_post(base), _APP_KEY).status_code == HTTPStatus.ACCEPTED
    conflict = {**base, "content": "b"}
    response = notify_messages_create(_post(conflict), _APP_KEY)
    assert response.status_code == HTTPStatus.CONFLICT
    assert loads(response.content)["error"]["code"] == "CONFLICT"


def test_get_status_contract_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    cache.clear()
    app = App.objects.create(app_key=_APP_KEY, name="EasyProject")
    _enable_notify(app)
    _auth(monkeypatch, app)
    user = UserMirror.objects.create(
        authentik_user_id="f7c31a09e5b24f8d9a1c",
        dingtalk_userid="user0123",
        dingtalk_corp_id=_CORP,
    )
    message = NotifyMessage.objects.create(
        app=app,
        channel=AppNotificationChannel.objects.get(app=app, is_active=True),
        template=NOTIFY_TEMPLATE_ACTION_CARD,
        title="任务逾期升级",
        content="x",
        deeplink_url="https://eproject.jiefakj.com/zh-CN/tasks/123",
        deeplink_title="查看任务",
        dedup_key="overdue-escalate:123:2026-07-16",
        payload_hash="a" * 64,
        biz_tag="overdue_escalation",
        status=NOTIFY_MESSAGE_STATUS_PARTIALLY_FAILED,
        recipient_total=2,
        recipient_sent=1,
        recipient_failed=1,
        requested_credential_type=CREDENTIAL_TYPE_STATIC_TOKEN,
        requested_credential_id=1,
        completed_at=timezone.now(),
    )
    _ = NotifyRecipient.objects.create(
        message=message,
        raw_ref="f7c31a09e5b24f8d9a1c",
        user=user,
        dingtalk_userid="user0123",
        status=NOTIFY_RECIPIENT_STATUS_DELIVERED,
        sent_at=timezone.now(),
        delivered_at=timezone.now(),
    )
    _ = NotifyRecipient.objects.create(
        message=message,
        raw_ref="dt:formeruser01",
        dingtalk_userid="formeruser01",
        status=NOTIFY_RECIPIENT_STATUS_FAILED,
        error_code=NOTIFY_ERROR_USER_INACTIVE,
        error="目录状态为 departed, 拒绝投递。",
    )

    request = RequestFactory().get(
        f"/api/v1/apps/{_APP_KEY}/notify/messages/{message.id}",
        HTTP_AUTHORIZATION=_AUTH_HEADER,
    )
    response = notify_message_detail(request, _APP_KEY, str(message.id))
    assert response.status_code == HTTPStatus.OK
    payload = loads(response.content)
    sample = _load_sample("message_status.json")
    assert set(payload.keys()) == set(sample.keys())
    assert payload["status"] == sample["status"]
    assert payload["template"] == sample["template"]
    assert payload["biz_tag"] == sample["biz_tag"]
    assert payload["dedup_key"] == sample["dedup_key"]
    assert payload["recipient_total"] == sample["recipient_total"]
    assert payload["recipient_sent"] == sample["recipient_sent"]
    assert payload["recipient_failed"] == sample["recipient_failed"]
    assert len(payload["recipients"]) == 2  # noqa: PLR2004
    keys = set(sample["recipients"][0].keys())
    assert set(payload["recipients"][0].keys()) == keys
    assert payload["recipients"][1]["error_code"] == "USER_INACTIVE"


def test_get_404_other_app(monkeypatch: pytest.MonkeyPatch) -> None:
    cache.clear()
    app = App.objects.create(app_key=_APP_KEY, name="EasyProject")
    other = App.objects.create(app_key="other", name="Other")
    _enable_notify(app)
    _auth(monkeypatch, app)
    other_channel = _channel(other)
    message = NotifyMessage.objects.create(
        app=other,
        channel=other_channel,
        template="text",
        content="x",
        payload_hash="b" * 64,
        requested_credential_type=CREDENTIAL_TYPE_STATIC_TOKEN,
        requested_credential_id=1,
    )
    request = RequestFactory().get("/", HTTP_AUTHORIZATION=_AUTH_HEADER)
    response = notify_message_detail(request, _APP_KEY, str(message.id))
    assert response.status_code == HTTPStatus.NOT_FOUND


def test_post_rate_limit_429(monkeypatch: pytest.MonkeyPatch) -> None:
    cache.clear()
    app = App.objects.create(app_key=_APP_KEY, name="EasyProject")
    _enable_notify(app, config={"rate_per_minute": 1})
    _auth(monkeypatch, app)
    _seed_user(authentik="rate-u", dingtalk="dt-rate")
    body = {
        "recipients": ["rate-u"],
        "template": "text",
        "content": "r1",
    }
    first = notify_messages_create(_post(body), _APP_KEY)
    assert first.status_code == HTTPStatus.ACCEPTED
    body2 = {**body, "content": "r2"}
    second = notify_messages_create(_post(body2), _APP_KEY)
    assert second.status_code == HTTPStatus.TOO_MANY_REQUESTS
    assert second["Retry-After"] == "60"
    assert loads(second.content)["error"]["code"] == "THROTTLED"


def test_capability_required(monkeypatch: pytest.MonkeyPatch) -> None:
    cache.clear()
    app = App.objects.create(app_key=_APP_KEY, name="EasyProject")
    _auth(monkeypatch, app)
    body = {"recipients": ["x"], "template": "text", "content": "c"}
    response = notify_messages_create(_post(body), _APP_KEY)
    assert response.status_code == HTTPStatus.FORBIDDEN
    assert "通知能力" in loads(response.content)["error"]["message"]
    rejected = AuditLog.objects.filter(event_type="app_notify_rejected")
    assert rejected.count() == 1
    assert rejected.get().metadata["error_code"] == "PERMISSION_DENIED"


def test_invalid_recipients_type_audits_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    cache.clear()
    app = App.objects.create(app_key=_APP_KEY, name="EasyProject")
    _enable_notify(app)
    _auth(monkeypatch, app)
    body = {"recipients": "not-a-list", "template": "text", "content": "c"}
    response = notify_messages_create(_post(body), _APP_KEY)
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    rejected = AuditLog.objects.filter(event_type="app_notify_rejected")
    assert rejected.count() == 1
    meta = rejected.get().metadata
    assert meta["error_code"] == "VALIDATION_ERROR"
    assert meta["recipient_count"] == 0


def test_error_code_enum_accept_time(monkeypatch: pytest.MonkeyPatch) -> None:
    cache.clear()
    app = App.objects.create(app_key=_APP_KEY, name="EasyProject")
    _enable_notify(app)
    _auth(monkeypatch, app)
    _ = UserMirror.objects.create(
        authentik_user_id="no-dt",
        dingtalk_userid="",
        dingtalk_corp_id="",
    )
    _seed_user(authentik="inactive-ak", dingtalk="inactive-dt", status="departed")

    body = {
        "recipients": ["missing-user", "no-dt", "dt:inactive-dt"],
        "template": "text",
        "content": "errs",
    }
    response = notify_messages_create(_post(body), _APP_KEY)
    assert response.status_code == HTTPStatus.ACCEPTED
    message_id = loads(response.content)["message_id"]
    detail_req = RequestFactory().get("/", HTTP_AUTHORIZATION=_AUTH_HEADER)
    detail = loads(notify_message_detail(detail_req, _APP_KEY, message_id).content)
    codes = {row["error_code"] for row in detail["recipients"]}
    assert "USER_NOT_FOUND" in codes
    assert "NO_DINGTALK_ID" in codes
    assert "USER_INACTIVE" in codes


def test_pipeline_accept_to_deliver(monkeypatch: pytest.MonkeyPatch) -> None:
    cache.clear()
    app = App.objects.create(app_key=_APP_KEY, name="EasyProject")
    _enable_notify(app)
    _auth(monkeypatch, app)
    _seed_user(authentik="pipe-u", dingtalk="dt-pipe")
    body = {
        "recipients": ["pipe-u"],
        "template": "text",
        "content": "pipeline",
    }
    response = notify_messages_create(_post(body), _APP_KEY)
    message_id = loads(response.content)["message_id"]

    client = MagicMock()
    client.send_work_notification.return_value = "task-pipe"

    def client_for_channel(_channel: AppNotificationChannel) -> tuple[MagicMock, int]:
        return client, 42

    monkeypatch.setattr(
        "easyauth.notify.services._dingtalk_client_and_agent",
        client_for_channel,
    )
    deliver_message(message_id, 1)

    detail_req = RequestFactory().get("/", HTTP_AUTHORIZATION=_AUTH_HEADER)
    detail = loads(notify_message_detail(detail_req, _APP_KEY, message_id).content)
    assert detail["status"] == "completed"
    assert detail["recipients"][0]["status"] == "sent"
    assert detail["recipient_sent"] == 1


def test_post_through_middleware_is_csrf_exempt(monkeypatch: pytest.MonkeyPatch) -> None:
    # RequestFactory 直调视图不经过 CsrfViewMiddleware, G1 冒烟曾因缺 @csrf_exempt
    # 在真实请求路径上 403; 此用例走完整中间件栈 + URL 路由防回归。
    cache.clear()
    app = App.objects.create(app_key=_APP_KEY, name="EasyProject")
    _enable_notify(app)
    _auth(monkeypatch, app)
    _seed_user(authentik="f7c31a09e5b24f8d9a1c", dingtalk="user0123")
    _ = DingTalkUserMirror.objects.create(
        source_slug=_SOURCE,
        corp_id=_CORP,
        user_id="manager8836",
        name="张主管",
        status="active",
    )
    client = Client(enforce_csrf_checks=True)
    response = client.post(
        f"/api/v1/apps/{_APP_KEY}/notify/messages",
        data=dumps(_load_sample("message_create_request.json")),
        content_type="application/json",
        HTTP_AUTHORIZATION=_AUTH_HEADER,
    )
    assert response.status_code == HTTPStatus.ACCEPTED
