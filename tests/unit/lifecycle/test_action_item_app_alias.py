from __future__ import annotations

import pytest

from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App
from easyauth.lifecycle.api_payloads import action_item
from easyauth.lifecycle.models import (
    ACTION_STATUS_PREVIEWED,
    HANDOVER_KIND_OFFBOARD,
    HandoverAppAction,
    HandoverTask,
)

pytestmark = pytest.mark.django_db


def test_action_item_reads_app_alias_live_from_app() -> None:
    subject = UserMirror.objects.create(authentik_user_id="alias-action-subject")
    app = App.objects.create(app_key="alias-action-app", name="EasyCustoms", alias="海关数据")
    task = HandoverTask.objects.create(
        kind=HANDOVER_KIND_OFFBOARD,
        subject_user=subject,
        assignee=subject,
        assignee_state="subject",
    )
    action = HandoverAppAction.objects.create(
        task=task,
        app=app,
        status=ACTION_STATUS_PREVIEWED,
        app_key_snapshot=app.app_key,
        app_name_snapshot="快照名",
    )

    payload = action_item(action)
    assert payload["app_name"] == "快照名"
    assert payload["app_alias"] == "海关数据"

    app.alias = "新别名"
    app.save(update_fields=["alias", "updated_at"])
    action.refresh_from_db()
    updated = action_item(action)
    assert updated["app_alias"] == "新别名"
