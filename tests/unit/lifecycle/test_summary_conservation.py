"""下游 execute summary 五元组守恒(00 §10.5)。"""

from __future__ import annotations

import pytest

from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.applications.models import App
from easyauth.lifecycle.handover_validation import validate_execute_summary_conservation
from easyauth.lifecycle.models import (
    HANDOVER_KIND_OFFBOARD,
    HandoverAppAction,
    HandoverAssetType,
    HandoverTask,
)

pytestmark = pytest.mark.django_db


def _action_with_type(*, count: int = 10) -> HandoverAppAction:
    subject = UserMirror.objects.create(
        authentik_user_id="sum-sub",
        name="s",
        status=USER_STATUS_ACTIVE,
    )
    app = App.objects.create(app_key="sum-app", name="sum")
    task = HandoverTask.objects.create(
        kind=HANDOVER_KIND_OFFBOARD,
        subject_user=subject,
        assignee=subject,
        assignee_state="subject",
    )
    action = HandoverAppAction.objects.create(
        task=task,
        app=app,
        status="previewed",
        generation=1,
    )
    _ = HandoverAssetType.objects.create(
        action=action,
        generation=1,
        type_key="customer",
        label_snapshot="客户",
        count=count,
        default_action="skip",
    )
    return action


def test_conservation_ok() -> None:
    action = _action_with_type(count=10)
    err = validate_execute_summary_conservation(
        action,
        response_payload={
            "summary": {
                "customer": {
                    "transferred": 7,
                    "released": 1,
                    "skipped": 2,
                    "merged": 0,
                    "failed": 0,
                },
            },
        },
    )
    assert err is None


def test_conservation_mismatch_fails() -> None:
    action = _action_with_type(count=10)
    err = validate_execute_summary_conservation(
        action,
        response_payload={
            "summary": {
                "customer": {
                    "transferred": 5,
                    "released": 0,
                    "skipped": 0,
                    "merged": 0,
                    "failed": 0,
                },
            },
        },
    )
    assert err is not None
    assert "不守恒" in err


def test_conservation_failed_gt_zero() -> None:
    action = _action_with_type(count=10)
    err = validate_execute_summary_conservation(
        action,
        response_payload={
            "summary": {
                "customer": {
                    "transferred": 9,
                    "released": 0,
                    "skipped": 0,
                    "merged": 0,
                    "failed": 1,
                },
            },
        },
    )
    assert err is not None
    assert "failed" in err


def test_conservation_missing_type() -> None:
    action = _action_with_type(count=3)
    err = validate_execute_summary_conservation(
        action,
        response_payload={"summary": {}},
    )
    assert err is not None
    assert "缺少" in err


@pytest.mark.parametrize(
    "row",
    [
        {"transferred": 10},
        {
            "transferred": 10,
            "released": 0,
            "skipped": 0,
            "merged": 0,
            "failed": False,
        },
        {
            "transferred": 10,
            "released": 0,
            "skipped": 0,
            "merged": 0,
            "failed": 0,
            "succeeded": 10,
        },
    ],
)
def test_conservation_requires_exact_integer_five_tuple(row: dict[str, object]) -> None:
    action = _action_with_type(count=10)

    err = validate_execute_summary_conservation(
        action,
        response_payload={"summary": {"customer": row}},  # type: ignore[dict-item]
    )

    assert err is not None
