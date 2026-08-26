from __future__ import annotations

from django.db import transaction

from easyauth.workflows.approval_delivery import deliver_completion
from easyauth.workflows.approval_state import apply_callback_locked
from easyauth.workflows.approval_types import (
    INSTANCE_STATUS_CONFLICT_MESSAGE,
    ApprovalCallbackConflictError,
    ApprovalInstanceNotFoundError,
)
from easyauth.workflows.models import (
    APPROVAL_TERMINAL_STATUSES,
    CALLBACK_STATE_CONFLICT,
    ApprovalInstance,
    PendingApprovalCallback,
)


def apply_instance_callback(
    *,
    process_instance_id: str,
    status: str,
) -> ApprovalInstance:
    """钉钉回调推进实例; 无法关联时先持久化, 待提交保存 process ID 后恢复。"""
    missing = False
    conflict: ApprovalCallbackConflictError | None = None
    instance: ApprovalInstance | None = None
    with transaction.atomic():
        instance = (
            ApprovalInstance.objects.select_for_update()
            .select_related("app", "template", "originator_user")
            .filter(dingtalk_process_instance_id=process_instance_id)
            .first()
        )
        callback, _created = PendingApprovalCallback.objects.select_for_update().get_or_create(
            process_instance_id=process_instance_id,
            defaults={"status": status},
        )
        if callback.status != status:
            callback.state = CALLBACK_STATE_CONFLICT
            callback.last_error = INSTANCE_STATUS_CONFLICT_MESSAGE
            callback.applied_at = None
            callback.save(update_fields=["state", "last_error", "applied_at", "updated_at"])
            conflict = ApprovalCallbackConflictError(
                instance_id=str(instance.id) if instance is not None else "",
                status=callback.status,
            )
        elif instance is None:
            missing = True
        else:
            _changed, conflict = apply_callback_locked(instance, callback)
            if conflict is None and instance.status in APPROVAL_TERMINAL_STATUSES:
                # 重复回调也补写事件, 且终态与 delivery/outbox 在同一事务提交。
                deliver_completion(instance)
    if conflict is not None:
        raise conflict
    if missing or instance is None:
        raise ApprovalInstanceNotFoundError
    return instance
