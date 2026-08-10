"""pre_offboard → offboard 升级(01 §5.1.2 / 00 §8.3)。"""

from __future__ import annotations

import pytest
from django.utils import timezone

from easyauth.accounts.models import USER_STATUS_ACTIVE, USER_STATUS_DEPARTED, UserMirror
from easyauth.applications.models import App
from easyauth.lifecycle.errors import HandoverConflictError
from easyauth.lifecycle.models import (
    ACTION_STATUS_BLOCKED,
    ACTION_STATUS_PENDING,
    ACTION_STATUS_SKIPPED,
    HANDOVER_KIND_OFFBOARD,
    HANDOVER_KIND_PRE_OFFBOARD,
    HandoverAppAction,
    HandoverTask,
)
from easyauth.lifecycle.offboarding import ensure_handover_task, upgrade_pre_offboard_to_offboard
from easyauth.webhooks.models import AppWebhookConfig

pytestmark = pytest.mark.django_db


def _subject(uid: str = "up-sub") -> UserMirror:
    return UserMirror.objects.create(
        authentik_user_id=uid,
        name=uid,
        status=USER_STATUS_ACTIVE,
        dingtalk_source_slug="src",
        dingtalk_corp_id="corp",
        dingtalk_userid=uid,
    )


def _app(key: str, *, capability: str = "declared") -> App:
    app = App.objects.create(
        app_key=key,
        name=key,
        handover_capability=capability,
        handover_asset_types=[
            {"type": "customer", "label": "客户", "detail_supported": False, "releasable": False},
        ]
        if capability == "declared"
        else [],
    )
    if capability == "declared":
        _ = AppWebhookConfig.objects.create(
            app=app,
            handover_url="https://example.test/handover",
            enabled=True,
        )
    return app


def test_upgrade_pre_offboard_to_offboard_resets_fields() -> None:
    subject = _subject()
    app = _app("easytrade")
    task, created = ensure_handover_task(
        subject=subject,
        kind=HANDOVER_KIND_PRE_OFFBOARD,
        created_by=subject.authentik_user_id,
        reason="提前交接测试",
        app_keys=(app.app_key,),
    )
    assert created
    action = HandoverAppAction.objects.get(task=task, app=app)
    action.data_completed_at = timezone.now()
    action.snapshot_token = "old-token"
    action.batch_seq = 3
    action.last_error = "old"
    action.last_error_raw = "raw"
    action.attempts = 5
    action.status = ACTION_STATUS_SKIPPED
    action.skip_reason = "admin skip"
    action.skipped_by = "admin"
    action.skipped_at = timezone.now()
    action.save()
    old_confirm = action.confirm_version
    old_gen = task.generation

    upgraded = upgrade_pre_offboard_to_offboard(
        task,
        created_by="directory_sync",
        reason="目录同步检出离职",
    )
    assert upgraded.kind == HANDOVER_KIND_OFFBOARD
    assert upgraded.generation == old_gen + 1

    action.refresh_from_db()
    assert action.generation == upgraded.generation
    assert action.data_completed_at is None
    assert action.snapshot_token == ""
    assert action.batch_seq == 0
    assert action.last_error == ""
    assert action.attempts == 0
    assert action.confirm_version == old_confirm + 1
    # 超管 skip 不继承 → declared 回到 pending
    assert action.status == ACTION_STATUS_PENDING


def test_upgrade_blocked_stays_blocked_not_skipped() -> None:
    subject = _subject("up-sub-2")
    app = _app("blocked-app", capability="undeclared")
    task, _ = ensure_handover_task(
        subject=subject,
        kind=HANDOVER_KIND_PRE_OFFBOARD,
        created_by=subject.authentik_user_id,
        app_keys=(app.app_key,),
    )
    action = HandoverAppAction.objects.get(task=task, app=app)
    action.status = ACTION_STATUS_SKIPPED
    action.skip_reason = "force"
    action.skipped_by = "admin"
    action.skipped_at = timezone.now()
    action.save()

    _ = upgrade_pre_offboard_to_offboard(task, created_by="directory_sync")
    action.refresh_from_db()
    assert action.status == ACTION_STATUS_BLOCKED


def test_ensure_offboard_upgrades_open_pre_offboard() -> None:
    subject = _subject("up-sub-3")
    _ = _app("et")
    task, _ = ensure_handover_task(
        subject=subject,
        kind=HANDOVER_KIND_PRE_OFFBOARD,
        created_by=subject.authentik_user_id,
    )
    assert task.kind == HANDOVER_KIND_PRE_OFFBOARD
    gen = task.generation

    subject.status = USER_STATUS_DEPARTED
    subject.save(update_fields=["status"])

    upgraded, created = ensure_handover_task(
        subject=subject,
        kind=HANDOVER_KIND_OFFBOARD,
        created_by="directory_sync",
        reason="目录同步检出离职",
    )
    assert created is False
    assert upgraded.pk == task.pk
    assert upgraded.kind == HANDOVER_KIND_OFFBOARD
    assert upgraded.generation == gen + 1
