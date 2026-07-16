from __future__ import annotations

import pytest
from django.utils import timezone

from easyauth.accounts.models import DingTalkUserMirror, UserMirror
from easyauth.applications.models import CAPABILITY_NOTIFY, App, AppCapability
from easyauth.notify.models import (
    CREDENTIAL_TYPE_STATIC_TOKEN,
    NOTIFY_ERROR_DINGTALK_REJECTED,
    NOTIFY_ERROR_USER_NOT_FOUND,
    NOTIFY_RECIPIENT_STATUS_FAILED,
    NOTIFY_RECIPIENT_STATUS_SENT,
    NOTIFY_TEMPLATE_TEXT,
    NotifyRecipient,
)
from easyauth.notify.services import NotifyAcceptError, accept_notify_message

pytestmark = pytest.mark.django_db

CORP_ID = "corp-quota"
SOURCE = "dingtalk-quota"


def _seed(authentik: str, dingtalk: str) -> None:
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


def test_daily_quota_exceeded_raises_throttled() -> None:
    app = App.objects.create(app_key="notify-quota", name="Quota")
    _ = AppCapability.objects.create(
        app=app,
        capability=CAPABILITY_NOTIFY,
        enabled=True,
        config={"daily_recipient_quota": 1},
    )
    _seed("q1", "dt-q1")
    _seed("q2", "dt-q2")

    first = accept_notify_message(
        app=app,
        recipients=["q1"],
        template=NOTIFY_TEMPLATE_TEXT,
        content="one",
        requested_credential_type=CREDENTIAL_TYPE_STATIC_TOKEN,
        requested_credential_id=1,
    )
    assert first.accepted is True

    with pytest.raises(NotifyAcceptError) as exc:
        _ = accept_notify_message(
            app=app,
            recipients=["q2"],
            template=NOTIFY_TEMPLATE_TEXT,
            content="two",
            requested_credential_type=CREDENTIAL_TYPE_STATIC_TOKEN,
            requested_credential_id=1,
        )
    assert exc.value.kind == "throttled"
    assert exc.value.retry_after_seconds is not None
    assert exc.value.retry_after_seconds >= 1


def test_idempotent_replay_recipient_rejected_only_accept_time_failures() -> None:
    """投递期失败不得混入幂等重放的 recipient_rejected(契约 §N2)。"""
    app = App.objects.create(app_key="notify-rej-count", name="Rej")
    _seed("r1", "dt-r1")

    first = accept_notify_message(
        app=app,
        recipients=["r1", "dt:missing-user"],
        template=NOTIFY_TEMPLATE_TEXT,
        content="same-payload",
        dedup_key="event:rej",
        requested_credential_type=CREDENTIAL_TYPE_STATIC_TOKEN,
        requested_credential_id=1,
    )
    assert first.accepted is True
    assert first.recipient_rejected == 1
    assert first.recipient_total == 2  # noqa: PLR2004

    # 模拟投递成功后再把另一收件人标为投递期失败。
    pending = NotifyRecipient.objects.get(
        message=first.message,
        status__in=("pending", "throttled"),
    )
    pending.status = NOTIFY_RECIPIENT_STATUS_SENT
    pending.dingtalk_task_id = "t1"
    pending.sent_at = timezone.now()
    pending.save()
    _ = NotifyRecipient.objects.create(
        message=first.message,
        raw_ref="extra-delivery-fail",
        dingtalk_userid="extra-fail",
        status=NOTIFY_RECIPIENT_STATUS_FAILED,
        error_code=NOTIFY_ERROR_DINGTALK_REJECTED,
        error="delivery fail",
    )
    # 上面 create 破坏了 total 语义, 仅用于计数过滤; 改为更新已有 accept 失败行之外的 sent 行。
    # 更干净: 直接把 sent 改成投递失败。
    pending.status = NOTIFY_RECIPIENT_STATUS_FAILED
    pending.error_code = NOTIFY_ERROR_DINGTALK_REJECTED
    pending.error = "delivery fail"
    pending.save()
    NotifyRecipient.objects.filter(raw_ref="extra-delivery-fail").delete()

    failed_all = NotifyRecipient.objects.filter(
        message=first.message,
        status=NOTIFY_RECIPIENT_STATUS_FAILED,
    ).count()
    assert failed_all == 2  # noqa: PLR2004 - 受理失败 1 + 投递失败 1

    second = accept_notify_message(
        app=app,
        recipients=["r1", "dt:missing-user"],
        template=NOTIFY_TEMPLATE_TEXT,
        content="same-payload",
        dedup_key="event:rej",
        requested_credential_type=CREDENTIAL_TYPE_STATIC_TOKEN,
        requested_credential_id=1,
    )
    assert second.accepted is False
    assert second.recipient_rejected == 1
    assert NotifyRecipient.objects.filter(
        message=first.message,
        error_code=NOTIFY_ERROR_USER_NOT_FOUND,
    ).count() == 1


def test_deeplink_title_persisted_and_in_payload_hash() -> None:
    app = App.objects.create(app_key="notify-deeplink-title", name="DL")
    _seed("d1", "dt-d1")

    first = accept_notify_message(
        app=app,
        recipients=["d1"],
        template="action_card",
        title="标题",
        content="正文",
        deeplink_url="https://example.com/x",
        deeplink_title="查看任务",
        dedup_key="dl:1",
        requested_credential_type=CREDENTIAL_TYPE_STATIC_TOKEN,
        requested_credential_id=1,
    )
    assert first.message.deeplink_title == "查看任务"

    # 同 dedup 但不同 deeplink_title → 冲突。
    with pytest.raises(NotifyAcceptError) as exc:
        _ = accept_notify_message(
            app=app,
            recipients=["d1"],
            template="action_card",
            title="标题",
            content="正文",
            deeplink_url="https://example.com/x",
            deeplink_title="另一按钮",
            dedup_key="dl:1",
            requested_credential_type=CREDENTIAL_TYPE_STATIC_TOKEN,
            requested_credential_id=1,
        )
    assert exc.value.kind == "conflict"
