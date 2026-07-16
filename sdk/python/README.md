# easyauth-app-sdk

EasyAuth 下游应用接入 SDK(Python)。与任何下游应用的业务代码彻底解耦, 零运行时依赖(FastAPI 集成为可选 extra)。

## 能力

1. **集成描述符端点**: 在下游应用暴露 `GET /.well-known/easyauth-app.json`, 返回应用元数据 + 权限 manifest。EasyAuth 控制台的「自动接入」凭 `下游地址 + app_key` 拉取该描述符, 自动完成应用注册与权限目录导入。
2. **描述符构建/解析**: `build_descriptor_payload` / `parse_descriptor_payload`, 双方共用同一契约。
3. **权限查询客户端**: `EasyAuthAppClient` 以 app 凭据调用 EasyAuth 公共权限查询 API。
4. **企业目录客户端**: 分页搜索员工、查询员工及主管/下属、列出部门，支持
   `user_id` 与 `dt:<dingtalk_user_id>` 两种引用。
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
- 建议分别创建权限查询、目录同步、通知发送 credential：权限查询 credential 不授予平台
  capability，目录 credential 仅授予 `directory`，通知 credential 仅授予 `notify`，避免单个
  token 同时拥有不必要的员工枚举与通知发送权限。

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

client = EasyAuthAppClient(base_url="https://iam.example.com", app_key="myapp", token="eat_...")
snapshot = client.query_user_permissions("ak_uid_xxx")
```

SDK 默认要求 `base_url` 使用 HTTPS。仅本地开发需要连接 HTTP 服务时，才应显式设置
`allow_insecure_http=True`；生产环境不得开启该选项。

## 企业目录

目录调用要求 App 已启用 `directory`，且当前 credential 已获 `directory` grant。目录中的员工
不一定已经完成 SSO，因此 `user_id` 可能为 `null`；此时应保存并使用
`dt:<dingtalk_user_id>` 引用。同步下游员工时，应使用接口返回的目录 generation、快照时间与
stale 状态判断快照是否完整可信，不能仅凭单次列表缺失就停用本地用户。

```python
first_page = client.search_directory_users(include_inactive=True, page=1, page_size=100)
snapshot_id = first_page["directory_snapshot"]["snapshot_id"]
second_page = client.search_directory_users(
    include_inactive=True,
    snapshot_id=snapshot_id,
    page=2,
    page_size=100,
)

detail = client.get_directory_user("dt:staff-001")
manager = client.get_directory_user_manager("dt:staff-001")
subordinates = client.list_directory_user_subordinates("dt:manager-001")
departments = client.list_directory_departments()
```

`include_inactive=True` 用于获取离职或停用员工；具体状态字段及分页/快照元数据以 EasyAuth
公共 API 契约为准。安全分页时，首屏不传 `snapshot_id`，后续每一页都传首屏返回的
`directory_snapshot.snapshot_id`。若同步期间目录发生变化，服务端返回 `409 CONFLICT`；SDK
会将 `error_code="CONFLICT"` 和 `details.expected_snapshot_id` / `actual_snapshot_id` 暴露在
`EasyAuthClientError` 中，并保持 `retryable=False`。调用方不得自动重试当前页或混合两个快照，
应放弃本轮结果并按业务调度策略从第一页重新开始。

## 钉钉通知

通知调用要求 App 已启用 `notify`，且当前 credential 已获 `notify` grant；为 App 启用能力不会
自动授权任何 credential。收件人必须由下游后端根据业务事件与授权规则计算，禁止提供把前端
任意 `userRef` 原样透传给 `send_notification` 的接口。

```python
accepted = client.send_notification(
    recipients=["dt:staff-001"],
    template="markdown",
    title="应收提醒",
    content="请处理已到期应收款。",
    dedup_key="ar.overdue:invoice-001:v1",
    biz_tag="ar.overdue",
)
message = client.get_notification(accepted["message_id"])
```

`send_notification` 的 HTTP `202` 只表示 EasyAuth 已受理，绝不表示钉钉已发送或用户已收到。
下游应持久化 `dedup_key`、EasyAuth `message_id` 与本地业务事件，并根据查询结果维护自己的
`queued → accepted → sent → delivered / failed` 状态。由于 EasyAuth 可能对长时间停留在
`sent` 的消息做乐观对账，`sent` 是最低可靠保证；`delivered` 不能解释为用户已读、审批已知悉
或合规/法务送达事实。

## 结构化错误

`EasyAuthClientError` 保留原有 `str(error)` 与 `status_code` 用法，同时暴露可编程的错误语义：

```python
from easyauth_app_sdk import EasyAuthClientError

try:
    client.send_notification(
        recipients=["dt:staff-001"],
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
