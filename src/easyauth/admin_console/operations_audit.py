from __future__ import annotations

from easyauth.audit.services import AuditRecord, AuditService


def record_dependency_health_read(actor_id: str) -> None:
    _ = AuditService.record(
        AuditRecord(
            actor_type="admin",
            actor_id=actor_id,
            action="dependency_health_read",
            target_type="dependency_health",
            target_id="latest",
            metadata={},
        ),
    )


def record_dependency_health_check_run(actor_id: str) -> None:
    _ = AuditService.record(
        AuditRecord(
            actor_type="admin",
            actor_id=actor_id,
            action="dependency_health_check_executed",
            target_type="dependency_health",
            target_id="latest",
            metadata={},
        ),
    )
