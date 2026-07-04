# EasyAuth 前端视觉契约

## 状态

本文记录 EasyAuth React 前端的视觉契约，用于约束控制台、员工门户和后续页面改动。当前前端已经迁移到 Tailwind v4，并采用 EasyTrade 同源 RGB token 作为视觉基础。旧 Django HTML UI 不是保留入口，控制台和门户页面统一返回 React shell。

## 适用范围

- 控制台页面：`/console`、`/console/apps/{app_key}`、`/console/operations/*`。
- 员工门户页面：`/portal`、`/portal/request`、`/portal/*`。
- React 组件、页面状态、表格 primitives、全局样式和 Django 页面壳。

不适用范围：

- 下游业务应用的页面样式。
- Django Admin 默认页面。
- 公共授权查询 API 的响应语义。

## 样式运行时

EasyAuth 前端保留 Vite + React 架构，样式运行时使用 Tailwind v4。

- `frontend/package.json` 声明 `tailwindcss` 和 `@tailwindcss/vite`。
- `frontend/vite.config.ts` 通过 `tailwindcss()` 启用 Tailwind v4。
- `frontend/src/styles/index.css` 是全局样式入口，负责导入 Tailwind、布局样式、响应式样式和基础全局规则。
- 新页面不得恢复旧 CSS 组件类作为视觉来源。

新增样式必须优先写在组件内部的 Tailwind class 或明确的全局布局文件中。只有跨页面基础能力可以进入 `frontend/src/styles/index.css`、`layout-shell.css` 或 `responsive.css`。

## Token 契约

EasyAuth 使用 EasyTrade 同源 RGB 三元组 token，并通过 Tailwind v4 `@theme inline` 暴露语义色。

当前核心 token：

| 类别 | token |
| --- | --- |
| 背景 | `--paper`、`--paper-deep`、`--paper-soft` |
| 文本 | `--ink`、`--ink-soft`、`--ink-faint` |
| 边框 | `--hairline`、`--hairline-strong`、`--hairline-soft` |
| 强调 | `--amber`、`--bond` |
| 状态 | `--evergreen`、`--signal` |
| 业务状态 | `--status-draft`、`--status-pending`、`--status-active`、`--status-stop`、`--status-archive` |

规则：

- 透明色使用 `rgb(var(--token) / alpha)` 形式。
- 新 token 必须有明确语义，不能为单个页面临时造色。
- 不得恢复 `--bg`、`--surface`、`--muted`、`--line`、`--brand`、`--accent`、`--danger`、`--success`、`--warning` 这批旧 token。
- 状态含义使用 `amber`、`evergreen`、`signal`、`bond` 等当前 tone，不再使用旧 `success`、`danger` tone 作为组件契约。

## 组件契约

页面必须优先复用基础组件，不直接拼装旧视觉类。

| 能力 | 组件 | 契约 |
| --- | --- | --- |
| 按钮 | `Button` | 支持 `primary`、`secondary`、`outline`、`ghost`、`ghost-danger`、`danger`；默认 `outline`；支持 `sm`、`md`、`lg` 和 `loading`。 |
| 标签 | `Badge` | tone 使用 `neutral`、`faint`、`ink`、`amber`、`evergreen`、`signal`、`bond`。 |
| 表单 | `Field`、`TextInput`、`TextArea`、`SelectInput` | 统一 label、hint、error 和可访问描述关系。 |
| 弹窗 | `Dialog` | 支持 `sm`、`md`、`lg`、`xl`，关闭按钮使用图标按钮。 |
| 页头 | `PageHeader` | 承载标题、描述、meta 和 actions，不在页面中重复定义页头视觉。 |
| 面板 | `PanelSurface` | 用于业务面板，不在页面中嵌套卡片式容器。 |
| 空态 | `EmptyState` | 用于局部空数据。 |
| 页面状态 | `PageState` | 用于整页加载失败、无权限、阻塞和完成状态。 |

业务页面只保留必要的布局 class。按钮、标签、表单、弹窗、页头、空态、页面状态不得回到页面内散落实现。

## 表格契约

表格统一使用 `frontend/src/components/ui/TablePrimitives.tsx` 提供的 primitives：

- `TableFrame`
- `TableRoot`
- `TableHead`
- `TableBody`
- `TableRow`
- `TableHeaderCell`
- `TableCell`
- `TableEmptyRow`
- `TableSkeletonRows`

规则：

- 表格 primitives 只负责视觉和结构，不持有远程分页、排序或筛选状态。
- 页面可以在业务层使用 TanStack Table，但渲染结构必须落到上述 primitives。
- 横向滚动由 `TableFrame` 承担，不恢复 `.table-scroll`、`.table-wrap` 等旧 class。
- 不恢复 `DataTable`、`CredentialTable`、`GrantTable`、`RequestTable` 旧包装组件。
- 不恢复 `tanstack-table`、`permission-table`、`matrix-table`、`data-table`、`empty-row` 等旧 class。

## 页面状态契约

控制台和门户页面必须显式处理以下状态：

- 加载中：使用按钮 `loading`、表格 skeleton 或页面加载状态。
- 空数据：局部区域使用 `EmptyState`，整页使用 `PageState`。
- 请求失败：展示可读中文错误，并提供可执行的重试或返回动作。
- 无权限或未登录：后端页面壳负责跳转登录；React 内部状态不得伪造授权。
- 提交中：提交按钮必须进入 `loading` 或禁用态，避免重复提交。

页面文案使用中文。`app_key`、`user_id`、`Bearer token`、HTTP 路径、API 字段和产品名可以保留英文。

## 旧模板删除策略

React 是控制台和门户的唯一页面主线。Django 只负责认证、授权、API 和 React shell。

当前策略：

- `src/easyauth/admin_console/views.py` 的控制台页面通过 `render_react_shell()` 返回 React shell。
- `src/easyauth/portal/views.py` 的门户页面通过 `render_react_shell()` 返回 React shell。
- 旧控制台 POST 表单入口返回 405，并提示使用 `/console/api/v1/`。
- 旧门户 POST 表单入口返回 405，并提示使用 `/portal/api/v1/me/access-requests`。
- 旧模板目录下的控制台详情模板、门户首页模板和对应样式 partial 已删除。

后续规则：

- 不新增 Django HTML 页面来承载控制台或门户业务 UI。
- 如果发现 React 尚未覆盖的旧表单能力，应先补齐 API 和 React 调用，再删除旧入口。
- 修改 Django 页面响应、React build 产物或 Vite manifest 后，必须重启当前 Django 开发服务，并用真实 HTTP 响应或浏览器页面确认新代码已加载。

## 验证要求

视觉契约相关改动至少运行以下检查：

```bash
pnpm --dir frontend typecheck
pnpm --dir frontend test frontend/src/components
pnpm --dir frontend test frontend/src/components/tableArchitecture.test.ts
rg -n '--bg|--surface|--muted|--line|--brand|--accent|--danger|--success|--warning' frontend/src
rg -n 'tanstack-table|table-scroll|permission-table|matrix-table|DataTable|CredentialTable|GrantTable|RequestTable' frontend/src
```

涉及 Django 页面响应时，还必须完成真实页面加载验证：

```bash
pnpm --dir frontend build
curl -I "http://127.0.0.1:${DJANGO_PORT}/console/"
curl -I "http://127.0.0.1:${DJANGO_PORT}/portal/"
curl -s "http://127.0.0.1:${DJANGO_PORT}/console/" | rg 'easyauth/frontend/assets/.*\.css|easyauth/frontend/assets/.*\.js'
```

## 2026-07-02 视觉纠偏记录

本轮以 EasyTrade 的本地 UI primitives 为基准，完成 EasyAuth React 前端的视觉纠偏：

- `Button` 语义切换为 EasyTrade 口径：`primary` 为深墨底，`secondary` 为品牌蓝底，默认按钮为 `outline`。
- `Badge`、`Field`、`Dialog`、`PanelSurface`、`EmptyState`、`PageState`、`StatusBanner`、`Toast`、`CodeBlock` 和 `SecretDialog` 已收敛到小圆角、细边框、低阴影和 RGB token。
- 表格渲染统一使用 `TablePrimitives`，表头、单元格密度、hover 和 skeleton 对齐 EasyTrade。
- 控制台、员工门户、运营页、权限选择器、工作台 tabs 和矩阵类页面已清理旧大圆角、`slate-*`、旧按钮色和旧表格类依赖。
- `frontend/e2e/visual-alignment.spec.ts` 已把 `/console` 新建应用弹窗纳入视觉回归。

已完成的验证：

```bash
pnpm --dir frontend typecheck
pnpm --dir frontend test
pnpm --dir frontend exec playwright test e2e/smoke.spec.ts --project=chromium
pnpm --dir frontend exec playwright test e2e/visual-alignment.spec.ts --project=chromium
pnpm --dir frontend build
rg -n 'rounded-lg|rounded-md|slate-|bg-amber-ink|text-bond-strong|shadow-2xl|text-xs text-slate' frontend/src
rg -n -- '--bg|--surface|--muted|--line|--brand|--accent|--danger|--success|--warning' frontend/src
rg -n 'tanstack-table|table-scroll|permission-table|matrix-table|DataTable|CredentialTable|GrantTable|RequestTable' frontend/src
```

扫描说明：旧视觉扫描和旧表格扫描的剩余命中只允许出现在 `frontend/src/components/tableArchitecture.test.ts` 的禁止规则文本中；产品代码不得命中。

Vite 入口资源名带内容哈希, 每次构建都会变化, 以 `src/easyauth/static/easyauth/frontend/.vite/manifest.json` 为准, 不在本契约中固定具体文件名。
