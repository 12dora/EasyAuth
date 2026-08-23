"""Round 3.5: 控制台 async-abandon / items 端点级契约钉扎。"""

from __future__ import annotations

import json
from http import HTTPStatus
from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from django.test import Client

from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.applications.models import App
from easyauth.lifecycle.lease import take_lease
from easyauth.lifecycle.models import (
    ACTION_STATUS_ASYNC_ATTENTION_REQUIRED,
    ACTION_STATUS_FAILED,
    HANDOVER_KIND_OFFBOARD,
    HandoverAppAction,
    HandoverAssetType,
    HandoverExecutionLease,
    HandoverTask,
)
from easyauth.webhooks.hooks import HookCallError
from easyauth.webhooks.models import AppWebhookConfig
from tests.integration.admin_console.auth_helpers import authenticate_console_admin

pytestmark = pytest.mark.django_db

LOGIN_VALUE = "console-r35"


def _logged_in_superuser(username: str) -> Client:
    _ = User.objects.create_superuser(username=username, password=LOGIN_VALUE)
    client = Client(HTTP_HOST="localhost", raise_request_exception=False)
    _ = authenticate_console_admin(client, username)
    return client


def _attention_fixture(
    *,
    app_key: str,
    detail_supported: bool = False,
) -> tuple[UserMirror, App, HandoverTask, HandoverAppAction]:
    subject = UserMirror.objects.create(
        authentik_user_id=f"r35-{app_key}-sub",
        name="s",
        status=USER_STATUS_ACTIVE,
        dingtalk_source_slug="s",
        dingtalk_corp_id="c",
        dingtalk_userid=f"r35-{app_key}",
    )
    app = App.objects.create(
        app_key=app_key,
        name=app_key,
        handover_capability="declared",
        handover_asset_types=[
            {
                "type": "customer",
                "label": "客户",
                "detail_supported": detail_supported,
                "releasable": False,
            },
        ],
    )
    _ = AppWebhookConfig.objects.create(
        app=app,
        handover_url="https://example.test/handover",
        enabled=True,
        secret="whsec-r35",
    )
    task = HandoverTask.objects.create(
        kind=HANDOVER_KIND_OFFBOARD,
        subject_user=subject,
        assignee=subject,
        assignee_state="subject",
    )
    action = HandoverAppAction.objects.create(
        task=task,
        app=app,
        status=ACTION_STATUS_ASYNC_ATTENTION_REQUIRED,
        generation=1,
        app_key_snapshot=app.app_key,
        app_name_snapshot=app.name,
        snapshot_token="tok",
    )
    _ = HandoverAssetType.objects.create(
        action=action,
        generation=1,
        type_key="customer",
        label_snapshot="客户",
        count=10,
        default_action="skip",
        detail_supported=detail_supported,
    )
    return subject, app, task, action


@pytest.mark.parametrize(
    ("outcome", "expected_status"),
    [("failed", ACTION_STATUS_FAILED), ("done", "done")],
)
def test_console_async_abandon_endpoint_releases_lease(
    outcome: str,
    expected_status: str,
) -> None:
    client = _logged_in_superuser(f"r35-abandon-{outcome}")
    _subject, app, task, action = _attention_fixture(app_key=f"r35-aa-{outcome}")
    handle = take_lease(action=action, owner="async:1", batch_seq=1)
    lease = HandoverExecutionLease.objects.get(pk=handle.lease_id)
    assert lease.released_at is None

    resp = client.post(
        f"/console/api/v1/lifecycle/handover-tasks/{task.id}/actions/{app.app_key}/async-abandon",
        data=json.dumps(
            {
                "outcome": outcome,
                "reason": "下游确认不可恢复, 人工收口本应用",
                "summary": None,
            },
        ),
        content_type="application/json",
    )
    assert resp.status_code == HTTPStatus.OK, resp.content.decode()
    body = resp.json()
    assert body["action"]["status"] == expected_status
    lease.refresh_from_db()
    assert lease.released_at is not None


@pytest.mark.parametrize(
    ("status_code", "reason"),
    [(412, "snapshot_stale"), (423, "downstream_locked")],
)
def test_console_items_maps_hook_status_to_reason(status_code: int, reason: str) -> None:
    client = _logged_in_superuser(f"r35-items-{status_code}")
    _subject, app, task, action = _attention_fixture(
        app_key=f"r35-items-{status_code}",
        detail_supported=True,
    )
    action.status = "previewed"
    action.save(update_fields=["status", "updated_at"])

    with patch(
        "easyauth.lifecycle.handover_validation.signed_hook_post",
        side_effect=HookCallError(f"HTTP {status_code}", status_code=status_code),
    ):
        resp = client.get(
            f"/console/api/v1/lifecycle/handover-tasks/{task.id}/actions/{app.app_key}"
            f"/assets/customer/items",
        )
    assert resp.status_code == status_code, resp.content.decode()
    body = resp.json()
    assert body["error"]["details"]["reason"] == reason
