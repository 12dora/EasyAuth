"""FastAPI 集成: 一行挂载描述符端点与生命周期交接端点。

注意: 本模块刻意不使用 ``from __future__ import annotations`` ——
endpoint 的 ``Request`` 注解必须在运行时保持真实类型, 否则 FastAPI
无法从字符串注解解析出请求对象(会误判为查询参数)。
"""

from typing import TYPE_CHECKING

from easyauth_app_sdk.descriptor import DESCRIPTOR_WELL_KNOWN_PATH
from easyauth_app_sdk.integration import (
    DescriptorProvider,
    TokenValidator,
    descriptor_http_response,
)
from easyauth_app_sdk.lifecycle import (
    DEFAULT_HANDOVER_PATH,
    DEFAULT_MAX_BODY_BYTES,
    BodyTooLargeError,
    LifecycleCallbacks,
    SecretProvider,
    _validate_signature_failure_status,
    body_too_large_response,
    lifecycle_http_response,
    read_bounded_body,
)

if TYPE_CHECKING:
    from fastapi import APIRouter, Response


def create_descriptor_router(
    provider: DescriptorProvider,
    *,
    token: "str | None" = None,
    token_validator: "TokenValidator | None" = None,
    path: str = DESCRIPTOR_WELL_KNOWN_PATH,
) -> "APIRouter":
    """创建暴露集成描述符的 FastAPI router。

    provider 返回当前 manifest(dict); 鉴权二选一: token 为固定共享密钥,
    token_validator 为动态校验回调(对接集成方自有密钥存储)。
    """
    from fastapi import APIRouter, Request, Response

    router = APIRouter()

    @router.get(path, include_in_schema=False)
    def get_easyauth_descriptor(request: Request) -> Response:
        status_code, headers, body = descriptor_http_response(
            provider,
            authorization=request.headers.get("authorization"),
            required_token=token,
            token_validator=token_validator,
        )
        return Response(content=body, status_code=status_code, media_type=headers["Content-Type"])

    return router


def easyauth_lifecycle_router(
    secret_provider: SecretProvider,
    callbacks: LifecycleCallbacks,
    *,
    path: str = DEFAULT_HANDOVER_PATH,
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
    signature_failure_status: int = 403,
) -> "APIRouter":
    """创建接收 EasyAuth 生命周期交接 webhook 的 FastAPI router。

    验签/事件分发/异常边界均由 SDK 承担, APP 实现业务回调:
    ``callbacks.on_handover_preview`` 返回 preview 响应体
    (``{"snapshot_token", "assets": [...]}``, 不落库),
    ``callbacks.on_handover_items`` 返回 items 响应体
    (明细分页; **必填**, 接线期失败优于运行时 422),
    ``callbacks.on_handover_execute`` 返回 execute 响应体(``{"summary": {...}}``, 按
    ``(task_id, generation, batch_id)`` 幂等)。``secret_provider`` 在每次请求时取密钥,
    避免 import 期读配置。

    ``signature_failure_status`` 控制签名/鉴权头失败的 HTTP 状态码(默认 403;
    EasyProject 传 401)。时间戳超窗始终 400, 不受此参数影响。

    在验签前先按 ``max_body_bytes`` 有界读取请求体, 超限返回 413。
    业务错误若带 ``retry_after``, 会透传为响应头 ``Retry-After``。
    """
    from fastapi import APIRouter, Request, Response

    _validate_signature_failure_status(signature_failure_status)

    router = APIRouter()

    @router.post(path, include_in_schema=False)
    async def post_easyauth_lifecycle_handover(request: Request) -> Response:
        try:
            raw_body = await read_bounded_body(request, max_body_bytes=max_body_bytes)
        except BodyTooLargeError:
            status_code, headers, body = body_too_large_response(max_body_bytes)
            return _as_response(status_code, headers, body)
        status_code, headers, body = lifecycle_http_response(
            secret_provider=secret_provider,
            headers=dict(request.headers),
            raw_body=raw_body,
            callbacks=callbacks,
            signature_failure_status=signature_failure_status,
        )
        return _as_response(status_code, headers, body)

    return router


def _as_response(status_code: int, headers: dict[str, str], body: bytes) -> "Response":
    """把内核 ``(status, headers, body)`` 转成 Starlette Response, 保留 Retry-After 等头。"""
    from fastapi import Response

    media_type = headers.get("Content-Type")
    extra = {key: value for key, value in headers.items() if key.lower() != "content-type"}
    return Response(
        content=body,
        status_code=status_code,
        media_type=media_type,
        headers=extra or None,
    )
