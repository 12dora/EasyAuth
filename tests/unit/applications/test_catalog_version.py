from __future__ import annotations

import pytest

from easyauth.applications.catalog_version import bump_catalog_version
from easyauth.applications.models import App
from easyauth.audit.models import AuditLog

pytestmark = pytest.mark.django_db
EXPECTED_BUMPED_CATALOG_VERSION = 2


def test_bump_catalog_version_increments_app_and_records_reason_in_audit_metadata() -> None:
    # Given
    app = App.objects.create(app_key="crm", name="CRM")

    # When
    bump_catalog_version(
        app,
        actor_id="admin-001",
        reason="permission import",
        metadata={"template_version": 3},
    )

    # Then
    assert app.catalog_version == EXPECTED_BUMPED_CATALOG_VERSION
    audit_log = AuditLog.objects.get(event_type="app_catalog_version_bumped")
    assert audit_log.actor_type == "user"
    assert audit_log.actor_id == "admin-001"
    assert audit_log.target_type == "app"
    assert audit_log.target_id == str(app.id)
    assert audit_log.metadata == {
        "app_id": app.id,
        "app_key": "crm",
        "catalog_version": EXPECTED_BUMPED_CATALOG_VERSION,
        "reason": "permission import",
        "template_version": 3,
    }
