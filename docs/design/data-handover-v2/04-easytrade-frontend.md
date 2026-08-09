# 04 · EasyTrade 前端改造设计

> ## ⛔ 本期取消 —— 本文件暂不实施
>
> 本文件的全部内容都是为了应对一个**新状态**：离职者作为负责人出现在 EasyTrade 的列表里
> （故障 F1/F2/F3）。该状态由「代管授权把 departed 用户并入主管的 `MANAGED_USERS`」造成。
>
> **代管授权已在第二轮复核后整体废弃**（契约 §7、`07-review-log.md` §1.1）。
> 离职者不会再进入任何人的 `MANAGED_USERS`，下游列表按 owner 过滤时根本查不到这批数据，
> **F1/F2/F3 三个故障都不会发生**。
>
> 因此本文件**本期不实施**，保留归档。若日后重新引入「人员集合 scope 泛化」并恢复代管能力，
> 本文件可直接复用。
>
> 唯一仍值得单独立项的卫生问题：写入型人员选择器不应把已停用用户列为可选项 —— 但这与数据交接无关。

> 基准文档：`00-overview-and-contract.md`（下称「契约」）
> 与本仓库 [`03-easytrade-backend.md`](03-easytrade-backend.md)（下称「后端设计」）。

---

## 1. 改造边界（先说不做什么）

**交接单界面不在 EasyTrade。** 发起交接、指定接收人、逐条改派、执行，全部在 EasyAuth 门户
（`02-easyauth-frontend.md`）。EasyTrade 前端**不实现任何交接向导**。

需要改的原因只有一个：后端设计 §3.1（修 B3）把 scope 解析里"剔除 inactive 用户"的逻辑去掉之后，
界面上会出现一个以前不可能出现的状态 ——

> 一个已离职的人，仍然作为客户负责人 / 订单负责人 / 任务执行人出现在列表里，且主管能看到、能点进去。

不改会有三类实际故障：

| 故障 | 现象 |
|---|---|
| F1 | 离职者与在职同事视觉上毫无区别，主管分不清哪些是"待交接的遗留数据"，交接推不动 |
| F2 | 人员选择器把离职者当成可选项，可以把新订单负责人指给一个已登不进系统的人 |
| F3 | 已停用用户的返回被当作异常或空值，姓名渲染成空白或直接掉出 ID |

本文件只解决这三件事。

---

## 2. 现有机制（好消息：架子已经对了）

`src/components/shared/entity-pickers.tsx` 已有统一的 `UserPicker`：

- 通过 `candidateContext` 走 `/api/v1/user-candidates?context=<ctx>`，无 context 时走 `/api/v1/users`
- 上下文已经区分了用途，`task.owner_filter` / `pipeline.owner_filter` /
  `report.margin.owner_filter` / `report.ar.owner_filter` 等**筛选类**上下文与写入类上下文是分开的
- `userPickerLabel()` 已统一姓名回退链：`name → fullName → username → email → id`

因此改造是在既有骨架上补两件事：**候选集按用途区分在职过滤** + **展示层加离职标记**。
**禁止**在各业务模块各写一份过滤逻辑。

---

## 3. 候选集：按用途区分（修 F2）

### 3.1 后端候选接口

`/api/v1/user-candidates` 按 `context` 决定是否包含非在职用户：

| context 类别 | 命名约定 | 是否含离职者 |
|---|---|---|
| 写入类（指定负责人、指派任务、选接收人） | 不带 `_filter` 后缀 | **否** |
| 筛选类（按负责人筛列表、报表分组） | `*_filter` 后缀 | **是** |

现有 context 枚举已符合此约定，本次只需在服务端按后缀分流，并**补齐仍缺的写入类 context**。
新增 context 时必须遵守该命名约定，并在 `entity-pickers.tsx` 的联合类型里登记。

### 3.2 候选项补字段

`UserPickerItem` 增加 `isActive: boolean`。
后端候选接口对筛选类 context 返回该字段，写入类恒为 `true`。

`userPickerLabel()` 保持不变（标签仍是纯姓名），在职状态由 §4 的渲染层处理，
**不要**把「已离职」拼进 label 字符串 —— 那会污染搜索匹配与报表分组名。

### 3.3 当前值是离职者时

写入类选择器遇到当前值本身是离职者（正是待交接的数据）：

- 以**只读的当前值**形式展示并标「已离职」
- 用户一旦改选他人，就不能再选回该离职者
- 提交前前端校验一次，命中则提示「该人员已离职，请选择在职同事」

`fetchUserCandidateById()` 已支持按 id 回填当前值，此路径需保证对离职者也能取到姓名
（否则会退化成 F3 的显示 ID）。

### 3.4 筛选器新增快捷项

所有 `*_filter` 上下文的选择器顶部增加一个快捷项：**「仅看已离职人员的数据」**。

这是本次前端改造里对推进交接帮助最大的功能 —— 主管靠它一次性捞出全部待交接数据。不要省略。

---

## 4. 展示：离职标记（修 F1、F3）

### 4.1 统一组件 `UserRef`

新建 `src/components/shared/UserRef.tsx`，作为人员展示的唯一入口：

```tsx
interface UserRefProps {
  userId: string;
  name?: string | null;
  isActive?: boolean;
  compact?: boolean;   // 表格密集场景: 只显示灰点, hover 提示
}
```

| 状态 | 表现 |
|---|---|
| 在职 | 姓名，正常色 |
| 已离职 | 姓名 + 中性灰 + 后缀标签「已离职」；`compact` 时姓名前一个灰点，hover 显示 |
| 解析不到 | 「未知人员」+ 灰色，**不显示原始 ID**，`console.warn` 一次（不静默） |

**不要用红色**：离职不是错误状态，红色会让主管以为数据坏了。

### 4.2 接入清单

| 界面 | 文件 |
|---|---|
| 客户列表负责人列 | `src/features/customers/components/CustomersListTable.tsx` |
| 客户详情负责人 | `src/components/customer/customer-detail-tabs.types.ts` 关联视图 |
| 订单详情负责人 | `src/features/orders/order-detail-model.ts` 关联视图 |
| 询盘/管道负责人 | `src/features/pipeline/`、`src/components/forms/inquiry-form-dialog.parts.tsx` |
| 任务列表与弹窗执行人 | `src/features/tasks/components/TasksTable.tsx`、`TaskDialog.tsx` |
| 需求负责人 | `src/features/requirements/` |
| 团队与销售看板 | `src/features/dashboard-widgets/widgets-team.tsx`、`src/features/sales-dashboard/` |
| 报表分组行头 | `src/app/[locale]/admin/reports/margin/page.tsx`、`.../ar-aging/page.tsx` |

表格与看板用 `compact` 形态，避免撑破列宽。

### 4.3 报表口径提示

利润率与账龄报表按负责人分组时，离职者的分组仍会出现。分组行头用 `UserRef` 标注即可，
**不要**把离职者的数据并入"其他"或隐藏 —— 那会让报表金额对不上，属于典型的静默兜底。

---

## 5. 交接提示（轻量导流）

客户详情、订单详情、询盘详情页，当负责人为离职者时顶部显示一条信息条：

> ⓘ 该客户的负责人已离职，数据尚未交接。请在 EasyAuth 门户完成交接。 [前往交接]

链接指向 EasyAuth 门户「我的交接」，地址走配置项。**不在 EasyTrade 内做任何交接操作，只导流。**

---

## 6. i18n

文案进现有多语言资源，key 前缀 `directory.userRef.*` 与 `handover.hint.*`。术语固定：

| 概念 | 中文 |
|---|---|
| inactive / departed | 已离职 |
| unknown user | 未知人员 |
| filter shortcut | 仅看已离职人员的数据 |

---

## 7. 测试

| 文件 | 覆盖 |
|---|---|
| `src/components/shared/UserRef.test.tsx` | 三种状态；`compact`；解析不到不泄露 ID 且有一次 warn |
| `src/components/shared/entity-pickers.test.tsx` | 写入类 context 不含离职者；筛选类含且有快捷项；当前值为离职者时只读且改后不可选回 |
| `src/features/customers/CustomersListTable.test.tsx` | 负责人列渲染离职标记 |
| e2e | 主管登录 → 客户列表用「仅看已离职人员的数据」筛出 → 每行显示「已离职」→ 详情页有前往交接链接 |

---

## 8. 交付顺序

1. §3.1 §3.2 候选接口按用途分流 + `isActive` 字段（前后端同一提交，否则前端拿不到状态）
2. §4.1 `UserRef`（可独立测试）
3. §4.2 逐界面接入
4. §3.3 §3.4 选择器行为与筛选快捷项
5. §4.3 报表 → §5 提示条 → §6 i18n → §7 测试

每完成一项立即单独 commit。前端改完后必须重建容器镜像并重启，host dev server 不算上线。
