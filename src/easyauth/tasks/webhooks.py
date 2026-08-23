from __future__ import annotations


from celery import shared_task

from easyauth.webhooks.delivery import (
    WEBHOOK_DELIVERY_TASK_NAME,
    WEBHOOK_DELIVERY_WATCHDOG_TASK_NAME,
    WebhookDeliveryAttemptError,
    WebhookNotConfiguredError,
    attempt_delivery,
    mark_delivery_exhausted,
    recover_expired_delivery_leases,
)

@shared_task(
    name=WEBHOOK_DELIVERY_TASK_NAME,
    acks_late=True,
    soft_time_limit=18,
    time_limit=20,
)  # pyright: ignore[reportCallIssue, reportUntypedFunctionDecorator]
def deliver_webhook_task(delivery_id: int, generation: int, expected_attempt: int = 1) -> str:
    # 重试计划以 WebhookDelivery.attempts(库内事实)为准, 不依赖 celery 任务链上下文,
    # 手动重投重置计数后自然重新走完整计划。
    try:
        delivery = attempt_delivery(delivery_id, generation, expected_attempt)
    except WebhookNotConfiguredError:
        # 配置在入队后被删除/停用: 无法再投递, 直接判定失败留待人工处理。
        mark_delivery_exhausted(delivery_id, generation)
        return "failed"
    except WebhookDeliveryAttemptError as error:
        return "retry_scheduled" if error.retry_scheduled else "failed"
    return delivery.status


@shared_task(name=WEBHOOK_DELIVERY_WATCHDOG_TASK_NAME)
def recover_expired_webhook_leases_task() -> dict[str, int]:
    recovered = recover_expired_delivery_leases()
    return {"recovered": recovered}
