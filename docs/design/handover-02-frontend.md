# 数据交接 v2：EasyAuth 前端改造设计

> 基准文档：[`handover-00-overview-and-contract.md`](handover-00-overview-and-contract.md)（下称「契约」）
> 与 [`handover-01-backend.md`](handover-01-backend.md)（下称「后端设计」）。
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
| 控制台 `HandoverTaskDetail` | 扩展 | 展示 blocked / skip / 代管剩余天数 / assignee 与上交层级 |
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

Django 侧无需改动：`portal_react_route`（`src/easyauth/portal/urls.py:51`）已用
`<path:_portal_path>` catch-all 把所有非 API 深路径交给同一 React 壳。

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
export type HandoverKind = "offboard" | "transfer" | "reassign";
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

export interface HandoverAssetType {
  type: string;
  label: string;
  count: number;
  detail_supported: boolean;
  releasable: boolean;
  selected: boolean;
  default_to_user: HandoverUserRef | null;
  override_count: number;
}

export interface HandoverAction {
  app_key: string;
  app_name: string;
  status: HandoverActionStatus;
  blocked_reason: string;
  skip_reason: string;
  last_error: string;
  asset_types: HandoverAssetType[];
}

export interface HandoverCustody {
  expires_at: string;
  days_left: number;
  active: boolean;
}

export interface HandoverTaskDetail {
  id: number;
  kind: HandoverKind;
  status: HandoverTaskStatus;
  generation: number;
  subject: HandoverUserRef;
  assignee: (HandoverUserRef & { state: HandoverAssigneeState; escalation_level: number }) | null;
  custody: HandoverCustody | null;
  reason: string;
  created_at: string;
  actions: HandoverAction[];
  team_items: HandoverTeamItem[];   // 既有类型，形状不变
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

数据源：`GET /portal/api/v1/me/handover-tasks` → `{ as_assignee: [...], as_subject: [...] }`

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

- 「还剩 N 天」来自 `custody.days_left`：`>7` 中性色，`3–7` 警示色，`<3` 危险色，`custody.active=false` 显示「已上交」。
- `blocked_app_count > 0` 时显示⚠行，文案：「N 个应用未接入交接，需管理员处理」，**不给普通用户跳过按钮**。
- 空态文案：「你当前没有需要处理的交接。」不要画插画占位，与现有门户风格一致。

`as_subject` 分区只读，展示自己发起的提前交接进度。

### 5.2 `PortalHandoverDetail`

顶部信息条：当事人、类型、状态、代管剩余天数、当前负责人与上交层级
（`escalation_level > 0` 时显示「已上交 N 级」）。

主体是**逐 APP 的可折叠区块**，按 `status` 决定形态：

| action.status | 区块表现 |
|---|---|
| `blocked` | 红底，标题「未接入交接」，正文「该应用尚未实现数据交接，无法确认是否有遗留数据。请联系管理员。」**无任何操作按钮** |
| `skipped` | 灰底，显示「已由管理员跳过：{skip_reason}」 |
| `pending` | 「尚未预演」+ [预演] 按钮 |
| `previewed` | 展开资产分配器（§6）+ [重新预演] [执行交接] |
| `executing` / `async_pending` | 骨架 + 轮询（React Query `refetchInterval: 3000`），禁用按钮 |
| `done` | 绿底，展示 `summary` 统计 |
| `failed` | 红底，展示 `last_error` + [重试] |

**关键交互约束**：[执行交接] 是不可逆动作，必须二次确认对话框，且确认文案要把后果说清楚：

> 即将把 **187 个客户、23 个在途订单** 移交给 **张某某**，其中 2 项另行指定了接收人。
> 执行后归属立即变更。如果发现给错人，需要再发起一次数据移交来纠正。

### 5.3 发起「提前交接」（`PortalSelfTransferDialog`）

入口：门户首页与「我的交接」页各一个次要按钮「我要提前交接工作」。

- 调 `POST /portal/api/v1/handover-tasks/self-transfer`
- 409 `open_task_exists` → 提示「你已有一张进行中的交接单」并给跳转链接
- 建单后直接跳详情页
- 对话框里必须明确写一句：「提前交接**只移交数据归属，不会影响你的账号权限**，你可以正常工作到最后一天。」
  （D7 的用户可见表达，避免员工因担心失去权限而不敢用）

### 5.4 发起「移交下属数据」（`PortalReassignDialog`）

入口：门户「我的交接」页，**仅当**当前用户对至少一人有管辖权时显示。
判定方式：`GET /portal/api/v1/handover-candidates?scope=managed` 返回非空。

字段：

| 字段 | 控件 | 校验 |
|---|---|---|
| 转出方 | 人员选择器，数据源 `?scope=managed` | 必填 |
| 理由 | `TextArea` | 必填，≥10 字符，前端先校验再提交 |

提交后建单跳详情，接收人在详情页的资产分配器里逐类指定（不在对话框里定）。
403 `out_of_managed_scope` → 「你没有该员工的管理权限，请联系管理员处理。」

---

## 6. 资产分配器（`src/features/handover/AssetAllocator.tsx`，核心组件）

这是 D10 的落地，门户与控制台共用。

### 6.1 折叠态（默认）

每个资产类型一行：

```
☑ 名下客户            187 条    接收人 [ 张某某  ▾ ]   其中 2 项单独指定  [展开明细]
☑ 在途订单             23 条    接收人 [ 张某某  ▾ ]                      [展开明细]
☐ 进行中询盘           41 条    接收人 [ 请选择  ▾ ]   ⓘ 此类不可无主      [展开明细]
```

- 勾选框 = `selected`，`PATCH .../assets/{type}`
- 接收人下拉 = `default_to_user_id`，同一端点。下拉里含一项「暂不指定（释放为无主）」，
  **仅当 `releasable=true` 时可选**；`releasable=false` 时该项禁用并 tooltip 说明
  「该应用要求这类数据必须有负责人」。
- `count=0` 的类型仍然显示，置灰并标「无数据」——**不要隐藏**。隐藏就等于回到了"看不出区别"的老问题。
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

- 每行接收人下拉默认显示继承自该类的 `default_to_user`，**灰色**表示继承。
- 一旦改成别人 → 变实色 + 右侧圆点标记，加入本地待提交的 override 集合。
- 改回与默认一致 → 自动从 override 集合移除（不要留一条"值相同的 override"，那会污染审计）。
- 保存：`PUT .../assets/{type}/overrides` **整体替换**。因此提交时必须带上当前完整的 override 集合，
  而不只是本页改动 —— override 集合由前端在组件级维护，与分页解耦。
- 响应 `stale=true` → 顶部黄条「清单已变化，建议重新预演后再分配」。

### 6.3 人员选择器（`HandoverUserPicker`）

数据源 `GET /portal/api/v1/handover-candidates?q=`（控制台走对应超管端点）。
输入 300ms 防抖，React Query `keepPreviousData`。
必须排除当事人本人（后端已排除，前端不重复实现，但要能正确渲染后端返回的空集）。

---

## 7. 控制台改造

### 7.1 `HandoverWizard` 重构

现有五段（应用 → 接收人 → 授权 → 预演 → 执行，`handoverWizardController.ts:5-18`）中，
**第 2 段「接收人」整段删除**，接收人不再是 APP 级选择。新的四段：

| 段 | 内容 |
|---|---|
| 1 应用 | 不变；`blocked` 的 APP 在此段即标红，且**不可勾选进入后续段** |
| 2 授权 | 不变（`HandoverGrantItem` 勾选，仅 `kind=offboard` 显示） |
| 3 预演与分配 | preview 后直接内嵌 §6 的 `AssetAllocator` |
| 4 执行 | 不变，加 blocked 汇总提示 |

`handoverWizardController.ts` 的 stage 枚举、跳转守卫、以及对应测试同步改。

### 7.2 `HandoverTaskDetail` 扩展

- 顶部新增「负责人」卡片：assignee 姓名、`assignee_state` 中文标签、`escalation_level`、
  代管到期时间与剩余天数、[手动续期] [认领]（`superuser_pool` 时）。
- 每个 action 区块新增 blocked/skipped 形态（同 §5.2 表格）。
- `blocked` 区块给超管一个 [强行跳过] 按钮 → 对话框必填理由（≥10 字符）→
  `POST .../actions/{app_key}/skip`。对话框需明确警示：
  > 跳过后这张交接单可以完成，但该应用里此人的数据**不会被交接，也不会有人知道**。

### 7.3 `HandoverTaskList` 扩展

新增筛选：`assignee_state`、「仅看被阻塞的」。
列表行新增两个角标：`blocked_app_count`（红）、`custody.days_left`（按 §5.1 配色）。

### 7.4 未接入告警条（`BlockedAppsBanner`）

数据源 `GET /console/api/v1/lifecycle/handover-blocked-apps`，挂在控制台 shell 顶部，常驻。

> ⚠ 3 个应用未接入数据交接，12 张交接单被阻塞。 [查看详情]

`count=0` 时不渲染。**不要做成可关闭的** —— 关掉就等于回到静默状态。

### 7.5 APP 能力声明（app-workspace 新标签页）

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
| CustodyGrant | 代管权限 | `custody` |
| asset type | 资产类型 | `assetType` |
| override | 单独指定 | `override` |
| blocked | 未接入交接 | `blocked` |
| release / 无主 | 暂不指定 | `unassignedPool` |

---

## 9. 测试

| 文件 | 覆盖 |
|---|---|
| `features/handover/AssetAllocator.test.tsx` | 勾选/取消；`releasable=false` 时禁用「暂不指定」；override 改回默认自动移除；整体替换提交的 payload 形状 |
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
