# 02 · EasyAuth 前端改造设计

> 基准文档：[`00-overview-and-contract.md`](00-overview-and-contract.md)（下称「契约」）
> 与 [`01-easyauth-backend.md`](01-easyauth-backend.md)（下称「后端设计」）。
> 本文件只依赖后端设计 **§6 HTTP API 契约**；该章节冻结后即可开工，不必等后端实现完成。
> 开发期可用 MSW 或本地 fixture 顶住，但**禁止把假数据留进产物**（`AGENTS.md`：不得用模拟数据掩盖真实问题）。

---

## 1. 现状与工程约定

单一 pnpm 包 `@easyauth/frontend`，Vite 7 + React 19 + TypeScript + Tailwind 4 + React Router 7，
一份产物同时承载门户与控制台两个界面，由 URL 与 Django 注入的 data 属性区分
（`frontend/src/main.tsx:15-54`）。

| 事项 | 约定 | 位置 |
|---|---|---|
| 路由 | 集中声明，页面懒加载 | `frontend/src/App.tsx:82-125` |
| 请求 | 手写 `apiRequest<T>` 包 `fetch`，带 session、CSRF、`ApiError`、401 全局事件 | `frontend/src/lib/api.ts:63-111` |
| 状态 | TanStack React Query，默认 `staleTime` 30s、关闭 focus refetch | `frontend/src/lib/query.ts:1-10` |
| 类型 | 领域 DTO 集中在 `frontend/src/lib/domain.ts`（lifecycle 段落 584-733） | — |
| 组件 | 无第三方组件库；自研 Tailwind 体系 + `components/ui/` 原语 | `frontend/src/components/ui/` |
| 表格 | TanStack Table headless + 自研 `TablePrimitives` | `components/ui/TablePrimitives.tsx:21-111` |
| 表单 | 自研 `Field` / `TextInput` / `TextArea` / `SelectInput` | `components/Field.tsx:6-87` |
| i18n | 自研 Provider，`zh-CN` 为权威 key 目录，英文编译期校验 key 对齐 | `src/i18n/I18nProvider.tsx`、`src/i18n/messages.ts` |
| 测试 | 同目录 `*.test.tsx`，Vitest + jsdom + Testing Library；e2e 在 `frontend/e2e/`、`frontend/e2e-fullstack/` | — |
| 构建 | `pnpm --filter @easyauth/frontend build`（tsc 工程检查 + Vite 构建 + bundle 预算） | `README.md:514-516` |

现有生命周期界面（**全部在控制台，门户零覆盖**）：

- `pages/console/lifecycle/HandoverTaskList.tsx` — 列表、筛选、分页、删除
- `pages/console/lifecycle/HandoverTaskDetail.tsx` — 详情、逐 APP action、转岗差异、团队项、重试/取消/删除
- `pages/console/lifecycle/HandoverWizard.tsx` + `handoverWizardController.ts` — 五段式向导：
  应用 → 接收人 → 授权 → 预演 → 执行
- `pages/console/lifecycle/OnboardingPage.tsx` — 入职模板

---

## 2. 改造总览

| 界面 | 性质 | 说明 |
|---|---|---|
| 门户「我的交接」列表 | **新建** | D1 自助化的入口 |
| 门户交接单详情 + 资产分配器 | **新建** | 承载 D10 的按类全选 + 逐条改派 |
| 门户「提前交接」发起 | **新建** | D7 |
| 门户「移交下属数据」发起 | **新建** | D8/D9 |
| 控制台 `HandoverWizard` | **重构** | 接收人从 APP 级下沉到资产条目级，第 2 段整段重写 |
| 控制台 `HandoverTaskDetail` | 扩展 | 展示 blocked / skip / **上交倒计时**（`escalation.days_left`）/ assignee 与上交层级；顺延按钮仅在 `escalation.deferred_at == null` 时可点 |
| 控制台 `HandoverTaskList` | 扩展 | 新增 `assignee_state`、`blocked` 筛选与角标 |
| 控制台顶部告警条 | **新建** | 未接入 APP 常驻告警（D6） |
| 控制台 APP 能力声明 | **新建** | 在 app 详情页声明 `none` / 手动同步 descriptor |

### 2.1 复用策略（重要）

门户与控制台的**资产分配器是同一个组件**，只是数据源端点前缀不同
（`/portal/api/v1/...` vs `/console/api/v1/lifecycle/...`）。
放在 `src/features/handover/`（新目录），两个 surface 各自的 page 只做壳与权限差异。
**禁止**为门户复制一份控制台组件 —— 那正是"App 一多难免遗漏"在前端的同构版本。

---

## 3. 路由与 Django 壳

### 3.1 新增门户路由（`src/App.tsx`）

| 路径 | 组件 |
|---|---|
| `/portal/handovers` | `PortalHandoverList` |
| `/portal/handovers/:taskId` | `PortalHandoverDetail` |

**Django 侧必须改动，不能只靠 React 路由。**
`portal_react_route`（`src/easyauth/portal/urls.py:51`）的 `<path:_portal_path>` catch-all
确实已经把深路径交给同一 React 壳，但 `portal_home` / `portal_react_route` 现在**只校验
session 用户 active**（`portal/views.py:16-27`）—— 而 break-glass 本地管理员正好是一个
active 的 `local-admin:*` `UserMirror`（`accounts/local_admin.py:125-134`）。

结果是「界面进得去、API 才拒绝」的**半授权状态**：本地管理员能打开 `/portal/handovers`，
看到完整的员工自助界面框架，只是每个请求都 403。

因此：**门户壳视图与全部自助 API 共用同一个门禁** `require_portal_user()`，
session subject 以 `LOCAL_ADMIN_SUBJECT_PREFIX` 开头时**在 Django 层直接 403**。
**React 路由不承担这条安全边界** —— 前端路由只管展示。

### 3.2 控制台

新增 `/console/apps/:appKey` 内的「数据交接」标签页（app-workspace tab），不新增顶层路由。

### 3.3 导航

- 门户侧边栏（`components/shell/Sidebar.tsx`）新增「我的交接」，**仅当**
  `GET /portal/api/v1/me/handover-tasks` 返回的两组之和 > 0 时显示角标数字；条目本身常驻，
  避免"有单却看不到入口"。
- 控制台 `Sidebar.tsx:43-49` 的 operations 分区新增 `blocked-apps` 段。

---

## 4. 类型定义（`src/lib/domain.ts`，追加）

严格对齐后端设计 §6.2。**不要另起 camelCase**：EasyAuth 后端 JSON 是 snake_case，
现有 `domain.ts` 也是 snake_case，保持一致。

```ts
export type HandoverKind = "offboard" | "transfer" | "pre_offboard" | "reassign";
export type HandoverTaskStatus = "pending" | "in_progress" | "completed" | "cancelled";
export type HandoverAssigneeState = "manager" | "subject" | "superuser_pool";
export type HandoverActionStatus =
  | "pending" | "previewed" | "executing" | "async_pending"
  | "done" | "failed" | "skipped" | "blocked";

export interface HandoverUserRef {
  user_id: string;
  name: string;
  department?: string;
  status?: "active" | "disabled" | "departed";
}

export type HandoverAssetAction = "transfer" | "release" | "skip";

export interface HandoverAssetType {
  type: string;
  label: string;
  count: number;
  detail_supported: boolean;
  releasable: boolean;
  default_action: HandoverAssetAction;
  default_to_user: HandoverUserRef | null;
  override_count: number;
}

export interface HandoverAssetSummary {
  transferred: number;
  released: number;
  skipped: number;
  merged: number;
  failed: number;
}

export type HandoverAllowedAction = "preview" | "execute" | "retry" | "skip";

export interface HandoverBatchProgress {
  completed: number;
  total: number;
  current_batch_seq: number;
}

export interface HandoverAction {
  app_key: string;
  app_name: string;
  status: HandoverActionStatus;
  blocked_reason: string;
  skip_reason: string;
  /** 强行跳过的责任链; 单据上永久展示「已由 X 于 T 强行跳过」 */
  skipped_by: string;
  skipped_at: string | null;
  last_error: string;
  /** 后端算好的可用操作; 前端不得解析 last_error 猜可不可重试 */
  allowed_actions: HandoverAllowedAction[];
  /** execute 必须回带; 与服务端不一致时 409 confirm_version_stale。
   *  preview 成功、改类型级默认、整体替换 overrides、改 grant_receiver 四件事都会 +1 */
  confirm_version: number;
  /** PUT overrides 必须回带; 整体替换的并发保护 */
  overrides_version: number;
  /** 413 分批时非 null。非 null 期间禁止改分配(后端会 409 batch_plan_in_progress) */
  batch_progress: HandoverBatchProgress | null;
  asset_types: HandoverAssetType[];
  /** 在途钉钉审批的存在性警示; 建单时写入, 升级与完成都不清除 */
  approval_instance_warning: { message: string; link: string; recorded_at: string } | null;
  /** 仅 kind=offboard 有意义; null = 只撤权不转授 */
  grant_receiver: HandoverUserRef | null;
  /** done 之后才有; 按 asset_type 分组的五元统计 */
  summary: Record<string, HandoverAssetSummary> | null;
  /** 非 null = 数据已落地、权限尚未转授(契约 §10.5.1.1)。failed 时靠它区分两种现场 */
  data_completed_at: string | null;
}

export interface HandoverDeferRecord {
  escalation_level: number;
  actor_id: string;
  at: string;
  reason: string;
}

export interface HandoverEscalation {
  deadline: string | null;   // null = 已落超管池, 不再上交
  days_left: number | null;
  level: number;
  /** 顺延责任链, 由审计事件生成; deferred_at 上交时会清空, 这个不会 */
  defer_history: HandoverDeferRecord[];
  /** 非 null = 本层级已被超管顺延过一次, 顺延按钮必须禁用(01 §6.3) */
  deferred_at: string | null;
}

export interface HandoverTaskDetail {
  id: number;
  kind: HandoverKind;
  status: HandoverTaskStatus;
  generation: number;
  subject: HandoverUserRef;
  assignee: HandoverUserRef | null;
  /** 与 assignee 平级: assignee 为 null(超管池)时这两个字段仍然有值 */
  assignee_state: HandoverAssigneeState;
  escalation_level: number;
  escalation: HandoverEscalation;
  reason: string;
  created_at: string;
  actions: HandoverAction[];
  team_items: HandoverTeamItemRow[];   // 既有类型(domain.ts:638), 形状不变——注意是 Row 后缀
}

export interface HandoverAssetItem {
  id: string;
  label: string;
  hint: string;
}

export interface HandoverAssetItemsPage {
  items: HandoverAssetItem[];
  page: number;
  page_size: number;
  total: number;
  stale?: boolean;
}
```

---

## 5. 门户界面

### 5.1 `PortalHandoverList`

数据源：`GET /portal/api/v1/me/handover-tasks` → `{ handover_tasks: { as_assignee: [...], as_subject: [...] } }`
（**带信封**，与详情一致；直接读裸对象会拿到 `undefined`）

布局：两个分区，**`as_assignee` 在上**（那是待办，有截止压力）。

`as_assignee` 每张卡片必须一眼看到四件事：

```
┌──────────────────────────────────────────────────────────┐
│ 王某某 · 华东销售部          [离职交接]  [还剩 9 天]      │
│ 待处理 2 个应用 · 251 条数据待交接                        │
│ ⚠ 1 个应用未接入交接                                      │
│                                        [ 去处理 ]        │
└──────────────────────────────────────────────────────────┘
```

- 「还剩 N 天」来自 `escalation.days_left`：`>7` 中性色，`3–7` 警示色，`<3` 危险色；`deadline` 为 null 显示「待超管认领」。
- `blocked_app_count > 0` 时显示⚠行，文案：「N 个应用未接入交接，需管理员处理」，**不给普通用户跳过按钮**。
- 空态文案：「你当前没有需要处理的交接。」不要画插画占位，与现有门户风格一致。

`as_subject` 分区只读，展示自己发起的提前交接进度。

### 5.2 `PortalHandoverDetail`

顶部信息条：当事人、类型、状态、距上交剩余天数、当前负责人与上交层级
（`escalation_level > 0` 时显示「已上交 N 级」）。

主体是**逐 APP 的可折叠区块**，按 `status` 决定形态：

| action.status | 区块表现 |
|---|---|
| `blocked` | 红底，标题「未接入交接」，正文「该应用尚未实现数据交接，无法确认是否有遗留数据。请联系管理员。」**无任何操作按钮** |
| `skipped` | 灰底，**永久**显示「已由 {skipped_by} 于 {format(skipped_at)} 强行跳过：{skip_reason}」。三个字段任一缺失 → 显示「责任链数据缺失」告警，**不得退化成匿名的「管理员」** |
| `pending` | 「尚未预演」+ [预演] 按钮 |
| `previewed` | 展开资产分配器（§6）+ [重新预演] [执行交接] |
| `executing` / `async_pending` | 骨架 + 轮询（React Query `refetchInterval: 3000`），禁用按钮 |
| **收到 `412 snapshot_stale`**（items 或 execute） | **立刻清掉该 action 的本地 items / override / 确认框状态**，重新拉详情，固定提示「清单已变化，请重新预演」。**不要把任何 409 当成快照失效** —— 409 是投递冲突或归属冲突，处置完全不同 |
| **收到 `423`** | 提示「该应用中部分对象正在审批/锁定，解除后请重新预演」，按钮按 `allowed_actions` 走（这是**可恢复**的临时状态，不是失败） |
| `done` | 绿底，按 `summary` 逐类展示五元统计（`merged`/`failed` 为 0 时可折叠，但不得隐藏字段） |
| `failed` 且 `data_completed_at == null` | 红底，「数据未移交，权限未变更」+ `last_error`。按钮**由 `allowed_actions` 决定**，不是固定 [重试] |
| `failed` 且 `data_completed_at != null` | 橙底，「**数据已移交成功，权限转移失败**」+ `last_error`。同上（重试只补做权限转移，不会重复搬数据） |

> **按钮一律读 `allowed_actions`，绝不自己判断。**
> 契约 §10.6 里 401/403/413/422 都是**不可重试**的 `failed`。
> 固定显示 [重试] 的话，用户会反复把同一份不受支持的载荷再发一遍，每次都失败；
> 而门户又不给 `failed` 任何跳过入口 —— action 永远进不了 `done`/`skipped`，整单卡死。
>
> - `allowed_actions` 含 `retry` → 显示 [重试]；
> - 含 `skip` → 显示 [填理由后跳过]（**只会出现在控制台**，D6 是超管专属）；
> - 两者都不含（门户遇到不可重试失败）→ 只显示「此项无法自动重试，请联系管理员处理」。
>
> **前端不得解析 `last_error` 文本去猜可重试性** —— 那是下游自由格式的字符串。

**控制台的 `failed` 区块多一个 [查看原始错误]（仅超管可见）**：点击才调
`GET .../actions/{app_key}/last-error-raw`，服务端每次读取都写审计。
**门户没有这个按钮**，`last_error_raw` 也不会出现在门户任何响应里（契约 §10.6）。

**413 不是不可重试的失败，别按 `failed` 渲染。** 后端此时 action 仍是 `previewed`
（只有那个超大 batch 记了 `failed`），`allowed_actions` 里也不会有 `retry` ——
重发同一份 payload 只会再 413 一次。

**`batch_progress != null` 时显示「已完成 {completed}/{total} 批」**
与 [执行下一批]，而不是 [重试]。每批执行前**必须重新预演**（契约 §10.5.2：同一 token 只能用一批），
所以 [执行下一批] 的动作是「重新 preview → 再 execute」两步，界面要把这一点说清楚。
只有最后一批成功后 action 才转 `done`。

> **最后两行必须分开显示，不能合成一个「失败」。** 契约 §10.5.1.1 把 execute 拆成
> 「先搬数据、再转授权」两步并持久化了中间态；两种失败的**现场完全不同**：
> 前者数据还在离职者名下，后者数据已经在接收人那里、只是权限还没跟上。
> 混成一句「执行失败」会让人以为可以放着不管，或者反过来手工再搬一次导致重复。

**关键交互约束**：[执行交接] 是不可逆动作，必须二次确认对话框，且确认文案要把后果说清楚：

> 即将把 **187 个客户、23 个在途订单** 移交给 **张某某**，其中 2 项另行指定了接收人。
> 执行后归属立即变更。如果发现给错人，需要再发起一次数据移交来纠正。

### 5.3 发起「提前交接」（`PortalPreOffboardDialog`）

入口：门户首页与「我的交接」页各一个次要按钮「我要提前交接工作」。

- 调 `POST /portal/api/v1/handover-tasks/pre-offboard`（建 `kind=pre_offboard` 单）
- 409 `open_task_exists` → 提示「你已有一张进行中的交接单」并给跳转链接
- 建单后直接跳详情页
- 对话框里必须明确写一句：「提前交接**只移交数据归属，不会影响你的账号权限**，你可以正常工作到最后一天。」
  （D7 的用户可见表达，避免员工因担心失去权限而不敢用）

### 5.4 发起「移交下属数据」（`PortalReassignDialog`）

入口：门户「我的交接」页，**仅当**当前用户对至少一人有管辖权时显示。
判定方式：`GET /portal/api/v1/handover-candidates?purpose=reassign_subject` 返回非空。

> **参数名以 `01` §6.1 为准：`purpose`，枚举 `receiver` / `reassign_subject`，必填。**
> 资产分配器里选**接收人**用 `purpose=receiver`（全体在职员工），
> 这里选**转出方**用 `purpose=reassign_subject`（限我的管辖范围）。
> 两者绝不能共用一次请求的结果 —— 把 `receiver` 的结果拿来当转出方候选，
> 等于让任何人都能移交任何人的数据。

字段：

| 字段 | 控件 | 校验 |
|---|---|---|
| 转出方 | 人员选择器，数据源 `?purpose=reassign_subject` | 必填 |
| **应用范围** | 多选，数据源 `GET /portal/api/v1/handover-app-options?subject_user_id=...`（`01` §6.1） | **必填至少一个**，对应 `01` §6.1 的 `app_keys` |
| 理由 | `TextArea` | 必填，≥10 字符，前端先校验再提交 |

提交 body 固定为 `{"subject_user_id": "...", "app_keys": ["..."], "reason": "..."}`，
并带 `Idempotency-Key` 头（对话框打开时生成一次 UUID，失败重试**复用同一个**，成功后才丢弃）。

**不得默认全选所有 APP** —— 那会把用户没打算移交的应用一起拉进单据（`00` §8.4 明说
同一 subject 可以有多张针对不同 APP 的 open `reassign` 单）。

> **列表的措辞是「可选择的应用」，不是「有数据的应用」。**
> preview 之前 EasyAuth 本地根本不知道某人在下游有没有数据 —— 那要建单之后才问得到。
> 写成「有数据的」会让实现者去找一个不存在的判据。

提交后建单跳详情，接收人在详情页的资产分配器里逐类指定（不在对话框里定）。
403 `out_of_managed_scope` → 「你没有该员工的管理权限，请联系管理员处理。」

---

## 6. 资产分配器（`src/features/handover/AssetAllocator.tsx`，核心组件）

这是 D10 的落地，门户与控制台共用。

### 6.1 折叠态（默认）

每个资产类型一行：

```
名下客户       187 条   [ 全部转给 ▾ ] [ 张某某 ▾ ]   其中 2 项单独指定   [展开明细]
在途订单        23 条   [ 暂不处理 ▾ ]                 其中 1 项单独指定   [展开明细]
进行中询盘      41 条   [ 全部释放 ▾ ]                                     [展开明细]
未完成任务       0 条   无数据
```

- **一个三选一的下拉**（不是勾选框）对应 `default_action`：

  | 选项文案 | `default_action` | 后续控件 |
  |---|---|---|
  | 全部转给… | `transfer` | 右侧出现人员选择器，必选 |
  | 全部释放为无主 | `release` | 无 |
  | 暂不处理 | `skip` | 无 |

- 「全部释放为无主」**仅当 `releasable=true` 时可选**；否则该项禁用，tooltip 写
  「该应用要求这类数据必须有负责人」。
- **逐条 override 的 action 下拉必须复用同一条规则**：所属类型 `releasable=false` 时，
  明细行的「释放为无主」同样禁用。只禁类型级、放行明细级的话，execute 前校验会整批返回 422
  （契约 §10.5 语义 3），连本来合法的逐条 `transfer` 也一起被拒。
- **`transfer` 与 `skip` 在任何 `releasable` 取值下都始终可用**，
  所以 `releasable=false` 的类型照样能用「暂不处理 + 逐条转移」做部分交接。
- **类型级的 action 或默认接收人一变，就必须立刻 `PATCH .../assets/{type}` 落库**，
  body `{"default_action": ..., "default_to_user_id": ...|null}`；保存期间禁用 [执行交接]；
  成功后用响应对象替换本地该类型，失败则**回滚控件**并保留错误提示。

  > 只改本地 state 不落库的话，会出现最难查的那种故障：用户把默认从「暂不处理」改成
  > 「全部转给张某」，确认框也显示"已安排 1 类"，而服务端存的还是 `skip` ——
  > execute **成功返回**，资产原样不动。

- 默认值是 `skip`（后端模型默认，见 `01` §2.3）。这意味着**用户什么都不做时不会误转任何数据**，
  但也意味着 UI 必须显眼地提示"还有 N 类未处理"，否则会出现"点了执行却什么都没发生"。
  在执行按钮旁常驻一行：`已安排 2 类 / 共 4 类`。
- `count=0` 的类型仍然显示，置灰标「无数据」并禁用下拉 —— **不要隐藏**。
  隐藏就等于回到了「看不出区别」的老问题。
- `detail_supported=false` 时不显示 [展开明细]。

### 6.2 展开态（明细改派）

`GET .../assets/{type}/items?page=&page_size=50&q=`，服务端分页 + 搜索。

```
搜索 [ 华东          ]                                       共 187 条
┌────────────────────────────────────────────────────────────┐
│ 上海某某国际贸易有限公司   最近跟进 2026-07-30 · 在途 3 单   │
│                                    接收人 [ 张某某 ▾ ]      │
│ 宁波某某进出口             最近跟进 2026-06-11               │
│                                    接收人 [ 李某某 ▾ ]  ●   │
└────────────────────────────────────────────────────────────┘
                                            [1] 2 3 4 →
```

- 每行是一个同样的三选一 + 人员选择器组合，默认**继承**该类的 `default_action`/`default_to_user`，
  以灰色表示"跟随默认"。
- 一旦改成与默认不同 → 变实色 + 右侧圆点标记，加入本地待提交的 override 集合。
- 改回与默认完全一致（action 与接收人都相同）→ 自动从 override 集合移除
  （不要留一条「值与默认相同的 override」，那会污染审计与 diff）。
- **展开明细时必须先 `GET .../assets/{type}/overrides` 把当前完整的 override 集合与
  `overrides_version` 一起拉回来**，加载成功前**禁止提交**。
- 保存：`PUT .../assets/{type}/overrides`，body 带 `overrides_version` + **完整**集合，**整体替换**。

  > **这两条是一体的，缺前一条会静默删数据。** PUT 是整体替换：
  > 用户刷新页面后只加载了当前页，组件里只有本页那几条 override，直接提交就会把
  > 其余（可能上百条）全部删掉，而且没有任何报错。
  >
  > `overrides_version` 不匹配 → `409 overrides_version_stale`：提示「有人刚刚改过这份分配，
  > 已为你重新加载」，**自动重新 GET 后让用户复核，不要静默覆盖**。

- 响应 `stale=true` → 顶部黄条「清单已变化，建议重新预演后再分配」。
  注意 `stale` 只在搜索框为空时才有意义（`q` 非空时 `total` 本来就是过滤后的数量，见 `01` §5.6）。

### 6.3 人员选择器（`HandoverUserPicker`）

数据源由 **surface adapter 注入**，不是把 URL 前缀替换一下：

| surface | 端点 |
|---|---|
| 门户 | `GET /portal/api/v1/handover-candidates?purpose=receiver&q=` |
| 控制台 | `GET /console/api/v1/lifecycle/handover-tasks/{id}/candidates?q=` |

> **不能只换前缀**：控制台既有的 `/console/api/v1/user-options` 的 `purpose` 只接受
> `employee` / `approver`（`admin_console/users_api.py:66-90`），传 `receiver` 直接 422；
> 传 `employee` 又会把当事人本人列进候选，一直到 execute 才报 `receiver_is_subject`。
`purpose` **必填**，漏传返回 `422 purpose_required`（`01` §6.1）。
输入 300ms 防抖。**React Query 是 v5**（`frontend/package.json`），保留上一批结果用
`placeholderData: (previous) => previous`，与现有 `components/UserSelect.tsx:22-39` 一致。
**不要写 v4 的 `keepPreviousData: true`** —— v5 的 options 类型不接受它，`pnpm build` 会在
TypeScript 阶段直接失败。
必须排除当事人本人（后端已排除，前端不重复实现，但要能正确渲染后端返回的空集）。

---

## 7. 控制台改造

### 7.1 `HandoverWizard` 重构

现有五段（应用 → 接收人 → 授权 → 预演 → 执行，`handoverWizardController.ts:5-18`）中，
**第 2 段「接收人」整段删除**，接收人不再是 APP 级选择。新的四段：

| 段 | 内容 |
|---|---|
| 1 应用 | 不变；`blocked` 的 APP 在此段即标红，且**不可勾选进入后续段** |
| 2 授权 | 不变（`HandoverGrantItem` 勾选，仅 `kind=offboard` 显示；`transfer` 转岗单仍走既有的差异确认界面） |
| 3 预演与分配 | preview 后直接内嵌 §6 的 `AssetAllocator`；**同段还要有一个 APP 级的「权限接收人」选择器**（`grant_receiver`），仅 `kind=offboard` 显示，可留空并注明"留空 = 只撤权、不转授" |
| 4 执行 | 不变，加 blocked 汇总提示 |

`handoverWizardController.ts` 的 stage 枚举、跳转守卫、以及对应测试同步改。

### 7.2 `HandoverTaskDetail` 扩展

- 顶部新增「负责人」卡片：assignee 姓名、`assignee_state` 中文标签、`escalation_level`、
  上交截止时间与剩余天数、**[顺延]**、[认领]（`assignee_state == "superuser_pool"` 时）。
- **[顺延] 打开理由对话框**（去空白后 ≥10 字符，前端先校验），
  提交 `POST .../escalation/defer` body `{"reason": reason}`；空 body 会稳定 422。
  按钮仅在 `escalation.deferred_at == null` 时可点（每层级一次）。
- **顺延的责任链要永久可见**：展示 `escalation.defer_history`
  （`[{escalation_level, actor_id, at, reason}]`），而不是只看 `deferred_at`
  —— 后者在上交到下一层级时会被清空，历史就没了。
  **[认领] 对本地管理员要禁用**：后端会返回 `403 local_admin_cannot_claim`（`01` §6.3）。
- 每个 action 区块新增 blocked/skipped 形态（同 §5.2 表格）。
- `blocked` 区块给超管一个 [强行跳过] 按钮 → 对话框必填理由（≥10 字符）→
  `POST .../actions/{app_key}/skip`。对话框需明确警示：
  > 跳过后这张交接单可以完成，但该应用里此人的数据**不会被交接，也不会有人知道**。

### 7.3 `HandoverTaskList` 扩展

新增筛选：`assignee_state`、「仅看被阻塞的」，对应 `01` §6.3 新增的 query
`assignee_state=manager|subject|superuser_pool` 与 `blocked=true|false`。
**必须由后端筛选**（它在数据库分页之前完成）；在当前页做本地过滤的话，
分页总数与后续每一页都是错的。
列表行新增两个角标：`blocked_app_count`（红）、`escalation.days_left`（按 §5.1 配色）。

### 7.3.1 控制台的「在职数据移交」入口（D9 的跨部门路径）

`01` §6.3 有超管专用的跨管辖范围 `reassign` 端点，但控制台里**没有任何入口** ——
门户正确地返回 `403 out_of_managed_scope` 并提示"请找管理员"，超管进了控制台却只看得到
offboard/transfer，业务流程到这里断掉。

在控制台人员页加一个「在职数据移交」按钮，表单三项：subject（人员选择器）、
**应用范围（多选，必填至少一项，不得默认全选）**、理由（≥10 字符）。
提交 `POST /console/api/v1/lifecycle/handover-tasks/reassign`，成功后跳转新单详情。

### 7.4 未接入告警条（`BlockedAppsBanner`）

数据源 `GET /console/api/v1/lifecycle/handover-blocked-apps`
（响应 `{app_count, task_count, apps:[{app_key, app_name, blocked_task_count}]}`），
挂在控制台 shell 顶部，常驻。

**仅在当前用户是超管时挂载**：`currentUser.isSuperuser` 为 false 时**既不渲染也不发请求** ——
控制台 workspace 允许 owner/developer 进入，他们请求这个超管端点只会持续拿到 403。
「数据交接」标签页同理：无权限时不加入 TABS，深链直接回退到 overview。

> ⚠ 3 个应用未接入数据交接，12 张交接单被阻塞。 [查看详情]

`count=0` 时不渲染。**不要做成可关闭的** —— 关掉就等于回到静默状态。

### 7.5 APP 能力声明（app-workspace 新标签页）

**初始数据源：`GET /console/api/v1/lifecycle/apps/{app_key}/handover-capability`**
（`01` §6.3）—— 既有的 app detail 接口**不返回**三态与资产类型，没有这个 GET 页面打开就是空白。

三态展示 + 两个操作：

- [重新同步声明] → `POST .../apps/{app_key}/handover-capability/sync`
- [声明本应用无用户级数据] → 对话框必填理由 → `POST .../apps/{app_key}/handover-capability`
  对话框警示：
  > 声明后，此应用将不再出现在任何交接单的待办里。如果它其实存有员工数据，这些数据将永久无人交接。

`declared` 时展示 descriptor 同步下来的 `asset_types` 表格（类型、名称、支持明细、可否无主）。

---

## 8. i18n

所有新增文案进 `src/i18n/messages.ts`，`zh-CN` 为权威，英文同步补齐（编译期 key 校验会挡住漏项）。
key 前缀统一 `handover.*`，门户专用 `handover.portal.*`，控制台专用 `handover.console.*`。

术语固定（**不得混用**）：

| 概念 | 中文 | 英文 key 片段 |
|---|---|---|
| HandoverTask | 交接单 | `task` |
| assignee | 负责人 | `assignee` |
| escalation | 上交 | `escalation` |
| asset type | 资产类型 | `assetType` |
| override | 单独指定 | `override` |
| blocked | 未接入交接 | `blocked` |
| release / 无主 | **释放为无主** | `release` |

---

## 9. 测试

| 文件 | 覆盖 |
|---|---|
| `features/handover/AssetAllocator.test.tsx` | 三选一切换；`releasable=false` 时「全部释放」禁用而「暂不处理」「全部转给」可用；`transfer` 必选接收人；override 改回默认自动移除；整体替换提交的 payload 形状；「已安排 N 类 / 共 M 类」计数 |
| `features/handover/HandoverUserPicker.test.tsx` | 防抖、空集渲染、排除本人 |
| `pages/portal/PortalHandoverList.test.tsx` | 两分区渲染；剩余天数配色分档；blocked 提示无跳过按钮 |
| `pages/portal/PortalHandoverDetail.test.tsx` | 八种 action 状态各自形态；执行前二次确认文案含数量与接收人 |
| `pages/portal/PortalReassignDialog.test.tsx` | 理由 <10 字符不可提交；403 文案 |
| `pages/console/lifecycle/handoverWizardController.test.ts` | 四段跳转守卫；blocked 应用不可进入后续段 |
| `pages/console/lifecycle/HandoverTaskDetail.test.tsx` | 跳过对话框必填理由；认领与续期按钮的显示条件 |
| `e2e-fullstack/handover-self-service.spec.ts` | 主管登录门户 → 打开单 → 改派 2 条 → 执行 → 状态变 done |

---

## 10. 交付顺序

1. §4 类型 → §6 `AssetAllocator` + `HandoverUserPicker`（可独立测试，不依赖页面）
2. §5 门户三个界面
3. §7 控制台改造
4. §8 i18n 补齐 → §9 测试
5. 全量 `pnpm --filter @easyauth/frontend build` 必须成功（含 bundle 预算）

每完成一项立即单独 commit。前端产物改动后必须重启 Django 开发服务并用真实 HTTP 响应验证新
manifest 已被加载，构建成功不等于上线（`AGENTS.md`）。
