"""EasyAuth 下游应用接入 SDK。

提供三块能力, 与任何下游应用的业务代码解耦:

1. 集成描述符: 下游应用在 ``/.well-known/easyauth-app.json`` 暴露应用元数据与权限 manifest,
   EasyAuth 控制台凭 ``下游地址 + app_key`` 即可自动完成注册与目录导入。
2. 描述符 HTTP 端点: 纯函数内核 + 可选 FastAPI 路由封装。
3. 权限查询客户端: 以 app 凭据调用 EasyAuth 公共权限查询 API。
"""

from easyauth_app_sdk.client import EasyAuthAppClient, EasyAuthClientError
from easyauth_app_sdk.descriptor import (
    DESCRIPTOR_VERSION,
    DESCRIPTOR_WELL_KNOWN_PATH,
    SDK_NAME,
    SDK_VERSION,
    AppDescriptor,
    DescriptorError,
    build_descriptor_payload,
    parse_descriptor_payload,
)
from easyauth_app_sdk.integration import (
    DescriptorProvider,
    TokenValidator,
    bearer_token,
    descriptor_http_response,
)
from easyauth_app_sdk.manifest import ManifestValidationError, validate_manifest

__all__ = [
    "DESCRIPTOR_VERSION",
    "DESCRIPTOR_WELL_KNOWN_PATH",
    "SDK_NAME",
    "SDK_VERSION",
    "AppDescriptor",
    "DescriptorError",
    "DescriptorProvider",
    "EasyAuthAppClient",
    "EasyAuthClientError",
    "ManifestValidationError",
    "TokenValidator",
    "bearer_token",
    "build_descriptor_payload",
    "descriptor_http_response",
    "parse_descriptor_payload",
    "validate_manifest",
]
