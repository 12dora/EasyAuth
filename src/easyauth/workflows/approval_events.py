from __future__ import annotations

from typing import TYPE_CHECKING

from easyauth.audit.services import AuditRecord, AuditService

if TYPE_CHECKING:
    from easyauth.workflows.models import ApprovalInstance


def record_instance_event(
    instance: ApprovalInstance,
    *,
    action: str,
    actor_id: str,
) -> None:
    _ = AuditService.record(
        AuditRecord(
            actor_type="app" if actor_id == instance.app.app_key else "system",
            actor_id=actor_id,
            action=action,
            target_type="approval_instance",
            target_id=str(instance.id),
            metadata={
                "app_key": instance.app.app_key,
                "template_key": instance.template.key,
                "biz_key": instance.biz_key,
                "status": instance.status,
                "dingtalk_process_instance_id": instance.dingtalk_process_instance_id,
            },
        ),
    )
