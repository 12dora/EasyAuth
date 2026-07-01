# EasyAuth 与 EasyTrade 视觉对齐修复计划

## 目标

把 EasyAuth 控制台和员工门户调整为与 EasyTrade 同一企业产品线的视觉语言。重点统一按钮、表格、表单、状态标签、页头、面板、弹窗、空态、加载态和导航密度；不改变授权业务语义，旧 UI 入口必须删除，不保留两套视觉系统。

本计划选择正本清源路线：EasyAuth React 前端引入 Tailwind v4，并以 EasyTrade 的 token 和基础 UI 语义作为唯一视觉来源。旧 CSS 组件类、旧 tone 命名、旧 Django HTML 页面渲染分支必须迁移后删除；不允许保留旧名、旧样式入口或旧页面入口。

## 基线结论

EasyTrade 的视觉基线来自：

- `frontend/src/app/globals.css`
- `frontend/src/components/ui/button.tsx`
- `frontend/src/components/ui/badge.tsx`
- `frontend/src/components/ui/field.tsx`
- `frontend/src/components/ui/dialog.tsx`
- `frontend/src/components/ui/page-header.tsx`
- `frontend/src/components/ui/data-grid.tsx`
- `frontend/src/components/ui/data-grid.parts.tsx`
- `frontend/src/components/ui/static-data-grid.tsx`

EasyAuth 当前主线是 Vite + React，样式入口是 `frontend/src/styles/index.css`。现有基础组件只有 `Button`、`Badge`、`Field`、`Dialog`、`PageHeader`，页面里仍有大量 `table.tanstack-table`、`table-scroll`、`permission-table`、`matrix-table` 等 class 级拼装。当前工作区还有未提交的表格迁移改动，`frontend/src/components/tableArchitecture.test.ts` 已禁止恢复 `DataTable`、`CredentialTable`、`GrantTable`、`RequestTable` 等旧包装组件。

因此后续实现遵守三条原则：

- Tailwind 是 React 前端唯一新样式运行时；保留 Vite + React 架构，不迁入 Next App Router。
- 基础组件承载视觉语义，业务页面不得继续直接拼旧 CSS 组件类。
- 表格可以新增语义清晰的新 primitives，但不得恢复被测试禁止的旧表格包装名称。

## 设计契约

实施时以这些视觉规格为准：

| 类别 | EasyTrade 基线 | EasyAuth 目标 |
|---|---|---|
| 背景 | `--paper`、`--paper-deep`、`--paper-soft` | 使用同名 token |
| 文字 | `--ink`、`--ink-soft`、`--ink-faint` | 使用同名 token |
| 品牌蓝 | `--amber`，值为 `#2563eb` | 使用 `--amber`，不另建 `--brand` |
| 危险 | `--signal` | 使用同名 token |
| 成功 | `--evergreen` | 使用同名 token |
| 次强调 | `--bond` | 使用同名 token |
| 控件圆角 | 2px 到 3px | 基础控件默认 2px |
| 面板圆角 | 6px 到 8px | 8px 以下 |
| 按钮高度 | sm 28px，md 36px，lg 44px | `Button` 支持同尺寸 |
| 表格单元格 | `px-3 py-2.5 text-[13px]` | 使用同密度 |
| 表头 | 10.5px mono uppercase | 同字体、同 tracking |
| Badge | 10.5px mono，2px 圆角 | 同 tone 体系 |
| 空态 | 居中、低对比、明确状态 | 同页面状态组件 |

Token 格式固定迁移为 EasyTrade 的 RGB 三元组写法，配合 Tailwind v4 `@theme inline` 使用。示例：

```css
:root {
  --paper: 255 255 255;
  --paper-deep: 248 250 252;
  --ink: 15 23 42;
  --amber: 37 99 235;
}

@theme inline {
  --color-paper: rgb(var(--paper));
  --color-ink: rgb(var(--ink));
  --color-amber-ink: rgb(var(--amber));
}
```

实现后不得再出现 `--bg`、`--surface`、`--muted`、`--line`、`--brand`、`--accent`、`--danger`、`--success`、`--warning` 这批旧 token。需要透明色时使用 `rgb(var(--amber) / 0.08)` 这类 Tailwind v4 原生语法。

按钮语义固定按 EasyTrade 的实际组件命名：

| Button variant | 视觉 | 用途 |
|---|---|---|
| `primary` | 深墨色背景、白字、深墨色边框 | 页面主提交、新建、确认等最强命令 |
| `secondary` | 品牌蓝背景、白字、品牌蓝边框 | 次级强调命令 |
| `outline` | 透明背景、深墨色细边框 | 默认按钮、刷新、编辑、进入详情 |
| `ghost` | 透明背景、弱文本 | 轻量操作、关闭、低优先级按钮 |
| `ghost-danger` | 透明背景、红色文本 | 危险轻量操作 |
| `danger` | 红色背景、白字 | 破坏性确认 |

EasyAuth 现有 `variant="primary"` 调用继续表达主命令，但视觉迁移为深墨色。未传 `variant` 的按钮默认改为 `outline`。确实需要蓝色强调的按钮才显式使用 `secondary`。

## 并发执行边界

后续编码建议使用子代理并发，但写入范围必须拆开：

| 子任务 | 可并发 | 独占写入范围 |
|---|---|---|
| A. Tailwind 与 token | 否，必须最先完成 | `frontend/package.json`、`frontend/vite.config.ts`、`frontend/src/styles/index.css`、`frontend/src/styles/tokens.css` |
| B. 基础组件 | 可在 A 后与 C 并行 | `frontend/src/components/Button.tsx`、`Badge.tsx`、`Field.tsx`、`Dialog.tsx`、`PageHeader.tsx`、`StatusBanner.tsx`、`Toast.tsx`、新增 UI primitives |
| C. 表格 primitives | 可在 A 后与 B 并行 | 新增表格 primitives、`frontend/src/styles/components/table.css` 的删除或清空、表格相关测试 |
| D. 顶层列表页面 | 可在 B/C 后并行 | `ConsoleAppList.tsx`、`OperationsPage.tsx`、`PortalPage.tsx`、门户表单组件 |
| E. 工作台 tabs | 可在 B/C 后并行，但只能一个代理处理 | `frontend/src/pages/console/workspace/**` |
| F. Django 旧模板删除 | 不与 D/E 并行 | `src/easyauth/admin_console/views.py`、`src/easyauth/portal/views.py`、旧模板目录 |
| G. 验证与截图 | 最终串行确认 | `frontend/e2e/**`、真实 Django 页面验证记录 |

## 任务 0：冻结当前工作区并建立截图基线

**目的：**保护当前未提交表格迁移，建立 EasyTrade/EasyAuth 改造前截图。

**文件：**

- 只读：`frontend/src/components/tableArchitecture.test.ts`
- 只读：当前 `git status --short` 中所有已修改前端文件
- 可新增：`docs/audits/visual-alignment/2026-07-01/` 下截图和说明

**步骤：**

- [ ] 运行 `git status --short`，记录已有改动。
- [ ] 运行 `git diff -- frontend/src/components/tableArchitecture.test.ts frontend/src/styles/components/table.css`，确认表格架构约束。
- [ ] EasyTrade 基线使用 Docker 运行面：在 `/Users/konata/code/EasyTrade` 执行 `docker compose up -d`，访问 `http://localhost:3000`。如需登录，使用 README 中的本地默认管理员 `admin` / `admin123`。
- [ ] EasyAuth 基线使用 Vite 运行面：在 `/Users/konata/code/EasyAuth` 执行 `pnpm --dir frontend dev`，用 Playwright route mocks 或 `frontend/e2e/smoke.spec.ts` 的 mock 数据进入控制台和门户页面。
- [ ] 截取 EasyTrade 页面：
  - `http://localhost:3000/zh-CN/admin/pipeline`
  - `http://localhost:3000/zh-CN/admin/orders`
  - `http://localhost:3000/zh-CN/admin/settings`
- [ ] 截取 EasyAuth 页面：
  - `http://127.0.0.1:5173/console`
  - `http://127.0.0.1:5173/console/operations/access-requests`
  - `http://127.0.0.1:5173/portal`
  - `http://127.0.0.1:5173/portal/request`
- [ ] 桌面和移动各截一轮，移动宽度用 390px。
- [ ] 记录文本溢出、按钮遮挡、表格横向滚动异常。

**验收：**

- 有 EasyTrade 和 EasyAuth 的改造前截图。
- 没有修改业务代码。
- 当前未提交改动范围被记录，后续任务不得回退这些改动。

## 任务 1：引入 Tailwind v4 并替换旧 token

**目的：**把 EasyAuth React 前端切到 Tailwind v4 + EasyTrade token 的单一视觉运行时。

**文件：**

- 修改：`frontend/package.json`
- 修改：`frontend/vite.config.ts`
- 修改：`frontend/src/styles/index.css`
- 修改：`frontend/src/styles/tokens.css`
- 删除或清空：`frontend/src/styles/components/buttons.css`
- 删除或清空：`frontend/src/styles/components/table.css`
- 删除或清空：`frontend/src/styles/components/forms.css`
- 删除或清空：`frontend/src/styles/components/dialog-toast.css`
- 删除或清空：`frontend/src/styles/features/workspace.css`
- 删除或清空：`frontend/src/styles/features/permission-selector.css`
- 删除或清空：`frontend/src/styles/features/matrix.css`

**步骤：**

- [ ] 安装 Tailwind v4 相关依赖，优先使用 Vite 插件路线：`tailwindcss` 和 `@tailwindcss/vite`。
- [ ] 在 `vite.config.ts` 启用 Tailwind 插件。
- [ ] 将 `index.css` 改为引入 Tailwind，并承载 EasyTrade 同名 token、`@theme inline`、全局字体、focus ring、scrollbar、基础动画。
- [ ] `tokens.css` 如果继续存在，只允许承载同一套 token；不得与 `index.css` 定义重复来源。更推荐把 token 全部集中到 `index.css` 后删除 `tokens.css` import。
- [ ] 删除旧 CSS 入口 import：`buttons.css`、`table.css`、`forms.css`、`dialog-toast.css`、`workspace.css`、`permission-selector.css`、`matrix.css` 不再作为视觉来源。
- [ ] 将所有旧 token 一次性替换掉；不得留下别名。
- [ ] 运行扫描：
  - `rg -n '--bg|--surface|--muted|--line|--brand|--accent|--danger|--success|--warning' frontend/src`
  - `rg -n 'button-|badge-|field-|control|dialog-|toast-|tanstack-table|table-scroll|permission-table|matrix-table|form-surface|matrix-panel|status-banner|code-block' frontend/src`
- [ ] 扫描结果必须为 0，除非匹配出现在删除迁移测试或明确的禁止规则中。

**验收：**

- `pnpm --dir frontend typecheck` 通过。
- `pnpm --dir frontend test frontend/src/components/tableArchitecture.test.ts` 通过。
- 旧 CSS 组件类不再作为页面实现依赖。

## 任务 2：重塑基础组件层

**目的：**让基础组件成为页面唯一视觉入口，组件内部使用 Tailwind class，不再依赖旧 CSS class。

**文件：**

- 修改：`frontend/src/components/Button.tsx`
- 修改：`frontend/src/components/Badge.tsx`
- 修改：`frontend/src/components/Field.tsx`
- 修改：`frontend/src/components/Dialog.tsx`
- 修改：`frontend/src/components/PageHeader.tsx`
- 修改：`frontend/src/components/StatusBanner.tsx`
- 修改：`frontend/src/components/Toast.tsx`
- 修改：`frontend/src/components/CodeBlock.tsx`
- 修改：`frontend/src/components/SecretDialog.tsx`
- 修改：`frontend/src/lib/status.ts`
- 新增：`frontend/src/components/ui/PanelSurface.tsx`
- 新增：`frontend/src/components/ui/EmptyState.tsx`
- 新增：`frontend/src/components/ui/PageState.tsx`

**步骤：**

- [ ] `Button` 支持 `primary`、`secondary`、`outline`、`ghost`、`ghost-danger`、`danger`，默认 `outline`。
- [ ] `Button` 支持 `sm`、`md`、`lg`，默认 `md`，高度分别对齐 28px、36px、44px。
- [ ] `Button` 支持 `loading`，渲染 12px spinner，并禁用点击。
- [ ] `BadgeTone` 一次性迁移为 `neutral`、`faint`、`ink`、`amber`、`evergreen`、`signal`、`bond`。
- [ ] `Toast` tone 同步迁移为 `evergreen` 和 `signal`；删除 `success`、`danger` tone 命名。
- [ ] `StatusBanner` 使用同一 tone 体系。
- [ ] `Field` 统一 label、hint、error、input、select、textarea，全部使用 Tailwind class。
- [ ] `Dialog` 支持 `sm`、`md`、`lg`、`xl`，遮罩、容器、header、body、footer 对齐 EasyTrade。
- [ ] `PageHeader` 使用底部细边框、26px 标题、13px 描述、11px meta。
- [ ] `CodeBlock` 删除 `.code-block` 类依赖，内部直接使用 Tailwind。
- [ ] 为 `Button`、`Badge`、`Dialog`、`Toast` 增加或更新组件测试。

**验收：**

- `pnpm --dir frontend test frontend/src/components` 通过。
- `pnpm --dir frontend typecheck` 通过。
- `rg -n '"success"|"warning"|"danger"|"primary"' frontend/src | rg 'Badge|BadgeTone|ToastTone|StatusBanner|tone='` 不再出现旧 tone 用法；`Button variant="primary"` 不受此检查影响。
- `rg -n 'className="[^"]*(button-|badge-|field|control|dialog-|toast-|code-block)' frontend/src` 无页面或组件实现依赖。

## 任务 3：建立新表格 primitives 并删除旧表格 class 路线

**目的：**表格观感对齐 EasyTrade，但不恢复旧 `DataTable` 路线，不继续依赖 `tanstack-table`、`table-scroll`、`permission-table`、`matrix-table` class。

**文件：**

- 新增：`frontend/src/components/ui/TablePrimitives.tsx`
- 新增：`frontend/src/components/ui/TableState.tsx`
- 修改：`frontend/src/components/tableArchitecture.test.ts`
- 修改：所有当前使用 `table-scroll`、`tanstack-table`、`permission-table`、`matrix-table` 的页面

**步骤：**

- [ ] 新增表格 primitives：`TableFrame`、`TableRoot`、`TableHead`、`TableBody`、`TableRow`、`TableHeaderCell`、`TableCell`、`TableEmptyRow`、`TableSkeletonRows`。
- [ ] primitives 只负责视觉和结构，不持有 TanStack Table 状态，不做远程分页行为。
- [ ] 更新 `tableArchitecture.test.ts`，禁止旧表格 class：`tanstack-table`、`table-scroll`、`permission-table`、`matrix-table`、`data-table`、`table-wrap`、`empty-row`。
- [ ] 迁移所有表格调用点到新 primitives。
- [ ] 权限选择树表和矩阵表保留业务交互，但结构也使用新 primitives。
- [ ] 删除旧表格 CSS 文件或清空 import。

**验收：**

- `pnpm --dir frontend test frontend/src/components/tableArchitecture.test.ts` 通过。
- `rg -n 'tanstack-table|table-scroll|permission-table|matrix-table|DataTable|CredentialTable|GrantTable|RequestTable' frontend/src` 无实现依赖。
- `pnpm --dir frontend exec playwright test e2e/smoke.spec.ts --project=chromium` 通过。

## 任务 4：迁移顶层列表页

**目的：**先迁移控制台列表、运营列表、门户列表和门户申请表单，让主路径获得一致视觉。

**文件：**

- 修改：`frontend/src/pages/console/ConsoleAppList.tsx`
- 修改：`frontend/src/pages/console/OperationsPage.tsx`
- 修改：`frontend/src/pages/portal/PortalPage.tsx`
- 修改：`frontend/src/pages/portal/components/AccessRequestForm.tsx`
- 修改：`frontend/src/pages/portal/components/AccessRequestFields.tsx`
- 修改：`frontend/src/pages/portal/components/RequestTargetPicker.tsx`
- 修改：`frontend/src/pages/portal/components/PermissionSelector.tsx`

**步骤：**

- [ ] `ConsoleAppList` 使用新版 `Button`、`Badge`、`Dialog`、`Field`、`PageHeader` 和表格 primitives。
- [ ] `OperationsPage` 使用统一刷新按钮、状态 Badge、错误状态、空态。
- [ ] `PortalPage` 权限列表和申请列表使用同一表格 primitives。
- [ ] 申请表单使用新版 `Field` 和按钮 loading/disabled 态。
- [ ] `PermissionSelector` 删除 `permission-table` 路线，改用表格 primitives。
- [ ] 页面文案统一中文正文；`app_key`、`user_id`、`Bearer token` 等不可翻译字段保留英文。

**验收：**

- `pnpm --dir frontend test frontend/src/pages/portal frontend/src/pages/console/ConsoleAppList.test.tsx` 通过。
- `pnpm --dir frontend exec playwright test e2e/smoke.spec.ts --project=chromium` 通过。
- `/console`、`/console/operations/access-requests`、`/portal`、`/portal/request` 桌面和移动截图无按钮遮挡、表格错位、文本溢出。

## 任务 5：迁移控制台工作台 tabs

**目的：**处理当前偏差最大的区域，消除高密度后台页面里的旧 class 和英文正文漂移。

**文件：**

- 修改：`frontend/src/pages/console/ConsoleAppWorkspace.tsx`
- 修改：`frontend/src/pages/console/workspace/tabs/OverviewTab.tsx`
- 修改：`frontend/src/pages/console/workspace/tabs/CatalogTab.tsx`
- 修改：`frontend/src/pages/console/workspace/tabs/MatrixTab.tsx`
- 修改：`frontend/src/pages/console/workspace/tabs/CredentialsTab.tsx`
- 修改：`frontend/src/pages/console/workspace/tabs/RulesTab.tsx`
- 修改：`frontend/src/pages/console/workspace/tabs/ManifestTab.tsx`
- 修改：`frontend/src/pages/console/workspace/tabs/QueryTestTab.tsx`
- 修改：`frontend/src/pages/console/workspace/tabs/GuideTab.tsx`
- 修改：`frontend/src/pages/console/workspace/credentials/CreateCredentialForm.tsx`
- 修改：`frontend/src/pages/console/workspace/matrix/RolePermissionMatrix.tsx`

**步骤：**

- [ ] 先阅读这些文件的当前 diff，确认已有未提交迁移逻辑，不回退任何表格拆分。
- [ ] `OverviewTab` 的 metric、状态 Banner、成员表格、问题表格统一使用新基础组件和表格 primitives。
- [ ] `CatalogTab` 统一三组表格和三组表单的视觉层级；非必要英文正文改成中文。
- [ ] `MatrixTab` 和 `RolePermissionMatrix` 保留矩阵交互，但删除 `matrix-table` class 路线。
- [ ] `CredentialsTab` 的凭据表、生成凭据表单、一次性密钥弹窗统一按钮和弹窗规格。
- [ ] `RulesTab` 的 blocking 状态改用 `signal` tone，审批人字段文案中文化。
- [ ] `ManifestTab` 的预览结果、差异分组、上传按钮、应用按钮使用统一面板和状态色。
- [ ] `QueryTestTab` 的测试结果表格、错误展示、代码块复制按钮对齐基础组件。
- [ ] `GuideTab` 的接入指南表格使用新表格 primitives，代码块不遮挡按钮。

**验收：**

- `pnpm --dir frontend typecheck` 通过。
- `pnpm --dir frontend test` 通过。
- `pnpm --dir frontend exec playwright test e2e/smoke.spec.ts --project=chromium` 通过。
- `rg -n 'table-scroll|tanstack-table|permission-table|matrix-table|form-surface|matrix-panel|status-banner|code-block' frontend/src` 无实现依赖。
- 手动或浏览器验证一个真实 `app_key` 的 `/console/apps/{app_key}`，逐 tab 检查桌面和移动布局。

## 任务 6：删除旧 Django HTML UI

**目的：**消除 React 主线之外的旧 HTML UI。旧模板不是迁移目标，而是删除目标。

**文件：**

- 修改：`src/easyauth/admin_console/views.py`
- 修改：`src/easyauth/portal/views.py`
- 删除：`src/easyauth/admin_console/templates/admin_console/app_detail.html`
- 删除：`src/easyauth/admin_console/templates/admin_console/_styles.html`
- 删除：`src/easyauth/admin_console/templates/admin_console/app_detail/**`
- 删除：`src/easyauth/portal/templates/portal/home.html`
- 删除：`src/easyauth/portal/templates/portal/_styles.html`

**步骤：**

- [ ] 删除 `admin_console.views._render_detail()` 对旧模板的渲染路径。
- [ ] 旧 POST 表单流程必须改为 React 已覆盖的 API 流程；如果发现没有 API，先补 API 和 React 调用，再删除旧模板。
- [ ] 删除 `portal.views._legacy_post_response()` 对 `portal/home.html` 的渲染路径。
- [ ] 删除旧模板文件和旧模板 partial。
- [ ] 补测试证明控制台和门户不会再返回旧 HTML UI。
- [ ] 扫描旧入口：
  - `rg -n 'admin_console/_styles|portal/_styles|PORTAL_TEMPLATE|CONSOLE_TEMPLATE|_legacy_post_response|_render_detail|admin_console/app_detail.html|portal/home.html' src/easyauth`

**验收：**

- 上述扫描结果为 0。
- `pytest tests/integration/admin_console tests/integration/portal` 通过。
- 修改 Django 模板或页面响应后，必须重启 Django 开发服务，并用真实 HTTP 验证新页面已加载。

## 任务 7：补视觉回归与真实加载验证

**目的：**避免只在 Vite dev server 上验证，漏掉 Django 静态 manifest 和真实页面壳问题。

**文件：**

- 修改：`frontend/e2e/smoke.spec.ts`
- 新增：`frontend/e2e/visual-alignment.spec.ts`
- 修改或检查：`src/easyauth/static/easyauth/frontend/.vite/manifest.json`

**步骤：**

- [ ] 前端开发态验证：运行 `pnpm --dir frontend exec playwright test --project=chromium`。
- [ ] 类型和单测验证：运行 `pnpm --dir frontend typecheck`、`pnpm --dir frontend test`。
- [ ] 构建静态资源：运行 `pnpm --dir frontend build`，确认 manifest 和 hashed assets 更新。
- [ ] 重启当前 Django 开发服务。端口先用 `lsof -iTCP -sTCP:LISTEN | rg '8000|8001|8010|manage.py|python'` 确认，不假设固定端口，并记录为 `DJANGO_PORT`。
- [ ] 如果需要登录态，使用本地开发登录入口进入门户：`http://127.0.0.1:${DJANGO_PORT}/auth/dev-login/?user_id=admin-001&next=/portal/`。控制台如果需要管理员身份，先确认本地种子数据或 session 中的角色能返回 `ConsoleActor`，不能只截图登录页。
- [ ] 真实 HTTP 验证：
  - `curl -I "http://127.0.0.1:${DJANGO_PORT}/console/"`
  - `curl -I "http://127.0.0.1:${DJANGO_PORT}/portal/"`
  - `curl -s "http://127.0.0.1:${DJANGO_PORT}/console/" | rg 'easyauth/frontend/assets/.*\\.css|easyauth/frontend/assets/.*\\.js'`
- [ ] 浏览器打开真实 Django 页面 `/console/`、`/portal/request`，确认加载的是最新 hashed asset。
- [ ] 与任务 0 的 EasyTrade/EasyAuth 截图做人工比对，重点看按钮高度、表头、Badge、面板边框、页头、移动端文本。

**验收：**

- Vite Playwright 通过。
- `pnpm --dir frontend build` 通过。
- Django 服务已重启。
- 真实 `/console/` 和 `/portal/` HTTP 响应引用最新 build asset。
- 桌面和移动真实页面无明显视觉偏差。

## 任务 8：文档和完成标准

**目的：**把视觉契约和验证方式写成项目事实，防止新页面重新发散。

**文件：**

- 修改：`docs/architecture/easyauth-architecture-design.md` 或新增 `docs/architecture/easyauth-frontend-visual-contract.md`
- 修改：`docs/README.md`
- 新增：`docs/audits/visual-alignment/2026-07-01/README.md`

**步骤：**

- [ ] 用中文记录 EasyAuth 前端视觉契约，包括 Tailwind v4、token、组件、表格、页面状态、旧模板删除策略。
- [ ] 在文档入口增加链接。
- [ ] 记录最终验证命令和结果。
- [ ] 文档中只保留必要英文标识符、路径、命令、API 字段和产品名。

**验收：**

- `rg -n '[A-Za-z]{20,}' docs/architecture docs/README.md docs/audits/visual-alignment/2026-07-01` 人工检查无非必要英文正文。
- 文档说明和代码实际实现一致。

## 推荐执行顺序

1. 任务 0：主线程完成，冻结基线和当前 diff。
2. 任务 1：单代理完成 Tailwind 和 token 切换，合并后立即跑基础测试。
3. 任务 2 和任务 3：两个代理并发，一个基础组件，一个表格 primitives。
4. 任务 4 和任务 5：两个代理并发，一个顶层列表，一个工作台 tabs；工作台 tabs 不再拆多代理，避免同目录冲突。
5. 任务 6：主线程或后端代理单独删除旧 Django HTML UI。
6. 任务 7：验证代理执行，主线程复核真实 Django 页面。
7. 任务 8：文档代理执行，主线程复核中文文档规则。

## 不做事项

- 不迁入 EasyTrade 的 Next App Router。
- 不恢复 `DataTable`、`CredentialTable`、`GrantTable`、`RequestTable` 旧包装组件。
- 不保留旧 token、旧 tone、旧 CSS class、旧 Django HTML UI。
- 不把视觉修复扩大成授权模型、API 契约或数据库 schema 改造。

## 最终完成定义

- EasyAuth React 前端使用 Tailwind v4 + EasyTrade token 作为唯一视觉系统。
- 控制台和门户的按钮、表格、表单、Badge、弹窗、页头、面板在桌面和移动端与 EasyTrade 基线保持一致。
- 当前表格架构测试通过，旧 `DataTable` 路线没有回归。
- 旧 Django HTML UI 已删除，真实页面只加载 React shell。
- 所有新增或修改文档为中文。
- `pnpm --dir frontend typecheck`、`pnpm --dir frontend test`、`pnpm --dir frontend build` 通过。
- `pnpm --dir frontend exec playwright test --project=chromium` 通过。
- Django 开发服务已重启，真实 `/console/` 和 `/portal/` 页面确认加载最新构建产物。
