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
| `order_in_transit` | `status NOT IN {COMPLETED, CANCELLED}` **且 `cancelled_at IS NULL`**。把集合写死，不要写成「非终态状态集」—— 重构时最容易漏掉 `CANCELLED` |
| `receivable_open` | `status NOT IN CLOSED_RECEIVABLE_STATUSES`（冻结集合 `{CLOSED, PAID, VOIDED, CANCELLED, CANCELED}` —— 写「未结清」三个字最容易只排除 `CLOSED/PAID`，把已作废的应收也搬走）、`cancelled_at IS NULL`，**且必须先 `join(Order)` 再用 `receivable_owner_filter({from_user_id})` 判归属**：<br>`db.query(OrderReceivable).join(Order, OrderReceivable.order_id == Order.id).filter(receivable_owner_filter({from_user_id}), OrderReceivable.cancelled_at.is_(None), ...)`<br>该 filter 的第二个分支直接引用 `Order.owner_user_id`（`domain/ar/ownership.py:16-19`）。**不 join 就在未关联的查询上调用它，SQLAlchemy 会把 `orders` 加成一张无关联的 FROM 表，产生笛卡尔积** —— 只要离职者名下有一张订单，全库所有 owner 为 NULL 的应收都会命中，preview 重复计数、execute 改错人 |
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
需要让 departed 用户进入 scope 集合。**代管已整体废弃**（契约 §7），
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

> **绝对不要写成嵌套的 `lifecycle.handover` 对象。** 早期版本那样写，会在**三处**被拒
> （契约 §9.1 的权威表也是三行）：
>
> | 拦截点 | 现状 | 归谁改 |
> |---|---|---|
> | `backend/app/domain/authz/easyauth_manifest_export.py:109` | `_require_fields(lifecycle, ..., {"handover_url","onboard_url","capabilities"})` —— **没传 `optional`**（`:409-420`），多一个键直接抛 `EasyAuthManifestExportError`；即便绕过它，返回字典（`:117-121`）也只重建这三个键 | A3（本仓） |
> | `backend/vendor/easyauth-app-sdk/.../manifest.py:101-107` | `_validate_lifecycle()` 的 `allowed = {"handover_url","onboard_url","capabilities"}`，未知字段直接 `raise ManifestValidationError` | A1a（SDK 0.4.0） |
> | **EasyAuth `applications/permission_template_parsing.py:116-123` 的 `_LifecyclePayload`** | `ConfigDict(extra="forbid")`，只有三个字段；承接它的 `permission_template_types.py:87-93` `AppManifestLifecycleInput` 同样 | **A1（EasyAuth 仓，`01` §5.2）—— 本仓改不了，只能依赖** |
>
> **第三道最容易漏，而漏了它本仓这一步会假绿。** EasyTrade 把自己两处扩完之后，
> 本地 `/.well-known/easyauth-app.json` 生成正常、单测全绿，§6 步骤 2 看上去就交付完成了；
> 但这份 descriptor 一推到 EasyAuth 做 manifest 导入/自动接入，就被 Pydantic 整份拒掉 ——
> 不是「少了资产声明」，是**应用根本接不进来**，而那时步骤 2/3/4 都已合入。
> 因此 **§6 步骤 2 的完成判据是「EasyAuth 侧 manifest 导入实际通过」**，
> 不是「本仓单测通过」。
>
> 因此本项的实际改动是**三处都要扩**（本仓负责前一处），缺一不可：
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
- 只读，不落库。**但必须开一个 `REPEATABLE READ READ ONLY` 只读事务**，让 8 类 count 与
  `snapshot_token` 取自**同一个数据库快照**（隔离级别写法照抄
  `api/v1/system_maintenance_export.py:201-216`）。
  默认的 READ COMMITTED 下，先统计 count、再算 token 之间发生的并发变更会让**响应从生成的那一刻
  就自相矛盾**：token 描述的集合与 count 数出来的不是同一批。
- **响应必须带 `snapshot_token`**（契约 §10.3 必填字段）。见 §3.5.1。

### 3.5 `items`（契约 §10.4，新增分支）

```
请求: {task_id, generation, snapshot_token, from_user_id, asset_type, page, page_size, q}
```

- `asset_type` 不在注册表 → `422 undeclared_asset_type`
- **任何查询之前**先校验上界（契约 §10.4）：`1 <= page <= 100000`、`1 <= page_size <= 200`、
  `len(q.strip().encode("utf-8")) <= 128`。违反直接 `422`，**不要钳制后继续查** ——
  钳制等于把一次攻击性输入变成一次正常查询。
  **三项一律 422，`page_size` 也不例外**（早期这里另写过一句「`page_size` 钳制到 1–200」，
  与本条互斥，已删）—— 钳制 `page_size` 会让 `page_size=1000000` 变成一次合法的 200 条查询，
  而它的 body 指纹每次都不同、缓存不命中，下面那套 single-flight/429 防读放大就被绕开一半
- 验签之后按**签名覆盖的 body 指纹**做 300 秒响应缓存或 single-flight；超并发/频率上限返回 `429`。
  **不能只按 `delivery_id` 去重** —— 那个头不在签名里，改一下就绕过去了。
  测试覆盖：超大 `page`、超长 UTF-8 `q`、以及同一份合法签名请求的连续与并发重放
- `q` 非空时按各类型自定字段模糊匹配（客户按名称，订单按单号，任务按标题…），由 `HandoverAssetSpec` 决定
- **`total` 是应用 `q` 之后的总数**（契约 §10.4）。仅当 `q` 为空串时，`total` 才必须等于同一
  `snapshot_token` 下 preview 的 `count`。想同时给出未过滤总数就另加可选字段 `unfiltered_total`。
  写成"无条件等于 preview count"会让搜索"华东"命中 2 条却返回 187，前端翻出一堆空页
- 排序必须稳定（按主键兜底），否则翻页会漏项/重项
- **同样在 `REPEATABLE READ READ ONLY` 事务内完成**：token 校验、`total` 与本页数据必须来自同一快照，
  否则会出现「token 校验通过了，翻页时读到的却是另一批数据」。
  身份解析等需要网络的前置动作在进这个只读事务**之前**完成

### 3.5.1 `snapshot_token` 的生成与校验（契约 §10.5.1，**原设计整段缺失**）

`preview` 必须返回它，`items` 与 `execute` 必须回带并校验它。三处**共用同一个生成函数**：

```python
def snapshot_token(db, *, from_user_id: uuid.UUID) -> str:
    """对当事人名下全部资产的当前状态取确定性摘要。

    摘要输入**只有** (type_key, id, 归属列, 状态列) —— task_id 与 generation
    不参与哈希, 所以也不收进签名 (要做日志关联在调用方拼)。
    收了却不用的形参会让人以为该拌进去: preview 与 execute 两条路径一旦对
    「拌不拌」取不同答案, token 恒不相等, 每次 execute 都 412, 表现成
    「清单一直在变」而数据其实纹丝未动。
    """
    # 逐 asset_type 调 spec.query(db, from_user_id), 取 (type_key, id, 归属列, 状态列)
    # 按 (type_key, id) 排序后拼串, SHA-256, 取前 32 hex → ≤128 字节 (契约 §10.5.1)
    # 摘要必须由数据库侧聚合产出 (每类一条 md5(string_agg(...)) 一类的聚合查询),
    # 不得把全部行物化进 Python 再拼串 —— items 每翻一页都要重算一次 token,
    # 名下几千条资产的当事人按 page_size=200 翻完就是几十次全量扫描。
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
> 接收人失败的状态码**分两种，不要一律 422**（详表见下方 §3.6 step 4）：
> **sub 映射不到本地用户 → `409`**（契约 §10.6「人员无法识别」，EasyProject 的
> `IDENTITY_UNMAPPED` 也是 409）；**为空 / 非 active / 等于当事人 → `422`**。
> 要改的具体函数是 `_required_receiver()`（现状 `easyauth_lifecycle.py:102` 一律抛 422）。

**整体执行顺序（步骤号就是必须的先后，不能重排）：**

```
0. 语法解析三元组与 canonical hash
1. advisory 锁 (task_id)            ← 第一项数据库操作
2. 查同三元组回执: hash 相同 → 直接返回原 summary(不做任何校验); hash 不同 → 409
3. generation 水位校验
4. 语法/声明层校验(未知 asset_type、release 落在 releasable=false、接收人形态)
5. 冻结全部候选主键(只查不写)
6. 按固定全局表序加行锁
7. 锁内重算 snapshot_token + 逐条复核归属与谓词   ← 校验必须在锁之后
8. 执行 overrides 与 default
9. 写回执 → flush → commit
```

> **第 7 步必须在第 6 步之后。** 早期版本把快照校验放在加锁之前、又把 `reassign()`
> 写在冻结之前，中间留了一个窗口：校验通过之后、拿到行锁之前，另一个事务先把客户从离职者
> 转给了 B；handover 随后拿到锁，`transfer_customer()` 刷新出的当前 owner 是 B，
> 而它**不校验预期来源**，于是把客户从 B 又转给了 C。
>
> **第 2 步必须在一切校验之前。** 首次成功已经改变了数据，因此 token 必然失效；
> 重放若先跑身份或快照校验，会返回 412/409 而不是那份保存好的 summary ——
> EasyAuth 看到的是"上次成功、这次失败"。

单事务内，逐 `assignment` 处理：

1. 查注册表拿 `HandoverAssetSpec`；未知类型 → `422 undeclared_asset_type`。
2. **前置校验**（修 B1/B2）。**四项都要，缺一不可**：
   - 任一 `action == "release"` 落在 `spec.releasable is False` 的类型上 → `422 asset_type_not_releasable`。
     绝不允许写 `NULL` 进非空列，也绝不允许静默保持原归属
   - 任一 `action == "transfer"` 的接收人有问题 → 拒绝。**状态码按原因分开，不能一律 422**
     （**默认接收人与每一条 override 的接收人，三个位置用同一套规则**）：

     | 原因 | 状态码 | 对齐依据 |
     |---|---|---|
     | 接收人 sub **映射不到本地用户** | **409** | 契约 §10.6「人员无法识别 → 409」。EasyProject 的 `IDENTITY_UNMAPPED` 也是 409，两个下游必须一致，否则同一种故障在 EasyAuth 上显示成两种语义 |
     | 接收人为空 / 非 active / 等于 `from_user_id` | **422** | 载荷本身不合法，与身份系统无关 |

     **这一整条早期漏了**：畸形 payload 会让可空列（客户、活动）被静默释放，
     非空列（订单、询盘、任务、需求、样品）则要到 flush 时才炸
   - `snapshot_token` 与当前数据状态不一致 → 整体 **`412`**（见 §3.5.1），**零写入**
   - **摘要一致之后**才逐条验证 override 的 id：存在、仍属于 `from_user_id`、仍满足该类型谓词。
     **不得**把无效 id 默默排除出默认集（那等于静默跳过）。
     此时失败只可能源于请求本身 —— `overrides` 引用了**本次快照集合之外**的 asset_id
     → 整体 `409`；**归属或谓词状态在 preview 之后变了 → 走 412，不是 409**

   > **这两项的先后是规范的一部分，不是实现自由**（契约 §10.5.1 第 4 条冻结）。
   > 逐条校验天然写在行循环里、比重算全量摘要更早，所以不写死顺序的话，
   > 「preview 之后有个客户被别人认领了」这一次普通竞态会**先命中 409** ——
   > 而 409 在 EasyAuth 侧是**不可重试的 `failed`**，界面只剩「应用拒绝了本次交接」，
   > assignee 没有任何前进路径。正确处置是 412 → 退回 `pending` → 重新预演。
   > 这是本节唯一会把可恢复故障变成死局的地方。
3. **先冻结主键集合，再统一加锁，且忽略 payload 里 assignments 的顺序。**

   两步走：
   - 第一步（无写入）：逐 `asset_type` 跑 `spec.query` 解析出受影响的主键集合，连同 override 的
     id 一起冻结下来。
   - 第二步：按**固定的全局表序**加 `with_for_update`，同表内按 id 升序：

     ```
     Customer → Inquiry → Activity → SampleRequest → Order → OrderReceivable
              → Task → ProductRequirement
     ```

   > **⚠ 既有代码里有三条反向锁路径，启用 handover 之前必须全部整改**（不是可选项）：
   >
   > | # | 现状 | 与本表序的冲突 |
   > |---|---|---|
   > | 1 | 活动 **update** 先锁 Activity 再取关联 Inquiry（`api/v1/activities.py:159-170`）。**`delete_activity`（`:195-197`）已经是正序**，只补回归用例，别去动它 | 本序是 `Inquiry → Activity` |
   > | 2 | 订单写路径先锁 `Order`，随后 `derive_stage()` 去改 `Inquiry`。**`orders` 表有三个彼此独立的行锁入口，三个都要改**：<br>① `api/v1/orders/common.py:80` 的 `_get_visible_order`（下游 `orders/routes.py:213`、`route_mutations.py:161`、`update_order_helpers.py:209`、`finance_payments.py:118`、`finance_payment_mutations.py:190`、`finance_receipt_confirmation.py:221` 都由它加锁）<br>② `api/v1/order_payment_completion.py:31` —— **同名但独立的私有 `_get_visible_order`**，无条件加锁，`:145` 调 `derive_stage`<br>③ `api/v1/pipeline_shipments.py:239` 的 `_resolve_order`，`:266` 调 `derive_stage`<br>（`derive_stage` 确实写 `Inquiry` 行：`domain/pipeline/stage_deriver.py:44-61` 直接赋值 `stage_id` / `last_activity_at` / `sampling_status` / `quotation_branch_status`，`:63` flush） | 本序是 `Inquiry → Order` |
   > | 3 | `delete_sample_request()` 先锁 `SampleRequest`，再进 `Inquiry → SampleRequest` 的 helper（`api/v1/sample_requests_delete.py:29-35`） | 本序是 `Inquiry → SampleRequest` |
   >
   > 整改口径统一为「**先无锁读出关联 id，再按全局表序加锁，锁后复核关联未变**」：
   >
   > 1. 活动：目标形态是 `Customer → Inquiry(id 升序) → Activity`
   >    —— 这**正是 `delete_activity` 的现状**，也是现成 helper `activity_helpers.py:127-144` 的形态。
   >    真正要做的只有一件事：把 `update_activity` 的 `inquiry_ids` 解析（`:167-169`）
   >    提到锁 Activity **之前**，合并成一次 `_lock_activity_aggregate_rows`，锁后复核
   >    `activity.inquiry_id` 未变。工作量比「update/delete 都要改」小一半；
   > 2. 订单：**改造对象是每一个 `orders` 表的 `with_for_update` 入口（上表列的三处），
   >    不是某一个 helper。** 每处都先只读拿到 `inquiry_id`，按 `Inquiry → Order` 加锁，
   >    锁后复核 `Order.inquiry_id` 未变，再做订单改写与阶段推导。
   >    只改 `orders/common.py` 的话，结算路径与发货推进路径仍是反向的，
   >    而三条死锁用例按旧文档只会覆盖那一处 —— **PR 合了、测试绿了，死锁还在**；
   > 3. 样品：`delete_sample_request()` **不得**在调 `lock_sample_write_roots()` 之前先锁
   >    `SampleRequest`；先无锁读，再统一 `Inquiry → SampleRequest` 加锁，锁内重验取消状态。
   >
   > 三条各补一个 PostgreSQL 双事务死锁用例。PostgreSQL 会回滚其中一方，交接那边表现为 5xx。
   >
   > **为什么必须无视 payload 顺序**：EasyAuth 的 `assignments` 数组顺序由前端决定。
   > 若照单遍历，一次「先 `receivable_open` 后 `order_in_transit`」的请求会**先锁应收再等订单**，
   > 而既有的订单取消路径（`api/v1/orders/routes.py`、`route_mutations.py`）是**先锁订单再改应收**
   > —— 两者反向，直接死锁。
   >
   > **另一个必须先冻结的理由**：应收的归属谓词会**继承订单负责人**（§2.1.1）。
   > 如果先改了订单 owner 再实时跑应收 selector，那些 owner 为 NULL 的应收会因为
   > 订单已经不属于当事人而**从集合里凭空消失**，静默漏转。
   > 所有 `reassign` 只能操作第一步冻结下来的主键集合，**不得在前序改写后重新执行责任谓词**。

4. **锁内**重算 `snapshot_token` 并逐条复核 —— **这一步的每一项校验都必须在拿到行锁之后重做一遍**：
   - 每个待改写的条目**当前仍属于 `from_user_id`** 且仍满足该类型谓词；
   - **接收人与来源用户的 `users` 行也要一起锁**（在资产之前锁），并在锁内复核
     `receiver.active` —— 否则校验通过之后、写入之前，目录同步可能刚好把接收人停用；
   - **顺序固定**：先重算摘要比对，不一致 → **412** 且零写入；
     摘要一致之后才逐条复核，此时失败只可能源于请求本身（`overrides` 引用快照外的
     asset_id / 接收人 sub 映射不到 / 迟到 generation）→ **409**。
     **归属在 preview 之后变化的一律 412，不得用 409 表达**（契约 §10.5.1 第 4 条）。二者都零写入。

   > 锁前校验、锁后写入之间的窗口是真实存在的：验证订单仍属 A 之后、拿到订单锁之前，
   > 并发事务把它转给了 C 并提交；handover 拿到锁却不重验，就把 C 的订单又覆盖给了 B。
5. 处理 `overrides`（精确 id 集合），再按 `default_action` 处理剩余条目
   —— **只在第 3 步冻结、第 4 步复核通过的集合上操作**：
   ```
   overridden_ids = {o.id for o in overrides}
   for o in overrides:
       if   o.action == "transfer": reassign(单条, o.to_user_id)
       elif o.action == "release":  reassign(单条, None)
       else:                        pass          # skip: 原样不动
   rest = frozen_ids - overridden_ids               # 不重跑谓词查询
   if   default_action == "transfer": reassign(rest, default_to_user_id)
   elif default_action == "release":  reassign(rest, None)
   else:                              pass        # skip: 整批不动
   ```
   写 `NULL` 只可能发生在 `action == "release"` 分支，而该分支已被第 2 步保证只落在
   `releasable=True`（即可空列）的类型上 —— B1 从结构上不可能再复发。

   #### 5.1 `receivable_open` 的 `skip` 需要一次显式物化，否则"不动"会变成"动了"

   应收的**有效负责人**在 `owner_user_id` 为 NULL 时**继承订单负责人**
   （`domain/ar/ownership.py:12-24`）。于是有这样一条路径：

   > 应收 R 的 `owner_user_id = NULL`，其订单 O 属于离职者。
   > 请求把 `order_in_transit` 转给 A，对 `receivable_open` 指定 `skip`。
   > 执行后 R 的列值确实一个字节没改 —— 但它的**有效负责人已经从离职者变成了 A**，
   > 而 summary 报的是 `skipped`。

   规定：冻结阶段为每条**继承型**（`owner_user_id IS NULL`）应收记下
   `effective_owner_before`；若其订单的负责人在本次会变化，则

   | 该应收的 action | 处理 |
   |---|---|
   | `transfer` | 正常写入指定接收人 |
   | `skip` / 该类型未出现在 `assignments` 里 | **把 `effective_owner_before` 显式写进 `OrderReceivable.owner_user_id`**，让"保持原归属"真的成立 |
   | `release` | 仍然 422（`releasable=false`） |

   这次物化写入**必须写审计**（它是一次真实的列变更，尽管语义上是"维持原状"）。
   验收用例必须包含「订单 transfer + 继承型应收 skip」这一组合。

6. **必须走既有的领域命令，保住副作用**，不能裸 UPDATE：
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
7. 客户归属变更继续写既有的负责人变更事件（`_handover_customers` 中的 owner history），
   `reason` 按 `kind` 取：`offboard`→「EasyAuth 离职交接」、`transfer`→「EasyAuth 转岗交接」、
   `reassign`→「EasyAuth 数据移交」，释放时→「EasyAuth 交接释放公海」。
8. 返回**冻结的五元** `{asset_type: {"transferred": n, "released": m, "skipped": k, "merged": 0, "failed": 0}}`，
   外层包成 `{"summary": result}`（契约 §10.5）。

   > **`merged` 与 `failed` 即使恒为 0 也必须显式返回。** 契约把 summary 定义为五元冻结结构，
   > EasyAuth 会按 `transferred + released + skipped + merged + failed == count` 做守恒校验；
   > 少两个键会让校验取不到值。EasyTrade 没有复合主键合并场景（`merged` 恒 0），
   > 也不实现部分成功（`failed` 恒 0），但**不返回**与**返回 0** 是两回事。
   >
   > 另注意现有实现返回的是 `customers_transferred` 这类扁平旧键（`easyauth_handover.py:61,117-129`），
   > 与 v2 完全不匹配，属于要整体替换掉的部分。

**幂等**：幂等键从 `task_id` 改为三元组 `(task_id, generation, batch_id)`（契约 §10.5.2）。

**串行化机制与顺序都定死**（对应上面的第 0–2 步）：

1. 解析出三元组与 canonical hash 之后，**第一项数据库操作**是
   `acquire_advisory_xact_lock(db, "easyauth_handover_task", task_id)`
   （复用既有的 `domain/shared/advisory_lock.py:16`）；
2. **锁内**先查同三元组回执：hash 相同 → **立即返回原 `result`，不做身份、active、snapshot 任何校验**；
   hash 不同 → `409`；
3. 只有全新键才继续读 generation 水位、校验快照、改写资产、插入回执；
4. 事务提交后释放锁（xact lock 随事务自动释放）。

> **顺序不能反**：首次成功已经改过数据，token 必然失效；重放若先校验，会返回 412/409
> 而不是那份保存好的 200 summary。
> **advisory lock 也不能省**：并发的 `generation=1` 与 `generation=2` 会同时读到相同的
> 水位值，各自通过判定、各自写入不同的三元组回执，旧一轮的 payload 在升级之后被执行。

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
**generation 水位单独建表，不用 `MAX()` 扫描**（与 EasyProject 的裁定一致，`08` §1.4）：

```
easyauth_handover_generation_watermarks(task_id VARCHAR(64) PRIMARY KEY,
                                        max_generation INTEGER NOT NULL,
                                        updated_at TIMESTAMPTZ NOT NULL)
```

事务内**先锁定或创建**该行 → 小于水位立即 409 → 大于则推进；
水位推进、回执写入、业务改写**同事务提交**。

> **不允许用未串行化的 `SELECT MAX(generation)`。** `generation=2` 与迟到的 `generation=1`
> 并发时，两个查询会互相看不见对方，双双通过判定，旧 payload 在升级之后被执行。

**DEFAULT 只为迁移历史行服务，加完必须去掉**：三列在应用层都是必填，
留着 server default 会让漏传字段变成静默写入默认值。

**`task_id` 收窄为 `VARCHAR(64)` 并加同等 CHECK**。契约 §5.4 的格式是 **`{handover_task.id}:{app.id}`，两段都是十进制**，所以入口校验必须写成 **`re.fullmatch(r"[0-9]+:[0-9]+", task_id)`**（或 `\A[0-9]+:[0-9]+\Z`）、UTF-8 长度 1–64 字节，不满足 → `422`。

**不要写成 `re.match(r"^[0-9]+:[0-9]+$", ...)`** —— Python 的 `$` 在**结尾换行之前**也匹配，
`"137:1\n"` 会通过校验。于是 `"137:1"` 与 `"137:1\n"` 是两个不同的 `task_id`，
落成两行回执、推进两次 generation 水位、执行两次归属改写 —— §3.7 的三元组幂等被整个绕过。
**不要写成 `[A-Za-z0-9:_-]`** —— 那会放行契约明令禁止的字母/下划线/连字符，把上游还没迁移完（仍在拼 `app_key`）这件事**掩盖过去**。
测试必须拒绝 `137:easytrade`、`137_app`、缺冒号的值，**以及 `"137:1\n"` 与 `" 137:1"`**。
不加的话，65–255 字符的非法键会被现有列**照单收下**，超过 255 才到 flush 时炸成 500 ——
一个本该在入口稳定 422 的输入变成了不稳定的 5xx。迁移前先检查历史行。

**不新增业务列**：所有资产类型都复用既有归属字段。`Order`/`Inquiry` 的非空约束
**保持不变**，靠 `releasable=false` 在契约层解决，而不是放宽不变量。

---

## 4. SDK 升级

`backend/vendor/easyauth-app-sdk` 更新到含 v2 的版本，接入点改动：

- **`backend/app/api/v1/easyauth_lifecycle.py` 必须改接 SDK 的
  `lifecycle_http_response()` / FastAPI helper，不能继续自己调 `verify_webhook` 再按头分发。**

  > 现状是：`await request.body()` 读全量体 → `verify_webhook(...)` → **按事件头 if/elif 分发**，
  > 且第一支就是 `if event.event_type == EVENT_WEBHOOK_TEST: return {"ok": True}`
  > （`api/v1/easyauth_lifecycle.py:39-50`）。
  >
  > 这意味着两件事：
  > 1. **"升级 SDK 就自动拿到 `event_type` 校验"是不成立的** —— 校验在 SDK 内核里，
  >    而这条路由压根不走内核。截获一个合法 execute 请求、只把事件头改成 `webhook.test`，
  >    它照样在业务分发前返回 200，数据一条没搬而 EasyAuth 记成功。
  > 2. `await request.body()` **在验签之前就把整个体读进内存**，256 KiB 上限形同虚设：
  >    不持有 secret 的人也能用超大或 chunked body 反复打内存。
  >    必须改用 SDK 的 `read_bounded_body()`（先看 `Content-Length` 预拒，再流式读到 N+1 截断）。
  >    测试要同时覆盖**伪造 `Content-Length`** 与 **chunked 超限**两种。

- 增加 `on_handover_items` 回调
- 请求体上限跟随 SDK 提升到 256 KiB
- 直接使用 SDK 的 `handover_payloads` TypedDict，**禁止**在 EasyTrade 内手抄字段名
- **业务错误一律抛 SDK 的 `HandoverBusinessError(status_code, code, message)`**（`01` §8 第 6.1 条）。
  现有 `HandoverCallback` 只返回 dict，内核把一切都包成 200 或 500 ——
  §3.6 要求的 409 / 412 / 422 **发不出去**。这是 SDK vNext 的前置改造，不是 EasyTrade 能绕开的
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

> **判定依据是 `event_type`，不是 `mode`**（`mode` 对 `items` 与 `webhook.test` 都失效，
> 理由见契约 §10.1）。这一校验由 SDK vNext 统一实现（`01` §8 第 6 条），
> EasyTrade 只需升级 SDK 并补验收用例。

**必须有负向测试**（§5）：签名合法的前提下，
① 把两个事件头对调、② 把事件头改成 `webhook.test`、③ 篡改 delivery 头 —— 断言前两者 422。

---

## 5. 测试

| 文件 | 覆盖 |
|---|---|
| `backend/app/tests/test_easyauth_handover_assets.py` | 8 类资产的 count 口径；`count=0` 也返回；注册表与 descriptor 一致（用同一常量断言） |
| `backend/app/tests/test_easyauth_handover_items.py` | 分页稳定性（连续翻页不漏不重）；**`page`/`page_size`/`q` 三项越界都返回 422**（含 `page_size` 为 0、负数、201 —— 断言必须是 422 而不是钳制，否则正确实现会被打红）；**`total` 的两种口径**：`q=""` 时等于 preview 的 `count`，`q!=""` 时等于**过滤后**的数量（可选的 `unfiltered_total` 才等于 `count`）。**不要写成"`total` 始终等于 preview count"** —— 那会把正确实现打红，而迎合它的实现会让前端翻出一堆空页 |
| `backend/app/tests/test_easyauth_handover_execute.py` | override 优先于 default；剩余条目按 `default_action`；三值 action 各自行为；**B1** 非空列永不写 NULL；**B2** `release` 落在 `releasable=false` 上抛 422 而非静默；`default_action="skip"` + 逐条 `transfer` 能对非空列做部分交接；`(task_id, generation, batch_id)` 幂等；不同 generation 真正重执行 |
| `backend/app/tests/contract/test_handover_v2_golden.py` | 从 `easyauth_app_sdk.contract_samples` 包内资源读取样本逐字段比对；样本缺失必须 fail |
| `backend/app/tests/test_easyauth_lifecycle.py` | 既有用例按 v2 payload 重写；**§4.1 负向用例**：签名合法但 `X-EasyAuth-Event` 与 body **`event_type`** 不一致（含把事件头改成 `webhook.test`）→ 422 |
| `backend/app/tests/test_easyauth_handover_snapshot.py` | §3.5.1：preview 返回 token；数据变动后 execute 整体 **412** 且**零写入**（**不是 409** —— 409 会被 EasyAuth 判 `failed`，只有 412 才退回重预演）；override 的 id 已不属当事人 → **409**；分批时旧 token 不可复用 |
| `backend/app/tests/test_easyauth_handover_locking.py` | §3.6 第 4 步：assignments 顺序颠倒时加锁次序不变；先冻结主键后订单 owner 改写不会让 NULL-owner 应收从集合消失 |
| `backend/app/tests/test_easyauth_handover_identity.py` | §3.6 身份边界：payload 里三个位置的 sub 全部解析为本地 id；**overrides 里的接收人不得漏解析**；**解析不到 → 409**（契约 §10.6「人员无法识别」，与 EasyProject 的 `IDENTITY_UNMAPPED` 一致）；**为空 / 非 active / 等于当事人 → 422** |

golden 样本的取用方式：**随 SDK 一起分发**，作为 `easyauth_app_sdk` 的包内数据资源
（`easyauth_app_sdk.contract_samples`），版本与 SDK 绑定。测试通过 `importlib.resources` 读取。

**不得**依赖 `../EasyAuth/` 这样的兄弟目录相对路径 —— 本仓库 CI 独立检出，那条路径必然不存在，
测试会稳定退化成 skip。**样本缺失必须让测试失败**，不允许 skip 通过（`AGENTS.md`：不得用空结果兜底掩盖真实问题）。

---

## 6. 交付顺序

0. **§4 SDK 升级放在第一步**：更新 `backend/vendor/easyauth-app-sdk` 到 vNext，
   更新 `VENDORED.md`（版本 + 构建 commit SHA + wheel SHA-256），
   并验证五项能力可用：items 回调、`handover_payloads`、256 KiB、
   `manifest.py` 放行 `handover_asset_types`、`HandoverBusinessError`。
   **这一步没做完，后面每一步都只能造本地 shim，之后再返工。**
0.5. **§3.6 第 3 步的三条反向锁路径整改，单独出一个 PR 先合。**
   活动 update/delete、订单经 `derive_stage()` 改询盘、样品删除 —— 三处的加锁方向与本设计相反，
   交接一上线就会与它们并发死锁（PostgreSQL 会回滚其中一方，交接侧表现为 5xx）。

   > **必须单独成 PR，不要混进交接的改动里。** 它改的是**既有业务路径**，
   > 回归面比交接代码本身大，混在一起 review 会无从下手；
   > 而且它与 SDK 升级无关，**可以与第 0 步并行做**。

1. ~~§3.1 修 B3~~ —— 本期取消（代管废弃）
2. §3.3 资产注册表 + §3.2 descriptor（两者共用常量，必须同一提交）
3. §3.4 preview + §3.5 items + §3.5.1 snapshot_token
4. §3.6 execute 重写 + §3.8 迁移（修 B1/B2）
5. §4.1 event_type 一致性校验的验收用例
6. §5 测试补齐

每完成一项立即单独 commit。改完后端后必须重建容器镜像并重启，host dev server 不算上线。
全量门禁：**`BACKEND_TESTS='app/tests' make finish-check`**。
**不能只写 `make finish-check`** —— 它默认跳过全部 `app/tests`（`scripts/finish-check.sh:68`），
本次新增的交接用例会**一条都不被收集，而门禁照样绿**。
（本仓库没有 `make quality` 这个目标。）
