# SDK 接口设计（easyauth-app-sdk 新增 directory / notify 客户端）

> 第 6 篇。服务端契约见第 1 篇；本篇方法与契约一一对应。

## 0. 风格约束（沿用现状，零偏离）

`sdk/python/src/easyauth_app_sdk/client.py` 的既有形态决定新方法的全部风格：

- 方法挂在 `EasyAuthAppClient`（frozen dataclass）上；
- 纯标准库 `urllib`，**零运行时依赖不变**；
- 一律返回服务端 JSON 原样解析的 `dict[str, Any]`，不引入响应模型；
- URL 经 `self._app_base()`（`{base_url}/api/v1/apps/{app_key}`）拼装，路径参数
  `quote(..., safe="")` 转义；
- 失败统一抛 `EasyAuthClientError(status_code=...)`，**SDK 不做重试**（与现状一致；
  通知投递的可靠性由服务端管道保证，SDK 只需保证「受理调用」的错误如实上抛）。

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
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """搜索/分页拉取用户目录。GET {app_base}/directory/users。

    返回 {"data": [...], "pagination": {...}}, 字段契约见公共 API 文档 §5。
    """

def get_directory_user(self, user_ref: str) -> dict[str, Any]:
    """用户详情(含主管摘要)。user_ref 为 user_id 或 "dt:<钉钉userid>"。
    GET {app_base}/directory/users/{user_ref}"""

def get_directory_user_manager(self, user_ref: str) -> dict[str, Any]:
    """直接主管。GET {app_base}/directory/users/{user_ref}/manager
    无主管时服务端返回 404 NOT_FOUND(见契约 §D3)。"""

def list_directory_user_subordinates(self, user_ref: str) -> dict[str, Any]:
    """直接下属(不分页, 全量)。GET {app_base}/directory/users/{user_ref}/subordinates"""

def list_directory_departments(
    self, *, parent_id: str | None = None,
) -> dict[str, Any]:
    """部门列表。parent_id 省略 → 全量扁平列表(客户端自建树);
    传入 → 该部门直接子部门。GET {app_base}/directory/departments"""

# ---- notify ----

def send_notification(
    self,
    *,
    recipients: Sequence[str],
    template: str,
    content: str,
    title: str | None = None,
    deeplink_url: str | None = None,
    dedup_key: str | None = None,
    biz_tag: str | None = None,
) -> dict[str, Any]:
    """发送钉钉工作通知(异步受理)。POST {app_base}/notify/messages。

    recipients 元素为 user_id 或 "dt:<钉钉userid>"; template 取
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
- 模板常量随手可用：在 `client.py` 顶部导出
  `NOTIFY_TEMPLATE_TEXT / NOTIFY_TEMPLATE_MARKDOWN / NOTIFY_TEMPLATE_ACTION_CARD`
  与 `DINGTALK_REF_PREFIX = "dt:"`，并加入 `__init__.py` 的 `__all__`。

## 2. 用例代码（EasyProject 的三个典型消费点）

```python
from easyauth_app_sdk import EasyAuthAppClient

client = EasyAuthAppClient(
    "https://iam.jiefakj.com", "easyproject", token=os.environ["EASYAUTH_APP_TOKEN"],
)

# ① 选人器: 按关键字搜活跃用户(下游自行做防抖与 60s 缓存)
result = client.search_directory_users(q="王", page_size=50)
for user in result["data"]:
    print(user["dingtalk_user_id"], user["name"], user["title"], user["user_id"])

# ② 逾期升级: 找到负责人的主管并发 action_card 提醒
manager = client.get_directory_user_manager(assignee_user_id)
receipt = client.send_notification(
    recipients=[manager["user_id"] or f"dt:{manager['dingtalk_user_id']}"],
    template="action_card",
    title="任务逾期升级",
    content=f"### 任务已逾期 3 天\n**{task.title}**\n负责人: {assignee_name}",
    deeplink_url=f"https://eproject.jiefakj.com/zh-CN/tasks/{task.id}",
    dedup_key=f"overdue-escalate:{task.id}:{date.today().isoformat()}",
    biz_tag="overdue_escalation",
)
message_id = receipt["message_id"]

# ③ 稍后核对投递状态
status = client.get_notification(message_id)
for item in status["recipients"]:
    if item["status"] == "failed":
        logger.warning("通知未达 %s: %s", item["raw_ref"], item["error_code"])
```

要点示范（会写进集成指南）：主管可能从未登录过 EasyAuth（`user_id` 为 null），
消费方引用人时统一用 `user["user_id"] or f"dt:{user['dingtalk_user_id']}"` 兜底。

## 3. 版本号策略

- `0.1.0 → 0.2.0`（minor：纯新增方法，无破坏性变更），**两处同步**：
  `sdk/python/pyproject.toml:7` 与 `descriptor.py:13 SDK_VERSION`。
- 借本次新增建立 `sdk/python/CHANGELOG.md`（Keep a Changelog 格式），首条补记
  0.1.0 的既有能力，0.2.0 记 directory/notify 方法与 manifest `capabilities` 节。
- 分发方式不变（下游 vendored 副本），EasyProject 直接 vendor 0.2.0。

## 4. manifest schema 扩展结论：**新增可选顶层节 `capabilities`**

- 形态：`"capabilities": ["directory", "notify"]`——字符串数组，取值白名单校验，
  可缺省（缺省 = 不申请任何平台能力）。
- 校验落点（两侧同步）：
  - SDK：`manifest.py` 的可选顶层节白名单（现 `lifecycle`/`webhook`，
    `manifest.py:42`）加入 `capabilities`，新增 `_validate_capabilities`
    （非空字符串、白名单、去重）；
  - 服务端：`applications/permission_templates.py` 的解析器同步接受该节
    （容忍未知能力值仅告警不拒绝，为老服务端兼容新 SDK 留余地——服务端先发布
    则无此问题，见第 7 篇发布顺序）。
- **语义（重要）**：申明 ≠ 开通。manifest 同步只把申明记录下来供 console 展示
  「该 app 请求了哪些平台能力」，`AppCapability.enabled` 仍由超管手工翻转
  （安全论证见第 5 篇 §1）。因此 manifest 导入逻辑对该节**不产生任何授权副作用**。

## 5. 文档增补清单

### `docs/api/easyauth-public-api.md`

- `## 5. 用户目录`（新增，5 个端点按既有端点模板书写，含字段说明表与
  「刻意不返回 email/工号/手机号」声明）；
- `## 6. 通知`（新增，2 个端点 + 状态机说明 + error_code 表 + 幂等语义）;
- 原 `## 5. Webhook` → `## 7.`，原 `## 6. SDK 对应方法` → `## 8.` 并补 7 行新方法映射；
- `## 统一错误结构` 无需扩码（复用既有 9 个 ErrorCode，映射见契约 §0.3）。

### `docs/guides/easyauth-app-sdk-integration.md`

- 新增 `## 用户目录与钉钉通知`（对齐现有「粗体术语 + 无序列表 + 代码块」风格）：
  能力开关前置条件（找超管开通）、`dt:` 引用兜底惯用法、dedup_key 取值建议、
  「先查目录拿 dingtalk_user_id 再通知」的推荐链路、投递状态轮询的克制建议
  （事件性通知不必轮询，失败靠 console 大盘兜底）。
- `## 契约` 节补一条：**目录数据滞后上游最多一个同步周期（300s），不保证实时**。
