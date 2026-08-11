from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from json import JSONDecodeError, dumps, loads
from typing import TYPE_CHECKING, Final, cast

from django.utils import timezone

from easyauth.webhooks.delivery import resolve_endpoint
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
    get_webhook,
    post_webhook,
)

if TYPE_CHECKING:
    from easyauth.applications.models import App
    from easyauth.applications.ops_models import JsonValue

# 交接钩子是同步请求-响应(§2.3): preview 要立即回显影响面, execute 要拿到交接摘要,
# 与异步投递通道(§5.1)共用同一签名规范。
HOOK_CONNECT_TIMEOUT_SECONDS: Final = 5.0
HOOK_TOTAL_TIMEOUT_SECONDS: Final = 30.0
HOOK_MAX_RESPONSE_BYTES: Final = 256 * 1024
HOOK_REQUEST_POLICY: Final = WebhookRequestPolicy(
    connect_timeout_seconds=HOOK_CONNECT_TIMEOUT_SECONDS,
    total_timeout_seconds=HOOK_TOTAL_TIMEOUT_SECONDS,
    max_response_bytes=HOOK_MAX_RESPONSE_BYTES,
)


class HookCallError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        payload: dict[str, JsonValue] | None = None,
        raw_body: str = "",
        location: str = "",
    ) -> None:
        super().__init__(message)
        self.status_code: int | None = status_code
        self.payload = payload
        self.raw_body = raw_body
        self.location = location


@dataclass(frozen=True, slots=True)
class HookResponse:
    status_code: int
    location: str
    payload: dict[str, JsonValue]
    raw_body: str = ""


def signed_hook_post(
    *,
    app: App,
    url: str,
    event_type: str,
    delivery_id: str,
    payload: dict[str, JsonValue],
) -> HookResponse:
    """向 APP 发一次带 §5.1 签名的同步 POST, 返回其 JSON 响应。

    在序列化与签名之前复制 payload 并强制写入 ``event_type``(契约 §10.1 /
    设计 01 §8.1): body 在签名覆盖范围内, 供下游 SDK 与事件头做一致性校验。
    """
    endpoint = resolve_endpoint(app, url=url)
    signed_payload = dict(payload)
    signed_payload["event_type"] = event_type
    body = dumps(signed_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    timestamp = str(int(timezone.now().timestamp()))
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        EVENT_HEADER: event_type,
        DELIVERY_HEADER: delivery_id,
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
            policy=HOOK_REQUEST_POLICY,
        )
    except WebhookTransportError as error:
        message = "应用交接接口不可达。"
        raise HookCallError(message) from error
    return _parse_hook_response(response)


def signed_hook_get(
    *,
    app: App,
    url: str,
    event_type: str,
    delivery_id: str,
) -> HookResponse:
    """查询 APP 异步交接状态; Location 仍受同 App 域名 allowlist 与 SSRF 校验。"""
    endpoint = resolve_endpoint(app, url=url)
    body = b""
    timestamp = str(int(timezone.now().timestamp()))
    headers = {
        "Accept": "application/json",
        EVENT_HEADER: event_type,
        DELIVERY_HEADER: delivery_id,
        TIMESTAMP_HEADER: timestamp,
        SIGNATURE_HEADER: sign_webhook_body(
            secret=endpoint.config.secret,
            timestamp=timestamp,
            body=body,
        ),
    }
    try:
        response = get_webhook(
            url=endpoint.url,
            allowed_hosts=endpoint.allowed_hosts,
            headers=headers,
            policy=HOOK_REQUEST_POLICY,
        )
    except WebhookTransportError as error:
        message = "应用交接状态接口不可达。"
        raise HookCallError(message) from error
    return _parse_hook_response(response)


def _parse_hook_response(response: WebhookHttpResponse) -> HookResponse:
    raw = response.body
    if not raw:
        if HTTPStatus.MULTIPLE_CHOICES <= response.status_code < HTTPStatus.BAD_REQUEST:
            message = f"应用交接接口返回 HTTP {response.status_code}。"
            raise HookCallError(
                message,
                status_code=response.status_code,
                location=response.location,
            )
        return HookResponse(
            status_code=response.status_code,
            location=response.location,
            payload={},
        )
    decoded = raw.decode("utf-8", errors="replace")
    try:
        parsed = cast("object", loads(decoded))
    except (JSONDecodeError, UnicodeDecodeError) as error:
        if not HTTPStatus.OK <= response.status_code < HTTPStatus.MULTIPLE_CHOICES:
            return HookResponse(
                status_code=response.status_code,
                location=response.location,
                payload={},
                raw_body=decoded,
            )
        message = "应用交接接口响应不是有效 JSON。"
        raise HookCallError(message, raw_body=decoded) from error
    if not isinstance(parsed, dict):
        if not HTTPStatus.OK <= response.status_code < HTTPStatus.MULTIPLE_CHOICES:
            return HookResponse(
                status_code=response.status_code,
                location=response.location,
                payload={},
                raw_body=decoded,
            )
        message = "应用交接接口响应必须是 JSON 对象。"
        raise HookCallError(message, raw_body=decoded)
    if HTTPStatus.MULTIPLE_CHOICES <= response.status_code < HTTPStatus.BAD_REQUEST:
        message = f"应用交接接口返回 HTTP {response.status_code}。"
        raise HookCallError(
            message,
            status_code=response.status_code,
            payload=cast("dict[str, JsonValue]", parsed),
            raw_body=decoded,
            location=response.location,
        )
    return HookResponse(
        status_code=response.status_code,
        location=response.location,
        payload=cast("dict[str, JsonValue]", parsed),
        raw_body=decoded,
    )
