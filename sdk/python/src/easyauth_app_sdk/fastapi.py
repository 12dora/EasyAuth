"""FastAPI 集成: 一行挂载描述符端点。

注意: 本模块刻意不使用 ``from __future__ import annotations`` ——
endpoint 的 ``Request`` 注解必须在运行时保持真实类型, 否则 FastAPI
无法从字符串注解解析出请求对象(会误判为查询参数)。
"""

from typing import TYPE_CHECKING

from easyauth_app_sdk.descriptor import DESCRIPTOR_WELL_KNOWN_PATH
from easyauth_app_sdk.integration import DescriptorProvider, descriptor_http_response

if TYPE_CHECKING:
    from fastapi import APIRouter


def create_descriptor_router(
    provider: DescriptorProvider,
    *,
    token: "str | None" = None,
    path: str = DESCRIPTOR_WELL_KNOWN_PATH,
) -> "APIRouter":
    """创建暴露集成描述符的 FastAPI router。

    provider 返回当前 manifest(dict); token 配置后要求 Bearer 认证。
    """
    from fastapi import APIRouter, Request, Response

    router = APIRouter()

    @router.get(path, include_in_schema=False)
    def get_easyauth_descriptor(request: Request) -> Response:
        status_code, headers, body = descriptor_http_response(
            provider,
            authorization=request.headers.get("authorization"),
            required_token=token,
        )
        return Response(content=body, status_code=status_code, media_type=headers["Content-Type"])

    return router
