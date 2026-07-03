# easyauth-app-sdk 下游集成指南

SDK 位于仓库 `sdk/python`(包名 `easyauth-app-sdk`,零运行时依赖,FastAPI 集成为可选 extra),与任何下游应用的业务代码彻底解耦。下游集成后,EasyAuth 控制台的「自动接入」凭 `下游地址 + app_key` 即可完成应用注册与权限目录导入,无需手动录入。

## 契约

- **集成描述符**: 下游在 `GET /.well-known/easyauth-app.json` 返回 `{descriptor_version, app{app_key,name,description}, manifest, sdk}`;`manifest` 即 EasyAuth App manifest(schema_version 单调递增)。
- **权限双语显示名**: manifest 每个权限必须携带 `name`(中文),可选 `name_en`;这是权限 i18n 从下游传递给 EasyAuth 的唯一通道,EasyAuth 门户/控制台按用户语言展示,不做硬编码兜底。
- **端点保护(可选)**: 下游配置共享密钥后,描述符端点要求 `Authorization: Bearer <token>`;EasyAuth 自动接入表单可填写该 token。

## 下游集成步骤(FastAPI 示例)

1. 安装 SDK(EasyTrade 采用 vendored 源码 + Dockerfile `pip install ./vendor/easyauth-app-sdk`)。
2. 挂载描述符端点:

   ```python
   from easyauth_app_sdk.fastapi import create_descriptor_router

   app.include_router(create_descriptor_router(current_manifest_provider, token=可选共享密钥))
   ```

3. `current_manifest_provider` 返回当前权限 manifest;契约变更时递增 schema_version(EasyTrade 用 `EASYAUTH_MANIFEST_SCHEMA_VERSION` 环境变量承载)。
4. 权限查询可复用 SDK 客户端 `EasyAuthAppClient(base_url, app_key, token).query_user_permissions(user_id)`,也可沿用自有客户端。

非 FastAPI 框架用 `descriptor_http_response()` 纯函数内核自行封装路由。

## EasyAuth 侧

- 自动接入 API: `POST /console/api/v1/apps/auto-onboarding`(系统管理员),入参 `{base_url, app_key, descriptor_token?}`。
- 幂等口径: 同 schema_version 同内容返回 `already_up_to_date=true`;同版本不同内容返回 409,必须由下游递增版本(下游是 manifest 事实源,EasyAuth 不代为改版本)。
- 审计动作: `app_auto_onboarded`。

## 参考实现

EasyTrade: `backend/vendor/easyauth-app-sdk`(vendored 副本,来源见 `VENDORED.md`)、`backend/app/api/v1/easyauth_descriptor.py`(挂载)、`backend/app/domain/authz/permission_display.py`(权限双语命名事实源)。
