from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta
from http import HTTPStatus
from json import dumps
from typing import TYPE_CHECKING, Final

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from easyauth.audit.services import AuditRecord, AuditService
from easyauth.config.net import (
    BlockedHostError,
    InvalidWebhookUrlError,
    parse_https_url,
)
from easyauth.outbox.services import enqueue_task
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
from easyauth.webhooks.transport import (
    WebhookRequestPolicy,
    WebhookTransportError,
    post_webhook,
)

if TYPE_CHECKING:
    from easyauth.applications.models import App
    from easyauth.applications.ops_models import JsonValue

# 指数退避重试间隔(秒): 1m/5m/30m/2h/6h, 共 5 次(§5.1)。
DELIVERY_RETRY_DELAYS_SECONDS: Final[tuple[int, ...]] = (60, 300, 1800, 7200, 21600)
DELIVERY_CONNECT_TIMEOUT_SECONDS: Final = 5.0
DELIVERY_TOTAL_TIMEOUT_SECONDS: Final = 15.0
DELIVERY_MAX_RESPONSE_BYTES: Final = 64 * 1024
DELIVERY_LEASE_SECONDS: Final = 45
DELIVERY_REQUEST_POLICY: Final = WebhookRequestPolicy(
    connect_timeout_seconds=DELIVERY_CONNECT_TIMEOUT_SECONDS,
    total_timeout_seconds=DELIVERY_TOTAL_TIMEOUT_SECONDS,
    max_response_bytes=DELIVERY_MAX_RESPONSE_BYTES,
)
WEBHOOK_NOT_CONFIGURED_MESSAGE: Final = "该应用未配置可用的 webhook。"
WEBHOOK_ENDPOINT_REJECTED_MESSAGE: Final = "Webhook 目标地址未通过安全校验。"
WEBHOOK_DELIVERY_TASK_NAME: Final = "easyauth.webhooks.deliver"
WEBHOOK_REDELIVERY_CONFLICT_MESSAGE: Final = "该投递已不处于失败状态, 不能重复重投。"


class WebhookNotConfiguredError(RuntimeError):
    def __init__(self) -> None:
        super().__init__(WEBHOOK_NOT_CONFIGURED_MESSAGE)


class WebhookEndpointRejectedError(WebhookNotConfiguredError):
    def __init__(self) -> None:
        RuntimeError.__init__(self, WEBHOOK_ENDPOINT_REJECTED_MESSAGE)


class WebhookDeliveryAttemptError(RuntimeError):
    attempts: int

    def __init__(self, message: str, *, attempts: int) -> None:
        super().__init__(message)
        self.attempts = attempts


class WebhookRedeliveryConflictError(RuntimeError):
    def __init__(self) -> None:
        super().__init__(WEBHOOK_REDELIVERY_CONFLICT_MESSAGE)


@dataclass(frozen=True, slots=True)
class WebhookEndpoint:
    config: AppWebhookConfig
    url: str
    allowed_hosts: tuple[str, ...]


def resolve_endpoint(app: App, *, url: str) -> WebhookEndpoint:
    config = AppWebhookConfig.objects.filter(app=app, enabled=True).first()
    if config is None or not config.secret or not url:
        raise WebhookNotConfiguredError
    allowed_hosts = tuple(config.allowed_hosts)
    try:
        _ = parse_https_url(url, allowed_hosts=allowed_hosts)
    except (BlockedHostError, InvalidWebhookUrlError) as error:
        raise WebhookEndpointRejectedError from error
    return WebhookEndpoint(config=config, url=url, allowed_hosts=allowed_hosts)


def enqueue_delivery(
    *,
    app: App,
    event_type: str,
    url: str,
    payload: dict[str, JsonValue],
) -> WebhookDelivery:
    # 先落 pending 行再交给 Celery: 事件事实不依赖队列可用性, 失败可控可重投。
    _ = resolve_endpoint(app, url=url)
    with transaction.atomic():
        delivery = WebhookDelivery.objects.create(
            app=app,
            delivery_id=uuid.uuid4().hex,
            event_type=event_type,
            target_url=url,
            payload=payload,
        )
        _schedule_delivery(delivery)
    return delivery


def attempt_delivery(delivery_id: int, generation: int) -> WebhookDelivery:
    """执行一次投递尝试; 失败时抛 WebhookDeliveryAttemptError 交由任务层重试。"""
    delivery, claim_token = _claim_delivery(delivery_id, generation)
    if claim_token is None:
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
    try:
        response = post_webhook(
            url=endpoint.url,
            allowed_hosts=endpoint.allowed_hosts,
            body=body,
            headers=headers,
            policy=DELIVERY_REQUEST_POLICY,
        )
    except WebhookTransportError as error:
        if not _mark_attempt_failed(delivery, claim_token, str(error)):
            return _current_delivery(delivery_id)
        message = "webhook 投递失败: 目标不可达。"
        raise WebhookDeliveryAttemptError(message, attempts=delivery.attempts) from error
    if not HTTPStatus.OK <= response.status_code < HTTPStatus.MULTIPLE_CHOICES:
        error = f"HTTP {response.status_code}"
        if not _mark_attempt_failed(delivery, claim_token, error):
            return _current_delivery(delivery_id)
        message = f"webhook 投递失败: {error}"
        raise WebhookDeliveryAttemptError(message, attempts=delivery.attempts)
    updated = WebhookDelivery.objects.filter(
        id=delivery.id,
        status=DELIVERY_STATUS_PENDING,
        generation=delivery.generation,
        claim_token=claim_token,
    ).update(
        status=DELIVERY_STATUS_DELIVERED,
        last_error="",
        claim_token="",
        lease_expires_at=None,
        updated_at=timezone.now(),
    )
    current = _current_delivery(delivery_id)
    if updated == 1:
        _record_delivery_event(current, action="webhook_delivered")
    return current


def mark_delivery_exhausted(delivery_id: int, generation: int) -> None:
    updated = WebhookDelivery.objects.filter(
        id=delivery_id,
        status=DELIVERY_STATUS_PENDING,
        generation=generation,
    ).update(
        status=DELIVERY_STATUS_FAILED,
        claim_token="",
        lease_expires_at=None,
        updated_at=timezone.now(),
    )
    if updated != 1:
        return
    delivery = _current_delivery(delivery_id)
    _record_delivery_event(delivery, action="webhook_delivery_exhausted")


def redeliver(delivery: WebhookDelivery) -> WebhookDelivery:
    # 条件更新是 failed → pending 的原子状态迁移; 同一失败行的并发重投只有一个能成功。
    with transaction.atomic():
        updated = WebhookDelivery.objects.filter(
            id=delivery.id,
            status=DELIVERY_STATUS_FAILED,
        ).update(
            status=DELIVERY_STATUS_PENDING,
            attempts=0,
            generation=F("generation") + 1,
            claim_token="",
            lease_expires_at=None,
            last_error="",
            updated_at=timezone.now(),
        )
        if updated != 1:
            raise WebhookRedeliveryConflictError
        delivery.refresh_from_db()
        _schedule_delivery(delivery)
    return delivery


def _schedule_delivery(delivery: WebhookDelivery) -> None:
    _ = enqueue_task(
        event_key=f"webhook-delivery:{delivery.delivery_id}:{delivery.generation}",
        task_name=WEBHOOK_DELIVERY_TASK_NAME,
        args=[delivery.id, delivery.generation],
    )


def _claim_delivery(delivery_id: int, generation: int) -> tuple[WebhookDelivery, str | None]:
    now = timezone.now()
    claim_token = uuid.uuid4().hex
    updated = (
        WebhookDelivery.objects.filter(
            id=delivery_id,
            status=DELIVERY_STATUS_PENDING,
            generation=generation,
        )
        .filter(
            Q(claim_token="")
            | Q(lease_expires_at__isnull=True)
            | Q(lease_expires_at__lte=now),
        )
        .update(
            attempts=F("attempts") + 1,
            claim_token=claim_token,
            lease_expires_at=now + timedelta(seconds=DELIVERY_LEASE_SECONDS),
            updated_at=now,
        )
    )
    delivery = _current_delivery(delivery_id)
    return delivery, claim_token if updated == 1 else None


def _mark_attempt_failed(
    delivery: WebhookDelivery,
    claim_token: str,
    error: str,
) -> bool:
    with transaction.atomic():
        updated = WebhookDelivery.objects.filter(
            id=delivery.id,
            status=DELIVERY_STATUS_PENDING,
            generation=delivery.generation,
            claim_token=claim_token,
        ).update(
            last_error=error,
            claim_token="",
            lease_expires_at=None,
            updated_at=timezone.now(),
        )
        if updated != 1:
            return False
        if delivery.attempts >= len(DELIVERY_RETRY_DELAYS_SECONDS):
            _ = WebhookDelivery.objects.filter(
                id=delivery.id,
                status=DELIVERY_STATUS_PENDING,
                generation=delivery.generation,
            ).update(status=DELIVERY_STATUS_FAILED, updated_at=timezone.now())
            _record_delivery_event(
                _current_delivery(delivery.id),
                action="webhook_delivery_exhausted",
            )
            return True
        delay_index = min(
            delivery.attempts - 1,
            len(DELIVERY_RETRY_DELAYS_SECONDS) - 1,
        )
        _ = enqueue_task(
            event_key=(
                f"webhook-delivery:{delivery.delivery_id}:{delivery.generation}:"
                f"attempt:{delivery.attempts + 1}"
            ),
            task_name=WEBHOOK_DELIVERY_TASK_NAME,
            args=[delivery.id, delivery.generation],
            countdown=DELIVERY_RETRY_DELAYS_SECONDS[delay_index],
        )
    return True


def _current_delivery(delivery_id: int) -> WebhookDelivery:
    return WebhookDelivery.objects.select_related("app").get(id=delivery_id)


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
