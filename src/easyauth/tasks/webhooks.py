from __future__ import annotations

from typing import Final

from celery import shared_task

from easyauth.webhooks.delivery import (
    DELIVERY_RETRY_DELAYS_SECONDS,
    WEBHOOK_DELIVERY_TASK_NAME,
    WebhookDeliveryAttemptError,
    WebhookNotConfiguredError,
    attempt_delivery,
    mark_delivery_exhausted,
)

MAX_DELIVERY_ATTEMPTS: Final = len(DELIVERY_RETRY_DELAYS_SECONDS)


@shared_task(
    name=WEBHOOK_DELIVERY_TASK_NAME,
    acks_late=True,
    soft_time_limit=18,
    time_limit=20,
)  # pyright: ignore[reportCallIssue, reportUntypedFunctionDecorator]
def deliver_webhook_task(delivery_id: int, generation: int) -> str:
    # 重试计划以 WebhookDelivery.attempts(库内事实)为准, 不依赖 celery 任务链上下文,
    # 手动重投重置计数后自然重新走完整计划。
    try:
        delivery = attempt_delivery(delivery_id, generation)
    except WebhookNotConfiguredError:
        # 配置在入队后被删除/停用: 无法再投递, 直接判定失败留待人工处理。
        mark_delivery_exhausted(delivery_id, generation)
        return "failed"
    except WebhookDeliveryAttemptError as error:
        return "failed" if error.attempts >= MAX_DELIVERY_ATTEMPTS else "retry_scheduled"
    return delivery.status
