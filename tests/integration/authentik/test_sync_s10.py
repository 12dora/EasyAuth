from __future__ import annotations

from typing import TYPE_CHECKING, Final

import pytest

from easyauth.accounts.models import (
    USER_STATUS_ACTIVE,
    USER_STATUS_DEPARTED,
    USER_STATUS_DISABLED,
    UserMirror,
)
from easyauth.accounts.services import AuthentikSyncService
from easyauth.applications.models import App, AuthorizationGroup
from easyauth.audit.models import AuditLog
from easyauth.grants.models import (
    GRANT_STATUS_REVOKED,
    AccessGrant,
    AccessGrantGroup,
)
from easyauth.tasks.authentik import StaticAuthentikPayloadSource, sync_authentik_users_from_source

if TYPE_CHECKING:
    from easyauth.integrations.authentik.payloads import AuthentikPayloadInput

pytestmark = pytest.mark.django_db

REVOKED_VERSION: Final = 2
NO_REVOKED_GRANTS: Final = 0
EXPECTED_DEPARTURE_EVENTS: Final = 1
EXPECTED_REVOKED_GRANTS: Final = 2
EXPECTED_SYNCED_PAYLOADS: Final = 2
AUTHENTIK_DEPARTURE_REASON: Final = "authentik_departure"


def test_s10_webhook_sync_upserts_new_and_existing_user() -> None:
    # Given
    first_payload: AuthentikPayloadInput = {
        "user": {
            "uid": "s10-sync-upsert-user",
            "name": "同步用户旧名",
            "email": "old@example.test",
            "attributes": {"department": "旧部门"},
        },
        "is_active": True,
    }
    second_payload: AuthentikPayloadInput = {
        "user": {
            "uid": "s10-sync-upsert-user",
            "name": "同步用户新名",
            "email": "new@example.test",
            "attributes": {"department": "新部门"},
        },
        "is_active": True,
    }

    # When
    created = AuthentikSyncService.sync_payload(first_payload)
    updated = AuthentikSyncService.sync_payload(second_payload)

    # Then
    user = UserMirror.objects.get(authentik_user_id="s10-sync-upsert-user")
    assert created.created is True
    assert updated.created is False
    assert UserMirror.objects.filter(authentik_user_id="s10-sync-upsert-user").count() == 1
    assert user.name == "同步用户新名"
    assert user.email == "new@example.test"
    assert user.department == "新部门"
    assert user.status == USER_STATUS_ACTIVE


def test_sync_payload_updates_dingtalk_fields() -> None:
    result = AuthentikSyncService.sync_payload(
        {
            "user": {
                "uid": "ak-user",
                "name": "张三",
                "email": "zhangsan@example.test",
                "attributes": {
                    "department": "旧部门",
                    "status": "active",
                    "dingtalk": {
                        "corp_id": "corp-1",
                        "user_id": "user-1",
                        "union_id": "union-1",
                        "job_number": "E001",
                    },
                    "dingtalk_org": {
                        "manager": {"user_id": "manager-1"},
                        "departments": [{"name": "销售部"}],
                    },
                },
            }
        },
    )

    assert result.user.dingtalk_corp_id == "corp-1"
    assert result.user.dingtalk_userid == "user-1"
    assert result.user.dingtalk_union_id == "union-1"
    assert result.user.employee_number == "E001"
    assert result.user.department == "销售部"
    assert result.user.manager_userid == "manager-1"


def test_s10_first_time_active_sync_without_grants_does_not_record_departure_event() -> None:
    # Given
    user_id = "s10-sync-new-active-without-grants"
    payload: AuthentikPayloadInput = {
        "user": {"uid": user_id},
        "is_active": True,
    }

    # When
    result = AuthentikSyncService.sync_payload(payload)

    # Then
    user = UserMirror.objects.get(authentik_user_id=user_id)
    assert result.created is True
    assert result.revoked_count == NO_REVOKED_GRANTS
    assert user.status == USER_STATUS_ACTIVE
    assert (
        AuditLog.objects.filter(
            event_type="user_departure_detected",
            target_id=user_id,
        ).count()
        == 0
    )


def test_s10_first_time_disabled_sync_without_grants_records_departure_once() -> None:
    # Given
    user_id = "s10-sync-new-disabled-without-grants"
    payload: AuthentikPayloadInput = {
        "user": {"uid": user_id},
        "is_active": False,
    }

    # When
    first = AuthentikSyncService.sync_payload(payload)
    repeated = AuthentikSyncService.sync_payload(payload)

    # Then
    user = UserMirror.objects.get(authentik_user_id=user_id)
    departure_logs = AuditLog.objects.filter(
        event_type="user_departure_detected",
        target_id=user_id,
    )
    assert first.created is True
    assert repeated.created is False
    assert first.revoked_count == NO_REVOKED_GRANTS
    assert repeated.revoked_count == NO_REVOKED_GRANTS
    assert user.status == USER_STATUS_DISABLED
    assert departure_logs.count() == EXPECTED_DEPARTURE_EVENTS
    departure_log = departure_logs.get()
    assert departure_log.actor_type == "authentik"
    assert departure_log.actor_id == user_id
    assert departure_log.metadata["user_id"] == user_id
    assert departure_log.metadata["status"] == USER_STATUS_DISABLED
    assert departure_log.metadata["revoked_count"] == NO_REVOKED_GRANTS


def test_s10_false_is_active_sync_disables_user_and_revokes_current_grant() -> None:
    # Given
    user = UserMirror.objects.create(authentik_user_id="s10-sync-disabled")
    app = App.objects.create(app_key="s10-sync-disabled-app", name="S10 Sync Disabled App")
    grant = _permanent_grant(user, app)
    payload: AuthentikPayloadInput = {
        "user": {"uid": user.authentik_user_id},
        "is_active": False,
    }

    # When
    result = AuthentikSyncService.sync_payload(payload)

    # Then
    user.refresh_from_db()
    grant.refresh_from_db()
    assert result.revoked_count == 1
    assert user.status == USER_STATUS_DISABLED
    assert grant.status == GRANT_STATUS_REVOKED
    assert grant.is_current is False
    assert grant.version == REVOKED_VERSION
    departure_log = AuditLog.objects.get(event_type="user_departure_detected")
    assert departure_log.actor_type == "authentik"
    assert departure_log.actor_id == "s10-sync-disabled"
    assert departure_log.metadata["user_id"] == "s10-sync-disabled"
    assert departure_log.metadata["status"] == USER_STATUS_DISABLED
    assert departure_log.metadata["revoked_count"] == 1


def test_s10_inactive_sync_without_grants_records_departure_once() -> None:
    # Given
    user = UserMirror.objects.create(authentik_user_id="s10-sync-inactive-no-grants")
    payload: AuthentikPayloadInput = {
        "user": {"uid": user.authentik_user_id},
        "status": "inactive",
    }

    # When
    first = AuthentikSyncService.sync_payload(payload)
    repeated = AuthentikSyncService.sync_payload(payload)

    # Then
    user.refresh_from_db()
    assert first.revoked_count == 0
    assert repeated.revoked_count == 0
    assert user.status == USER_STATUS_DISABLED
    departure_logs = AuditLog.objects.filter(event_type="user_departure_detected")
    assert departure_logs.count() == 1
    departure_log = departure_logs.get()
    assert departure_log.actor_type == "authentik"
    assert departure_log.actor_id == user.authentik_user_id
    assert departure_log.metadata["status"] == USER_STATUS_DISABLED
    assert departure_log.metadata["revoked_count"] == 0


def test_s10_departed_sync_revokes_all_active_grants_and_is_idempotent() -> None:
    # Given
    user = UserMirror.objects.create(authentik_user_id="s10-sync-departed")
    crm = App.objects.create(app_key="s10-sync-crm", name="S10 Sync CRM")
    erp = App.objects.create(app_key="s10-sync-erp", name="S10 Sync ERP")
    crm_grant = _permanent_grant(user, crm)
    erp_grant = _permanent_grant(user, erp)
    payload: AuthentikPayloadInput = {
        "user": {
            "uid": user.authentik_user_id,
            "attributes": {"status": "departed"},
        },
        "is_active": True,
    }

    # When
    first = AuthentikSyncService.sync_payload(payload)
    repeated = AuthentikSyncService.sync_payload(payload)

    # Then
    user.refresh_from_db()
    crm_grant.refresh_from_db()
    erp_grant.refresh_from_db()
    assert first.revoked_count == EXPECTED_REVOKED_GRANTS
    assert repeated.revoked_count == 0
    assert user.status == USER_STATUS_DEPARTED
    assert crm_grant.version == REVOKED_VERSION
    assert erp_grant.version == REVOKED_VERSION
    grant_revoked_logs = AuditLog.objects.filter(
        event_type="grant_revoked",
        actor_type="authentik",
        actor_id=user.authentik_user_id,
    )
    assert grant_revoked_logs.count() == EXPECTED_REVOKED_GRANTS
    for audit_log in grant_revoked_logs:
        assert audit_log.metadata["reason"] == AUTHENTIK_DEPARTURE_REASON
    departure_log = AuditLog.objects.get(event_type="user_departure_detected")
    assert departure_log.metadata["user_id"] == user.authentik_user_id
    assert departure_log.metadata["status"] == USER_STATUS_DEPARTED
    assert departure_log.metadata["revoked_count"] == EXPECTED_REVOKED_GRANTS


def test_s10_scheduled_sync_entry_processes_multiple_payloads_from_static_source() -> None:
    # Given
    disabled_user = UserMirror.objects.create(authentik_user_id="s10-task-disabled")
    app = App.objects.create(app_key="s10-task-app", name="S10 Task App")
    grant = _permanent_grant(disabled_user, app)
    source = StaticAuthentikPayloadSource(
        payloads=(
            {
                "user": {"uid": "s10-task-active", "name": "任务同步用户"},
                "is_active": True,
            },
            {
                "context": {"sub": disabled_user.authentik_user_id},
                "is_active": False,
            },
        ),
    )

    # When
    result = sync_authentik_users_from_source(source)

    # Then
    grant.refresh_from_db()
    active_user = UserMirror.objects.get(authentik_user_id="s10-task-active")
    disabled_user.refresh_from_db()
    assert result.synced_count == EXPECTED_SYNCED_PAYLOADS
    assert result.revoked_count == 1
    assert active_user.status == USER_STATUS_ACTIVE
    assert disabled_user.status == USER_STATUS_DISABLED
    assert grant.status == GRANT_STATUS_REVOKED


def _permanent_grant(user: UserMirror, app: App) -> AccessGrant:
    group = AuthorizationGroup.objects.create(
        app=app,
        key="member",
        kind="role",
        name="成员",
    )
    grant = AccessGrant.objects.create(user=user, app=app)
    _ = AccessGrantGroup.objects.create(
        grant=grant,
        authorization_group=group,
        expires_at=None,
    )
    return grant
