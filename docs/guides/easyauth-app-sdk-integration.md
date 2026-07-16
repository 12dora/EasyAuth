# easyauth-app-sdk 下游集成指南

SDK 位于仓库 `sdk/python`(包名 `easyauth-app-sdk`,零运行时依赖,FastAPI 集成为可选 extra),与任何下游应用的业务代码彻底解耦。下游集成后,EasyAuth 控制台的「自动接入」凭 `下游地址 + app_key` 即可完成应用注册与权限目录导入,无需手动录入。

## 契约

- **集成描述符**: 下游在 `GET /.well-known/easyauth-app.json` 返回 `{descriptor_version, app{app_key,name,description}, manifest, sdk}`;`manifest` 即 EasyAuth App manifest(schema_version 单调递增)。
- **权限双语显示名**: manifest 每个权限必须携带 `name`(中文),可选 `name_en`;这是权限 i18n 从下游传递给 EasyAuth 的唯一通道,EasyAuth 门户/控制台按用户语言展示,不做硬编码兜底。
- **端点保护(可选)**: 下游配置共享密钥后,描述符端点要求 `Authorization: Bearer <token>`;EasyAuth 自动接入表单可填写该 token。
- **目录数据滞后**: 用户目录来自钉钉镜像同步,滞后上游最多一个同步周期(300s),不保证实时。

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

## 用户目录与钉钉通知

SDK `0.2.0` 起,`EasyAuthAppClient` 提供用户目录查询与钉钉工作通知两个平台能力。

### 能力开关前置条件

- 两能力默认关闭,须由 **EasyAuth 超管** 在控制台为该 app 开通
  (`AppCapability.enabled`);manifest 顶层可申明 `"capabilities": ["directory", "notify"]`
  供控制台展示「该 app 请求了哪些平台能力」,但 **申明 ≠ 开通**,导入不会自动翻转开关。
- 未开通时目录/通知 API 返回 `403 PERMISSION_DENIED`(message 分别为
  「应用未开通目录能力。」/「应用未开通通知能力。」);接入前先确认超管已开启。

### `dt:` 引用兜底惯用法

目录全量含未登录过 EasyAuth 的员工,其 `user_id` 可为 `null`,但 `dingtalk_user_id` 恒存在。
引用人时统一用:

```python
ref = user["user_id"] or f"{DINGTALK_REF_PREFIX}{user['dingtalk_user_id']}"
# 等价于 user["user_id"] or f"dt:{user['dingtalk_user_id']}"
```

目录详情、主管、下属、通知收件人均接受 `user_id` 或 `dt:<钉钉userid>` 两种引用。

### 推荐链路: 先查目录再通知

```python
from easyauth_app_sdk import (
    DINGTALK_REF_PREFIX,
    NOTIFY_TEMPLATE_ACTION_CARD,
    EasyAuthAppClient,
)

client = EasyAuthAppClient(base_url, app_key, token=os.environ["EASYAUTH_APP_TOKEN"])

# ① 选人器: 按关键字搜活跃用户(下游自行做 ≥300ms 防抖与 60s 缓存)
result = client.search_directory_users(q="王", page_size=50)
for user in result["data"]:
    print(user["dingtalk_user_id"], user["name"], user["title"], user["user_id"])

# ② 逾期升级: 找到负责人的主管并发 action_card 提醒
manager = client.get_directory_user_manager(assignee_user_id)
manager_ref = manager["user_id"] or f"{DINGTALK_REF_PREFIX}{manager['dingtalk_user_id']}"
receipt = client.send_notification(
    recipients=[manager_ref],
    template=NOTIFY_TEMPLATE_ACTION_CARD,
    title="任务逾期升级",
    content=f"### 任务已逾期 3 天\n**{task.title}**\n负责人: {assignee_name}",
    deeplink_url=f"https://eproject.example.com/tasks/{task.id}",
    dedup_key=f"overdue-escalate:{task.id}:{date.today().isoformat()}",
    biz_tag="overdue_escalation",
)
message_id = receipt["message_id"]
```

### `dedup_key` 取值建议

- app 内 **永久幂等键**(非时间窗口): 相同 key + 相同载荷 → 返回同一 `message_id` 且
  `accepted=false`;相同 key 但载荷不同 → `409 CONFLICT`。
- 应编入事件发生标识,例如 `task-assigned:123:v2`、`overdue-remind:123:2026-07-16`;
  想再次发送就换 key(或在 key 中加入日期/版本)。
- 钉钉侧另有「相同内容 + 同一收件人 + 同一天」去重,content 中请带业务变量,避免字面完全相同。

### 投递状态轮询的克制建议

- `send_notification` 为 **异步受理**: `202`/`accepted=true` 仅表示已落库并排程,
  不代表钉钉已送达。
- **事件性通知不必轮询**;失败靠 EasyAuth 控制台通知大盘与审计兜底。
- 确需核对时用 `get_notification(message_id)` 查逐收件人明细,但不要对每条消息做 tight loop。

### 其它方法一览

| 方法 | 用途 |
|---|---|
| `search_directory_users` | 搜索/分页用户(`q`/`department_id`/`manager_id`/`include_inactive`) |
| `get_directory_user` | 用户详情(含主管摘要) |
| `get_directory_user_manager` | 直接主管;无主管时服务端 `404` |
| `list_directory_user_subordinates` | 直接下属(不分页全量) |
| `list_directory_departments` | 部门列表(`parent_id` 省略=全量扁平列表,树由消费方自建) |
| `send_notification` | 发送钉钉工作通知(异步受理;可选 `deeplink_title` 按钮文案,缺省「查看详情」) |
| `get_notification` | 查询投递状态 |

## 参考实现

EasyTrade: `backend/vendor/easyauth-app-sdk`(vendored 副本,来源见 `VENDORED.md`)、`backend/app/api/v1/easyauth_descriptor.py`(挂载)、`backend/app/domain/authz/permission_display.py`(权限双语命名事实源)。

