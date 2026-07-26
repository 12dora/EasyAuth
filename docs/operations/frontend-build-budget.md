# 前端构建分包与体积预算

## 目标

前端生产构建必须保持路由级分包，避免门户用户同步下载控制台、应用工作区和生命周期管理代码。
预算检查是发布门禁的一部分，不能通过调高 Vite 告警阈值、隐藏 warning 或删除 manifest 来绕过。

## 当前分包边界

- `main`：只承载 React 挂载、鉴权 shell、路由表、加载态和错误边界。
- `vendor`：第三方 React、Router、Query、Table 与图标依赖。
- `i18n`：中英文消息目录。
- 门户路由：`PortalPage` 独立异步 chunk。
- 控制台路由：`ConsoleAppList`、`ConsoleAppWorkspace`、`ConsoleSettingsPage`、`ConsoleTeamList`、
  `ConsoleTeamDetail`、`ApprovalTemplatesPage`、`ApprovalInstancesPage`、`OperationsPage` 独立异步 chunk。
- 生命周期路由：`ConsolePeopleList`、`HandoverTaskList`、`HandoverTaskDetail`、`OnboardingPage` 独立异步 chunk。
- 应用接入路由：`AppOnboardingWizard` 独立异步 chunk。

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
- 单个异步路由 chunk 原始体积不超过 `140 KiB`，gzip 不超过 `40 KiB`；
- 全部 JavaScript 原始体积不超过 `900 KiB`；
- `App.tsx` 中的全部页面级路由必须继续以 Vite manifest key 出现在入口 `dynamicImports` 中,且对应
  manifest 条目必须标记 `isDynamicEntry`。删除任一控制台、门户或生命周期路由 chunk 都会使预算检查失败。

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

若只验证已有构建产物预算，可运行：

```bash
node frontend/scripts/check-build-budget.mjs
```
