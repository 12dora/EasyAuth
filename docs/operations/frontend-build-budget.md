# 前端构建分包与体积预算

## 目标

前端生产构建必须保持路由级分包，避免门户用户同步下载控制台、应用工作区和生命周期管理代码。
预算检查是发布门禁的一部分，不能通过调高 Vite 告警阈值、隐藏 warning 或删除 manifest 来绕过。

## 当前分包边界

- `main`：只承载 React 挂载、鉴权 shell、路由表、加载态和错误边界。
- `vendor`：第三方 React、Router、Query、Table 与图标依赖。
- `antd`：Ant Design 及其运行时（`antd`、`@ant-design/*`、`rc-*`、`@rc-component/*`，
  以及只被 antd 使用的传递依赖 `@babel/runtime`、`classnames`、`dayjs`、`throttle-debounce`、
  `scroll-into-view-if-needed` 等）。判定逻辑在 `vite.config.ts` 的 `isAntdModule()`：
  只看路径里最后一个 `node_modules/` 之后的包名，避免 pnpm 的 `.pnpm/<pkg>@<ver>/` 目录误判。
- `i18n`：中英文消息目录。
- 门户路由：`PortalPage`、`PortalHandoverList`、`PortalHandoverDetail` 独立异步 chunk。
- 控制台路由：`ConsoleAppList`、`ConsoleAppWorkspace`、`ConsoleSettingsPage`、`ConsoleTeamList`、
  `ConsoleTeamDetail`、`ApprovalTemplatesPage`、`ApprovalInstancesPage`、`OperationsPage` 独立异步 chunk。
- 生命周期路由：`ConsolePeopleList`、`HandoverTaskList`、`HandoverTaskDetail`、`OnboardingPage` 独立异步 chunk。
- 应用接入路由：`AppOnboardingWizard` 独立异步 chunk。
- 数据交接共享组件（`features/handover/*`）由门户详情与控制台详情/向导异步 chunk 复用，不进入 `main`。

`App.tsx` 的懒加载边界必须保留 `AppShell`、侧边栏、顶栏、`route-transition`、`role="status"` 加载态和
路由错误边界；不能为了减少代码而把懒加载 fallback 改成空节点。

## 自动预算

`pnpm --dir frontend build` 会在 `vite build` 后执行：

```bash
node scripts/check-build-budget.mjs
```

脚本读取 `src/easyauth/static/easyauth/frontend/.vite/manifest.json` 和真实磁盘产物，校验：

- 入口 `main` 原始体积不超过 `80 KiB`，gzip 不超过 `30 KiB`；
- 单个同步 chunk 原始体积不超过 `360 KiB`，gzip 不超过 `110 KiB`；
  例外：`antd` chunk 单独走 `CHUNK_BUDGET_OVERRIDES`，上限 `760 KiB` / gzip `240 KiB`
  （2026-09-04 从 720 / 230 上调：门户「我的申请」详情弹窗接入 `Modal` + `Steps` + `Tooltip`，
  实测 antd chunk 732 KiB / gzip 229 KiB；antd 是手工 chunk，页面级懒加载不会把这些组件拆出去）。
  之所以不整体调高 `synchronousChunk*`，是为了让 `vendor` 继续守住 360 KiB —— 否则
  antd 的体积会顺带把 vendor 的门禁一起放松掉；
- 单个异步路由 chunk 原始体积不超过 `140 KiB`，gzip 不超过 `40 KiB`；
- 全部 JavaScript 原始体积不超过 `1700 KiB`（Ant Design 表格地基落地后上调，见下节基线）；
- `App.tsx` 中的全部页面级路由必须继续以 Vite manifest key 出现在入口 `dynamicImports` 中,且对应
  manifest 条目必须标记 `isDynamicEntry`。删除任一控制台、门户或生命周期路由 chunk 都会使预算检查失败。

## antd 表格地基的体积基线（2026-08-27）

三组数字都来自本机 `pnpm --dir frontend build` 实测：

| 构建 | `main` 入口 | `vendor` | `antd` | JavaScript 总量 |
| --- | --- | --- | --- | --- |
| 接入 antd 之前 | 36.5 KiB / gzip 11.8 | 325.2 KiB / gzip 100.7 | — | 942.7 KiB |
| 现状：只挂了 `AppConfigProvider` | 38.3 KiB / gzip 12.6 | 327.8 KiB / gzip 101.6 | 86.4 KiB / gzip 30.8 | 1031.9 KiB |
| 投影：页面开始 `import` `AppTable` 之后 | 41.1 KiB / gzip 13.6 | 327.8 KiB / gzip 101.6 | 661.0 KiB / gzip 208.3 | 1595.7 KiB |

- 第三行是把 `AppTable`/列预设/`useServerTable` 临时引入入口测出来的**上限**，
  代表 antd `Table` + `Select` + `Pagination` + `Input` + `Button` 全部进包之后的规模；
  预算按这个数留余量设置，页面迁移时不需要再来调预算。
- `antd` chunk 目前是**同步**加载的：`AppConfigProvider` 在 `src/main.tsx` 里全局挂载，
  ConfigProvider 与 Table 被 `manualChunks` 归到同一个 chunk。这是用「一个长期可缓存的
  vendor chunk」换「首屏多下载一段」的取舍；如果之后首屏预算吃紧，可考虑把
  `antd/es/config-provider` 与其余 antd 模块拆成两个 chunk。
- `vendor` 只从 325.2 涨到 327.8 KiB，因为 antd 独占的传递依赖也被归进了 `antd` chunk。
- 表格迁移完成、`@tanstack/react-table` 与自研表格原语删除后，`vendor` 与各页面 chunk
  会回落，届时应当把这里的数字重新实测下调。

## 失败处理

预算失败时先查看脚本输出的超限文件名，再按以下顺序处理：

1. 确认是否把新页面同步导入到 `App.tsx`、shell、i18n 以外的共享入口。
2. 对新增的大型页面或工作区页签使用动态导入，保持错误边界和加载态。
3. 对只在单页使用的第三方库放到该页的异步 chunk，不放进 `vendor`。
4. 只有在新增真实产品能力且经过构建证据确认后，才能调整预算；调整必须同步更新本文档和预算测试。

## 本地验证

常用命令：

```bash
pnpm --dir frontend typecheck
pnpm --dir frontend test src/App.test.tsx src/buildBudget.test.ts
pnpm --dir frontend build
```

表格地基相关的用例：

```bash
pnpm --dir frontend test src/components/antd/AppTable.test.tsx src/components/tableArchitecture.antd.test.ts
```

若只验证已有构建产物预算，可运行：

```bash
node frontend/scripts/check-build-budget.mjs
```
