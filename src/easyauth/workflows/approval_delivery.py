from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import transaction

from easyauth.webhooks.delivery import WebhookNotConfiguredError, enqueue_delivery
from easyauth.webhooks.models import (
    WEBHOOK_EVENT_APPROVAL_COMPLETED,
    AppWebhookConfig,
)
from easyauth.workflows.models import ApprovalInstance

if TYPE_CHECKING:
    from easyauth.applications.ops_models import JsonValue


def deliver_completion(instance: ApprovalInstance) -> None:
    # 结果经 §5.1 通道推给发起 APP; 未配置 webhook 时保持无关联投递行,
    # delivery_state() 派生为 skipped(APP 侧轮询兜底)。
    with transaction.atomic():
        locked = (
            ApprovalInstance.objects.select_for_update()
            .select_related("app", "template", "originator_user")
            .get(id=instance.id)
        )
        if locked.completion_delivery_id is not None:  # pyright: ignore[reportUnknownMemberType, reportAttributeAccessIssue]
            instance.completion_delivery_id = locked.completion_delivery_id  # pyright: ignore[reportUnknownMemberType, reportAttributeAccessIssue]
            return
        config = AppWebhookConfig.objects.filter(app=locked.app, enabled=True).first()
        url = config.approval_callback_url if config is not None else ""
        try:
            delivery = enqueue_delivery(
                app=locked.app,
                event_type=WEBHOOK_EVENT_APPROVAL_COMPLETED,
                url=url,
                payload=completion_event_payload(locked),
            )
        except WebhookNotConfiguredError:
            return
        locked.completion_delivery = delivery
        locked.save(update_fields=["completion_delivery", "updated_at"])
        instance.completion_delivery = delivery


def completion_event_payload(instance: ApprovalInstance) -> dict[str, JsonValue]:
    return {
        "instance_id": str(instance.id),
        "template_key": instance.template.key,
        "biz_key": instance.biz_key,
        "status": instance.status,
        "originator_user_id": instance.originator_user.authentik_user_id,
        "completed_at": (
            instance.completed_at.isoformat() if instance.completed_at is not None else None
        ),
    }
