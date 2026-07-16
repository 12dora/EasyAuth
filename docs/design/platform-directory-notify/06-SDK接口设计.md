# SDK 接口设计（easyauth-app-sdk 新增 directory / notify 客户端）

> 第 6 篇。服务端契约见第 1 篇；本篇方法与契约一一对应。

## 0. 风格约束（沿用现状，零偏离）

`sdk/python/src/easyauth_app_sdk/client.py` 的既有形态决定新方法的全部风格：

- 方法挂在 `EasyAuthAppClient`（frozen dataclass）上；
- 纯标准库 `urllib`，**零运行时依赖不变**；
- 一律返回服务端 JSON 原样解析的 `dict[str, Any]`，不引入响应模型；
- URL 经 `self._app_base()`（`{base_url}/api/v1/apps/{app_key}`）拼装，路径参数
  `quote(..., safe="")` 转义；
- 失败统一抛 `EasyAuthClientError`，结构化暴露 `status_code`、`error_code`、
  `details`、`retry_after`、`retry_after_seconds`、`retryable`、`transport_error`；
- **SDK 不做重试**，只如实标记可重试性；`429` 的调用方必须遵守 `Retry-After`；
- 生产 `base_url` 默认必须使用 HTTPS；仅本地开发可显式开启 `allow_insecure_http`。

## 1. 新增方法签名（`client.py`）

```python
# ---- directory ----

def search_directory_users(
    self,
    *,
    q: str | None = None,
    department_id: str | None = None,
    manager_id: str | None = None,
    include_inactive: bool = False,
    snapshot_id: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """搜索/分页拉取用户目录。GET {app_base}/directory/users。

    department_id / manager_id 必须分别使用目录响应的 opaque department_ref / user_ref。
    返回 {"data": [...], "pagination": {...}}, 字段契约见公共 API 文档 §5。
    """

def get_directory_user(self, user_ref: str) -> dict[str, Any]:
    """用户详情(含主管摘要)。传目录条目返回的 opaque user_ref。
    GET {app_base}/directory/users/{user_ref}"""

def get_directory_user_manager(self, user_ref: str) -> dict[str, Any]:
    """直接主管。user_ref 使用目录响应返回的 opaque user_ref, 不得自行构造。
    GET {app_base}/directory/users/{user_ref}/manager
    无主管时服务端返回 404 NOT_FOUND(见契约 §D3)。"""

def list_directory_user_subordinates(self, user_ref: str) -> dict[str, Any]:
    """直接下属(不分页, 全量)。user_ref 使用目录响应返回的 opaque user_ref。
    GET {app_base}/directory/users/{user_ref}/subordinates"""

def list_directory_departments(
    self, *, parent_id: str | None = None,
) -> dict[str, Any]:
    """部门列表。parent_id 省略 → 全量扁平列表(客户端自建树);
    传入 → 使用目录响应返回的 opaque department_ref 查询直接子部门。
    GET {app_base}/directory/departments"""

# ---- notify ----

def send_notification(
    self,
    *,
    recipients: Sequence[str],
    template: str,
    content: str,
    title: str | None = None,
    deeplink_url: str | None = None,
    deeplink_title: str | None = None,
    dedup_key: str | None = None,
    biz_tag: str | None = None,
) -> dict[str, Any]:
    """发送钉钉工作通知(异步受理)。POST {app_base}/notify/messages。

    recipients 元素为目录条目返回的 opaque user_ref（每项服务端上限 4096 字符）;
    legacy 引用仅为 deprecated 兼容输入，不得新构造。template 取
    "text" | "markdown" | "action_card"。返回 {"message_id", "accepted", ...}。
    幂等: 相同 dedup_key 重复调用返回同一 message_id 且 accepted=False。
    """

def get_notification(self, message_id: str) -> dict[str, Any]:
    """查询通知投递状态(含逐收件人明细)。GET {app_base}/notify/messages/{message_id}"""
```

实现注意点：

- `send_notification` 的 body 只放显式传入的可选字段（`None` 不进 JSON），与服务端
  pydantic `extra="forbid"` 的校验风格互不为难；
- `search_directory_users` 的查询串用既有 `urlencode` 组装方式（对齐
  `list_approvals`），`include_inactive` 序列化为 `"true"`/省略；
  `department_id` / `manager_id` 分别传服务端返回的 `department_ref` / `user_ref`；
  首页省略 `snapshot_id`，后续页传回首页 `directory_snapshot.snapshot_id`；
  遇到 `409 CONFLICT` 由消费方从首页重拉，SDK 不自动重试；
- 模板常量随手可用：在 `client.py` 顶部导出
  `NOTIFY_TEMPLATE_TEXT / NOTIFY_TEMPLATE_MARKDOWN / NOTIFY_TEMPLATE_ACTION_CARD`。
  旧 `DINGTALK_REF_PREFIX` 仅保留兼容；新代码不得据此构造引用。
- 用户、部门、主管响应都带 `source_slug` / `corp_id` 与 canonical ref。SDK 原样透传；
  下游不得解析或重建 ref，并应将其用于详情、主管、过滤与通知。

## 2. 用例代码（EasyProject 的三个典型消费点）

```python
import os
from datetime import date

from easyauth_app_sdk import EasyAuthAppClient

permission_client = EasyAuthAppClient(
    "https://iam.jiefakj.com",
    "easyproject",
    token=os.environ["EASYAUTH_PERMISSION_TOKEN"],  # 不授予 directory / notify
)

directory_client = EasyAuthAppClient(
    "https://iam.jiefakj.com",
    "easyproject",
    token=os.environ["EASYAUTH_DIRECTORY_TOKEN"],  # 仅 directory
)
notify_client = EasyAuthAppClient(
    "https://iam.jiefakj.com",
    "easyproject",
    token=os.environ["EASYAUTH_NOTIFY_TOKEN"],  # 仅 notify
)

# ① 选人器: 按关键字搜活跃用户(下游自行做防抖与 60s 缓存)
result = directory_client.search_directory_users(q="王", page_size=50)
for user in result["data"]:
    print(user["user_ref"], user["name"], user["title"], user["user_id"])

# ② 逾期升级: 找到负责人的主管并发 action_card 提醒
manager = directory_client.get_directory_user_manager(assignee_user_ref)
receipt = notify_client.send_notification(
    recipients=[manager["user_ref"]],
    template="action_card",
    title="任务逾期升级",
    content=f"### 任务已逾期 3 天\n**{task.title}**\n负责人: {assignee_name}",
    deeplink_url=f"https://eproject.jiefakj.com/zh-CN/tasks/{task.id}",
    dedup_key=f"overdue-escalate:{task.id}:{date.today().isoformat()}",
    biz_tag="overdue_escalation",
)
message_id = receipt["message_id"]

# ③ 稍后核对投递状态
status = notify_client.get_notification(message_id)
for item in status["recipients"]:
    if item["status"] == "failed":
        logger.warning("通知未达 %s: %s", item["raw_ref"], item["error_code"])
```

要点示范（会写进集成指南）：主管可能从未登录过 EasyAuth（`user_id` 为 null），
但 `user_ref` 始终是服务端给出的可回传引用。legacy 裸 ID / `dt:` 只在全局唯一时
兼容；directory endpoint 的歧义为 409、畸形 scoped ref 为 422。notify 请求体合法时，
畸形/未知/歧义/scope mismatch 分别成为逐收件人 `USER_NOT_FOUND`、
`USER_AMBIGUOUS`、`USER_SCOPE_MISMATCH`，POST 仍为 202。
权限查询、directory 与 notify 必须使用三条独立凭据和三个 client 实例，不得复用
token；每条凭据只授予该链路所需 capability。

## 3. 版本号与错误策略

- `0.2.0` 引入 directory/notify 方法与 manifest `capabilities`；
  `0.3.0` 引入结构化错误语义和 HTTPS 默认约束。版本同时写入
  `sdk/python/pyproject.toml` 与 `descriptor.py` 的 `SDK_VERSION`。
- 错误处理矩阵：directory endpoints 的 legacy ref 歧义为 `409`、畸形 scoped ref
  为 `422`。notify 请求体合法时，畸形/未知/歧义/scope mismatch 由 202 后的逐收件人
  error code 表达；只有 recipients 数量/空值/单项 >4096 等请求体校验才返回 `422`；
  `429` 按 Retry-After 重试；`401` / `403` 视为凭据或 capability 配置问题；
  `5xx` 与网络错误标记 `retryable=true`。
- 权限查询、directory、notify 必须各用一条 credential 和独立 client；平台能力必须
  同时通过 App 层与 credential 层，manifest 声明不会自动开通任一层。

## 4. manifest schema 扩展结论：**新增可选顶层节 `capabilities`**

- 形态：`"capabilities": ["directory", "notify"]`——非空字符串数组，
  可缺省（缺省 = 不申请任何平台能力）。当前可开通值为 directory / notify；
  校验器接受未知非空值，以允许服务端未来扩码。
- 校验落点（两侧同步）：
  - SDK：`manifest.py` 的可选顶层节白名单（现 `lifecycle`/`webhook`，
    `manifest.py:42`）加入 `capabilities`，新增 `_validate_capabilities`
    （trim 后非空、重复值按归一化值校验，但不改写输入对象）；
  - 服务端：`applications/permission_template_parsing.py` 的解析器同步接受该节
    （容忍未知能力值仅告警不拒绝，为老服务端兼容新 SDK 留余地——服务端先发布
    则无此问题，见第 7 篇发布顺序）。
- **语义（重要）**：申明 ≠ 开通。manifest 同步只把申明记录下来供 console 展示
  「该 app 请求了哪些平台能力」。超管手工开通 `AppCapability`，
  App owner 手工授权单 credential；因此 manifest 导入对两层**都不产生授权副作用**。

## 5. 文档增补清单

### `docs/api/easyauth-public-api.md`

- `## 5. 用户目录`：记录 email/mobile/employee_number/status/active、tombstone、
  多企业 `directory_snapshot` 与 `snapshot_id` 固定分页；
- `## 6. 通知`（新增，2 个端点 + 状态机说明 + error_code 表 + 幂等语义）;
- 原 `## 5. Webhook` → `## 7.`，原 `## 6. SDK 对应方法` → `## 8.` 并补 7 行新方法映射；
- `## 统一错误结构` 无需扩码（复用既有 9 个 ErrorCode，映射见契约 §0.3）。

### `docs/guides/easyauth-app-sdk-integration.md`

- 新增 `## 用户目录与钉钉通知`（对齐现有「粗体术语 + 无序列表 + 代码块」风格）：
  能力开关前置条件（找超管开通）、三条独立 credential、opaque scoped ref 原样保存、
  dedup_key 取值建议、「使用目录返回的 user_ref 通知」推荐链路、投递状态轮询的克制建议
  （事件性通知不必轮询，失败靠 console 大盘兜底）。
- `## 契约` 节补充：目标同步周期是 300s，故障时可以滞后更久；
  消费方必须以 `directory_snapshot.authoritative` / `stale` / `complete` 为准。
