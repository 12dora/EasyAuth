"""EasyAuth 下游应用接入 SDK。

提供五块能力, 与任何下游应用的业务代码解耦:

1. 集成描述符: 下游应用在 ``/.well-known/easyauth-app.json`` 暴露应用元数据与权限 manifest,
   EasyAuth 控制台凭 ``下游地址 + app_key`` 即可自动完成注册与目录导入。
2. 描述符 HTTP 端点: 纯函数内核 + 可选 FastAPI 路由封装。
3. API 客户端: 以 app 凭据调用 EasyAuth 权限查询与审批中心(create/get_approval)。
4. webhook 验签: 校验 EasyAuth 反向推送(审批结果/交接事件)的签名与时间戳。
5. 生命周期交接端点: 接收离职/转岗数据交接的 preview/execute 同步回调,
   纯函数内核 + 可选 FastAPI 路由封装(``easyauth_lifecycle_router``)。
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
from easyauth_app_sdk.fastapi import easyauth_lifecycle_router
from easyauth_app_sdk.integration import (
    DescriptorProvider,
    TokenValidator,
    bearer_token,
    descriptor_http_response,
)
from easyauth_app_sdk.lifecycle import (
    DEFAULT_HANDOVER_PATH,
    HANDOVER_EXECUTE_EVENT,
    HANDOVER_PREVIEW_EVENT,
    WEBHOOK_TEST_EVENT,
    HandoverCallback,
    SecretProvider,
    lifecycle_http_response,
)
from easyauth_app_sdk.manifest import ManifestValidationError, validate_manifest
from easyauth_app_sdk.webhook import (
    WebhookEvent,
    WebhookVerificationError,
    verify_webhook,
)

__all__ = [
    "DEFAULT_HANDOVER_PATH",
    "DESCRIPTOR_VERSION",
    "DESCRIPTOR_WELL_KNOWN_PATH",
    "HANDOVER_EXECUTE_EVENT",
    "HANDOVER_PREVIEW_EVENT",
    "SDK_NAME",
    "SDK_VERSION",
    "WEBHOOK_TEST_EVENT",
    "AppDescriptor",
    "DescriptorError",
    "DescriptorProvider",
    "EasyAuthAppClient",
    "EasyAuthClientError",
    "HandoverCallback",
    "ManifestValidationError",
    "SecretProvider",
    "TokenValidator",
    "WebhookEvent",
    "WebhookVerificationError",
    "bearer_token",
    "build_descriptor_payload",
    "descriptor_http_response",
    "easyauth_lifecycle_router",
    "lifecycle_http_response",
    "parse_descriptor_payload",
    "validate_manifest",
    "verify_webhook",
]
