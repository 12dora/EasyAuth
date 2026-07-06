from __future__ import annotations

from json import JSONDecodeError, dumps, loads
from typing import TYPE_CHECKING, Final, Self, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.utils import timezone

from easyauth.webhooks.delivery import resolve_endpoint
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

# 交接钩子是同步请求-响应(§2.3): preview 要立即回显影响面, execute 要拿到交接摘要,
# 与异步投递通道(§5.1)共用同一签名规范。
HOOK_TIMEOUT_SECONDS: Final = 30.0


class _ReadableResponse:
    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    def read(self) -> bytes: ...


class HookCallError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code: int | None = status_code


def signed_hook_post(
    *,
    app: App,
    url: str,
    event_type: str,
    delivery_id: str,
    payload: dict[str, JsonValue],
) -> dict[str, JsonValue]:
    """向 APP 发一次带 §5.1 签名的同步 POST, 返回其 JSON 响应。"""
    endpoint = resolve_endpoint(app, url=url)
    body = dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
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
    request = Request(endpoint.url, data=body, headers=headers, method="POST")  # noqa: S310 - URL 来自控制台管理员配置。
    try:
        with cast(
            "_ReadableResponse",
            urlopen(request, timeout=HOOK_TIMEOUT_SECONDS),  # noqa: S310
        ) as response:
            raw = response.read()
    except HTTPError as error:
        message = f"应用交接接口返回 HTTP {error.code}。"
        raise HookCallError(message, status_code=error.code) from error
    except (URLError, TimeoutError) as error:
        message = "应用交接接口不可达。"
        raise HookCallError(message) from error
    if not raw:
        return {}
    try:
        parsed = cast("object", loads(raw.decode("utf-8")))
    except (JSONDecodeError, UnicodeDecodeError) as error:
        message = "应用交接接口响应不是有效 JSON。"
        raise HookCallError(message) from error
    if not isinstance(parsed, dict):
        message = "应用交接接口响应必须是 JSON 对象。"
        raise HookCallError(message)
    return cast("dict[str, JsonValue]", parsed)
