from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta
from http import HTTPStatus
from json import dumps
from typing import TYPE_CHECKING, Final

from django.db import transaction
from django.db.models import F
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
    WebhookHttpResponse,
    WebhookRequestPolicy,
    WebhookTransportError,
    post_webhook,
)

if TYPE_CHECKING:
    from easyauth.applications.models import App
    from easyauth.applications.ops_models import JsonValue

# 指数退避重试间隔(秒): 首次尝试后最多重试 5 次(§5.1)。
DELIVERY_RETRY_DELAYS_SECONDS: Final[tuple[int, ...]] = (60, 300, 1800, 7200, 21600)
MAX_DELIVERY_ATTEMPTS: Final = 1 + len(DELIVERY_RETRY_DELAYS_SECONDS)
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
WEBHOOK_DELIVERY_WATCHDOG_TASK_NAME: Final = "easyauth.webhooks.recover_expired_leases"
WEBHOOK_REDELIVERY_CONFLICT_MESSAGE: Final = "该投递已不处于失败状态, 不能重复重投。"
WEBHOOK_UNEXPECTED_ERROR_PREFIX: Final = "非预期异常"
WEBHOOK_RECOVERY_ERROR: Final = "投递租约过期, 已创建恢复尝试。"
WEBHOOK_RECOVERY_BATCH_SIZE: Final = 100
WEBHOOK_PAYLOAD_MINIMIZED_MESSAGE: Final = "该投递原文已超过保留窗口并被最小化, 不能重投。"


class WebhookNotConfiguredError(RuntimeError):
    def __init__(self) -> None:
        super().__init__(WEBHOOK_NOT_CONFIGURED_MESSAGE)


class WebhookEndpointRejectedError(WebhookNotConfiguredError):
    def __init__(self) -> None:
        RuntimeError.__init__(self, WEBHOOK_ENDPOINT_REJECTED_MESSAGE)


class WebhookDeliveryAttemptError(RuntimeError):
    attempts: int
    retry_scheduled: bool

    def __init__(self, message: str, *, attempts: int, retry_scheduled: bool) -> None:
        super().__init__(message)
        self.attempts = attempts
        self.retry_scheduled = retry_scheduled


class WebhookRedeliveryConflictError(RuntimeError):
    def __init__(self, message: str = WEBHOOK_REDELIVERY_CONFLICT_MESSAGE) -> None:
        super().__init__(message)


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
            next_attempt_at=timezone.now(),
        )
        _schedule_delivery(delivery)
    return delivery


def attempt_delivery(
    delivery_id: int, generation: int, expected_attempt: int = 1
) -> WebhookDelivery:
    """执行一次投递尝试; 失败时抛 WebhookDeliveryAttemptError 交由任务层重试。"""
    delivery, claim_token = _claim_delivery(delivery_id, generation, expected_attempt)
    if claim_token is None:
        return delivery
    try:
        response = _post_delivery(delivery)
    except WebhookNotConfiguredError:
        raise
    except WebhookTransportError as error:
        return _handle_transport_failure(delivery, claim_token, error)
    except BaseException as error:
        if not isinstance(error, Exception):
            raise
        return _handle_unexpected_failure(delivery, claim_token, error)
    return _handle_delivery_response(delivery, claim_token, response)


def _post_delivery(delivery: WebhookDelivery) -> WebhookHttpResponse:
    endpoint = resolve_endpoint(delivery.app, url=delivery.target_url)
    # 复制 payload 后强制注入 event_type, 再序列化签名(契约 §10.1 / 01 §8.1)。
    # webhook.test 等经 enqueue_delivery 落库的 body 原先不含该字段; 若不在此注入,
    # 下游 SDK 会在 webhook.test 短路前因 event_type 缺失返回 422。
    signed_payload = dict(delivery.payload)
    signed_payload["event_type"] = delivery.event_type
    body = dumps(signed_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    timestamp = str(int(timezone.now().timestamp()))
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        EVENT_HEADER: delivery.event_type,
        DELIVERY_HEADER: delivery.delivery_id,
        TIMESTAMP_HEADER: timestamp,
        SIGNATURE_HEADER: sign_webhook_body(
            secret=endpoint.config.secret,
            timestamp=timestamp,
            body=body,
        ),
    }
    return post_webhook(
        url=endpoint.url,
        allowed_hosts=endpoint.allowed_hosts,
        body=body,
        headers=headers,
        policy=DELIVERY_REQUEST_POLICY,
    )


def _handle_transport_failure(
    delivery: WebhookDelivery,
    claim_token: str,
    error: WebhookTransportError,
) -> WebhookDelivery:
    retry_scheduled = _mark_attempt_failed(delivery, claim_token, str(error))
    if retry_scheduled is None:
        return _current_delivery(delivery.id)
    message = "webhook 投递失败: 目标不可达。"
    raise WebhookDeliveryAttemptError(
        message,
        attempts=delivery.attempts,
        retry_scheduled=retry_scheduled,
    ) from error


def _handle_unexpected_failure(
    delivery: WebhookDelivery,
    claim_token: str,
    error: Exception,
) -> WebhookDelivery:
    retry_scheduled = _mark_attempt_failed(
        delivery,
        claim_token,
        f"{WEBHOOK_UNEXPECTED_ERROR_PREFIX}: {type(error).__name__}: {error}",
    )
    if retry_scheduled is None:
        return _current_delivery(delivery.id)
    message = "webhook 投递失败: 非预期异常已记录并等待恢复。"
    raise WebhookDeliveryAttemptError(
        message,
        attempts=delivery.attempts,
        retry_scheduled=retry_scheduled,
    ) from error


def _handle_delivery_response(
    delivery: WebhookDelivery,
    claim_token: str,
    response: WebhookHttpResponse,
) -> WebhookDelivery:
    if HTTPStatus.OK <= response.status_code < HTTPStatus.MULTIPLE_CHOICES:
        return _mark_attempt_delivered(delivery, claim_token)
    return _handle_http_failure(delivery, claim_token, response)


def _handle_http_failure(
    delivery: WebhookDelivery,
    claim_token: str,
    response: WebhookHttpResponse,
) -> WebhookDelivery:
    error = f"HTTP {response.status_code}"
    retry_delay = (
        _retry_after_seconds(response.retry_after)
        if response.status_code == HTTPStatus.TOO_MANY_REQUESTS
        else None
    )
    retry_scheduled = _mark_attempt_failed(
        delivery,
        claim_token,
        error,
        retryable=_is_retryable_status(response.status_code),
        retry_delay_seconds=retry_delay,
    )
    if retry_scheduled is None:
        return _current_delivery(delivery.id)
    message = f"webhook 投递失败: {error}"
    raise WebhookDeliveryAttemptError(
        message,
        attempts=delivery.attempts,
        retry_scheduled=retry_scheduled,
    )


def _mark_attempt_delivered(delivery: WebhookDelivery, claim_token: str) -> WebhookDelivery:
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
        next_attempt_at=timezone.now(),
        updated_at=timezone.now(),
    )
    current = _current_delivery(delivery.id)
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
    if delivery.payload_minimized_at is not None:
        raise WebhookRedeliveryConflictError(WEBHOOK_PAYLOAD_MINIMIZED_MESSAGE)
    with transaction.atomic():
        updated = WebhookDelivery.objects.filter(
            id=delivery.id,
            status=DELIVERY_STATUS_FAILED,
            payload_minimized_at__isnull=True,
        ).update(
            status=DELIVERY_STATUS_PENDING,
            attempts=0,
            generation=F("generation") + 1,
            claim_token="",
            lease_expires_at=None,
            next_attempt_at=timezone.now(),
            last_error="",
            updated_at=timezone.now(),
        )
        if updated != 1:
            raise WebhookRedeliveryConflictError
        delivery.refresh_from_db()
        _schedule_delivery(delivery)
    return delivery


def recover_expired_delivery_leases(
    *,
    batch_size: int = WEBHOOK_RECOVERY_BATCH_SIZE,
) -> int:
    """扫描过期租约并推进 generation, 由新任务显式接管。"""
    if batch_size <= 0:
        return 0
    now = timezone.now()
    with transaction.atomic():
        deliveries = list(
            WebhookDelivery.objects.select_for_update()
            .filter(
                status=DELIVERY_STATUS_PENDING,
                claim_token__gt="",
                lease_expires_at__lte=now,
            )
            .order_by("lease_expires_at", "id")[:batch_size],
        )
        for delivery in deliveries:
            delivery.generation += 1
            delivery.claim_token = ""
            delivery.lease_expires_at = None
            delivery.last_error = WEBHOOK_RECOVERY_ERROR
            delivery.updated_at = now
        if deliveries:
            _ = WebhookDelivery.objects.bulk_update(
                deliveries,
                fields=(
                    "generation",
                    "claim_token",
                    "lease_expires_at",
                    "last_error",
                    "updated_at",
                ),
            )
            for delivery in deliveries:
                _schedule_delivery(delivery)
                _record_delivery_event(delivery, action="webhook_delivery_recovery_scheduled")
    return len(deliveries)


def _schedule_delivery(delivery: WebhookDelivery) -> None:
    _ = enqueue_task(
        event_key=f"webhook-delivery:{delivery.delivery_id}:{delivery.generation}",
        task_name=WEBHOOK_DELIVERY_TASK_NAME,
        args=[delivery.id, delivery.generation, delivery.attempts + 1],
    )


def _claim_delivery(
    delivery_id: int,
    generation: int,
    expected_attempt: int,
) -> tuple[WebhookDelivery, str | None]:
    now = timezone.now()
    claim_token = uuid.uuid4().hex
    updated = WebhookDelivery.objects.filter(
        id=delivery_id,
        status=DELIVERY_STATUS_PENDING,
        generation=generation,
        attempts=expected_attempt - 1,
        next_attempt_at__lte=now,
        claim_token="",
        lease_expires_at__isnull=True,
    ).update(
        attempts=F("attempts") + 1,
        claim_token=claim_token,
        lease_expires_at=now + timedelta(seconds=DELIVERY_LEASE_SECONDS),
        updated_at=now,
    )
    delivery = _current_delivery(delivery_id)
    return delivery, claim_token if updated == 1 else None


def _mark_attempt_failed(
    delivery: WebhookDelivery,
    claim_token: str,
    error: str,
    *,
    retryable: bool = True,
    retry_delay_seconds: int | None = None,
) -> bool | None:
    with transaction.atomic():
        should_retry = retryable and delivery.attempts < MAX_DELIVERY_ATTEMPTS
        delay_index = min(delivery.attempts - 1, len(DELIVERY_RETRY_DELAYS_SECONDS) - 1)
        delay_seconds = (
            DELIVERY_RETRY_DELAYS_SECONDS[delay_index]
            if retry_delay_seconds is None
            else retry_delay_seconds
        )
        next_attempt_at = timezone.now() + timedelta(seconds=delay_seconds)
        updated = WebhookDelivery.objects.filter(
            id=delivery.id,
            status=DELIVERY_STATUS_PENDING,
            generation=delivery.generation,
            claim_token=claim_token,
        ).update(
            last_error=error,
            claim_token="",
            lease_expires_at=None,
            next_attempt_at=next_attempt_at if should_retry else timezone.now(),
            status=DELIVERY_STATUS_PENDING if should_retry else DELIVERY_STATUS_FAILED,
            updated_at=timezone.now(),
        )
        if updated != 1:
            return None
        if not should_retry:
            _record_delivery_event(
                _current_delivery(delivery.id),
                action="webhook_delivery_exhausted",
            )
            return False
        _ = enqueue_task(
            event_key=(
                f"webhook-delivery:{delivery.delivery_id}:{delivery.generation}:"
                f"attempt:{delivery.attempts + 1}"
            ),
            task_name=WEBHOOK_DELIVERY_TASK_NAME,
            args=[delivery.id, delivery.generation, delivery.attempts + 1],
            countdown=delay_seconds,
        )
    return True


def _is_retryable_status(status_code: int) -> bool:
    return status_code in {
        HTTPStatus.BAD_REQUEST,
        HTTPStatus.LOCKED,
        HTTPStatus.TOO_MANY_REQUESTS,
    } or (status_code >= HTTPStatus.INTERNAL_SERVER_ERROR)


def _retry_after_seconds(value: str) -> int | None:
    if not value or not value.isascii() or not value.isdecimal():
        return None
    seconds = int(value)
    if seconds < 1:
        return None
    return min(seconds, DELIVERY_RETRY_DELAYS_SECONDS[-1])


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
