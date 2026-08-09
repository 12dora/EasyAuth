# 06 · EasyProject 前端改造设计

> 基准文档：`00-overview-and-contract.md`（下称「契约」）
> 与本仓库 [`05-easyproject-backend.md`](05-easyproject-backend.md)（下称「后端设计」）。

---

## 1. 本仓库前端的改造边界（先说不做什么）

**交接单本身的界面不在 EasyProject。** 发起交接、分配接收人、逐条改派、执行，全部在 EasyAuth 门户
（`02-easyauth-frontend.md`）。EasyProject 前端**不实现任何交接向导**。

那为什么还要改？因为后端设计 §2.2 改了可见范围之后，界面上会出现一个**以前不可能出现的状态**：

> 一个已离职的人，仍然作为项目负责人 / 任务执行人 / 待审批发起人出现在列表里，
> 并且主管能看到、能点进去。

现有界面从未考虑过这种数据。不改的话会出现三类实际故障：

| 故障 | 现象 |
|---|---|
| F1 | 离职者与在职同事视觉上毫无区别，主管不知道哪些是"待交接的遗留数据"，交接根本推不动 |
| F2 | 人员选择器把离职者当成可选项，用户可以把新任务指派给一个已经登不进系统的人 |
| F3 | 目录接口对已停用用户的返回被前端当作异常/空值处理，姓名渲染成空白或 ID |

本文件只解决这三件事，范围刻意收紧。

---

## 2. 工程约定（沿用）

Next.js 16 App Router、React 19、TypeScript、Tailwind v4、EasyUI 为主、AntD v5 受限边界；
文案走 `frontend/messages/{zh-CN,en}/*.json`；类型来自 OpenAPI 生成物
（`frontend/src/lib/api/generated/openapi.d.ts`，由 AG-00 统一生成，**模块不手改**）。

按 `AGENTS.md` 不变量 7，`frontend` 的 lockfile / layout / providers / 全局 messages / 导航
以及 OpenAPI 与 TS 生成物属共享热点，**只交补丁，不直接并发编辑**。

---

## 3. 人员展示：离职标记（修 F1、F3）

### 3.1 统一组件 `UserRef`

新建 `frontend/src/components/directory/UserRef.tsx`，**全站唯一的人员展示入口**。
现有各处直接渲染人名的地方逐步收敛到它（本次改造只要求覆盖 §3.3 列出的界面）。

```tsx
interface UserRefProps {
  dingtalkUserId: string;
  /** 目录返回的在职状态；缺省时组件自行按 id 从目录缓存取 */
  isActive?: boolean;
  displayName?: string;
  size?: "sm" | "md";
  /** 列表密集场景下只显示圆点不显示文字标签 */
  compact?: boolean;
}
```

渲染规则：

| 状态 | 表现 |
|---|---|
| 在职 | 姓名，正常色 |
| 已离职 / 已停用 | 姓名 + 中性灰 + 后缀标签「已离职」；`compact` 时改为姓名前一个灰点，hover 显示「已离职」 |
| 解析不到 | 显示「未知人员」+ 灰色，**不显示原始 ID**，并 `console.warn` 一次（不要静默） |

**不要用红色**。离职不是错误状态，红色会让主管误以为数据出了问题。

### 3.2 目录数据来源

`directory_users` 已有 `is_active`（后端设计 §2.2 明确**不得**因 inactive 剔除），
所以列表接口返回的人员对象里必须带上在职状态。

**该字段已经有了，不需要任何后端改动**（这与本文件早期版本的说法不同，以此处为准）：
`backend/app/api/v1/directory.py:170,193,221,262,357` 的 DTO 都含 `is_active`，
生成的 TS 类型里也有。

真正要改的是**调用方传参**：`includeInactive` query 参数早就存在
（`backend/app/api/v1/directory.py:292`，默认 `false`）。前端此前一直用默认值，所以从来看不到离职者。

> 因此本项**没有后端前置依赖，也不需要 CCR**，前端可以立即开工。

### 3.3 需要接入 `UserRef` 的界面

| 界面 | 位置 |
|---|---|
| 项目列表 / 项目详情的负责人 | 项目模块 |
| 项目成员列表 | 项目模块 |
| 任务列表的执行人、指派人 | 任务模块（含看板卡片、甘特图行首） |
| 任务详情的执行人、指派人、协作人 | 任务模块 |
| 周期任务模板的负责人、指派人、协作人 | 周期任务模块 |
| 工作记录的参与人 | 工作记录模块 |
| 待审批列表的发起人 | 审批模块 |

看板与甘特图用 `compact` 形态，避免标签撑破卡片布局。

---

## 4. 人员选择器：不得选中离职者（修 F2）

### 4.1 规则

所有**写入型**的人员选择（指派任务、加项目成员、改负责人、加协作人、选参与人）：

- 搜索结果**过滤掉**非在职人员
- 若当前值本身是一个离职者（正是待交接的数据），下拉里以**只读的当前值**形式展示并标「已离职」，
  但用户一旦更改就不能再选回去
- 提交前做一次前端校验，命中则提示「该人员已离职，请选择在职同事」

### 4.2 例外：筛选器可以选离职者

**查询型**的人员筛选（按执行人筛任务、按负责人筛项目）**必须允许**选中离职者 ——
这正是主管在代管期内找出"待交接数据"的主要手段。

筛选器额外提供一个快捷项：**「仅看已离职人员的数据」**。
这是本次前端改造里对交接推进帮助最大的一个功能，不要省略。

### 4.3 实现位置

选择器与筛选器共用一个底层查询 hook，通过参数区分：

```ts
// purpose 决定是否给目录接口传 includeInactive
useDirectoryUserOptions({ purpose: "assign" })  // includeInactive=false（默认），过滤离职
useDirectoryUserOptions({ purpose: "filter" })  // includeInactive=true，保留离职 + 「仅看已离职」快捷项
```

**禁止**在各业务模块各写一份过滤逻辑 —— 那是遗漏的温床，和后端"每个 APP 各自决定交接什么"
是同一类错误。

---

## 5. 交接提示（轻量，非必需但推荐）

在项目详情与任务详情页，当负责人/执行人为离职者时，顶部显示一条信息条：

> ⓘ 该项目的负责人已离职，数据尚未交接。请在 EasyAuth 门户完成交接。 [前往交接]

链接指向 EasyAuth 门户的「我的交接」页（配置项，如 `NEXT_PUBLIC_EASYAUTH_PORTAL_URL`）。
**不要**在 EasyProject 里做任何交接操作，只做导流。

---

## 6. i18n

新增文案进 `frontend/messages/zh-CN/` 与 `frontend/messages/en/`，key 前缀 `directory.userRef.*`
与 `handover.hint.*`。术语固定：

| 概念 | 中文 |
|---|---|
| inactive / departed | 已离职 |
| unknown user | 未知人员 |
| filter shortcut | 仅看已离职人员的数据 |

全局 messages 属共享热点，按 `AGENTS.md` 不变量 7 交补丁给 AG-00。

---

## 7. 测试

| 文件 | 覆盖 |
|---|---|
| `components/directory/UserRef.test.tsx` | 三种状态渲染；`compact` 形态；解析不到时不泄露原始 ID 且有一次 warn |
| `hooks/useDirectoryUserOptions.test.ts` | `purpose="assign"` 过滤离职；`purpose="filter"` 保留并含快捷项 |
| `features/tasks/AssigneeSelect.test.tsx` | 当前值为离职者时只读展示；改动后不可选回；提交前校验拦截 |
| `playwright/tests/handover-departed-visibility.spec.ts` | 主管登录 → 用「仅看已离职人员的数据」筛出任务 → 每行显示「已离职」标记 → 顶部提示条含前往交接链接 |

---

## 8. 交付顺序

1. ~~等待后端补字段~~ —— **无前置依赖**，`is_active` 与 `includeInactive` 均已存在，直接开工
2. §3.1 `UserRef` + §4.3 `useDirectoryUserOptions`（可独立测试）
3. §3.3 逐界面接入
4. §4.1 §4.2 选择器与筛选器
5. §5 提示条 → §6 i18n → §7 测试

每完成一项立即单独 commit。前端改动后须跑通既有前端检查（`scripts/quality-gate.sh` 的前端段）。
