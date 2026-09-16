from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from easyauth.accounts.models import DingTalkUserMirror, UserMirror
from easyauth.applications.integration_settings import IntegrationSettings
from easyauth.applications.models import App, AppNotificationChannel
from easyauth.integrations.dingtalk.api_client import (
    DingTalkApiRequestError,
    DingTalkRobotOtoResult,
)
from easyauth.notify.acceptance import (
    NotifyAcceptanceInput,
    NotifyCredentialInput,
    NotifyMessageInput,
    accept_notify_message,
)
from easyauth.notify.delivery import deliver_message
from easyauth.notify.models import (
    CREDENTIAL_TYPE_STATIC_TOKEN,
    NOTIFY_ERROR_DINGTALK_REJECTED,
    NOTIFY_MESSAGE_STATUS_COMPLETED,
    NOTIFY_MESSAGE_STATUS_FAILED,
    NOTIFY_RECIPIENT_STATUS_FAILED,
    NOTIFY_RECIPIENT_STATUS_SENT,
    NOTIFY_ROBOT_STATUS_FAILED,
    NOTIFY_ROBOT_STATUS_SENT,
    NotifyMessage,
    NotifyRecipient,
)

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("notification_channel_for_apps")]

CORP_ID = "corp-delivery"
SOURCE = "dingtalk-primary"


def _seed_user(*, authentik: str, dingtalk: str) -> None:
    _ = DingTalkUserMirror.objects.create(
        source_slug=SOURCE,
        corp_id=CORP_ID,
        user_id=dingtalk,
        name=dingtalk,
        status="active",
    )
    _ = UserMirror.objects.create(
        authentik_user_id=authentik,
        dingtalk_source_slug=SOURCE,
        dingtalk_userid=dingtalk,
        dingtalk_corp_id=CORP_ID,
    )


def _accept(app: App, recipients: list[str], *, deeplink_url: str = "") -> NotifyMessage:
    result = accept_notify_message(
        NotifyAcceptanceInput(
            app=app,
            message=NotifyMessageInput(
                title="课程提醒",
                content="请完成本周学习",
                recipients=tuple(recipients),
                author="张三",
                deeplink_url=deeplink_url,
            ),
            credential=NotifyCredentialInput(
                credential_type=CREDENTIAL_TYPE_STATIC_TOKEN,
                credential_id=1,
            ),
        ),
    )
    return result.message


def _robot_ok(user_ids: object) -> tuple[DingTalkRobotOtoResult, ...]:
    ids = tuple(str(item) for item in list(user_ids))  # type: ignore[arg-type]
    return (
        DingTalkRobotOtoResult(
            process_query_key="pqk-dual",
            user_ids=ids,
            invalid_staff_ids=frozenset(),
            flow_controlled_staff_ids=frozenset(),
        ),
    )


def _patch_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    work_side_effect: object | None = None,
    robot_side_effect: object | None = None,
) -> MagicMock:
    client = MagicMock()
    client.app_key = "svc-key"
    if work_side_effect is not None:
        client.send_work_notification.side_effect = work_side_effect
    else:
        client.send_work_notification.return_value = "task-oa"
    if robot_side_effect is not None:
        client.send_robot_oto_messages.side_effect = robot_side_effect
    else:

        def robot_ok(**kwargs: object) -> tuple[DingTalkRobotOtoResult, ...]:
            return _robot_ok(kwargs["user_ids"])

        client.send_robot_oto_messages.side_effect = robot_ok

    def fake_client_and_agent(_channel: AppNotificationChannel) -> tuple[MagicMock, int]:
        return client, 9001

    monkeypatch.setattr(
        "easyauth.notify.channel_config.dingtalk_client_and_agent",
        fake_client_and_agent,
    )
    return client


def test_delivery_records_work_notice_and_robot_independently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = App.objects.create(app_key="notify-robot-dual", name="学习工作台")
    _seed_user(authentik="r1", dingtalk="dt-r1")
    message = _accept(app, ["r1"], deeplink_url="https://learn.example.com/1")
    client = _patch_client(monkeypatch)

    deliver_message(str(message.id), 1)

    message.refresh_from_db()
    recipient = NotifyRecipient.objects.get(message=message)
    assert message.status == NOTIFY_MESSAGE_STATUS_COMPLETED
    assert recipient.status == NOTIFY_RECIPIENT_STATUS_SENT
    assert recipient.dingtalk_task_id == "task-oa"
    assert recipient.robot_status == NOTIFY_ROBOT_STATUS_SENT
    assert recipient.robot_process_query_key == "pqk-dual"
    assert recipient.robot_error is None
    client.send_work_notification.assert_called_once()
    client.send_robot_oto_messages.assert_called_once()
    robot_kwargs = client.send_robot_oto_messages.call_args.kwargs
    assert robot_kwargs["robot_code"] == "svc-key"
    assert robot_kwargs["user_ids"] == ("dt-r1",)
    assert robot_kwargs["title"] == "学习工作台 · 课程提醒"
    assert robot_kwargs["text"].startswith("### 学习工作台 · 课程提醒\n")
    assert "请完成本周学习" in robot_kwargs["text"]
    assert "来自 张三" in robot_kwargs["text"]
    assert robot_kwargs["single_url"] == "https://learn.example.com/1"


def test_oa_failure_does_not_mark_robot_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    app = App.objects.create(app_key="notify-robot-oa-fail", name="学习工作台")
    _seed_user(authentik="r2", dingtalk="dt-r2")
    message = _accept(app, ["r2"])
    _patch_client(
        monkeypatch,
        work_side_effect=DingTalkApiRequestError("permission denied", errcode=88),
    )

    deliver_message(str(message.id), 1)

    message.refresh_from_db()
    recipient = NotifyRecipient.objects.get(message=message)
    assert message.status == NOTIFY_MESSAGE_STATUS_FAILED
    assert recipient.status == NOTIFY_RECIPIENT_STATUS_FAILED
    assert recipient.error_code == NOTIFY_ERROR_DINGTALK_REJECTED
    assert recipient.robot_status == NOTIFY_ROBOT_STATUS_SENT
    assert recipient.robot_process_query_key == "pqk-dual"


def test_robot_failure_does_not_mark_work_notice_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = App.objects.create(app_key="notify-robot-fail", name="学习工作台")
    _seed_user(authentik="r3", dingtalk="dt-r3")
    message = _accept(app, ["r3"])
    _patch_client(
        monkeypatch,
        robot_side_effect=DingTalkApiRequestError("robot denied", status_code=403),
    )

    deliver_message(str(message.id), 1)

    message.refresh_from_db()
    recipient = NotifyRecipient.objects.get(message=message)
    assert message.status == NOTIFY_MESSAGE_STATUS_COMPLETED
    assert recipient.status == NOTIFY_RECIPIENT_STATUS_SENT
    assert recipient.error_code == ""
    assert recipient.robot_status == NOTIFY_ROBOT_STATUS_FAILED
    assert recipient.robot_process_query_key is None
    assert recipient.robot_error is not None
    assert "robot denied" in recipient.robot_error


def test_robot_switch_off_skips_robot_call(monkeypatch: pytest.MonkeyPatch) -> None:
    row = IntegrationSettings.load()
    row.dingtalk_notify_robot_enabled = False
    row.save(update_fields=["dingtalk_notify_robot_enabled", "updated_at"])
    app = App.objects.create(app_key="notify-robot-off", name="学习工作台")
    _seed_user(authentik="r4", dingtalk="dt-r4")
    message = _accept(app, ["r4"])
    client = _patch_client(monkeypatch)

    deliver_message(str(message.id), 1)

    message.refresh_from_db()
    recipient = NotifyRecipient.objects.get(message=message)
    assert message.status == NOTIFY_MESSAGE_STATUS_COMPLETED
    assert recipient.status == NOTIFY_RECIPIENT_STATUS_SENT
    assert recipient.robot_status is None
    assert recipient.robot_process_query_key is None
    assert recipient.robot_error is None
    client.send_work_notification.assert_called_once()
    client.send_robot_oto_messages.assert_not_called()
