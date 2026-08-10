"""门户交接 API 权限边界与 reason 字符串(01 §6.1 / §10)。"""

from __future__ import annotations

import json

import pytest
from django.test import Client

from easyauth.accounts.auth import AUTHENTIK_SESSION_KEY
from easyauth.accounts.local_admin import LOCAL_ADMIN_SUBJECT_PREFIX
from easyauth.accounts.models import (
    USER_STATUS_ACTIVE,
    DingTalkUserOrgContext,
    UserMirror,
)
from easyauth.applications.models import App
from easyauth.lifecycle.models import (
    HANDOVER_KIND_PRE_OFFBOARD,
    HandoverAppAction,
    HandoverTask,
)
from easyauth.lifecycle.offboarding import ensure_handover_task
from easyauth.webhooks.models import AppWebhookConfig

pytestmark = pytest.mark.django_db

SOURCE = "src-p"
CORP = "corp-p"


def _user(uid: str, *, dtuid: str | None = None) -> UserMirror:
    return UserMirror.objects.create(
        authentik_user_id=uid,
        name=uid,
        status=USER_STATUS_ACTIVE,
        dingtalk_source_slug=SOURCE,
        dingtalk_corp_id=CORP,
        dingtalk_userid=dtuid or uid,
    )


def _login(client: Client, user: UserMirror) -> Client:
    session = client.session
    session[AUTHENTIK_SESSION_KEY] = user.authentik_user_id
    session.save()
    return client


def test_local_admin_forbidden_on_portal_handover() -> None:
    admin = UserMirror.objects.create(
        authentik_user_id=f"{LOCAL_ADMIN_SUBJECT_PREFIX}root",
        name="admin",
        status=USER_STATUS_ACTIVE,
    )
    client = _login(Client(), admin)
    resp = client.get("/portal/api/v1/me/handover-tasks")
    assert resp.status_code == 403


def test_me_handover_tasks_envelope() -> None:
    user = _user("portal-me")
    client = _login(Client(), user)
    resp = client.get("/portal/api/v1/me/handover-tasks")
    assert resp.status_code == 200
    body = resp.json()
    assert "handover_tasks" in body
    assert "as_assignee" in body["handover_tasks"]
    assert "as_subject" in body["handover_tasks"]


def test_non_assignee_gets_404_on_detail() -> None:
    subject = _user("subj-a", dtuid="sa")
    other = _user("other-a", dtuid="oa")
    app = App.objects.create(
        app_key="pa",
        name="pa",
        handover_capability="declared",
        handover_asset_types=[
            {"type": "t", "label": "t", "detail_supported": False, "releasable": False},
        ],
    )
    _ = AppWebhookConfig.objects.create(
        app=app,
        handover_url="https://example.test/h",
        enabled=True,
    )
    task, _ = ensure_handover_task(
        subject=subject,
        kind=HANDOVER_KIND_PRE_OFFBOARD,
        created_by=subject.authentik_user_id,
        app_keys=(app.app_key,),
    )
    client = _login(Client(), other)
    resp = client.get(f"/portal/api/v1/handover-tasks/{task.id}")
    assert resp.status_code == 404


def test_candidates_purpose_required() -> None:
    user = _user("cand-u")
    client = _login(Client(), user)
    resp = client.get("/portal/api/v1/handover-candidates")
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["details"]["reason"] == "purpose_required"


def test_reassign_out_of_scope() -> None:
    actor = _user("mgr-x", dtuid="mx")
    stranger = _user("str-x", dtuid="sx")
    # stranger 的链里没有 actor
    _ = DingTalkUserOrgContext.objects.create(
        source_slug=SOURCE,
        corp_id=CORP,
        user_id="sx",
        manager_chain=[{"user_id": "someone-else"}],
        stale=False,
    )
    client = _login(Client(), actor)
    resp = client.post(
        "/portal/api/v1/handover-tasks/reassign",
        data=json.dumps(
            {
                "subject_user_id": stranger.authentik_user_id,
                "app_keys": ["any"],
                "reason": "这是超过十字的理由文字",
            },
        ),
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="idem-1",
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["details"]["reason"] == "out_of_managed_scope"


def test_pre_offboard_requires_idempotency_key() -> None:
    user = _user("pre-u")
    client = _login(Client(), user)
    resp = client.post(
        "/portal/api/v1/handover-tasks/pre-offboard",
        data=json.dumps({"reason": "test"}),
        content_type="application/json",
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["details"]["reason"] == "idempotency_key_required"


def test_pre_offboard_creates_task() -> None:
    user = _user("pre-ok")
    client = _login(Client(), user)
    resp = client.post(
        "/portal/api/v1/handover-tasks/pre-offboard",
        data=json.dumps({"reason": "提前交接准备"}),
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="pre-1",
    )
    assert resp.status_code == 201
    body = resp.json()
    assert "handover_task" in body
    assert body["handover_task"]["kind"] == "pre_offboard"
    assert body["handover_task"]["assignee"]["user_id"] == user.authentik_user_id


def test_action_blocked_on_preview() -> None:
    subject = _user("blk-s", dtuid="bs")
    app = App.objects.create(
        app_key="blk",
        name="blk",
        handover_capability="undeclared",
    )
    task, _ = ensure_handover_task(
        subject=subject,
        kind=HANDOVER_KIND_PRE_OFFBOARD,
        created_by=subject.authentik_user_id,
        app_keys=(app.app_key,),
    )
    action = HandoverAppAction.objects.get(task=task, app=app)
    assert action.status == "blocked"
    client = _login(Client(), subject)
    resp = client.post(
        f"/portal/api/v1/handover-tasks/{task.id}/actions/blk/preview",
        content_type="application/json",
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["details"]["reason"] == "action_blocked"
