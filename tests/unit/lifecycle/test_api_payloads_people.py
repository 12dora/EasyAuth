from __future__ import annotations

import pytest

from easyauth.accounts.models import UserMirror
from easyauth.accounts.person_payload import person_payload
from easyauth.audit.models import AuditLog
from easyauth.lifecycle.api_payloads import (
    console_task_list_item,
    handover_list_people,
    task_detail,
)
from easyauth.lifecycle.models import HANDOVER_KIND_OFFBOARD, HandoverTask

pytestmark = pytest.mark.django_db


def test_console_task_list_item_includes_created_by_person() -> None:
    creator = UserMirror.objects.create(
        authentik_user_id="payload-created-by",
        name="建单人",
        department="安环部",
    )
    subject = UserMirror.objects.create(authentik_user_id="payload-subject", name="当事人")
    task = HandoverTask.objects.create(
        kind=HANDOVER_KIND_OFFBOARD,
        subject_user=subject,
        created_by=creator.authentik_user_id,
    )
    people, labels = handover_list_people((task,))
    item = console_task_list_item(task, department_labels=labels, people=people)

    assert item["created_by"] == creator.authentik_user_id
    assert item["created_by_person"] == person_payload(creator, labels)


def test_console_task_list_item_created_by_person_is_null_for_system_actor() -> None:
    subject = UserMirror.objects.create(authentik_user_id="payload-system-subject")
    task = HandoverTask.objects.create(
        kind=HANDOVER_KIND_OFFBOARD,
        subject_user=subject,
        created_by="directory_sync",
    )
    people, labels = handover_list_people((task,))
    item = console_task_list_item(task, department_labels=labels, people=people)

    assert item["created_by"] == "directory_sync"
    assert item["created_by_person"] is None


def test_task_detail_defer_history_includes_actor_person() -> None:
    creator = UserMirror.objects.create(
        authentik_user_id="payload-detail-creator",
        name="建单人",
    )
    actor = UserMirror.objects.create(
        authentik_user_id="payload-detail-actor",
        name="顺延人",
        department="研发部",
    )
    subject = UserMirror.objects.create(authentik_user_id="payload-detail-subject")
    task = HandoverTask.objects.create(
        kind=HANDOVER_KIND_OFFBOARD,
        subject_user=subject,
        created_by=creator.authentik_user_id,
    )
    _ = AuditLog.objects.create(
        actor_type="admin",
        actor_id=actor.authentik_user_id,
        event_type="handover_task_deferred",
        target_type="handover_task",
        target_id=str(task.id),
        metadata={"reason": "出差", "escalation_level": 1},
    )
    _ = AuditLog.objects.create(
        actor_type="system",
        actor_id="directory_sync",
        event_type="handover_task_deferred",
        target_type="handover_task",
        target_id=str(task.id),
        metadata={"reason": "系统顺延", "escalation_level": 2},
    )

    detail = task_detail(task)
    history = detail["escalation"]["defer_history"]

    assert detail["created_by"] == creator.authentik_user_id
    assert detail["created_by_person"] == person_payload(creator, {})
    assert history[0]["actor_id"] == actor.authentik_user_id
    assert history[0]["actor_person"] == person_payload(actor, {})
    assert history[0]["reason"] == "出差"
    assert history[1]["actor_id"] == "directory_sync"
    assert history[1]["actor_person"] is None
