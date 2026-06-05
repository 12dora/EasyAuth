from __future__ import annotations

from typing import Final

import pytest

from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App
from easyauth.audit.models import AuditLog
from easyauth.grants.models import (
    GRANT_STATUS_REVOKED,
    GRANT_TYPE_PERMANENT,
    AccessGrant,
)
from easyauth.grants.services import GrantService

pytestmark = pytest.mark.django_db

INITIAL_VERSION: Final = 1
REVOKED_VERSION: Final = 2


def test_s10_pin_revoke_grant_revokes_active_current_grant_and_records_audit() -> None:
    # Given
    user = UserMirror.objects.create(authentik_user_id="s10-pin-user")
    app = App.objects.create(app_key="s10-pin-app", name="S10 Pin App")
    grant = AccessGrant.objects.create(
        user=user,
        app=app,
        grant_type=GRANT_TYPE_PERMANENT,
        version=INITIAL_VERSION,
    )

    # When
    revoked = GrantService.revoke_grant(
        user=user,
        app=app,
        actor_type="authentik",
        actor_id=user.authentik_user_id,
    )

    # Then
    assert revoked is not None
    grant.refresh_from_db()
    assert grant.status == GRANT_STATUS_REVOKED
    assert grant.is_current is False
    assert grant.version == REVOKED_VERSION
    audit_log = AuditLog.objects.get(
        event_type="grant_revoked",
        target_id=f"{user.authentik_user_id}:{app.app_key}",
    )
    assert audit_log.actor_type == "authentik"
    assert audit_log.actor_id == "s10-pin-user"
    assert audit_log.metadata["version"] == REVOKED_VERSION
