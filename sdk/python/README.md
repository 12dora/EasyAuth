# easyauth-app-sdk

EasyAuth 下游应用接入 SDK(Python)。与任何下游应用的业务代码彻底解耦, 零运行时依赖(FastAPI 集成为可选 extra)。

## 能力

1. **集成描述符端点**: 在下游应用暴露 `GET /.well-known/easyauth-app.json`, 返回应用元数据 + 权限 manifest。EasyAuth 控制台的「自动接入」凭 `下游地址 + app_key` 拉取该描述符, 自动完成应用注册与权限目录导入。
2. **描述符构建/解析**: `build_descriptor_payload` / `parse_descriptor_payload`, 双方共用同一契约。
3. **权限查询客户端**: `EasyAuthAppClient` 以 app 凭据调用 EasyAuth 公共权限查询 API。

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
