"""分批执行期间的 API 汇总展示。"""

from __future__ import annotations

import pytest

from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App
from easyauth.lifecycle.api_payloads import aggregated_summary
from easyauth.lifecycle.models import (
    ACTION_STATUS_PREVIEWED,
    HANDOVER_KIND_OFFBOARD,
    HandoverAppAction,
    HandoverTask,
)

pytestmark = pytest.mark.django_db


def test_aggregated_summary_is_visible_during_partial_plan() -> None:
    subject = UserMirror.objects.create(authentik_user_id="summary-progress-subject")
    app = App.objects.create(app_key="summary-progress-app", name="汇总进度")
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
        generation=1,
        data_completed_at=None,
        result_summary={
            "customer": {
                "transferred": 4,
                "released": 0,
                "skipped": 6,
                "merged": 0,
                "failed": 0,
            },
        },
    )

    assert aggregated_summary(action) == action.result_summary
