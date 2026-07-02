# EasyAuth 与 EasyTrade 视觉一致性纠偏执行计划

> **给代理执行者：** 实施本计划时必须使用 `superpowers:subagent-driven-development` 或等价的并发子代理流程。每个任务只能写入本任务列出的文件范围；跨任务共享的基础组件必须先合并、再让页面任务继续。

**目标：** 让 EasyAuth 控制台和员工门户在按钮、表格、表单、弹窗、页头、面板、状态组件和壳层细节上对齐 EasyTrade 的企业后台视觉语言。

**架构：** 不抽取跨仓库共享包，不复制 EasyTrade 的 Next.js 组件。保留 EasyAuth 的 Vite + React Router 架构，在 EasyAuth 本地复刻 EasyTrade 的 token 与 UI primitives 视觉契约，然后逐页清理散落 Tailwind class。

**技术栈：** EasyAuth 使用 Django + Vite + React 19 + Tailwind v4 + TanStack Query/Table；EasyTrade 基线来自 Next.js + Tailwind v4 + 自维护 UI primitives。

---

## 当前结论

EasyAuth 已经引入 Tailwind v4，并且 `frontend/src/styles/index.css` 中的颜色 token 大体接近 EasyTrade；偏差主要不在 token，而在组件契约和页面散落样式。

已确认的主要偏差：

- `Button`：EasyAuth 的 `primary` 当前是蓝底；EasyTrade 的 `primary` 是深墨底，蓝底是 `secondary`。
- `TablePrimitives`：EasyAuth 仍使用 `rounded-lg`、`slate-*`、较松的表格密度；EasyTrade 是 `paper-card`、`rounded-[3px]`、`px-3 py-2.5`、`10.5px mono uppercase` 表头。
- `Field`：EasyAuth label 是 13px 普通粗体；EasyTrade 是 11px uppercase、较大 tracking、小圆角输入框。
- `Badge`：EasyAuth 是 6px 圆角和普通半粗体；EasyTrade 是 2px 圆角、mono、10.5px、uppercase。
- `Dialog`：EasyAuth 是 `rounded-lg`、较厚阴影；EasyTrade 是 `paper-card`、`rounded-[3px]`、分区边框、轻遮罩和滚动锁定。
- 页面中仍有裸样式：`frontend/src/App.tsx`、`frontend/src/pages/console/ConsoleAppWorkspace.tsx`、`frontend/src/pages/console/workspace/tabs/*`、`frontend/src/pages/portal/components/*`。
- `frontend/src/styles/tokens.css` 和 `frontend/src/styles/components/*.css` 当前为空文件，容易误导后续修改；应明确删除或保留为空并加入扫描约束。
- `docs/architecture/easyauth-frontend-visual-contract.md` 声称“最终页面验证已完成”，但当前代码仍与 EasyTrade 有明显差异，文档需要在最终修复后更新为真实状态。

## EasyTrade 视觉基准

基准文件：

- `/Users/konata/code/EasyTrade/frontend/src/app/globals.css`
- `/Users/konata/code/EasyTrade/frontend/src/components/ui/button.tsx`
- `/Users/konata/code/EasyTrade/frontend/src/components/ui/field.tsx`
- `/Users/konata/code/EasyTrade/frontend/src/components/ui/badge.tsx`
- `/Users/konata/code/EasyTrade/frontend/src/components/ui/dialog.tsx`
- `/Users/konata/code/EasyTrade/frontend/src/components/ui/page-header.tsx`
- `/Users/konata/code/EasyTrade/frontend/src/components/ui/panel-surface.tsx`
- `/Users/konata/code/EasyTrade/frontend/src/components/ui/data-grid.parts.tsx`

固定契约：

- 背景：`--paper`、`--paper-deep`、`--paper-soft`
- 文本：`--ink`、`--ink-soft`、`--ink-faint`
- 边框：`--hairline`、`--hairline-strong`、`--hairline-soft`
- 强调：`--amber`，实际颜色为 `#2563EB`
- 主按钮：深墨底，不是蓝底
- 控件圆角：默认 2px；表格/弹窗外壳 3px；面板最多 8px
- 表格密度：表头 `10.5px mono uppercase tracking-[0.14em]`，单元格 `text-[13px] px-3 py-2.5`
- 面板：`paper-card`，细边框，极轻阴影
- 动效：150ms 到 300ms，少量 fade/translate，不做营销式装饰

## 并发边界

| 子任务 | 可并发性 | 独占写入范围 |
| --- | --- | --- |
| A. 基线截图与扫描 | 可并发，只读 | 无写入 |
| B. 表格 primitives | 必须先于页面表格迁移 | `frontend/src/components/ui/TablePrimitives.tsx`、`frontend/src/components/ui/TableState.tsx`、`frontend/src/components/tableArchitecture.test.ts`、`frontend/src/components/baseComponents.test.tsx` |
| C. 表单、面板、弹窗、Badge | 可与 B 并行 | `frontend/src/components/Field.tsx`、`frontend/src/components/ui/PanelSurface.tsx`、`frontend/src/components/Dialog.tsx`、`frontend/src/components/Badge.tsx`、`frontend/src/components/StatusBanner.tsx`、`frontend/src/components/Toast.tsx` |
| D. Button 语义切换 | 可与 B/C 并行，但需单独提交 | `frontend/src/components/Button.tsx`、`frontend/src/components/baseComponents.test.tsx`、裸按钮调用点 |
| E. 壳层微调 | B/C/D 后执行 | `frontend/src/styles/layout-shell.css`、`frontend/src/styles/responsive.css`、`frontend/src/components/shell/*` |
| F. 页面散落样式收敛 | B/C/D 后并发拆分 | `frontend/src/pages/console/**` 与 `frontend/src/pages/portal/**`，每个子代理按目录独占 |
| G. 文档与验证 | 最后串行 | `docs/architecture/easyauth-frontend-visual-contract.md`、截图记录、构建产物 |

## 任务 0：冻结真实基线

**文件：**

- 只读：`/Users/konata/code/EasyTrade/frontend/src/app/globals.css`
- 只读：`/Users/konata/code/EasyTrade/frontend/src/components/ui/*.tsx`
- 只读：`/Users/konata/code/EasyAuth/frontend/src/**`
- 新增：`docs/audits/visual-alignment/2026-07-02/README.md`

**步骤：**

- [ ] 运行 `git status --short`，记录 EasyAuth 工作区已有改动。
- [ ] 运行 `rg -n 'rounded-lg|rounded-md|slate-|bg-amber-ink|text-bond-strong|shadow-2xl|text-xs text-slate' frontend/src`，保存当前偏差清单。
- [ ] 启动 EasyAuth Vite：`pnpm --dir frontend dev`。
- [ ] 用 Playwright 截图 `/console`、`/console/operations/access-requests`、`/portal`、`/portal/request` 的桌面 1280px 与移动 390px。
- [ ] 若 EasyTrade 本地可启动，截图 `/zh-CN/admin/pipeline`、`/zh-CN/admin/orders`、`/zh-CN/admin/settings` 作为对照。

**验收：**

- 偏差清单和截图记录存在。
- 未修改业务代码。

## 任务 1：表格 primitives 纠偏

**文件：**

- 修改：`frontend/src/components/ui/TablePrimitives.tsx`
- 修改：`frontend/src/components/ui/TableState.tsx`
- 修改：`frontend/src/components/tableArchitecture.test.ts`
- 修改：`frontend/src/components/baseComponents.test.tsx`

**具体规则：**

- `TableFrame` 改为 `paper-card overflow-hidden rounded-[3px] p-0` 风格，内部负责横向滚动。
- `TableRoot` 改为 `min-w-full border-separate border-spacing-0 text-[13px]`。
- `TableHead` 改为 `bg-paper-deep/60`。
- `TableHeaderCell` 改为 `border-b border-ink/15 px-3 py-2.5 text-left align-bottom font-mono text-[10.5px] uppercase tracking-[0.14em] text-ink-soft font-medium`。
- `TableCell` 改为 `border-b border-ink/8 px-3 py-2.5 text-[13px] text-ink align-middle`。
- `TableRow` hover 改为 `hover:bg-[rgb(var(--amber))]/[0.05]`。
- `TableSkeletonRows` 的骨架色使用 `animate-shimmer` 或 `bg-paper-deep`，不得继续使用 `slate-*`。

**验证：**

```bash
pnpm --dir frontend test frontend/src/components/tableArchitecture.test.ts
pnpm --dir frontend test frontend/src/components/baseComponents.test.tsx
rg -n 'rounded-lg|slate-|shadow-slate|bg-white' frontend/src/components/ui/TablePrimitives.tsx
```

预期：测试通过；`rg` 只允许无结果。

## 任务 2：表单、Badge、Dialog、PanelSurface 纠偏

**文件：**

- 修改：`frontend/src/components/Field.tsx`
- 修改：`frontend/src/components/Badge.tsx`
- 修改：`frontend/src/components/Dialog.tsx`
- 修改：`frontend/src/components/StatusBanner.tsx`
- 修改：`frontend/src/components/Toast.tsx`
- 修改：`frontend/src/components/ui/PanelSurface.tsx`
- 修改：`frontend/src/components/ui/EmptyState.tsx`
- 修改：`frontend/src/components/ui/PageState.tsx`
- 修改：`frontend/src/components/baseComponents.test.tsx`

**具体规则：**

- `Field` label 使用 `text-[11px] uppercase tracking-[0.14em] text-ink-soft font-medium`。
- `TextInput`、`TextArea`、`SelectInput` 使用 `rounded-[2px] border-ink/15 bg-paper-soft text-[13px]`，focus 仅改变边框为 `rgb(var(--amber))`。
- `Badge` 使用 `rounded-[2px] px-1.5 py-0.5 font-mono text-[10.5px] leading-4 uppercase tracking-[0.14em]`。
- `Dialog` 外壳使用 `paper-card rounded-[3px] p-0`，header/body/footer 分区对齐 EasyTrade，关闭按钮可保留 lucide 图标但视觉改为无边框轻按钮。
- `PanelSurface` 使用 `paper-card`，padding 允许 `none/sm/md/lg`，默认 `md`。
- `StatusBanner` 和 `Toast` tone 只使用 `amber`、`evergreen`、`signal`、`bond`、`neutral`，不恢复 `success/danger/warning` 命名。

**验证：**

```bash
pnpm --dir frontend test frontend/src/components/baseComponents.test.tsx
rg -n 'rounded-lg|rounded-md|slate-|shadow-2xl|success|danger|warning' frontend/src/components frontend/src/components/ui
```

预期：测试通过；`success/danger/warning` 不再作为 tone 契约出现，`danger` 只允许作为 `Button` variant 名称。

## 任务 3：Button 语义切换

**文件：**

- 修改：`frontend/src/components/Button.tsx`
- 修改：`frontend/src/App.tsx`
- 修改：`frontend/src/pages/console/ConsoleAppWorkspace.tsx`
- 修改：`frontend/src/components/baseComponents.test.tsx`

**具体规则：**

- `primary`：`bg-ink text-paper border border-ink hover:bg-ink/90 active:translate-y-px`。
- `secondary`：`bg-[rgb(var(--amber))] text-paper border border-[rgb(var(--amber))] hover:bg-[rgb(var(--amber))]/90 active:translate-y-px`。
- `outline`：`bg-transparent text-ink border border-ink/30 hover:border-ink/60 hover:bg-ink/[0.04] active:translate-y-px`。
- `ghost`：`bg-transparent text-ink-soft hover:text-ink hover:bg-ink/[0.04] border border-transparent active:translate-y-px`。
- `ghost-danger` 和 `danger` 保持红色语义。
- 所有裸 `<a className="inline-flex ...">` 的按钮样式替换为组件或与组件完全一致的 class，优先改 `frontend/src/App.tsx` 的登出页按钮。

**验证：**

```bash
pnpm --dir frontend test frontend/src/components/baseComponents.test.tsx
rg -n 'bg-amber-ink|rounded-md border|focus-visible:outline-amber-ink' frontend/src/App.tsx frontend/src/components/Button.tsx frontend/src/pages/console/ConsoleAppWorkspace.tsx
```

预期：`Button` 的 `primary` 不再是蓝底；裸按钮样式显著减少。

## 任务 4：壳层微调

**文件：**

- 修改：`frontend/src/styles/layout-shell.css`
- 修改：`frontend/src/styles/responsive.css`
- 修改：`frontend/src/components/shell/Topbar.tsx`
- 修改：`frontend/src/components/shell/Sidebar.tsx`
- 修改：`frontend/src/components/shell/UserSummary.tsx`
- 修改：`frontend/src/components/AppShell.test.tsx`

**具体规则：**

- 保留 `56px topbar + 240px sidebar + max 1440px` 架构。
- 导航项圆角统一 2px 到 3px；如需保留 6px，必须与 EasyTrade mobile nav 视觉一致并在测试里固定。
- topbar popover 使用 `rounded-[2px]`、低阴影和 `border hairline`。
- `content` padding 桌面保持 40px 左右，移动端不得出现横向溢出。
- active indicator 使用 `rgb(var(--amber))`，禁止新增临时色。

**验证：**

```bash
pnpm --dir frontend test frontend/src/components/AppShell.test.tsx
pnpm --dir frontend exec playwright test e2e/visual-alignment.spec.ts --project=chromium
```

预期：桌面和 390px 移动端均无按钮遮挡、无文字溢出、导航可点击。

## 任务 5：顶层页面收敛，作为最小可验证切片

**文件：**

- 修改：`frontend/src/pages/console/ConsoleAppList.tsx`
- 修改：`frontend/src/pages/console/OperationsPage.tsx`
- 修改：`frontend/src/pages/portal/PortalPage.tsx`
- 修改：`frontend/src/pages/portal/components/AccessRequestForm.tsx`
- 修改：`frontend/src/pages/portal/components/AccessRequestFields.tsx`
- 修改：`frontend/src/pages/portal/components/RequestTargetPicker.tsx`
- 修改：`frontend/src/pages/portal/components/PermissionSelector.tsx`
- 修改：`frontend/e2e/visual-alignment.spec.ts`

**具体规则：**

- `/console` 必须覆盖页头、主按钮、刷新按钮、表格、状态 Badge、空态、新建应用弹窗和表单。
- `/portal` 与 `/portal/request` 必须覆盖门户表格、权限选择树、表单控件、提交按钮和错误状态。
- `visual-alignment.spec.ts` 增加“打开新建应用弹窗”的断言，确保弹窗和表单进入视觉回归。
- 页面内 `code`、版本号、权限 key 使用 `font-mono text-[13px] leading-5 text-ink-soft`，不得继续用 `text-xs text-slate-500`。

**验证：**

```bash
pnpm --dir frontend test frontend/src/pages/console frontend/src/pages/portal
pnpm --dir frontend exec playwright test e2e/visual-alignment.spec.ts --project=chromium
rg -n 'text-xs text-slate|rounded-lg|rounded-md|slate-|bg-amber-ink|text-bond-strong' frontend/src/pages/console frontend/src/pages/portal
```

预期：最小切片视觉对齐；扫描结果为 0 或仅剩明确登记的后续工作项。

## 任务 6：工作台页面和矩阵类页面收敛

**文件：**

- 修改：`frontend/src/pages/console/workspace/tabs/CatalogTab.tsx`
- 修改：`frontend/src/pages/console/workspace/tabs/CredentialsTab.tsx`
- 修改：`frontend/src/pages/console/workspace/tabs/GuideTab.tsx`
- 修改：`frontend/src/pages/console/workspace/tabs/ManifestTab.tsx`
- 修改：`frontend/src/pages/console/workspace/tabs/MatrixTab.tsx`
- 修改：`frontend/src/pages/console/workspace/tabs/OverviewTab.tsx`
- 修改：`frontend/src/pages/console/workspace/tabs/QueryTestTab.tsx`
- 修改：`frontend/src/pages/console/workspace/tabs/RulesTab.tsx`
- 修改：`frontend/src/pages/console/workspace/matrix/RolePermissionMatrix.tsx`
- 修改：`frontend/src/pages/console/workspace/credentials/CreateCredentialForm.tsx`

**具体规则：**

- 所有 `rounded-lg border ... shadow-sm` 业务面板替换为 `PanelSurface` 或 `paper-card`。
- 所有 TanStack 表格渲染结构落到 `TablePrimitives`。
- 权限矩阵 sticky cell 背景使用 `bg-paper-deep` 或 `bg-inherit`，不得使用 `bg-slate-50`。
- 表单区统一 `Field`，按钮统一 `Button`。
- 不新增长期兼容 class，不保留旧视觉分支。

**验证：**

```bash
pnpm --dir frontend test frontend/src/pages/console/ConsoleAppWorkspace.test.tsx
pnpm --dir frontend test frontend/src/pages/console/workspace
pnpm --dir frontend exec playwright test e2e/smoke.spec.ts --project=chromium
rg -n 'rounded-lg|rounded-md|slate-|bg-amber-ink|text-bond-strong|shadow-sm' frontend/src/pages/console/workspace
```

预期：工作台主路径、矩阵、凭据、manifest、query test 均无旧视觉类依赖。

## 任务 7：文档、构建产物和真实 Django 验证

**文件：**

- 修改：`docs/architecture/easyauth-frontend-visual-contract.md`
- 修改：`docs/plans/2026-07-01-easyauth-easytrade-visual-alignment-plan.md`，标注已被本计划纠偏或归档
- 生成：`src/easyauth/static/easyauth/frontend/.vite/manifest.json`
- 生成：`src/easyauth/static/easyauth/frontend/assets/main-*.css`
- 生成：`src/easyauth/static/easyauth/frontend/assets/main-*.js`

**步骤：**

- [ ] 更新视觉契约文档，删除“已完成验证”的不准确表述，改为记录本轮真实完成范围。
- [ ] 构建前端：`pnpm --dir frontend build`。
- [ ] 重启当前 Django 开发服务。
- [ ] 用真实 HTTP 响应确认 `/console/` 和 `/portal/request` 加载新 manifest 对应的 CSS/JS。
- [ ] 用浏览器或 Playwright 访问真实 Django URL，确认页面加载的是新构建产物，不只验证 Vite dev server。

**验证：**

```bash
pnpm --dir frontend typecheck
pnpm --dir frontend test
pnpm --dir frontend exec playwright test e2e/smoke.spec.ts --project=chromium
pnpm --dir frontend exec playwright test e2e/visual-alignment.spec.ts --project=chromium
pnpm --dir frontend build
curl -I "http://127.0.0.1:${DJANGO_PORT}/console/"
curl -I "http://127.0.0.1:${DJANGO_PORT}/portal/request"
curl -s "http://127.0.0.1:${DJANGO_PORT}/console/" | rg 'easyauth/frontend/assets/.*\\.css|easyauth/frontend/assets/.*\\.js'
```

预期：所有检查通过；真实 Django 页面响应包含最新构建产物路径。

## 最终扫描门禁

最终合并前必须通过：

```bash
rg -n 'rounded-lg|rounded-md|slate-|bg-amber-ink|text-bond-strong|shadow-2xl|text-xs text-slate' frontend/src
rg -n '--bg|--surface|--muted|--line|--brand|--accent|--danger|--success|--warning' frontend/src
rg -n 'tanstack-table|table-scroll|permission-table|matrix-table|DataTable|CredentialTable|GrantTable|RequestTable' frontend/src
```

允许例外只能出现在测试禁止规则、历史文档或明确登记的第三方示例中；产品代码不允许保留。

## 推荐提交顺序

1. `test/ui: 固定 EasyTrade 视觉契约扫描与组件断言`
2. `style/ui: 对齐表格 primitives 到 EasyTrade 密度`
3. `style/ui: 对齐表单弹窗标签和面板 primitives`
4. `style/ui: 切换 Button variant 到 EasyTrade 语义`
5. `style/shell: 微调 EasyAuth 壳层与导航视觉`
6. `style/pages: 收敛控制台和门户主路径视觉`
7. `style/pages: 收敛控制台工作台视觉`
8. `docs: 更新视觉契约与真实验证记录`

每个提交都应能独立运行对应任务的验证命令；如果某一步失败，回滚该提交不应影响其他已完成任务。
