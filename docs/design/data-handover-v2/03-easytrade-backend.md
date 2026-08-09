# 03 · EasyTrade 后端改造设计

> 基准文档：`00-overview-and-contract.md`（下称「契约」）。
> 契约里的事件名、payload 形状、错误码、身份标识规则是**冻结**的，本文件不重复定义，只给 EasyTrade 侧落地方案。
> **开工条件：SDK vNext 发布后**（需要 items 回调、`handover_payloads` TypedDict、256 KiB 上限、
> `handover_asset_types` 的 manifest 白名单、`event_type` 一致性校验 —— 现有 SDK 一个都没有）。
> 之后与 EasyAuth、EasyProject 的实现并行推进，唯一耦合点是契约 §10 的 webhook 形状与
> SDK 包内的契约样本（`easyauth_app_sdk.contract_samples.handover_v2`，用 `importlib.resources` 读）。
> **不要**去 `../EasyAuth/tests/` 找样本 —— 本仓库 CI 独立检出，兄弟目录必然不存在，测试会稳定退化成 skip。

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

### 2.1.1 终态谓词必须冻结在共享选择器里

> **§2.1 的"判定口径"列只是业务说明，不是查询定义。唯一可执行的谓词是本节下表。**
> preview / items / execute 三处**只能**调用 `HandoverAssetSpec.query`，
> 不得按 §2.1 的简写条件另行拼装 —— 两份口径并存时，同一 generation 的 `count` 与明细会对不上，
> 而这种不一致恰好会被 `snapshot_token` 校验放大成整批 409。

必须逐条补齐并**冻结在一处**（`handover_assets.py` 的 `HandoverAssetSpec.query`）：

| 类型 | 完整谓词 |
|---|---|
| `customer` | **未软删 = `Customer.status != CustomerStatus.DELETED.value`**，直接复用 `domain/customer/soft_delete.py:11` 的 `exclude_deleted_customers(query)`。**`Customer` 没有 `deleted_at` 字段**（`domain/customer/models.py:96` 只有 `status`），写 `deleted_at IS NULL` 会直接构造失败 |
| `inquiry_open` | `deleted_at IS NULL` 且 `PipelineStage.is_terminal = false` 且 `lost_at IS NULL` 且 `cancelled_at IS NULL` |
| `order_in_transit` | 非终态状态集 **且 `cancelled_at IS NULL`** |
| `receivable_open` | 未结清、`cancelled_at IS NULL`，**且必须先 `join(Order)` 再用 `receivable_owner_filter({from_user_id})` 判归属**：<br>`db.query(OrderReceivable).join(Order, OrderReceivable.order_id == Order.id).filter(receivable_owner_filter({from_user_id}), OrderReceivable.cancelled_at.is_(None), ...)`<br>该 filter 的第二个分支直接引用 `Order.owner_user_id`（`domain/ar/ownership.py:16-19`）。**不 join 就在未关联的查询上调用它，SQLAlchemy 会把 `orders` 加成一张无关联的 FROM 表，产生笛卡尔积** —— 只要离职者名下有一张订单，全库所有 owner 为 NULL 的应收都会命中，preview 重复计数、execute 改错人 |
| `task_open` | `status='OPEN' AND voided_at IS NULL` |
| `activity_followup` | `voided_at IS NULL AND next_action_owner_user_id IS NOT NULL`（**不加日期条件**，逾期的最该交） |
| `requirement_open` | 状态不在 `{COMPLETED, REJECTED, MERGED}`（`ON_HOLD` **仍算活跃**） |
| `sample_request_open` | 状态不在 `{CLOSED_WON, CLOSED_LOST, CANCELLED}` 且 `cancelled_at IS NULL` |

> `releasable=false` 的**六类**（`inquiry_open` / `order_in_transit` / `receivable_open` / `task_open` / `requirement_open` / `sample_request_open`），一旦 EasyAuth 侧对其指定 `default_to_user_id=null`，
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

`backend/app/api/v1/easyauth_descriptor.py` 输出的 `/.well-known/easyauth-app.json`，
`lifecycle` 段**保持扁平**（契约 §9.1）：

```json
{
  "lifecycle": {
    "handover_url": "https://<host>/api/v1/easyauth/lifecycle/handover",
    "onboard_url": null,
    "capabilities": ["handover.v2"],
    "handover_asset_types": [
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
```

> **绝对不要写成嵌套的 `lifecycle.handover` 对象。** 早期版本那样写，会在**两处**被拒：
>
> | 拦截点 | 现状 |
> |---|---|
> | `backend/app/domain/authz/easyauth_manifest_export.py:109` | `_require_fields(lifecycle, ..., {"handover_url","onboard_url","capabilities"})`，且返回字典（`:117-121`）只重建这三个键 —— 多出来的键会被**静默剥掉** |
> | `backend/vendor/easyauth-app-sdk/.../manifest.py:101-107` | `_validate_lifecycle()` 的 `allowed = {"handover_url","onboard_url","capabilities"}`，未知字段直接 `raise ManifestValidationError` |
>
> 因此本项的实际改动是**两处都要扩**，缺一不可：
>
> 1. `easyauth_manifest_export.py` 的 `_require_fields` 白名单与返回字典加 `handover_asset_types`，
>    并校验其为 list[dict]、每项含 `type`/`label`/`detail_supported`/`releasable` 四键；
> 2. **SDK `manifest.py` 的 `_validate_lifecycle()` 的 `allowed` 集合同步加 `handover_asset_types`**
>    —— 这一条属于 SDK vNext 的交付内容（A1 的第 0 步），A3 依赖它发布后才能通过校验。
>    SDK 不改，descriptor 连生成都生成不出来。
>
> `capabilities` 里出现 `"handover.v2"` 是 EasyAuth 判定「已接入」的**唯一**依据，
> 不再有独立的 `capability` 字段。

`handover_asset_types` 是**单一事实来源**：`preview` 返回的 `type` 必须全部出自这里，否则 EasyAuth 判
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
- **响应必须带 `snapshot_token`**（契约 §10.3 必填字段）。见 §3.5.1。

### 3.5 `items`（契约 §10.4，新增分支）

```
请求: {task_id, generation, snapshot_token, from_user_id, asset_type, page, page_size, q}
```

- `asset_type` 不在注册表 → `422 undeclared_asset_type`
- `page_size` 钳制到 1–200
- `q` 非空时按各类型自定字段模糊匹配（客户按名称，订单按单号，任务按标题…），由 `HandoverAssetSpec` 决定
- **`total` 是应用 `q` 之后的总数**（契约 §10.4）。仅当 `q` 为空串时，`total` 才必须等于同一
  `snapshot_token` 下 preview 的 `count`。想同时给出未过滤总数就另加可选字段 `unfiltered_total`。
  写成"无条件等于 preview count"会让搜索"华东"命中 2 条却返回 187，前端翻出一堆空页
- 排序必须稳定（按主键兜底），否则翻页会漏项/重项

### 3.5.1 `snapshot_token` 的生成与校验（契约 §10.5.1，**原设计整段缺失**）

`preview` 必须返回它，`items` 与 `execute` 必须回带并校验它。三处**共用同一个生成函数**：

```python
def snapshot_token(db, *, task_id: str, generation: int, from_user_id: uuid.UUID) -> str:
    """对当事人名下全部资产的当前状态取确定性摘要。"""
    # 逐 asset_type 调 spec.query(db, from_user_id), 取 (type_key, id, 归属列, 状态列)
    # 按 (type_key, id) 排序后拼串, SHA-256, 取前 32 hex → ≤128 字节 (契约 §10.5.1)
```

- `execute` 在**任何写入之前**重算一次；与请求携带的 token 不一致 → 整体 **`412`**（不是 409），
  EasyAuth 侧按契约 §10.6 把 action 退回 `pending` 并提示「清单已变化，请重新预演」。
  **412 与 409 必须分开**：409 会被判 `failed`，只有 412 才退回重预演。
- `items` 也校验：不一致时同样 **412**，让前端立刻重新 preview，而不是翻着一份已经过期的清单做决定。
- **逐条校验是独立的第二层**：每个被改写的 id 必须当前仍属于 `from_user_id` 且仍满足该类型谓词，
  任一不满足 → 整体 409。**不允许**跳过该条继续处理其余条目。
- 分批时每批都要重新 preview 换新 token（契约 §10.5.2），同一 token 只能用于一批。

### 3.6 `execute`（契约 §10.5，重写）

```python
@dataclass(frozen=True, slots=True)
class OverrideSpec:
    id: str                              # 契约字段名就叫 id, 不是 asset_id
    action: str                          # transfer | release | skip
    to_local_user_id: uuid.UUID | None   # 已由 sub 解析为本地 users.id

@dataclass(frozen=True, slots=True)
class AssignmentSpec:
    asset_type: str
    default_action: str                       # transfer | release | skip
    default_to_local_user_id: uuid.UUID | None
    overrides: tuple[OverrideSpec, ...]

def execute_handover(
    db: Session,
    *,
    kind: str,
    task_id: str,
    generation: int,
    batch_id: int,
    snapshot_token: str,
    from_local_user_id: uuid.UUID,
    assignments: list[AssignmentSpec],   # 取代旧的 to_user_id + release_customers_to_pool
) -> dict[str, dict[str, int]]:
```

> **身份边界：HTTP 层收到的全是 Authentik `sub` 字符串，内部 DTO 里全是本地 `users.id`。**
> 契约 §5.1 规定 payload 的 `from_user_id` / `default_to_user_id` / `overrides[].to_user_id`
> **一律是 sub**；而 EasyTrade 的归属列外键指向本地 `User.id`（`domain/shared/models.py`）。
> 二者恰好都是 UUID，把 sub 直接当本地 id 赋值**不会有类型错误**，只会在 flush 时报 FK 违约
> —— 或者更糟，撞上某个真实存在的本地 id。
>
> 因此：`_handle_execute` 必须在构造 DTO **之前**，把三个位置的 sub **逐个**经
> `_find_external_user()` 解析成本地 id，**尤其不能只解析默认接收人而漏掉 overrides 里的**
> （每条 override 可以有不同接收人，这正是 D10 的用法）。
> 内部 DTO 的字段名统一带 `local` 前缀（如上），让漏解析在类型层面就显眼。
> 任一接收人解析不到 / 非 active / 等于当事人 → `422`。

单事务内，逐 `assignment` 处理：

1. 查注册表拿 `HandoverAssetSpec`；未知类型 → `422 undeclared_asset_type`。
2. **前置校验**（修 B1/B2）。**四项都要，缺一不可**：
   - 任一 `action == "release"` 落在 `spec.releasable is False` 的类型上 → `422 asset_type_not_releasable`。
     绝不允许写 `NULL` 进非空列，也绝不允许静默保持原归属
   - 任一 `action == "transfer"` 的接收人有问题 → 拒绝。**状态码按原因分开，不能一律 422**：

     | 原因 | 状态码 | 对齐依据 |
     |---|---|---|
     | 接收人 sub **映射不到本地用户** | **409** | 契约 §10.6「人员无法识别 → 409」。EasyProject 的 `IDENTITY_UNMAPPED` 也是 409，两个下游必须一致，否则同一种故障在 EasyAuth 上显示成两种语义 |
     | 接收人为空 / 非 active / 等于 `from_user_id` | **422** | 载荷本身不合法，与身份系统无关 |

     **这一整条早期漏了**：畸形 payload 会让可空列（客户、活动）被静默释放，
     非空列（订单、询盘、任务、需求、样品）则要到 flush 时才炸
   - **override 的 id 必须先验证**：存在、仍属于 `from_user_id`、仍满足该类型谓词。
     任一不满足 → 整体 `409`。**不得**把无效 id 默默排除出默认集（那等于静默跳过）
   - `snapshot_token` 与当前数据状态不一致 → 整体 **`412`**（见 §3.5.1）
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
4. **先冻结主键集合，再统一加锁，且忽略 payload 里 assignments 的顺序。**

   两步走：
   - 第一步（无写入）：逐 `asset_type` 跑 `spec.query` 解析出受影响的主键集合，连同 override 的
     id 一起冻结下来。
   - 第二步：按**固定的全局表序**加 `with_for_update`，同表内按 id 升序：

     ```
     Customer → Inquiry → Activity → SampleRequest → Order → OrderReceivable
              → Task → ProductRequirement
     ```

   > **为什么必须无视 payload 顺序**：EasyAuth 的 `assignments` 数组顺序由前端决定。
   > 若照单遍历，一次「先 `receivable_open` 后 `order_in_transit`」的请求会**先锁应收再等订单**，
   > 而既有的订单取消路径（`api/v1/orders/routes.py`、`route_mutations.py`）是**先锁订单再改应收**
   > —— 两者反向，直接死锁。
   >
   > **另一个必须先冻结的理由**：应收的归属谓词会**继承订单负责人**（§2.1.1）。
   > 如果先改了订单 owner 再实时跑应收 selector，那些 owner 为 NULL 的应收会因为
   > 订单已经不属于当事人而**从集合里凭空消失**，静默漏转。
   > 所有 `reassign` 只能操作第一步冻结下来的主键集合，**不得在前序改写后重新执行责任谓词**。

5. **必须走既有的领域命令，保住副作用**，不能裸 UPDATE：
   - 客户转移走 `transfer_customer()`；释放公海走 `release_customer_to_pool(action="auto_release")`
     —— 现有 `_handover_customers` 释放时也写 `action="transfer"`，事件分类是错的，光改 reason 修不了
   - 任务改派须**清空 `reminder_dismissed_at`**，否则新负责人收到的是一条已被前任忽略掉的提醒
   - **订单改 owner 必须新写一个事务内的 `reassign_order_owner()`，禁止调用
     `finish_update_order()`** —— 那个 helper 在
     `backend/app/api/v1/orders/update_order_helpers.py:209` **自己 `db.commit()`**。
     一旦调用它，后面任何一个 assignment 校验失败返回 409 时，订单归属**已经永久落库**，
     execute 就退化成了部分成功，与契约 §10.5「整事务成败一致」直接冲突。
     新函数的职责：存 `_order_update_audit_snapshot()` 的 before 快照 → 改 `owner_user_id` →
     写 `action="order.update"` 的审计行 → **只 `flush()`**。提交与回滚一律由 execute 外层统一做。
     其余任何"内部自己 commit"的 API helper 同样禁止在 execute 路径里调用。
6. 客户归属变更继续写既有的负责人变更事件（`_handover_customers` 中的 owner history），
   `reason` 按 `kind` 取：`offboard`→「EasyAuth 离职交接」、`transfer`→「EasyAuth 转岗交接」、
   `reassign`→「EasyAuth 数据移交」，释放时→「EasyAuth 交接释放公海」。
7. 返回**冻结的五元** `{asset_type: {"transferred": n, "released": m, "skipped": k, "merged": 0, "failed": 0}}`，
   外层包成 `{"summary": result}`（契约 §10.5）。

   > **`merged` 与 `failed` 即使恒为 0 也必须显式返回。** 契约把 summary 定义为五元冻结结构，
   > EasyAuth 会按 `transferred + released + skipped + merged + failed == count` 做守恒校验；
   > 少两个键会让校验取不到值。EasyTrade 没有复合主键合并场景（`merged` 恒 0），
   > 也不实现部分成功（`failed` 恒 0），但**不返回**与**返回 0** 是两回事。
   >
   > 另注意现有实现返回的是 `customers_transferred` 这类扁平旧键（`easyauth_handover.py:61,117-129`），
   > 与 v2 完全不匹配，属于要整体替换掉的部分。

**幂等**：幂等键从 `task_id` 改为三元组 `(task_id, generation, batch_id)`（契约 §10.5.2）。
同键同 payload hash 返回首次 `summary`；同键不同 hash 返回 `409`；
`generation` 小于该 `task_id` 已见最大值的请求一律 `409`（迟到的旧一轮）。
表结构改动见 §3.8。

### 3.7 任务提醒的连带处理

通知中心的提醒是从"指派给该用户的未完成任务"实时派生的
（`backend/app/domain/task/reminders.py:15`、`backend/app/api/v1/notifications.py:21`）。
因此 `task_open` 转移后提醒自动跟随接收人，**无需额外迁移通知数据**。
这一点要写进代码注释，避免后来者误加一段"迁移通知"的冗余逻辑。

### 3.8 数据库迁移

| 迁移 | 内容 |
|---|---|
| `<rev>_handover_receipt_v2_key` | `easyauth_handover_receipts` 表：**新增三列** `generation INTEGER NOT NULL DEFAULT 1`、`batch_id INTEGER NOT NULL DEFAULT 1`、`payload_sha256 CHAR(64) NOT NULL DEFAULT ''`；**删除** `uq_easyauth_handover_receipts_task_id`；**新增** `UNIQUE(task_id, generation, batch_id)` |

> **`batch_id` 是新列，不是已有列。** 现表（`domain/authz/models.py:107-120`）只有
> `task_id` / `mode` / `payload` / `result`，唯一约束是 `UniqueConstraint("task_id")` 单列。
> 早期版本写的"加 `generation` 列，唯一键改为三元组"**建不出来** —— 迁移会因为
> `batch_id` 列不存在而直接失败；而只加 `generation` 的话，同一 generation 的第二批
> 仍然会被旧键吞掉（这正是 §3.6 幂等段要防的那个坑）。
>
> 另需持久化每个 `task_id` 的**已见最大 `generation`**（可用同表 `MAX(generation)` 查，
> 但必须在 task 级串行化之后读，否则并发下两个旧请求会互相"看不见"对方）。
> 用哪种实现由 A3 定，但**必须在 PR 说明里写明结论**。

**DEFAULT 只为迁移历史行服务，加完必须去掉**：三列在应用层都是必填，
留着 server default 会让漏传字段变成静默写入默认值。

**不新增业务列**：所有资产类型都复用既有归属字段。`Order`/`Inquiry` 的非空约束
**保持不变**，靠 `releasable=false` 在契约层解决，而不是放宽不变量。

---

## 4. SDK 升级

`backend/vendor/easyauth-app-sdk` 更新到含 v2 的版本，接入点改动：

- `backend/app/api/v1/easyauth_lifecycle.py` 增加 `on_handover_items` 回调
- 请求体上限跟随 SDK 提升到 256 KiB
- 直接使用 SDK 的 `handover_payloads` TypedDict，**禁止**在 EasyTrade 内手抄字段名
- SDK `manifest.py` 的 `_validate_lifecycle()` 已放行 `handover_asset_types`（§3.2）——
  **vendor 目录必须一并更新到该版本**，否则 descriptor 生成时抛 `ManifestValidationError`

### 4.1 事件头与 body 的一致性校验（契约 §10.1 的强制补偿）

签名串**不覆盖** `X-EasyAuth-Event`（契约 §10.1 已知弱点）。现有实现
（`backend/app/api/v1/easyauth_lifecycle.py:39-50`）**完全按头分发**，handler 不看 body。
攻击者或一个坏掉的中间代理只要在 300 秒窗口内替换事件头，就能让一个合法签名的
execute body 走进 preview 分支，或反过来。

因此契约 §10.1 规定：**所有 body 都带 `event_type` 字段，取值与 `X-EasyAuth-Event` 完全相同**，
`preview` / `items` / `execute` / `webhook.test` 无一例外。body 在签名覆盖范围内，该字段不可篡改。

校验位置：**验签之后、`webhook.test` 短路与任何分发之前**。不一致 → **422**。

> 早期版本写的是「校验事件头与 body 的 `mode` 一致」，有两个洞：
> `items` 根本没有 `mode` 字段；`webhook.test` 在 SDK 里直接短路返回 `{"ok": true}`，
> 把事件头改成 `webhook.test` 就能让一次真实的 execute 变成一句"好的"，而 EasyAuth 把 200 当成功。
> `event_type` 同时堵住这两个洞。这一校验由 SDK vNext 统一实现（`01` §8 第 6 条），
> EasyTrade 只需升级 SDK 并补验收用例。

**必须有负向测试**（§5）：签名合法的前提下，
① 把两个事件头对调、② 把事件头改成 `webhook.test`、③ 篡改 delivery 头 —— 断言前两者 422。

---

## 5. 测试

| 文件 | 覆盖 |
|---|---|
| `backend/app/tests/test_easyauth_handover_assets.py` | 8 类资产的 count 口径；`count=0` 也返回；注册表与 descriptor 一致（用同一常量断言） |
| `backend/app/tests/test_easyauth_handover_items.py` | 分页稳定性（连续翻页不漏不重）；`q` 过滤；`total` 与 preview 一致；`page_size` 钳制 |
| `backend/app/tests/test_easyauth_handover_execute.py` | override 优先于 default；剩余条目按 `default_action`；三值 action 各自行为；**B1** 非空列永不写 NULL；**B2** `release` 落在 `releasable=false` 上抛 422 而非静默；`default_action="skip"` + 逐条 `transfer` 能对非空列做部分交接；`(task_id, generation, batch_id)` 幂等；不同 generation 真正重执行 |
| `backend/app/tests/contract/test_handover_v2_golden.py` | 从 `easyauth_app_sdk.contract_samples` 包内资源读取样本逐字段比对；样本缺失必须 fail |
| `backend/app/tests/test_easyauth_lifecycle.py` | 既有用例按 v2 payload 重写；**§4.1 负向用例**：签名合法但 `X-EasyAuth-Event` 与 body `mode` 对调 → 422 |
| `backend/app/tests/test_easyauth_handover_snapshot.py` | §3.5.1：preview 返回 token；数据变动后 execute 整体 409 且**零写入**；override 的 id 已不属当事人 → 409；分批时旧 token 不可复用 |
| `backend/app/tests/test_easyauth_handover_locking.py` | §3.6 第 4 步：assignments 顺序颠倒时加锁次序不变；先冻结主键后订单 owner 改写不会让 NULL-owner 应收从集合消失 |
| `backend/app/tests/test_easyauth_handover_identity.py` | §3.6 身份边界：payload 里三个位置的 sub 全部解析为本地 id；**overrides 里的接收人不得漏解析**；解析不到/非 active/等于当事人 → 422 |

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
