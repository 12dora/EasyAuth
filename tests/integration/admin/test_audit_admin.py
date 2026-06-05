from __future__ import annotations

import pytest
from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory

from easyauth.audit.admin import AuditLogAdmin
from easyauth.audit.models import AuditLog
from easyauth.audit.services import AuditRecord, AuditService

pytestmark = pytest.mark.django_db


def test_audit_log_admin_rejects_change_and_delete_for_existing_object() -> None:
    # Given
    audit_log = AuditService.record(
        AuditRecord(
            actor_type="system",
            actor_id="admin-smoke",
            action="admin_readonly_checked",
            target_type="audit_log",
            target_id="audit-log-001",
            metadata={"surface": "django-admin"},
        ),
    )
    request = RequestFactory().get("/admin/audit/auditlog/1/change/")
    admin = AuditLogAdmin(AuditLog, AdminSite())

    # When
    can_change = admin.has_change_permission(request, audit_log)
    can_delete = admin.has_delete_permission(request, audit_log)

    # Then
    assert can_change is False
    assert can_delete is False
