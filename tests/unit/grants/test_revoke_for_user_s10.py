from __future__ import annotations

from typing import Final

import pytest

from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App
from easyauth.audit.models import AuditLog
from easyauth.grants.models import (
    GRANT_STATUS_EXPIRED,
    GRANT_STATUS_REVOKED,
    AccessGrant,
)
from easyauth.grants.services import GrantService

pytestmark = pytest.mark.django_db

INITIAL_VERSION: Final = 1
REVOKED_VERSION: Final = 2
HISTORICAL_VERSION: Final = 3
EXPECTED_REVOKED_GRANTS: Final = 2
AUTHENTIK_DEPARTURE_REASON: Final = "authentik_departure"


def test_s10_revoke_for_user_revokes_all_current_active_grants_once() -> None:
    # Given
    user = UserMirror.objects.create(authentik_user_id="s10-revoke-user")
    crm = App.objects.create(app_key="s10-revoke-crm", name="S10 Revoke CRM")
    erp = App.objects.create(app_key="s10-revoke-erp", name="S10 Revoke ERP")
    crm_grant = AccessGrant.objects.create(user=user, app=crm)
    erp_grant = AccessGrant.objects.create(user=user, app=erp)

    # When
    first = GrantService.revoke_for_user(
        user=user,
        reason=AUTHENTIK_DEPARTURE_REASON,
        actor_type="authentik",
        actor_id=user.authentik_user_id,
    )
    repeated = GrantService.revoke_for_user(
        user=user,
        reason=AUTHENTIK_DEPARTURE_REASON,
        actor_type="authentik",
        actor_id=user.authentik_user_id,
    )

    # Then
    crm_grant.refresh_from_db()
    erp_grant.refresh_from_db()
    assert [grant.app.app_key for grant in first] == ["s10-revoke-crm", "s10-revoke-erp"]
    assert repeated == []
    assert crm_grant.status == GRANT_STATUS_REVOKED
    assert erp_grant.status == GRANT_STATUS_REVOKED
    assert crm_grant.is_current is False
    assert erp_grant.is_current is False
    assert crm_grant.version == REVOKED_VERSION
    assert erp_grant.version == REVOKED_VERSION
    audit_logs = AuditLog.objects.filter(
        event_type="grant_revoked",
        actor_type="authentik",
        actor_id=user.authentik_user_id,
    )
    assert audit_logs.count() == EXPECTED_REVOKED_GRANTS
    for audit_log in audit_logs:
        assert audit_log.metadata["reason"] == AUTHENTIK_DEPARTURE_REASON


def test_s10_revoke_for_user_ignores_non_current_and_inactive_grants() -> None:
    # Given
    user = UserMirror.objects.create(authentik_user_id="s10-revoke-inactive-user")
    current_app = App.objects.create(app_key="s10-current-app", name="S10 Current App")
    inactive_app = App.objects.create(app_key="s10-inactive-app", name="S10 Inactive App")
    current_grant = AccessGrant.objects.create(
        user=user,
        app=current_app,
        version=INITIAL_VERSION,
    )
    inactive_grant = AccessGrant.objects.create(
        user=user,
        app=inactive_app,
        status=GRANT_STATUS_EXPIRED,
        is_current=False,
        version=HISTORICAL_VERSION,
    )

    # When
    revoked = GrantService.revoke_for_user(
        user=user,
        reason=AUTHENTIK_DEPARTURE_REASON,
        actor_type="authentik",
        actor_id=user.authentik_user_id,
    )

    # Then
    current_grant.refresh_from_db()
    inactive_grant.refresh_from_db()
    assert [grant.app.app_key for grant in revoked] == ["s10-current-app"]
    assert current_grant.status == GRANT_STATUS_REVOKED
    assert current_grant.version == REVOKED_VERSION
    assert inactive_grant.status == GRANT_STATUS_EXPIRED
    assert inactive_grant.version == HISTORICAL_VERSION
    assert AuditLog.objects.filter(event_type="grant_revoked").count() == 1
