from __future__ import annotations

import pytest

from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App
from easyauth.lifecycle.core import refresh_task_status
from easyauth.lifecycle.models import (
    ACTION_STATUS_BLOCKED,
    ACTION_STATUS_DONE,
    ACTION_STATUS_SKIPPED,
    HANDOVER_KIND_OFFBOARD,
    TASK_STATUS_COMPLETED,
    TASK_STATUS_IN_PROGRESS,
    TASK_STATUS_PENDING,
    HandoverAppAction,
    HandoverTask,
)
from easyauth.lifecycle.task_status import compute_task_status

pytestmark = pytest.mark.django_db


def test_blocked_action_prevents_task_completion() -> None:
    subject = UserMirror.objects.create(authentik_user_id="b-sub", name="b")
    app_ok = App.objects.create(app_key="ok-app", name="ok")
    app_block = App.objects.create(app_key="block-app", name="block")
    task = HandoverTask.objects.create(
        kind=HANDOVER_KIND_OFFBOARD,
        subject_user=subject,
        created_by="admin",
    )
    _ = HandoverAppAction.objects.create(
        task=task,
        app=app_ok,
        status=ACTION_STATUS_DONE,
        generation=1,
    )
    _ = HandoverAppAction.objects.create(
        task=task,
        app=app_block,
        status=ACTION_STATUS_BLOCKED,
        blocked_reason="capability_undeclared",
        generation=1,
    )
    refreshed = refresh_task_status(task)
    assert refreshed.status != TASK_STATUS_COMPLETED
    # 已有 done 则 in_progress, 但 blocked 阻止 completed(D13)
    nxt = compute_task_status(task, list(task.app_actions.all()), [], plan_confirmed=True)
    assert nxt == TASK_STATUS_IN_PROGRESS


def test_all_skipped_or_done_completes() -> None:
    subject = UserMirror.objects.create(authentik_user_id="c-sub", name="c")
    app_a = App.objects.create(app_key="a-app", name="a")
    app_b = App.objects.create(app_key="b-app", name="b")
    task = HandoverTask.objects.create(
        kind=HANDOVER_KIND_OFFBOARD,
        subject_user=subject,
        created_by="admin",
    )
    _ = HandoverAppAction.objects.create(
        task=task,
        app=app_a,
        status=ACTION_STATUS_DONE,
        generation=1,
    )
    _ = HandoverAppAction.objects.create(
        task=task,
        app=app_b,
        status=ACTION_STATUS_SKIPPED,
        generation=1,
    )
    refreshed = refresh_task_status(task)
    assert refreshed.status == TASK_STATUS_COMPLETED


def test_only_blocked_stays_pending_not_in_progress() -> None:
    subject = UserMirror.objects.create(authentik_user_id="d-sub", name="d")
    app = App.objects.create(app_key="only-block", name="ob")
    task = HandoverTask.objects.create(
        kind=HANDOVER_KIND_OFFBOARD,
        subject_user=subject,
        created_by="admin",
    )
    _ = HandoverAppAction.objects.create(
        task=task,
        app=app,
        status=ACTION_STATUS_BLOCKED,
        generation=1,
    )
    refreshed = refresh_task_status(task)
    assert refreshed.status == TASK_STATUS_PENDING
