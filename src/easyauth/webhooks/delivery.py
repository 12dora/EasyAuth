from __future__ import annotations

import uuid
from dataclasses import dataclass
from json import dumps
from typing import TYPE_CHECKING, Final, Self, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from celery import current_app
from django.db import transaction
from django.utils import timezone

from easyauth.audit.services import AuditRecord, AuditService
from easyauth.webhooks.models import (
    DELIVERY_STATUS_DELIVERED,
    DELIVERY_STATUS_FAILED,
    DELIVERY_STATUS_PENDING,
    AppWebhookConfig,
    WebhookDelivery,
)
from easyauth.webhooks.signing import (
    DELIVERY_HEADER,
    EVENT_HEADER,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    sign_webhook_body,
)

if TYPE_CHECKING:
    from types import TracebackType

    from easyauth.applications.models import App
    from easyauth.applications.ops_models import JsonValue

# 指数退避重试间隔(秒): 1m/5m/30m/2h/6h, 共 5 次(§5.1)。
DELIVERY_RETRY_DELAYS_SECONDS: Final[tuple[int, ...]] = (60, 300, 1800, 7200, 21600)
DELIVERY_TIMEOUT_SECONDS: Final = 10.0
WEBHOOK_NOT_CONFIGURED_MESSAGE: Final = "该应用未配置可用的 webhook。"
WEBHOOK_DELIVERY_TASK_NAME: Final = "easyauth.webhooks.deliver"


class _ReadableResponse:
    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    def read(self) -> bytes: ...


class WebhookNotConfiguredError(RuntimeError):
    def __init__(self) -> None:
        super().__init__(WEBHOOK_NOT_CONFIGURED_MESSAGE)


class WebhookDeliveryAttemptError(RuntimeError):
    attempts: int

    def __init__(self, message: str, *, attempts: int) -> None:
        super().__init__(message)
        self.attempts = attempts


@dataclass(frozen=True, slots=True)
class WebhookEndpoint:
    config: AppWebhookConfig
    url: str


def resolve_endpoint(app: App, *, url: str) -> WebhookEndpoint:
    config = AppWebhookConfig.objects.filter(app=app, enabled=True).first()
    if config is None or not config.secret or not url:
        raise WebhookNotConfiguredError
    return WebhookEndpoint(config=config, url=url)


def enqueue_delivery(
    *,
    app: App,
    event_type: str,
    url: str,
    payload: dict[str, JsonValue],
) -> WebhookDelivery:
    # 先落 pending 行再交给 Celery: 事件事实不依赖队列可用性, 失败可控可重投。
    _ = resolve_endpoint(app, url=url)
    delivery = WebhookDelivery.objects.create(
        app=app,
        delivery_id=uuid.uuid4().hex,
        event_type=event_type,
        target_url=url,
        payload=payload,
    )
    _schedule_delivery(delivery.id)
    return delivery


def attempt_delivery(delivery_id: int) -> WebhookDelivery:
    """执行一次投递尝试; 失败时抛 WebhookDeliveryAttemptError 交由任务层重试。"""
    delivery = WebhookDelivery.objects.select_related("app").get(id=delivery_id)
    if delivery.status == DELIVERY_STATUS_DELIVERED:
        return delivery
    endpoint = resolve_endpoint(delivery.app, url=delivery.target_url)
    body = dumps(delivery.payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    timestamp = str(int(timezone.now().timestamp()))
    headers = {
        "Content-Type": "application/json",
        EVENT_HEADER: delivery.event_type,
        DELIVERY_HEADER: delivery.delivery_id,
        TIMESTAMP_HEADER: timestamp,
        SIGNATURE_HEADER: sign_webhook_body(
            secret=endpoint.config.secret,
            timestamp=timestamp,
            body=body,
        ),
    }
    delivery.attempts += 1
    request = Request(endpoint.url, data=body, headers=headers, method="POST")  # noqa: S310 - URL 来自控制台管理员配置。
    try:
        with cast(
            "_ReadableResponse",
            urlopen(request, timeout=DELIVERY_TIMEOUT_SECONDS),  # noqa: S310
        ) as response:
            _ = response.read()
    except HTTPError as error:
        _mark_attempt_failed(delivery, f"HTTP {error.code}")
        message = f"webhook 投递失败: HTTP {error.code}"
        raise WebhookDeliveryAttemptError(message, attempts=delivery.attempts) from error
    except (URLError, TimeoutError) as error:
        _mark_attempt_failed(delivery, str(error))
        message = "webhook 投递失败: 目标不可达。"
        raise WebhookDeliveryAttemptError(message, attempts=delivery.attempts) from error
    delivery.status = DELIVERY_STATUS_DELIVERED
    delivery.last_error = ""
    delivery.save(update_fields=["status", "attempts", "last_error", "updated_at"])
    _record_delivery_event(delivery, action="webhook_delivered")
    return delivery


def mark_delivery_exhausted(delivery_id: int) -> None:
    delivery = WebhookDelivery.objects.select_related("app").filter(id=delivery_id).first()
    if delivery is None or delivery.status == DELIVERY_STATUS_DELIVERED:
        return
    delivery.status = DELIVERY_STATUS_FAILED
    delivery.save(update_fields=["status", "updated_at"])
    _record_delivery_event(delivery, action="webhook_delivery_exhausted")


def redeliver(delivery: WebhookDelivery) -> WebhookDelivery:
    # 手动重投: 重置状态与计数, 重新走完整重试计划。
    delivery.status = DELIVERY_STATUS_PENDING
    delivery.attempts = 0
    delivery.last_error = ""
    delivery.save(update_fields=["status", "attempts", "last_error", "updated_at"])
    _schedule_delivery(delivery.id)
    return delivery


def _schedule_delivery(delivery_id: int) -> None:
    # 行提交后再发任务: 先发任务会让 worker 读到不存在的投递行(经典竞态)。
    # 按任务名投递, 避免 delivery(被任务模块导入)反向导入任务模块形成环。
    transaction.on_commit(
        lambda: current_app.send_task(WEBHOOK_DELIVERY_TASK_NAME, args=[delivery_id]),
    )


def _mark_attempt_failed(delivery: WebhookDelivery, error: str) -> None:
    delivery.last_error = error
    delivery.save(update_fields=["attempts", "last_error", "updated_at"])


def _record_delivery_event(delivery: WebhookDelivery, *, action: str) -> None:
    _ = AuditService.record(
        AuditRecord(
            actor_type="system",
            actor_id="webhook_delivery",
            action=action,
            target_type="webhook_delivery",
            target_id=delivery.delivery_id,
            metadata={
                "app_key": delivery.app.app_key,
                "event_type": delivery.event_type,
                "attempts": delivery.attempts,
                "last_error": delivery.last_error,
            },
        ),
    )
