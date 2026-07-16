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
    HandoverCallback,
    SecretProvider,
    body_too_large_response,
    lifecycle_http_response,
    read_bounded_body,
)

if TYPE_CHECKING:
    from fastapi import APIRouter


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
    on_handover_preview: HandoverCallback,
    on_handover_execute: HandoverCallback,
    *,
    path: str = DEFAULT_HANDOVER_PATH,
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
) -> "APIRouter":
    """创建接收 EasyAuth 生命周期交接 webhook 的 FastAPI router。

    验签/事件分发/异常边界均由 SDK 承担, APP 只需实现两个业务回调:
    ``on_handover_preview`` 返回 preview 响应体(``{"assets": [...]}``, 不落库),
    ``on_handover_execute`` 返回 execute 响应体(``{"summary": {...}}``, 按
    ``payload.task_id`` 幂等)。``secret_provider`` 在每次请求时取密钥,
    避免 import 期读配置。

    在验签前先按 ``max_body_bytes`` 有界读取请求体, 超限返回 413。
    """
    from fastapi import APIRouter, Request, Response

    router = APIRouter()

    @router.post(path, include_in_schema=False)
    async def post_easyauth_lifecycle_handover(request: Request) -> Response:
        try:
            raw_body = await read_bounded_body(request, max_body_bytes=max_body_bytes)
        except BodyTooLargeError:
            status_code, headers, body = body_too_large_response(max_body_bytes)
            return Response(
                content=body,
                status_code=status_code,
                media_type=headers["Content-Type"],
            )
        status_code, headers, body = lifecycle_http_response(
            secret_provider=secret_provider,
            headers=dict(request.headers),
            raw_body=raw_body,
            on_handover_preview=on_handover_preview,
            on_handover_execute=on_handover_execute,
        )
        return Response(content=body, status_code=status_code, media_type=headers["Content-Type"])

    return router
