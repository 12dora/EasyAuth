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

## 权限模板自动同步(下游主动推送)

自动接入解决"首次注册";之后下游新增模块/权限时,不需要管理员再回控制台点自动接入:

- 应用侧 API: `POST /api/v1/apps/{app_key}/manifest-sync`,鉴权用下游自己的静态
  token(`Authorization: Bearer eat_...`),入参 `{"manifest": {...}, "base_url"?: "..."}`。
  应用必须已注册(本端点不建新应用);`base_url` 可选,用于把 manifest lifecycle 里的
  相对路径补全成 EasyAuth 可回调的 webhook 绝对地址。
- 版本/幂等语义与自动接入完全一致(共享 `applications.manifest_import.sync_app_manifest`):
  同版本同内容 `already_up_to_date=true`;同版本不同内容 409(提示下游递增版本);
  版本递增则导入并落新 `PermissionTemplateVersion`。
- 审计动作: `app_manifest_synced`(actor_type=`app`)。
- 下游推荐姿势(EasyTrade 已内置): 应用启动时后台推送一次,失败只告警不阻塞启动。
  于是"新增模块 → schema_version +1 → 部署重启"即完成同步;内容变了但忘了递增版本时,
  启动日志会出现 `easyauth_manifest_push_conflict` 提示。相关开关:
  `EASYAUTH_MANIFEST_AUTO_PUSH`(默认开)、`EASYAUTH_MANIFEST_PUSH_BASE_URL`(可选)。
- manifest 的 `lifecycle`/`webhook` 可选节会在导入时回填应用的 Webhook 配置
  (交接/入职事件 URL),但控制台管理员改过的值优先(`updated_by` 非 manifest 时不覆盖)。

## 参考实现

EasyTrade: `backend/vendor/easyauth-app-sdk`(vendored 副本,来源见 `VENDORED.md`)、`backend/app/api/v1/easyauth_descriptor.py`(挂载)、`backend/app/domain/authz/permission_display.py`(权限双语命名事实源)。
