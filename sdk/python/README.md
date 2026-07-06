# easyauth-app-sdk

EasyAuth 下游应用接入 SDK(Python)。与任何下游应用的业务代码彻底解耦, 零运行时依赖(FastAPI 集成为可选 extra)。

## 能力

1. **集成描述符端点**: 在下游应用暴露 `GET /.well-known/easyauth-app.json`, 返回应用元数据 + 权限 manifest。EasyAuth 控制台的「自动接入」凭 `下游地址 + app_key` 拉取该描述符, 自动完成应用注册与权限目录导入。
2. **描述符构建/解析**: `build_descriptor_payload` / `parse_descriptor_payload`, 双方共用同一契约。
3. **权限查询客户端**: `EasyAuthAppClient` 以 app 凭据调用 EasyAuth 公共权限查询 API。
4. **webhook 验签**: `verify_webhook` 校验 EasyAuth 反向推送(审批结果/交接事件)的签名与时间戳。
5. **生命周期交接端点**: `easyauth_lifecycle_router` 接收离职/转岗数据交接的
   `lifecycle.handover.preview` / `lifecycle.handover.execute` 同步回调, 验签与事件分发由 SDK 承担。

## 下游集成(FastAPI 示例)

```python
from easyauth_app_sdk.fastapi import create_descriptor_router

def current_manifest() -> dict:
    # 返回本应用当前权限 manifest(schema_version 单调递增, permissions 携带 name/name_en 双语显示名)
    ...

app.include_router(create_descriptor_router(current_manifest, token=可选共享密钥))
```

鉴权二选一(均不配置则端点开放, 建议仅内网部署时使用):

- `token`: 固定共享密钥。EasyAuth 拉取描述符时必须携带 `Authorization: Bearer <token>`。
- `token_validator`: 动态校验回调 `Callable[[str | None], bool]`, 接收从 `Authorization: Bearer` 头解析出的 token(缺失时为 `None`), 返回是否放行。用于对接集成方自有密钥存储或轮换机制:

  ```python
  app.include_router(
      create_descriptor_router(current_manifest, token_validator=my_key_store.is_valid)
  )
  ```

其它约束:

- manifest 中每个权限必须携带 `name`(中文显示名), 可选 `name_en`;这是权限 i18n 从下游传递给 EasyAuth 的唯一通道, EasyAuth 不做任何硬编码兜底。
- `validate_manifest` 与 EasyAuth 导入管线口径一致: `scopes` 必须非空, 且每个权限的 `supported_scopes` 必须是已声明 scope 的子集, 避免下游拿到"本地通过但服务端拒绝"的假绿灯。

## 生命周期交接(离职/转岗)端点

EasyAuth 会向 manifest `lifecycle.handover_url` 声明的地址发同步 POST(两阶段):
`lifecycle.handover.preview` 预演统计(不落库), `lifecycle.handover.execute` 真正执行
(payload `task_id` 为幂等键, 重复 execute 必须安全返回同一结果)。APP 只需实现两个业务回调:

```python
from easyauth_app_sdk import WebhookEvent, easyauth_lifecycle_router

def on_preview(event: WebhookEvent) -> dict:
    # 统计待交接资产, 返回 {"assets": [{"type": ..., "count": ..., "label": ...}]}
    ...

def on_execute(event: WebhookEvent) -> dict:
    # 按 event.payload["task_id"] 幂等执行交接, 返回 {"summary": {...}}
    ...

app.include_router(
    easyauth_lifecycle_router(lambda: settings.easyauth_webhook_secret, on_preview, on_execute)
)
```

验签失败返回 403, `webhook.test` 自动应答 `{"ok": true}`, 未知事件返回 422, 回调异常统一转
500 JSON。`secret_provider` 在每次请求时取密钥, 便于对接热更新的密钥存储。不使用 FastAPI 的
集成方可直接调用纯函数内核 `lifecycle_http_response`。

manifest 可选顶层节(结构由 `validate_manifest` 校验, 描述符 build/parse 原样携带):

```json
{
  "lifecycle": {"handover_url": "/api/v1/easyauth/lifecycle/handover", "onboard_url": null, "capabilities": ["preview", "reassign"]},
  "webhook": {"signing": "hmac-sha256"}
}
```

## 权限查询

```python
from easyauth_app_sdk import EasyAuthAppClient

client = EasyAuthAppClient(base_url="http://easyauth:8001", app_key="myapp", token="eat_...")
snapshot = client.query_user_permissions("ak_uid_xxx")
```

## 测试

```bash
PYTHONPATH=sdk/python/src .venv/bin/pytest sdk/python/tests
```
