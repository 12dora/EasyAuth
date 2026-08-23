"""生命周期提醒跨 outbox 与 notify 受理边界的恢复测试。"""

from __future__ import annotations

import pytest
from celery.exceptions import Retry

from easyauth.accounts.models import USER_STATUS_ACTIVE, DingTalkUserMirror, UserMirror
from easyauth.applications.models import App, AppCredential, AppNotificationChannel
from easyauth.lifecycle.models import (
    ASSIGNEE_STATE_MANAGER,
    HANDOVER_KIND_OFFBOARD,
    TASK_STATUS_PENDING,
    HandoverTask,
)
from easyauth.notify.models import NotifyMessage
from easyauth.outbox.models import OUTBOX_STATUS_PUBLISHED, OutboxEvent
from easyauth.outbox.services import dispatch_pending_events, enqueue_task
from easyauth.tasks.lifecycle import LIFECYCLE_SEND_REMINDER_TASK, lifecycle_send_reminder_task

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def isolate_outbox_events() -> None:
    # transaction=True 的集成用例可能留下已提交事件。本模块只发布自身创建的事件。
    _ = OutboxEvent.objects.all().delete()


def test_missing_identity_retries_after_outbox_publish_then_provisioning_delivers() -> None:
    _ = DingTalkUserMirror.objects.create(
        source_slug="corp-main",
        corp_id="corp-1",
        user_id="manager-1",
        name="主管",
        status="active",
    )
    assignee = UserMirror.objects.create(
        authentik_user_id="reminder-recovery-assignee",
        name="主管",
        status=USER_STATUS_ACTIVE,
        dingtalk_source_slug="corp-main",
        dingtalk_corp_id="corp-1",
        dingtalk_userid="manager-1",
    )
    subject = UserMirror.objects.create(
        authentik_user_id="reminder-recovery-subject",
        name="员工",
        status=USER_STATUS_ACTIVE,
    )
    task = HandoverTask.objects.create(
        kind=HANDOVER_KIND_OFFBOARD,
        subject_user=subject,
        assignee=assignee,
        assignee_state=ASSIGNEE_STATE_MANAGER,
        status=TASK_STATUS_PENDING,
    )
    event = enqueue_task(
        event_key="reminder-recovery-boundary",
        task_name=LIFECYCLE_SEND_REMINDER_TASK,
        kwargs={
            "task_id": task.id,
            "kind": "daily",
            "assignee_user_id": assignee.authentik_user_id,
        },
    )

    published = dispatch_pending_events(send_task=lambda *_args, **_kwargs: object())
    event.refresh_from_db()
    assert published.published == 1
    assert event.status == OUTBOX_STATUS_PUBLISHED
    with pytest.raises(Retry):
        _ = lifecycle_send_reminder_task.apply(kwargs=event.kwargs, throw=True)

    identity = App.objects.create(app_key="easyauth-lifecycle", name="生命周期通知")
    _ = AppNotificationChannel.objects.create(
        app=identity,
        name="生命周期钉钉通道",
        dingtalk_app_key="ding-key",
        dingtalk_app_secret="ding-secret",
        agent_id="1001",
        directory_source_slug="corp-main",
        corp_id="corp-1",
        version=1,
    )
    credential = AppCredential.objects.create(
        app=identity,
        credential_type="static_token",
        name="生命周期内部凭据",
        capabilities=["notify"],
        token_hash="not-used-by-internal-task",
        token_lookup="0" * 64,
    )

    result = lifecycle_send_reminder_task.run(**event.kwargs)

    assert result == "accepted"
    message = NotifyMessage.objects.get(app=identity)
    assert message.requested_credential_id == credential.id
    assert message.recipient_total == 1
    assert OutboxEvent.objects.filter(event_key=f"notify-delivery:{message.id}:1").exists()
