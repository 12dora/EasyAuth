from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

from easyauth.audit.models import AuditLog
from easyauth.audit.services import AuditRecord, AuditService

pytestmark = pytest.mark.django_db


def test_record_creates_audit_log_with_actor_action_target_and_metadata() -> None:
    # Given
    metadata = {"app_key": "crm", "version": 7}

    # When
    audit_log = AuditService.record(
        AuditRecord(
            actor_type="admin",
            actor_id="admin-001",
            action="grant_created",
            target_type="grant",
            target_id="grant-001",
            metadata=metadata,
        ),
    )

    # Then
    stored_log = AuditLog.objects.get(
        actor_id=audit_log.actor_id,
        event_type=audit_log.event_type,
        target_id=audit_log.target_id,
    )
    assert stored_log.actor_type == "admin"
    assert stored_log.actor_id == "admin-001"
    assert stored_log.event_type == "grant_created"
    assert stored_log.target_type == "grant"
    assert stored_log.target_id == "grant-001"
    assert stored_log.metadata == metadata


def test_saved_audit_log_rejects_update_when_saved_again() -> None:
    # Given
    audit_log = AuditService.record(
        AuditRecord(
            actor_type="system",
            actor_id="scheduler",
            action="grant_expired",
            target_type="grant",
            target_id="grant-002",
            metadata={"reason": "expired"},
        ),
    )

    # When
    audit_log.metadata = {"reason": "mutated"}

    # Then
    with pytest.raises(ValidationError):
        audit_log.save()


def test_saved_audit_log_rejects_delete_when_deleted() -> None:
    # Given
    audit_log = AuditService.record(
        AuditRecord(
            actor_type="system",
            actor_id="scheduler",
            action="grant_revoked",
            target_type="grant",
            target_id="grant-003",
            metadata={"reason": "departure"},
        ),
    )

    # When / Then
    with pytest.raises(ValidationError):
        _ = audit_log.delete()


def test_saved_audit_log_rejects_bulk_update_when_queryset_updates() -> None:
    # Given
    audit_log = AuditService.record(
        AuditRecord(
            actor_type="system",
            actor_id="scheduler",
            action="grant_changed",
            target_type="grant",
            target_id="grant-004",
            metadata={"reason": "change"},
        ),
    )

    # When / Then
    with pytest.raises(ValidationError):
        _ = AuditLog.objects.filter(target_id=audit_log.target_id).update(
            metadata={"reason": "bulk-mutated"},
        )


def test_saved_audit_log_rejects_bulk_delete_when_queryset_deletes() -> None:
    # Given
    audit_log = AuditService.record(
        AuditRecord(
            actor_type="system",
            actor_id="scheduler",
            action="grant_removed",
            target_type="grant",
            target_id="grant-005",
            metadata={"reason": "remove"},
        ),
    )

    # When / Then
    with pytest.raises(ValidationError):
        _ = AuditLog.objects.filter(target_id=audit_log.target_id).delete()
