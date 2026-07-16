# easyauth-app-sdk 下游集成指南

SDK 位于仓库 `sdk/python`(包名 `easyauth-app-sdk`,零运行时依赖,FastAPI 集成为可选 extra),与任何下游应用的业务代码彻底解耦。下游集成后,EasyAuth 控制台的「自动接入」凭 `下游地址 + app_key` 即可完成应用注册与权限目录导入,无需手动录入。

## 契约

- **集成描述符**: 下游在 `GET /.well-known/easyauth-app.json` 返回 `{descriptor_version, app{app_key,name,description}, manifest, sdk}`;`manifest` 即 EasyAuth App manifest(schema_version 单调递增)。
- **权限双语显示名**: manifest 每个权限必须携带 `name`(中文),可选 `name_en`;这是权限 i18n 从下游传递给 EasyAuth 的唯一通道,EasyAuth 门户/控制台按用户语言展示,不做硬编码兜底。
- **端点保护(可选)**: 下游配置共享密钥后,描述符端点要求 `Authorization: Bearer <token>`;EasyAuth 自动接入表单可填写该 token。
- **目录数据新鲜度**: 镜像同步的目标周期是 300s，但故障时可以滞后更久。
  消费方必须以 `directory_snapshot.authoritative` / `stale` / `complete` 判定可信性，
  不得根据调度周期推断快照权威。

## 下游集成步骤(FastAPI 示例)

1. 安装 SDK(EasyTrade 采用 vendored 源码 + Dockerfile `pip install ./vendor/easyauth-app-sdk`)。
2. 挂载描述符端点:

   ```python
   from easyauth_app_sdk.fastapi import create_descriptor_router

   app.include_router(create_descriptor_router(current_manifest_provider, token=可选共享密钥))
   ```

3. `current_manifest_provider` 返回当前权限 manifest;契约变更时递增 schema_version(EasyTrade 用 `EASYAUTH_MANIFEST_SCHEMA_VERSION` 环境变量承载)。
4. 权限查询可复用 SDK 客户端 `EasyAuthAppClient(base_url, app_key, token).query_user_permissions(user_id)`,也可沿用自有客户端。
   `base_url` 生产环境默认必须使用 HTTPS；只有本地开发可显式设置
   `allow_insecure_http=True`。

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

SDK `0.3.0` 提供用户目录、钉钉工作通知与结构化错误语义。

### 能力开关前置条件

- 两能力默认关闭，必须同时满足两层条件：**EasyAuth 超管**为该 App 开通
  `AppCapability.enabled`，**App owner**再将对应 capability 授予具体静态 token 或
  OAuth client credential。任一层缺失都返回 `403 PERMISSION_DENIED`。
- manifest 顶层可声明 `"capabilities": ["directory", "notify"]` 供控制台展示需求，
  但 **声明 ≠ App 开通 ≠ 凭据授权**，导入不会自动翻转任何开关。
- 建议把权限查询、`directory`、`notify` 拆分为三条凭据；通知凭据不应同时
  承载常规权限查询，以限制泄漏后的爆炸半径。
- 兼容升级迁移 `applications/0025_credential_capabilities.py` 会把当时已开启的
  App capabilities 回填给该 App **全部 active 静态凭据和 OAuth 凭据**，
  以避免升级瞬间打断既有调用。只有迁移后新建凭据默认为空 capability 集。
  上线后超管与 App owner 必须立即审计回填结果，拆分权限/directory/notify 凭据，
  并撤销旧 permission token 上多余的 `directory` / `notify` grant。
- 下游必须在后端根据业务事件和权限规则计算收件人；不得提供「前端传任意
  `userRef` 即调用 `send_notification`」的透传接口。`notify` 凭据能通知任意 active 员工，
  即使该员工没有下游 App 权限。
- `notify` App 还需由 App owner 在该 App workspace 配置独立、版本化的钉钉通知通道；
  通道必须从控制台返回的权威目录作用域列表选择 `directory_source_slug` / `corp_id`，
  通知受理后会冻结当时的通道版本。首次配置必须填 secret，更新其他字段时
  可省略 secret 并安全复用已有密文；控制台不回显 secret，连通性失败也不暴露钉钉底层错误原文。

### 目录引用必须 opaque 传递

用户、部门和主管条目分别返回 `source_slug`、`corp_id`、`user_ref` / `department_ref`。
这些 ref 已包含目录源和企业作用域；下游必须原样保存并用于详情、主管、通知和过滤，
不得自行拼接、解析或从 `dingtalk_user_id` / `department_id` 重建：

```python
user_ref = user["user_ref"]
department_ref = user["departments"][0]["department_ref"]
```

裸 Authentik `user_id`、旧 `dt:<钉钉userid>` 和原始部门 ID 仅作唯一匹配兼容；
跨企业歧义时目录 API 返回 `409`，畸形 scoped ref 返回 `422`。通知受理不会因单个
legacy ref 歧义而整体失败，而会把该收件人记为 `USER_AMBIGUOUS`。

### 推荐链路: 先查目录再通知

```python
import os
from datetime import date

from easyauth_app_sdk import (
    NOTIFY_TEMPLATE_ACTION_CARD,
    EasyAuthAppClient,
)

# 两条凭据必须分开，且只授予各自所需 capability。
directory_client = EasyAuthAppClient(
    base_url,
    app_key,
    token=os.environ["EASYAUTH_DIRECTORY_TOKEN"],  # 仅 directory
)
notify_client = EasyAuthAppClient(
    base_url,
    app_key,
    token=os.environ["EASYAUTH_NOTIFY_TOKEN"],  # 仅 notify
)

# ① 选人器: 按关键字搜活跃用户(下游自行做 ≥300ms 防抖与 60s 缓存)
result = directory_client.search_directory_users(q="王", page_size=50)
for user in result["data"]:
    print(user["user_ref"], user["name"], user["title"], user["user_id"])

# ② 逾期升级: 找到负责人的主管并发 action_card 提醒
manager = directory_client.get_directory_user_manager(assignee_user_ref)
receipt = notify_client.send_notification(
    recipients=[manager["user_ref"]],
    template=NOTIFY_TEMPLATE_ACTION_CARD,
    title="任务逾期升级",
    content=f"### 任务已逾期 3 天\n**{task.title}**\n负责人: {assignee_name}",
    deeplink_url=f"https://eproject.example.com/tasks/{task.id}",
    dedup_key=f"overdue-escalate:{task.id}:{date.today().isoformat()}",
    biz_tag="overdue_escalation",
)
message_id = receipt["message_id"]
```

目录条目返回 `email`、`mobile`、`employee_number`、`status` 与 `active`。
所有目录成功响应都带 `directory_snapshot`；只有其 `authoritative=true` 时，
消费方才可根据完整快照收敛离职/停用状态。分页拉取时应将首页
`directory_snapshot.snapshot_id` 传给后续页的 `snapshot_id`；遇到 `409`
就从第一页重新拉取。SDK 不自动循环或重试：

```python
first = directory_client.search_directory_users(page=1, page_size=200)
snapshot_id = first["directory_snapshot"]["snapshot_id"]
second = directory_client.search_directory_users(
    page=2,
    page_size=200,
    snapshot_id=snapshot_id,
)
```

部门和主管过滤也传 scoped ref：

```python
members = directory_client.search_directory_users(
    department_id=department["department_ref"],
)
reports = directory_client.search_directory_users(
    manager_id=manager["user_ref"],
)
```

目录稳定排序会把 `source_slug` / `corp_id` 纳入次级键；消费方仍必须用
`snapshot_id` 固定分页，不要依赖跨快照行序。

### `dedup_key` 取值建议

- app 内 **永久幂等键**(非时间窗口): 相同 key + 相同载荷 → 返回同一 `message_id` 且
  `accepted=false`;相同 key 但载荷不同 → `409 CONFLICT`。
- 应编入事件发生标识,例如 `task-assigned:123:v2`、`overdue-remind:123:2026-07-16`;
  想再次发送就换 key(或在 key 中加入日期/版本)。
- 钉钉侧另有「相同内容 + 同一收件人 + 同一天」去重,content 中请带业务变量,避免字面完全相同。

### 投递状态轮询的克制建议

- `send_notification` 为 **异步受理**: `202`/`accepted=true` 仅表示已落库并排程,
  不代表钉钉已送达。
- `sent` 是可依赖的最低保证。`delivered` 仅表示钉钉明确的 send-result 回执
  将用户归类进 read/unread 名单，不表示已读、审批知悉或法务送达。
  无明确名单归类时保持 `sent`，超过 24 小时也不会乐观推断为 `delivered`。
- EasyAuth 持久化 `last_reconciled_at`，每轮公平轮转最多 50 个唯一
  `(channel, task_id)`；即使回执未分类也推进游标并保持 `sent`。部分收件人失败而
  其余仍为 `sent` 时，消息聚合状态是 `partially_failed`。
- **事件性通知不必轮询**;失败靠 EasyAuth 控制台通知大盘与审计兜底。
- 确需核对时用 `get_notification(message_id)` 查逐收件人明细,但不要对每条消息做 tight loop。

### SDK `0.3.0` 错误处理

`EasyAuthClientError` 暴露 `status_code`、`error_code`、`details`、`retry_after`、
`retry_after_seconds`、`retryable` 和 `transport_error`。SDK **不自动重试**；业务层可按下表决定：

| 情形 | 处理 |
|---|---|
| `404` | 用户不存在或没有主管；按 `details.reason` 做业务分支，不重试 |
| `409` | 幂等键载荷冲突、目录快照变化或 legacy ref 歧义；修正请求、改传 scoped ref 或从首页重拉，不原样重试 |
| `422` | 永久参数错误或畸形 scoped ref；修复载荷，不重试 |
| `429` | `retryable=true`；必须遵守 `retry_after` / `retry_after_seconds` |
| `401` / `403` | 凭据、App capability 或 credential capability 配置问题；停止重试并告警 |
| `5xx` | `retryable=true`；在幂等边界内指数退避 |
| 网络/超时 | `transport_error=true`、`retryable=true`；在幂等边界内重试 |

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
