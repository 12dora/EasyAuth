# 03 · EasyTrade 后端改造设计

> 基准文档：`00-overview-and-contract.md`（下称「契约」）。
> 契约里的事件名、payload 形状、错误码、身份标识规则是**冻结**的，本文件不重复定义，只给 EasyTrade 侧落地方案。
> 本仓库的改造与 EasyAuth、EasyProject **完全并行**，唯一耦合点是契约 §10 的 webhook 形状与
> `EasyAuth/tests/contract_samples/handover_v2/` 下的 golden JSON。

---

## 1. 现状

EasyTrade 是三个下游里唯一已接入交接的应用：

| 位置 | 内容 |
|---|---|
| `backend/app/api/v1/easyauth_lifecycle.py:53` | 签名校验 + 两阶段 preview/execute 端点，`task_id` 持久化幂等 |
| `backend/app/domain/authz/easyauth_handover.py:39` | 资产统计与归属转移实现 |
| `backend/app/tests/test_easyauth_lifecycle.py` | 现有测试 |

身份对接是干净的：本地 `users` 行按 `(external_source="authentik", external_user_id=sub)` upsert
（`backend/app/domain/identity/oidc.py:211`），数据库有部分唯一索引兜底
（`backend/app/domain/shared/models.py:109`）。**契约 §5 的 `authentik_user_id` 可直接当外部键用，无需映射层。**

### 1.1 必须修复的三个缺陷

| # | 缺陷 | 位置 | 后果 |
|---|---|---|---|
| B1 | 无接收人时把非空列 `Order.owner_user_id` 置 `NULL` | `easyauth_handover.py:123` 经 `_reassign_owners` | 违反模型不变量，事务本应失败却被放过 |
| B2 | 询盘在无接收人时**静默保持原归属** | `easyauth_handover.py:132-142` | 典型的静默兜底：调用方以为交接完成，实际数据还挂在离职者名下 |
| B4 | lifecycle 路由直接抛 FastAPI `HTTPException`，实际错误体是 `{"detail": ...}` | `backend/app/api/v1/easyauth_lifecycle.py` | 与本仓库其他接口的错误体不一致。契约 §10.6 只规范状态码，因此**不强制统一**，但需在实现时明确选一种并写进测试，不要两种混用 |

B1/B2 的根因相同：把"能不能没有负责人"这件事藏在实现里，而不是作为契约声明出去。
v2 用 descriptor 的 `releasable` 字段把它显式化（契约 §9.1），由 EasyAuth 在发请求前就拦掉非法组合。

### 1.2 覆盖缺口

现有 bulk 交接只覆盖 4 类：客户、非终态订单、非终态询盘、未结应收。
按契约 §11「活的责任」标准，以下同样属于必须转移但目前完全遗漏的：

- 未完成任务（`Task.assignee_user_id`）及其派生的通知中心提醒
- 活动的下一步负责人（`Activity.next_action_owner_user_id`）
- 未关闭的产品需求（`ProductRequirement.owner_user_id`）
- 未完成的样品申请（`SampleRequest.requested_by_user_id`）

---

## 2. 资产类型清单（契约 §11 要求的三列判定）

### 2.1 活的责任 —— 转移，纳入 `asset_type`

| `asset_type` | 中文名 | 字段 | 可空 | `releasable` | 判定口径 |
|---|---|---|---|---|---|
| `customer` | 名下客户 | `Customer.owner_user_id`（`domain/customer/models.py:87`） | 是 | **true** | 未软删除的全部客户；`NULL` 即公海，是既有的合法状态 |
| `inquiry_open` | 进行中询盘 | `Inquiry.owner_user_id`（`domain/order/model_inquiry.py:39`） | 否 | **false** | `PipelineStage.is_terminal = false` |
| `order_in_transit` | 在途订单 | `Order.owner_user_id`（`domain/order/model_order.py:52`） | 否 | **false** | 非终态订单 |
| `receivable_open` | 未结应收计划 | `OrderReceivable.owner_user_id`（`domain/order/model_finance.py:277`） | 是 | **false** | 未结清。**列可空但不可 release**：`domain/ar/ownership.py` 明确 owner 为 `NULL` 时**回退到订单负责人**，不是无主。若订单尚未转移，置 NULL 等于把应收又挂回离职者 —— 是静默兜底的另一种形态 |
| `task_open` | 未完成任务 | `Task.assignee_user_id`（`domain/task/models.py:33`） | 否 | **false** | 状态非完成/取消。**新增覆盖** |
| `activity_followup` | 待跟进活动 | `Activity.next_action_owner_user_id`（`domain/activity/models.py:50`） | 是 | **true** | 口径：`voided_at IS NULL AND next_action_owner_user_id IS NOT NULL`。**不得**加"下一步日期未过期"条件 —— 逾期未跟进的活动恰恰是最需要移交的那批。**新增覆盖** |
| `requirement_open` | 进行中产品需求 | `ProductRequirement.owner_user_id`（`domain/requirement/models.py:79`） | 否 | **false** | 未关闭。**新增覆盖** |
| `sample_request_open` | 未完成样品申请 | `SampleRequest.requested_by_user_id`（`domain/crm/models.py:71`） | 否 | **false** | 未终结。**新增覆盖** |

> `releasable=false` 的四类，一旦 EasyAuth 侧对其指定 `default_to_user_id=null`，
> EasyAuth 会在发请求前直接返回 `422 asset_type_not_releasable`（契约 §9.1）。
> EasyTrade 收到这种组合仍要防御性返回 `422`，**不得**再走静默保持原状的老路（修 B2）。

### 2.2 历史事实 —— 一律不动

`Task.created_by_user_id`、`Activity.created_by_user_id`、`Quotation.created_by`、
`QuotationRevision.created_by`、`Document.created_by`、`DocumentVersion.created_by`、
`SampleShipment.created_by`、`SampleFeedback.recorded_by_user_id`、`CustomerFollowup.user_id`、
COA 档案/批次创建人、需求进展与附件创建人、文档与产品上传人、邮件发送人、应收响应创建人、
汇率操作人、业绩目标创建人，以及全部 `*_by_user_id` 形式的取消人 / 完成人 / 确认人 / 释放人 /
停用人 / 作废人 / 评估人 / 审计署名。

### 2.3 个人配置 —— 不转移

- `UserDashboardLayout.user_id`：仪表盘布局，随账号停用自然失效。
- `PerformanceTarget.user_id`：**业绩目标不转移**。
  它参与 `(user, period, metric, entity)` 的部分唯一键，转移会与接收人已有目标冲突；
  更重要的是业绩归属是考核事实，转移即失真。契约 §11 已把此条列为全局判例。

### 2.4 无需单列的对象

报价单、文档等草稿不单列 `asset_type`：其访问权通过客户/询盘/订单的归属继承，
父对象转移后接收人自然可见（契约 §11 判例）。

---

## 3. 后端改造

### 3.1 ~~修 B3（scope 解析剔除 inactive）~~ —— **本期取消**

原本要求去掉 `_managed_user_ids_from_resolved_grant()` 里的 `row.active` 判定，理由是代管授权
需要让 departed 用户进入 scope 集合。**代管已在第二轮复核后整体废弃**（契约 §7），
离职者不会再进入任何人的 `MANAGED_USERS`，本项**没有依据，本期不做**，`scope_resolution.py` 一行不改。

### 3.1.1 `hint` 是硬要求，不是可选项

代管废弃后，主管**只能靠交接单里的明细判断归属**，看不到业务系统里的上下文。
因此 `items` 响应里每条的 `hint`（≤120 字符）承担了全部判断依据，必须给足信息：

| `asset_type` | `hint` 必须包含 |
|---|---|
| `customer` | 最近跟进日期 + 在途单数 + 客户等级/区域 |
| `order_in_transit` | 单号 + 客户名 + 当前阶段 + 金额 |
| `inquiry_open` | 客户名 + 当前 pipeline 阶段 + 最近活动日期 |
| `receivable_open` | 关联单号 + 到期日 + 未结金额 |
| `task_open` | 关联对象 + 截止日期 |
| `activity_followup` | 客户名 + 下一步日期 |
| `requirement_open` | 产品/客户 + 当前状态 |
| `sample_request_open` | 客户名 + 样品 + 当前状态 |

**`hint` 为空或只有 ID 视为未完成本项**，验收用例须逐类断言非空且含上表要素。

### 3.2 descriptor 声明（契约 §9.1）

`backend/app/api/v1/easyauth_descriptor.py` 输出的 `/.well-known/easyauth-app.json` 增加：

```json
{
  "lifecycle": {
    "handover": {
      "capability": "declared",
      "url": "https://<host>/api/v1/easyauth/lifecycle/handover",
      "asset_types": [
        {"type": "customer",            "label": "名下客户",       "detail_supported": true,  "releasable": true},
        {"type": "inquiry_open",        "label": "进行中询盘",     "detail_supported": true,  "releasable": false},
        {"type": "order_in_transit",    "label": "在途订单",       "detail_supported": true,  "releasable": false},
        {"type": "receivable_open",     "label": "未结应收计划",   "detail_supported": true,  "releasable": false},
        {"type": "task_open",           "label": "未完成任务",     "detail_supported": true,  "releasable": false},
        {"type": "activity_followup",   "label": "待跟进活动",     "detail_supported": true,  "releasable": true},
        {"type": "requirement_open",    "label": "进行中产品需求", "detail_supported": true,  "releasable": false},
        {"type": "sample_request_open", "label": "未完成样品申请", "detail_supported": true,  "releasable": false}
      ]
    }
  }
}
```

`asset_types` 是**单一事实来源**：`preview` 返回的 `type` 必须全部出自这里，否则 EasyAuth 判
`422 undeclared_asset_type`。为杜绝手抄漂移，descriptor 与实现共用同一份常量表（§3.3）。

### 3.3 资产注册表（新文件 `backend/app/domain/authz/handover_assets.py`）

把「一个资产类型」抽象成一条注册项，descriptor、preview、items、execute 四处共用：

```python
@dataclass(frozen=True, slots=True)
class HandoverAssetSpec:
    type_key: str
    label: str
    detail_supported: bool
    releasable: bool
    # 返回该用户名下"活的责任"查询; 调用方负责加锁与分页
    query: Callable[[Session, uuid.UUID], Query]
    # 明细行 -> (id, label, hint)
    render_item: Callable[[Any], tuple[str, str, str]]
    # 执行归属改写; to_user_id 为 None 表示释放
    reassign: Callable[[Session, Query, uuid.UUID | None], int]

HANDOVER_ASSETS: Final[tuple[HandoverAssetSpec, ...]] = (...)
HANDOVER_ASSETS_BY_KEY: Final[dict[str, HandoverAssetSpec]] = {...}
```

新增类型只需往这张表里加一行，descriptor 与三个 webhook 分支自动覆盖 —— 这是防止未来再次出现
"覆盖缺口"的结构性保证。

### 3.4 `preview`（契约 §10.3）

- 遍历 `HANDOVER_ASSETS`，逐条 `query(...).count()`。
- **所有已声明类型都要返回，包括 `count=0` 的**（契约明确要求，省略与"不支持"无法区分）。
- 只读，不落库，不开写事务。

### 3.5 `items`（契约 §10.4，新增分支）

```
请求: {task_id, generation, from_user_id, asset_type, page, page_size, q}
```

- `asset_type` 不在注册表 → `422 undeclared_asset_type`
- `page_size` 钳制到 1–200
- `q` 非空时按各类型自定字段模糊匹配（客户按名称，订单按单号，任务按标题…），由 `HandoverAssetSpec` 决定
- `total` 必须与同 `generation` 的 preview `count` 用**同一个 query** 计算，保证一致
- 排序必须稳定（按主键兜底），否则翻页会漏项/重项

### 3.6 `execute`（契约 §10.5，重写）

```python
@dataclass(frozen=True, slots=True)
class OverrideSpec:
    id: str          # 契约字段名就叫 id, 不是 asset_id
    action: str                       # transfer | release | skip
    to_user_id: uuid.UUID | None

@dataclass(frozen=True, slots=True)
class AssignmentSpec:
    asset_type: str
    default_action: str               # transfer | release | skip
    default_to_user_id: uuid.UUID | None
    overrides: tuple[OverrideSpec, ...]

def execute_handover(
    db: Session,
    *,
    kind: str,
    from_user_id: uuid.UUID,
    assignments: list[AssignmentSpec],   # 取代旧的 to_user_id + release_customers_to_pool
) -> dict[str, dict[str, int]]:
```

单事务内，逐 `assignment` 处理：

1. 查注册表拿 `HandoverAssetSpec`；未知类型 → `422 undeclared_asset_type`。
2. **前置校验**（修 B1/B2）：任一 `action == "release"` 落在 `spec.releasable is False` 的类型上
   → 抛领域错误 → `422 asset_type_not_releasable`。
   **绝不允许**再出现写 `NULL` 进非空列，也**绝不允许**静默保持原归属。
3. 先处理 `overrides`（精确 id 集合），再按 `default_action` 处理剩余条目：
   ```
   overridden_ids = {o.id for o in overrides}
   for o in overrides:
       if   o.action == "transfer": reassign(单条, o.to_user_id)
       elif o.action == "release":  reassign(单条, None)
       else:                        pass          # skip: 原样不动
   rest = query.filter(id.notin_(overridden_ids))
   if   default_action == "transfer": reassign(rest, default_to_user_id)
   elif default_action == "release":  reassign(rest, None)
   else:                              pass        # skip: 整批不动
   ```
   写 `NULL` 只可能发生在 `action == "release"` 分支，而该分支已被第 2 步保证只落在
   `releasable=True`（即可空列）的类型上 —— B1 从结构上不可能再复发。
4. 全程 `with_for_update`，与既有实现一致。
5. 客户归属变更继续写既有的负责人变更事件（`_handover_customers` 中的 owner history），
   `reason` 按 `kind` 取：`offboard`→「EasyAuth 离职交接」、`transfer`→「EasyAuth 转岗交接」、
   `reassign`→「EasyAuth 数据移交」，释放时→「EasyAuth 交接释放公海」。
6. 返回 `{asset_type: {"transferred": n, "released": m, "skipped": k}}`。

**幂等**：幂等键从 `task_id` 改为 `(task_id, generation, batch_id)`（契约 §10.5）。
本地幂等记录表加 `generation` 列；同键重放返回首次的 `summary`，不同 `generation` 必须真正执行。

### 3.7 任务提醒的连带处理

通知中心的提醒是从"指派给该用户的未完成任务"实时派生的
（`backend/app/domain/task/reminders.py:15`、`backend/app/api/v1/notifications.py:21`）。
因此 `task_open` 转移后提醒自动跟随接收人，**无需额外迁移通知数据**。
这一点要写进代码注释，避免后来者误加一段"迁移通知"的冗余逻辑。

### 3.8 数据库迁移

| 迁移 | 内容 |
|---|---|
| `<rev>_handover_idempotency_generation` | 幂等记录表加 `generation` 列（非空，默认 1），唯一键改为 `(task_id, generation, batch_id)` |

**不新增业务列**：所有资产类型都复用既有归属字段。`Order`/`Inquiry` 的非空约束
**保持不变**，靠 `releasable=false` 在契约层解决，而不是放宽不变量。

---

## 4. SDK 升级

`backend/vendor/easyauth-app-sdk` 更新到含 v2 的版本，接入点改动：

- `backend/app/api/v1/easyauth_lifecycle.py` 增加 `on_handover_items` 回调
- 请求体上限跟随 SDK 提升到 256 KiB
- 直接使用 SDK 的 `handover_payloads` TypedDict，**禁止**在 EasyTrade 内手抄字段名

---

## 5. 测试

| 文件 | 覆盖 |
|---|---|
| `backend/app/tests/test_easyauth_handover_assets.py` | 8 类资产的 count 口径；`count=0` 也返回；注册表与 descriptor 一致（用同一常量断言） |
| `backend/app/tests/test_easyauth_handover_items.py` | 分页稳定性（连续翻页不漏不重）；`q` 过滤；`total` 与 preview 一致；`page_size` 钳制 |
| `backend/app/tests/test_easyauth_handover_execute.py` | override 优先于 default；剩余条目按 `default_action`；三值 action 各自行为；**B1** 非空列永不写 NULL；**B2** `release` 落在 `releasable=false` 上抛 422 而非静默；`default_action="skip"` + 逐条 `transfer` 能对非空列做部分交接；`(task_id, generation, batch_id)` 幂等；不同 generation 真正重执行 |
| `backend/app/tests/contract/test_handover_v2_golden.py` | 从 `easyauth_app_sdk.contract_samples` 包内资源读取样本逐字段比对；样本缺失必须 fail |
| `backend/app/tests/test_easyauth_lifecycle.py` | 既有用例按 v2 payload 重写 |

golden 样本的取用方式：**随 SDK 一起分发**，作为 `easyauth_app_sdk` 的包内数据资源
（`easyauth_app_sdk.contract_samples`），版本与 SDK 绑定。测试通过 `importlib.resources` 读取。

**不得**依赖 `../EasyAuth/` 这样的兄弟目录相对路径 —— 本仓库 CI 独立检出，那条路径必然不存在，
测试会稳定退化成 skip。**样本缺失必须让测试失败**，不允许 skip 通过（`AGENTS.md`：不得用空结果兜底掩盖真实问题）。

---

## 6. 交付顺序

1. ~~§3.1 修 B3~~ —— 本期取消（代管废弃）
2. §3.3 资产注册表 + §3.2 descriptor（两者共用常量，必须同一提交）
3. §3.4 preview + §3.5 items
4. §3.6 execute 重写 + §3.8 迁移（修 B1/B2）
5. §4 SDK 升级
6. §5 测试补齐

每完成一项立即单独 commit。改完后端后必须重建容器镜像并重启，host dev server 不算上线。
全量门禁：`make finish-check`（Makefile 中的既有目标，串起 migrations / backend-style / backend-tests / frontend-typecheck / frontend-tests）。**本仓库没有 `make quality` 这个目标。**
