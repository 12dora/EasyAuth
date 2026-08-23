"""Round 3.5: 门户 items 端点 412/423 映射。"""

from __future__ import annotations

from http import HTTPStatus
from unittest.mock import patch

import pytest
from django.test import Client

from easyauth.accounts.auth import AUTHENTIK_SESSION_KEY
from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.applications.models import App
from easyauth.lifecycle.models import (
    HANDOVER_KIND_OFFBOARD,
    HandoverAppAction,
    HandoverAssetType,
    HandoverTask,
)
from easyauth.webhooks.hooks import HookCallError
from easyauth.webhooks.models import AppWebhookConfig

pytestmark = pytest.mark.django_db


def _login(client: Client, user: UserMirror) -> Client:
    session = client.session
    session[AUTHENTIK_SESSION_KEY] = user.authentik_user_id
    session.save()
    return client


@pytest.mark.parametrize(
    ("status_code", "reason"),
    [(412, "snapshot_stale"), (423, "downstream_locked")],
)
def test_portal_items_maps_hook_status_to_reason(status_code: int, reason: str) -> None:
    assignee = UserMirror.objects.create(
        authentik_user_id=f"portal-items-{status_code}",
        name="a",
        status=USER_STATUS_ACTIVE,
        dingtalk_source_slug="s",
        dingtalk_corp_id="c",
        dingtalk_userid=f"pi{status_code}",
    )
    subject = UserMirror.objects.create(
        authentik_user_id=f"portal-items-sub-{status_code}",
        name="s",
        status=USER_STATUS_ACTIVE,
        dingtalk_source_slug="s",
        dingtalk_corp_id="c",
        dingtalk_userid=f"ps{status_code}",
    )
    app = App.objects.create(
        app_key=f"portal-items-{status_code}",
        name="p",
        handover_capability="declared",
        handover_asset_types=[
            {
                "type": "customer",
                "label": "客户",
                "detail_supported": True,
                "releasable": False,
            },
        ],
    )
    _ = AppWebhookConfig.objects.create(
        app=app,
        handover_url="https://example.test/h",
        enabled=True,
        secret="whsec",
    )
    task = HandoverTask.objects.create(
        kind=HANDOVER_KIND_OFFBOARD,
        subject_user=subject,
        assignee=assignee,
        assignee_state="manager",
    )
    action = HandoverAppAction.objects.create(
        task=task,
        app=app,
        status="previewed",
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
        count=5,
        default_action="skip",
        detail_supported=True,
    )
    client = _login(Client(), assignee)
    with patch(
        "easyauth.lifecycle.handover_validation.signed_hook_post",
        side_effect=HookCallError(f"HTTP {status_code}", status_code=status_code),
    ):
        resp = client.get(
            f"/portal/api/v1/handover-tasks/{task.id}/actions/{app.app_key}"
            f"/assets/customer/items",
        )
    assert resp.status_code == status_code, resp.content.decode()
    body = resp.json()
    assert body["error"]["details"]["reason"] == reason
    assert resp.status_code != HTTPStatus.INTERNAL_SERVER_ERROR
