"""门户交接 API 权限边界与 reason 字符串(01 §6.1 / §10)。"""

from __future__ import annotations

import json

import pytest
from django.db import connection
from django.test import Client

from easyauth.accounts.auth import AUTHENTIK_SESSION_KEY
from easyauth.accounts.local_admin import LOCAL_ADMIN_SUBJECT_PREFIX
from easyauth.accounts.models import (
    USER_STATUS_ACTIVE,
    DingTalkUserOrgContext,
    UserMirror,
)
from easyauth.applications.models import App
from easyauth.audit.models import AuditLog
from easyauth.lifecycle.jurisdiction import JurisdictionResult
from easyauth.lifecycle.models import (
    ASSIGNEE_STATE_MANAGER,
    HANDOVER_KIND_OFFBOARD,
    HANDOVER_KIND_PRE_OFFBOARD,
    HANDOVER_KIND_REASSIGN,
    HandoverAppAction,
    HandoverAssetOverride,
    HandoverAssetType,
    HandoverTask,
)
from easyauth.lifecycle.offboarding import HandoverCreationSpec, ensure_handover_task
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


def _assigned_action(
    actor: UserMirror,
    subject: UserMirror,
    *,
    app_key: str,
    kind: str = HANDOVER_KIND_OFFBOARD,
) -> tuple[HandoverTask, HandoverAppAction, HandoverAssetType]:
    app = App.objects.create(
        app_key=app_key,
        name=app_key,
        handover_capability="declared",
    )
    task = HandoverTask.objects.create(
        kind=kind,
        subject_user=subject,
        assignee=actor,
        assignee_state=ASSIGNEE_STATE_MANAGER,
        authority_source="manager_chain",
    )
    action = HandoverAppAction.objects.create(
        task=task,
        app=app,
        app_key_snapshot=app.app_key,
        app_name_snapshot=app.name,
    )
    asset = HandoverAssetType.objects.create(
        action=action,
        generation=action.generation,
        type_key="customer",
        label_snapshot="客户",
        detail_supported=True,
        releasable=True,
    )
    return task, action, asset


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
        spec=HandoverCreationSpec(app_keys=(app.app_key,)),
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


def test_pre_offboard_idempotent_replay_still_returns_created() -> None:
    user = _user("pre-replay")
    client = _login(Client(), user)
    request = {
        "path": "/portal/api/v1/handover-tasks/pre-offboard",
        "data": json.dumps({"reason": "提前交接准备"}),
        "content_type": "application/json",
        "HTTP_IDEMPOTENCY_KEY": "pre-replay-key",
    }

    first = client.post(**request)
    replay = client.post(**request)

    assert first.status_code == 201
    assert replay.status_code == 201
    assert replay.json()["handover_task"]["id"] == first.json()["handover_task"]["id"]


def test_reassign_creation_assigns_initiator_in_original_transaction() -> None:
    direct_manager = _user("reassign-direct", dtuid="direct")
    initiator = _user("reassign-upper", dtuid="upper")
    subject = _user("reassign-subject", dtuid="subject")
    _ = DingTalkUserOrgContext.objects.create(
        source_slug=SOURCE,
        corp_id=CORP,
        user_id=subject.dingtalk_userid,
        manager_chain=[{"user_id": "direct"}, {"user_id": "upper"}],
        stale=False,
    )
    _ = App.objects.create(app_key="reassign-create-app", name="在职移交应用")
    client = _login(Client(), initiator)

    response = client.post(
        "/portal/api/v1/handover-tasks/reassign",
        data=json.dumps(
            {
                "subject_user_id": subject.authentik_user_id,
                "app_keys": ["reassign-create-app"],
                "reason": "这是足够十个字符的在职移交理由",
            },
        ),
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="reassign-create-key",
    )

    assert response.status_code == 201
    task = HandoverTask.objects.get(pk=response.json()["handover_task"]["id"])
    assert task.assignee_id == initiator.pk
    assert task.assignee_id != direct_manager.pk
    assignee_events = AuditLog.objects.filter(
        target_type="handover_task",
        target_id=str(task.pk),
        event_type="handover_assignee_assigned",
    )
    assert assignee_events.count() == 1
    assert assignee_events.get().metadata["assignee_user_id"] == initiator.authentik_user_id

    replay = client.post(
        "/portal/api/v1/handover-tasks/reassign",
        data=json.dumps(
            {
                "subject_user_id": subject.authentik_user_id,
                "app_keys": ["reassign-create-app"],
                "reason": "这是足够十个字符的在职移交理由",
            },
        ),
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="reassign-create-key",
    )
    assert replay.status_code == 201
    assert replay.json()["handover_task"]["id"] == task.pk


def test_put_overrides_rejects_duplicate_without_erasing_existing_set() -> None:
    actor = _user("override-actor")
    subject = _user("override-subject")
    task, action, asset = _assigned_action(actor, subject, app_key="override-duplicate")
    _ = HandoverAssetOverride.objects.create(
        asset_type=asset,
        asset_id="existing",
        action="skip",
    )
    client = _login(Client(), actor)

    response = client.put(
        f"/portal/api/v1/handover-tasks/{task.pk}/actions/{action.app.app_key}"
        "/assets/customer/overrides",
        data=json.dumps(
            {
                "overrides_version": 0,
                "overrides": [
                    {"asset_id": "same", "action": "skip"},
                    {"asset_id": "same", "action": "skip"},
                ],
            },
        ),
        content_type="application/json",
    )

    assert response.status_code == 422
    assert response.json()["error"]["details"]["reason"] == "duplicate_assignment"
    assert list(asset.overrides.values_list("asset_id", flat=True)) == ["existing"]
    action.refresh_from_db()
    assert action.overrides_version == 0


def test_put_overrides_rejects_unknown_action_without_erasing_existing_set() -> None:
    actor = _user("override-action-actor")
    subject = _user("override-action-subject")
    task, action, asset = _assigned_action(actor, subject, app_key="override-action")
    _ = HandoverAssetOverride.objects.create(
        asset_type=asset,
        asset_id="existing",
        action="skip",
    )
    client = _login(Client(), actor)

    response = client.put(
        f"/portal/api/v1/handover-tasks/{task.pk}/actions/{action.app.app_key}"
        "/assets/customer/overrides",
        data=json.dumps(
            {
                "overrides_version": 0,
                "overrides": [{"asset_id": "new", "action": "garbage"}],
            },
        ),
        content_type="application/json",
    )

    assert response.status_code == 422
    assert list(asset.overrides.values_list("asset_id", flat=True)) == ["existing"]
    action.refresh_from_db()
    assert action.overrides_version == 0


def test_grant_receiver_patch_requires_explicit_field() -> None:
    actor = _user("grant-actor")
    subject = _user("grant-subject")
    receiver = _user("grant-receiver")
    task, action, _asset = _assigned_action(actor, subject, app_key="grant-required")
    action.grant_receiver = receiver
    action.confirm_version = 3
    action.save(update_fields=["grant_receiver", "confirm_version"])
    client = _login(Client(), actor)

    response = client.patch(
        f"/portal/api/v1/handover-tasks/{task.pk}/actions/{action.app.app_key}",
        data=json.dumps({}),
        content_type="application/json",
    )

    assert response.status_code == 422
    action.refresh_from_db()
    assert action.grant_receiver_id == receiver.pk
    assert action.confirm_version == 3


def test_malformed_items_page_is_rejected_before_downstream_dispatch() -> None:
    actor = _user("page-actor")
    subject = _user("page-subject")
    task, action, _asset = _assigned_action(actor, subject, app_key="items-page")
    client = _login(Client(), actor)

    response = client.get(
        f"/portal/api/v1/handover-tasks/{task.pk}/actions/{action.app.app_key}"
        "/assets/customer/items?page=abc",
    )

    assert response.status_code == 422
    assert response.json()["error"]["details"]["reason"] == "items_page_out_of_range"


def test_reassign_mutation_rechecks_jurisdiction_inside_lock_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor = _user("tx-manager", dtuid="tx-manager")
    subject = _user("tx-subject", dtuid="tx-subject")
    _ = DingTalkUserOrgContext.objects.create(
        source_slug=SOURCE,
        corp_id=CORP,
        user_id=subject.dingtalk_userid,
        manager_chain=[{"user_id": actor.dingtalk_userid}],
        stale=False,
    )
    task, action, _asset = _assigned_action(
        actor,
        subject,
        app_key="tx-jurisdiction",
        kind=HANDOVER_KIND_REASSIGN,
    )
    observed_atomic: list[bool] = []

    def observe_jurisdiction(
        checked_actor: UserMirror,
        checked_subject: UserMirror,
        *,
        lock_context: bool = False,
    ) -> JurisdictionResult:
        assert checked_actor.pk == actor.pk
        assert checked_subject.pk == subject.pk
        observed_atomic.append(connection.in_atomic_block and lock_context)
        return JurisdictionResult(allowed=True)

    monkeypatch.setattr(
        "easyauth.portal.handover_api.assert_manager_of",
        observe_jurisdiction,
    )
    client = _login(Client(), actor)
    response = client.patch(
        f"/portal/api/v1/handover-tasks/{task.pk}/actions/{action.app.app_key}/assets/customer",
        data=json.dumps({"default_action": "skip", "default_to_user_id": None}),
        content_type="application/json",
    )

    assert response.status_code == 200
    assert observed_atomic == [True]


def test_reassign_operation_rechecks_jurisdiction_in_reservation_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor = _user("operation-manager", dtuid="operation-manager")
    subject = _user("operation-subject", dtuid="operation-subject")
    _ = DingTalkUserOrgContext.objects.create(
        source_slug=SOURCE,
        corp_id=CORP,
        user_id=subject.dingtalk_userid,
        manager_chain=[{"user_id": actor.dingtalk_userid}],
        stale=False,
    )
    task, action, _asset = _assigned_action(
        actor,
        subject,
        app_key="operation-jurisdiction",
        kind=HANDOVER_KIND_REASSIGN,
    )
    observed_atomic: list[bool] = []

    def observe_jurisdiction(
        checked_actor: UserMirror,
        checked_subject: UserMirror,
        *,
        lock_context: bool = False,
    ) -> JurisdictionResult:
        assert checked_actor.pk == actor.pk
        assert checked_subject.pk == subject.pk
        observed_atomic.append(connection.in_atomic_block and lock_context)
        return JurisdictionResult(allowed=True)

    monkeypatch.setattr(
        "easyauth.portal.handover_api.assert_manager_of",
        observe_jurisdiction,
    )
    client = _login(Client(), actor)
    response = client.post(
        f"/portal/api/v1/handover-tasks/{task.pk}/actions/{action.app.app_key}/retry",
        content_type="application/json",
    )

    assert response.status_code == 409
    assert observed_atomic == [False, True]


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
        spec=HandoverCreationSpec(app_keys=(app.app_key,)),
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
