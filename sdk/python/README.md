# easyauth-app-sdk

EasyAuth 下游应用接入 SDK(Python)。与任何下游应用的业务代码彻底解耦, 零运行时依赖(FastAPI 集成为可选 extra)。

## 能力

1. **集成描述符端点**: 在下游应用暴露 `GET /.well-known/easyauth-app.json`, 返回应用元数据 + 权限 manifest。EasyAuth 控制台的「自动接入」凭 `下游地址 + app_key` 拉取该描述符, 自动完成应用注册与权限目录导入。
2. **描述符构建/解析**: `build_descriptor_payload` / `parse_descriptor_payload`, 双方共用同一契约。
3. **权限查询客户端**: `EasyAuthAppClient` 以 app 凭据调用 EasyAuth 公共权限查询 API。
4. **企业目录客户端**: 分页搜索员工、查询员工及主管/下属、列出部门，并消费目录返回的
   opaque `user_ref` / `department_ref`。
5. **钉钉通知客户端**: 异步提交通知并查询消息及逐收件人投递状态。
6. **webhook 验签**: `verify_webhook` 校验 EasyAuth 反向推送(审批结果/交接事件)的签名与时间戳。
7. **生命周期交接端点**: `easyauth_lifecycle_router` 接收离职/转岗数据交接的
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
- 顶层 `capabilities` 只用于申明应用需要的 EasyAuth 平台能力；manifest 声明不等于开通，
  也不产生任何授权。实际调用 `directory` / `notify` 必须同时满足双层 AND gate：EasyAuth
  超管先为 App 启用对应 capability，再向当前 credential 单独 grant 同一 capability。
  App enable 不等于 credential grant；新 credential 默认没有 `directory` / `notify`。校验时
  会按服务端语义对字符串做
  trim/去重判断，并接受未来新增的 capability；`validate_manifest` 仍返回传入的原对象，不会
  原地改写。
- 必须分别创建权限查询、目录同步、通知发送 credential：权限查询 credential 不授予平台
  capability，目录 credential 仅授予 `directory`，通知 credential 仅授予 `notify`，避免单个
  token 同时拥有不必要的员工枚举与通知发送权限。三个 `EasyAuthAppClient` 实例不得复用同一
  token。

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
  "capabilities": ["directory", "notify"],
  "lifecycle": {"handover_url": "/api/v1/easyauth/lifecycle/handover", "onboard_url": null, "capabilities": ["preview", "reassign"]},
  "webhook": {"signing": "hmac-sha256"}
}
```

## 权限查询

```python
from easyauth_app_sdk import EasyAuthAppClient

permission_client = EasyAuthAppClient(
    base_url="https://iam.example.com",
    app_key="myapp",
    token=settings.EASYAUTH_PERMISSION_TOKEN,
)
snapshot = permission_client.query_user_permissions("ak_uid_xxx")
```

SDK 默认要求 `base_url` 使用 HTTPS。仅本地开发需要连接 HTTP 服务时，才应显式设置
`allow_insecure_http=True`；生产环境不得开启该选项。

## 企业目录

目录调用要求 App 已启用 `directory`，且目录专用 credential 已获 `directory` grant。目录中的
员工不一定已经完成 SSO，因此 `user_id` 可能为 `null`；无论是否完成 SSO，下游都必须原样保存
目录返回的 opaque `user_ref`。部门同样必须原样保存 `department_ref`。不得自行拼接、解码或
根据 `dingtalk_user_id` / `department_id` 推导 ref；详情、主管、下属、目录过滤和通知收件人
都使用上游返回的 ref。同步下游员工时，应使用接口返回的目录 generation、快照时间与 stale
状态判断快照是否完整可信，不能仅凭单次列表缺失就停用本地用户。

```python
directory_client = EasyAuthAppClient(
    base_url="https://iam.example.com",
    app_key="myapp",
    token=settings.EASYAUTH_DIRECTORY_TOKEN,
)

first_page = directory_client.search_directory_users(
    include_inactive=True,
    page=1,
    page_size=100,
)
snapshot_id = first_page["directory_snapshot"]["snapshot_id"]
second_page = directory_client.search_directory_users(
    include_inactive=True,
    snapshot_id=snapshot_id,
    page=2,
    page_size=100,
)

stored_user_ref = first_page["data"][0]["user_ref"]
detail = directory_client.get_directory_user(stored_user_ref)
manager = directory_client.get_directory_user_manager(stored_user_ref)
subordinates = directory_client.list_directory_user_subordinates(manager["user_ref"])

departments = directory_client.list_directory_departments()
stored_department_ref = departments["data"][0]["department_ref"]
department_members = directory_client.search_directory_users(
    department_id=stored_department_ref,
)
```

`include_inactive=True` 用于获取离职或停用员工；具体状态字段及分页/快照元数据以 EasyAuth
公共 API 契约为准。安全分页时，首屏不传 `snapshot_id`，后续每一页都传首屏返回的
`directory_snapshot.snapshot_id`。若同步期间目录发生变化，服务端返回 `409 CONFLICT`；SDK
会将 `error_code="CONFLICT"` 和 `details.expected_snapshot_id` / `actual_snapshot_id` 暴露在
`EasyAuthClientError` 中，并保持 `retryable=False`。调用方不得自动重试当前页或混合两个快照，
应放弃本轮结果并按业务调度策略从第一页重新开始。

裸 Authentik `user_id`、旧 `dt:<id>` 与原始 `department_id` 仅是 legacy 兼容输入，不是下游
应持久化或新建的引用。只有在所有目录源与企业作用域中唯一匹配时才会解析；歧义的用户或部门
引用由目录 API 返回 `409 CONFLICT` 和 `candidate_refs`。格式畸形的 scoped `user_ref` /
`department_ref` 由目录 API 返回 `422 VALIDATION_ERROR`。调用方应改用目录响应给出的 opaque
ref，而不是尝试修补或重新构造引用。

## 钉钉通知

通知调用要求 App 已启用 `notify`，且通知专用 credential 已获 `notify` grant；为 App 启用能力
不会自动授权任何 credential。通知通道还必须绑定一个权威目录作用域
`(directory_source_slug, corp_id)`，只允许向该 source + corp scope 内的 active 员工投递，
跨 scope 收件人会被拒绝。收件人必须由下游后端根据业务事件与授权规则计算，并使用此前从目录
保存的 opaque `user_ref`；禁止提供把前端任意引用原样透传给 `send_notification` 的接口。

```python
notify_client = EasyAuthAppClient(
    base_url="https://iam.example.com",
    app_key="myapp",
    token=settings.EASYAUTH_NOTIFY_TOKEN,
)

accepted = notify_client.send_notification(
    recipients=[stored_user_ref],
    template="markdown",
    title="应收提醒",
    content="请处理已到期应收款。",
    dedup_key="ar.overdue:invoice-001:v1",
    biz_tag="ar.overdue",
)
message = notify_client.get_notification(accepted["message_id"])
```

`send_notification` 的 HTTP `202` 只表示 EasyAuth 已受理，绝不表示钉钉已发送或用户已收到。
格式畸形的 scoped ref、未知 ref、legacy 歧义和通道 scope 不匹配不会把整次请求改成 HTTP
`422`；在请求体结构本身有效时，消息仍以 `202` 受理，这些收件人随后分别成为终态 `failed`。
当前逐收件人 `error_code` 为：`USER_NOT_FOUND`（畸形或未知引用）、`NO_DINGTALK_ID`、
`USER_INACTIVE`、`USER_AMBIGUOUS`（legacy 引用歧义）、`USER_SCOPE_MISMATCH`、
`DINGTALK_REJECTED`、`DINGTALK_DUPLICATE`、`DINGTALK_DAILY_LIMIT`、`EXHAUSTED`。只有请求体
级校验失败（例如 recipients 不是 1~500 个非空且长度合规的字符串）才返回 HTTP `422`。
下游应持久化 `dedup_key`、EasyAuth `message_id` 与本地业务事件，并根据查询结果维护自己的
`queued → accepted → sent → delivered / failed` 状态。`sent` 是最低可靠保证；只有命中明确的
成功或失败回执名单时才推进状态。当前主要成功名单包括 `read_user_id_list`、
`unread_user_id_list`；主要失败名单包括 `invalid_user_id_list`、`failed_user_id_list`、
`forbidden_user_id_list` 以及结构化 `forbidden_list`（重复、日上限或其他拒绝）。未命中任何
明确成功或失败名单时保持 `sent`，即使超过 24 小时也不会自动改为 `delivered`。这些字段只是
当前主要回执，不应作为未来字段的穷举；`delivered` 也不能解释为用户已读、审批已知悉或合规/
法务送达事实。

## 结构化错误

`EasyAuthClientError` 保留原有 `str(error)` 与 `status_code` 用法，同时暴露可编程的错误语义：

```python
from easyauth_app_sdk import EasyAuthClientError

try:
    notify_client.send_notification(
        recipients=[stored_user_ref],
        template="text",
        content="测试通知",
        dedup_key="example:001",
    )
except EasyAuthClientError as error:
    # error_code: EasyAuth 统一错误 code；details: 结构化错误详情。
    # retry_after: 原始 Retry-After；retry_after_seconds: 可解析的非负整数秒。
    if error.retryable:
        schedule_retry(after_seconds=error.retry_after_seconds)
    else:
        raise
```

`transport_error=True` 表示网络、连接或传输层失败。网络错误、`429` 和 `5xx` 的
`retryable=True`；`401`、`403`、`404`、`409`、`422` 均不可自动重试，应分别处理凭据/
capability 配置、资源或主管不存在、幂等冲突和永久参数错误。客户端使用拒绝所有 3xx 的
opener，防止携带 Bearer token 的请求在自动重定向时泄露 `Authorization`。

## 测试

```bash
PYTHONPATH=sdk/python/src .venv/bin/pytest sdk/python/tests
```
