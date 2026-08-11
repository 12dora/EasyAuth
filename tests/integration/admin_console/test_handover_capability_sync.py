from __future__ import annotations

from http import HTTPStatus
from types import SimpleNamespace

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.utils import timezone

from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.admin_console import auto_onboarding_api
from easyauth.applications.handover_capability import sync_handover_capability_from_manifest
from easyauth.applications.manifest_import import sync_app_manifest
from easyauth.applications.models import (
    HANDOVER_CAPABILITY_DECLARED,
    HANDOVER_CAPABILITY_NONE,
    HANDOVER_CAPABILITY_UNDECLARED,
    App,
)
from easyauth.audit.models import AuditLog
from easyauth.lifecycle.models import (
    ACTION_STATUS_BLOCKED,
    ACTION_STATUS_PENDING,
    BLOCKED_REASON_CAPABILITY_UNDECLARED,
    HANDOVER_KIND_OFFBOARD,
    HandoverAppAction,
    HandoverTask,
)
from tests.integration.admin_console.auth_helpers import authenticate_console_admin

pytestmark = pytest.mark.django_db


def _manifest(app_key: str) -> dict:
    return {
        "schema_version": 1,
        "app": {"app_key": app_key, "name": "同步应用"},
        "scopes": [{"key": "SELF", "name": "本人"}],
        "permission_groups": [{"key": "core", "name": "核心"}],
        "permissions": [
            {
                "key": "core.read",
                "name": "查看",
                "group_key": "core",
                "supported_scopes": ["SELF"],
            },
        ],
        "authorization_groups": [],
        "approval_rules": [],
        "lifecycle": {
            "handover_url": "/handover",
            "onboard_url": None,
            "capabilities": ["handover.v2"],
            "handover_asset_types": [
                {
                    "type": "record",
                    "label": "记录",
                    "detail_supported": False,
                    "releasable": False,
                },
            ],
        },
    }


def test_console_resync_reuses_credential_and_reconciles_unchanged_manifest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "easyauth.config.net.resolve_public_addresses",
        lambda _hostname, *, port, **_kwargs: (("93.184.216.34",) if port == 443 else ()),
    )
    app = App.objects.create(
        app_key="console-resync",
        name="控制台重同步",
        descriptor_base_url="https://downstream.example",
        descriptor_token="descriptor-secret-token",  # noqa: S106 - 测试 bearer。
    )
    manifest = _manifest(app.app_key)
    _ = sync_app_manifest(
        app=app,
        manifest=manifest,
        actor_id="manifest",
        downstream_base_url=app.descriptor_base_url,
    )
    app.refresh_from_db()
    assert app.handover_capability == HANDOVER_CAPABILITY_DECLARED
    app.handover_capability = HANDOVER_CAPABILITY_UNDECLARED
    app.save(update_fields=["handover_capability", "updated_at"])

    subject = UserMirror.objects.create(
        authentik_user_id="console-resync-subject",
        status=USER_STATUS_ACTIVE,
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
        app_key_snapshot=app.app_key,
        app_name_snapshot=app.name,
        generation=task.generation,
        status=ACTION_STATUS_BLOCKED,
        blocked_reason=BLOCKED_REASON_CAPABILITY_UNDECLARED,
    )
    seen: dict[str, object] = {}

    def fake_fetch(base_url: str, token: str | None) -> dict:
        seen["base_url"] = base_url
        seen["token"] = token
        return {
            "descriptor_version": 1,
            "app": {"app_key": app.app_key, "name": app.name},
            "manifest": manifest,
            "sdk": {"name": "test", "version": "1"},
        }

    monkeypatch.setattr(auto_onboarding_api, "_fetch_descriptor", fake_fetch)
    username = "console-resync-admin"
    _ = User.objects.create_superuser(username=username, password="unused-password")
    client = Client(HTTP_HOST="localhost", raise_request_exception=False)
    _ = authenticate_console_admin(client, username)

    response = client.post(
        f"/console/api/v1/lifecycle/apps/{app.app_key}/handover-capability/sync",
    )

    assert response.status_code == HTTPStatus.OK, response.content
    assert seen == {
        "base_url": "https://downstream.example",
        "token": "descriptor-secret-token",
    }
    app.refresh_from_db()
    action.refresh_from_db()
    assert app.handover_capability == HANDOVER_CAPABILITY_DECLARED
    assert action.status == ACTION_STATUS_PENDING
    audit = AuditLog.objects.get(event_type="handover_action_unblocked")
    assert audit.actor_type == "admin"
    assert audit.actor_id == username


def test_console_capability_conflict_audit_is_admin_actor() -> None:
    app = App.objects.create(
        app_key="console-conflict",
        name="控制台冲突",
        handover_capability=HANDOVER_CAPABILITY_NONE,
        handover_capability_declared_by="admin-before",
        handover_capability_declared_at=timezone.now(),
    )

    sync_handover_capability_from_manifest(
        app,
        SimpleNamespace(
            capabilities=("handover.v2", "handover.none"),
            handover_url="https://downstream.example/handover",
            handover_asset_types=(),
        ),
        actor_id="console-admin",
        actor_type="admin",
    )

    app.refresh_from_db()
    assert app.handover_capability == HANDOVER_CAPABILITY_UNDECLARED
    audit = AuditLog.objects.get(event_type="handover_capability_conflict")
    assert audit.actor_type == "admin"
    assert audit.actor_id == "console-admin"
