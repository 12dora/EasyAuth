from __future__ import annotations

import pytest

from easyauth.accounts.models import DingTalkUserMirror, UserMirror
from easyauth.applications.models import App
from easyauth.notify.models import (
    CREDENTIAL_TYPE_STATIC_TOKEN,
    NOTIFY_MESSAGE_STATUS_FAILED,
    NOTIFY_MESSAGE_STATUS_PENDING,
    NOTIFY_RECIPIENT_STATUS_FAILED,
    NOTIFY_TEMPLATE_TEXT,
    NotifyMessage,
    NotifyRecipient,
)
from easyauth.notify.services import NotifyAcceptError, accept_notify_message
from easyauth.outbox.models import OutboxEvent

pytestmark = pytest.mark.django_db

CORP_ID = "corp-accept"
SOURCE = "dingtalk-primary"


def _seed_active_user(*, authentik: str, dingtalk: str) -> None:
    _ = DingTalkUserMirror.objects.create(
        source_slug=SOURCE,
        corp_id=CORP_ID,
        user_id=dingtalk,
        name=dingtalk,
        status="active",
    )
    _ = UserMirror.objects.create(
        authentik_user_id=authentik,
        dingtalk_userid=dingtalk,
        dingtalk_corp_id=CORP_ID,
    )


def _accept(
    app: App,
    *,
    recipients: list[str],
    content: str = "hello",
    dedup_key: str = "",
) -> object:
    return accept_notify_message(
        app=app,
        recipients=recipients,
        template=NOTIFY_TEMPLATE_TEXT,
        content=content,
        dedup_key=dedup_key,
        requested_credential_type=CREDENTIAL_TYPE_STATIC_TOKEN,
        requested_credential_id=1,
    )


def test_accept_creates_message_recipients_and_outbox() -> None:
    app = App.objects.create(app_key="notify-accept-new", name="Notify Accept")
    _seed_active_user(authentik="u1", dingtalk="dt-u1")

    result = _accept(app, recipients=["u1"], content="body-1")

    assert result.accepted is True
    assert result.recipient_total == 1
    assert result.recipient_rejected == 0
    message = result.message
    assert message.status == NOTIFY_MESSAGE_STATUS_PENDING
    assert message.recipient_total == 1
    assert NotifyRecipient.objects.filter(message=message).count() == 1
    assert OutboxEvent.objects.filter(
        event_key=f"notify-delivery:{message.id}:1",
        task_name="easyauth.notify.deliver_message",
    ).exists()


def test_accept_idempotent_same_dedup_key_same_payload() -> None:
    app = App.objects.create(app_key="notify-accept-idem", name="Notify Idem")
    _seed_active_user(authentik="u2", dingtalk="dt-u2")

    first = _accept(
        app,
        recipients=["u2"],
        content="same-body",
        dedup_key="event:1",
    )
    second = _accept(
        app,
        recipients=["u2"],
        content="same-body",
        dedup_key="event:1",
    )

    assert first.accepted is True
    assert second.accepted is False
    assert first.message.id == second.message.id
    assert NotifyMessage.objects.filter(app=app).count() == 1
    assert OutboxEvent.objects.filter(event_key__startswith="notify-delivery:").count() == 1


def test_accept_conflict_when_dedup_key_payload_differs() -> None:
    app = App.objects.create(app_key="notify-accept-conflict", name="Notify Conflict")
    _seed_active_user(authentik="u3", dingtalk="dt-u3")

    _ = _accept(
        app,
        recipients=["u3"],
        content="body-a",
        dedup_key="event:conflict",
    )

    with pytest.raises(NotifyAcceptError) as exc:
        _ = _accept(
            app,
            recipients=["u3"],
            content="body-b",
            dedup_key="event:conflict",
        )
    assert exc.value.kind == "conflict"
    assert NotifyMessage.objects.filter(app=app).count() == 1


def test_accept_empty_dedup_key_always_creates() -> None:
    app = App.objects.create(app_key="notify-accept-empty-dedup", name="Notify Empty")
    _seed_active_user(authentik="u4", dingtalk="dt-u4")

    first = _accept(app, recipients=["u4"], content="x", dedup_key="")
    second = _accept(app, recipients=["u4"], content="x", dedup_key="")

    assert first.accepted is True
    assert second.accepted is True
    assert first.message.id != second.message.id
    assert NotifyMessage.objects.filter(app=app).count() == 2  # noqa: PLR2004


def test_accept_all_recipients_failed_enters_failed_without_outbox() -> None:
    app = App.objects.create(app_key="notify-accept-all-fail", name="Notify All Fail")

    result = _accept(app, recipients=["dt:nobody-here"], content="x")

    assert result.accepted is True
    assert result.recipient_total == 1
    assert result.recipient_rejected == 1
    assert result.message.status == NOTIFY_MESSAGE_STATUS_FAILED
    assert result.message.completed_at is not None
    assert result.message.recipient_failed == 1
    assert not OutboxEvent.objects.filter(
        event_key=f"notify-delivery:{result.message.id}:1",
    ).exists()
    recipient = NotifyRecipient.objects.get(message=result.message)
    assert recipient.status == NOTIFY_RECIPIENT_STATUS_FAILED


def _patch_dedup_precheck_miss(monkeypatch: pytest.MonkeyPatch) -> None:
    """模拟并发: 预检查未命中已有行, 写入时撞唯一约束走 IntegrityError 分支。"""
    original_filter = NotifyMessage.objects.filter

    def filter_miss_precheck(*args: object, **kwargs: object) -> object:
        queryset = original_filter(*args, **kwargs)
        if "dedup_key" in kwargs:

            class _Miss:
                def first(self) -> None:
                    return None

            return _Miss()
        return queryset

    monkeypatch.setattr(NotifyMessage.objects, "filter", filter_miss_precheck)


def test_accept_integrity_error_same_payload_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = App.objects.create(app_key="notify-accept-race-idem", name="Notify Race Idem")
    _seed_active_user(authentik="u-race-1", dingtalk="dt-race-1")
    first = _accept(
        app,
        recipients=["u-race-1"],
        content="race-same-body",
        dedup_key="race:same",
    )

    _patch_dedup_precheck_miss(monkeypatch)
    second = _accept(
        app,
        recipients=["u-race-1"],
        content="race-same-body",
        dedup_key="race:same",
    )

    assert first.accepted is True
    assert second.accepted is False
    assert second.message.id == first.message.id
    assert NotifyMessage.objects.filter(app=app).count() == 1


def test_accept_integrity_error_different_payload_is_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = App.objects.create(app_key="notify-accept-race-conflict", name="Notify Race Conflict")
    _seed_active_user(authentik="u-race-2", dingtalk="dt-race-2")
    first = _accept(
        app,
        recipients=["u-race-2"],
        content="race-body-a",
        dedup_key="race:conflict",
    )

    _patch_dedup_precheck_miss(monkeypatch)
    with pytest.raises(NotifyAcceptError) as exc:
        _ = _accept(
            app,
            recipients=["u-race-2"],
            content="race-body-b",
            dedup_key="race:conflict",
        )

    assert exc.value.kind == "conflict"
    assert NotifyMessage.objects.filter(app=app).count() == 1
    assert NotifyMessage.objects.get(app=app).id == first.message.id
