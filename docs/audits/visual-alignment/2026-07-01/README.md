# EasyAuth / EasyTrade 视觉对齐截图基线

生成时间：2026-07-01

## 工作区冻结记录

任务开始时执行 `git status --short`，已有改动如下：

```text
 D frontend/src/components/DataTable.tsx
 M frontend/src/lib/api.test.ts
 M frontend/src/lib/api.ts
 M frontend/src/pages/console/ConsoleAppList.tsx
 M frontend/src/pages/console/OperationsPage.tsx
 D frontend/src/pages/console/workspace/credentials/CredentialTable.tsx
 M frontend/src/pages/console/workspace/matrix/RolePermissionMatrix.tsx
 M frontend/src/pages/console/workspace/tabs/CatalogTab.tsx
 M frontend/src/pages/console/workspace/tabs/CredentialsTab.tsx
 M frontend/src/pages/console/workspace/tabs/GuideTab.tsx
 M frontend/src/pages/console/workspace/tabs/ManifestTab.tsx
 M frontend/src/pages/console/workspace/tabs/MatrixTab.tsx
 M frontend/src/pages/console/workspace/tabs/OverviewTab.tsx
 M frontend/src/pages/console/workspace/tabs/QueryTestTab.tsx
 M frontend/src/pages/console/workspace/tabs/RulesTab.tsx
 M frontend/src/pages/portal/PortalPage.tsx
 D frontend/src/pages/portal/components/GrantTable.tsx
 M frontend/src/pages/portal/components/PermissionSelector.tsx
 D frontend/src/pages/portal/components/RequestTable.tsx
 M frontend/src/styles/components/table.css
?? docs/plans/2026-07-01-easyauth-easytrade-visual-alignment-plan.md
?? frontend/src/components/tableArchitecture.test.ts
```

任务结束前再次执行 `git status --short`，除本目录 `docs/audits/` 外，观察到工作区又出现了更多非审计目录改动；按任务规则未回退、未提交。

## 表格架构约束确认

执行命令：

```bash
git diff -- frontend/src/components/tableArchitecture.test.ts frontend/src/styles/components/table.css
```

确认到的关键差异：

- `.table-wrap` 不再作为卡片外观和横向滚动容器。
- `.table-scroll` 承担横向滚动。
- `.data-table` 收敛为 `.tanstack-table`。
- `.empty-row` 收敛为 `.table-empty`。

## 运行面

- EasyTrade：在 `/Users/konata/code/EasyTrade` 执行 `docker compose up -d`，容器 `easytrade-postgres-1`、`easytrade-backend-1`、`easytrade-frontend-1` 已运行，`http://localhost:3000/zh-CN/admin/pipeline` 返回 HTTP 200。未遇到登录阻塞。
- EasyAuth：在 `/Users/konata/code/EasyAuth` 执行 `pnpm --dir frontend dev`，服务地址为 `http://127.0.0.1:5173/`。首次启动后 `@vite/client` 返回异常 HTML，已重启 Vite；重启后 `@vite/client` 返回 `text/javascript`，页面可以加载。
- EasyAuth 数据：使用 Playwright route mocks，数据形状参考 `frontend/e2e/smoke.spec.ts`，并为 `/console/api/v1/operations/access-requests`、`/portal/api/v1/me/grants`、`/portal/api/v1/request-catalog` 等目标页接口补充 mock。

## 截图清单

桌面视口为 1280x800，移动视口宽度为 390px。

| 应用 | 页面 | 桌面截图 | 移动截图 |
| --- | --- | --- | --- |
| EasyTrade | `/zh-CN/admin/pipeline` | `screenshots/easytrade-pipeline-desktop.png` | `screenshots/easytrade-pipeline-mobile390.png` |
| EasyTrade | `/zh-CN/admin/orders` | `screenshots/easytrade-orders-desktop.png` | `screenshots/easytrade-orders-mobile390.png` |
| EasyTrade | `/zh-CN/admin/settings` | `screenshots/easytrade-settings-desktop.png` | `screenshots/easytrade-settings-mobile390.png` |
| EasyAuth | `/console` | `screenshots/easyauth-console-desktop.png` | `screenshots/easyauth-console-mobile390.png` |
| EasyAuth | `/console/operations/access-requests` | `screenshots/easyauth-console-operations-access-requests-desktop.png` | `screenshots/easyauth-console-operations-access-requests-mobile390.png` |
| EasyAuth | `/portal` | `screenshots/easyauth-portal-desktop.png` | `screenshots/easyauth-portal-mobile390.png` |
| EasyAuth | `/portal/request` | `screenshots/easyauth-portal-request-desktop.png` | `screenshots/easyauth-portal-request-mobile390.png` |

机器检测明细保存在 `baseline-results.json`。

## 视觉问题记录

本轮自动检测项：文本溢出、按钮中心点遮挡、表格横向滚动容器异常、页面级横向溢出。

- EasyTrade 3 个页面桌面和移动均未检测到文本溢出、按钮遮挡、表格横向滚动异常或页面级横向溢出。
- EasyAuth `/console` 桌面和移动均未检测到上述问题。
- EasyAuth `/console/operations/access-requests` 移动端检测到 `.table-scroll` 横向内容宽度 362px、容器宽度 350px，但计算样式 `overflow-x: visible`，属于表格横向滚动异常；页面级宽度仍为 390px，未撑破整页。
- EasyAuth `/portal` 移动端检测到 `.table-scroll` 横向内容宽度 764px、容器宽度 350px，但计算样式 `overflow-x: visible`，属于表格横向滚动异常；页面级宽度仍为 390px，未撑破整页。
- EasyAuth `/portal/request` 桌面和移动均未检测到上述问题。

## 阻塞与处理

- Docker 未阻塞。
- EasyTrade 登录未阻塞。
- EasyAuth 首轮截图因 Vite 客户端脚本返回异常内容导致 React 未挂载；重启 Vite 后重新采集，最终 8 张 EasyAuth 截图均为成功状态。
- 本任务未修改业务代码，未提交 git commit。

## 迁移目标

本轮视觉对齐的目标是把 EasyAuth 控制台和员工门户统一到 EasyTrade 同源视觉语言，并删除 React 主线之外的旧 Django HTML UI。

- React 前端使用 Tailwind v4 和 EasyTrade RGB token。
- 基础控件统一通过 `Button`、`Badge`、`Field`、`Dialog`、`PageHeader`、`PanelSurface`、`EmptyState`、`PageState` 表达视觉语义。
- 表格统一使用 `TablePrimitives`，不恢复旧 `DataTable`、`CredentialTable`、`GrantTable`、`RequestTable` 包装组件。
- 页面需要显式处理加载中、空数据、请求失败、无权限或未登录、提交中等状态。
- 控制台和门户由 Django 返回 React shell；旧模板和旧表单入口不作为继续维护的页面入口。

详细契约见 `docs/architecture/easyauth-frontend-visual-contract.md`。

## 完成验证

任务 7 已完成最终收口验证。验证时间为 2026-07-01，当前 Django 开发服务端口记录为 `DJANGO_PORT=8010`。

### 命令清单

```bash
pnpm --dir frontend typecheck
pnpm --dir frontend test
pnpm --dir frontend exec playwright test --project=chromium
pnpm --dir frontend build
.venv/bin/pytest tests/integration/admin_console tests/integration/portal
rg -n '--bg|--surface|--muted|--line|--brand|--accent|--danger|--success|--warning' frontend/src
rg -n 'tanstack-table|table-scroll|permission-table|matrix-table|DataTable|CredentialTable|GrantTable|RequestTable' frontend/src
rg -n 'admin_console/_styles|portal/_styles|PORTAL_TEMPLATE|CONSOLE_TEMPLATE|_legacy_post_response|_render_detail|admin_console/app_detail.html|portal/home.html' src/easyauth
```

涉及真实 Django 页面响应时，已重启当前 Django 开发服务后执行：

```bash
curl -I "http://127.0.0.1:8010/console/"
curl -I "http://127.0.0.1:8010/portal/"
curl -s -L -b "$COOKIE" "http://127.0.0.1:8010/console/" | rg 'easyauth/frontend/assets/.*\.css|easyauth/frontend/assets/.*\.js'
```

### 验证结果

- `pnpm --dir frontend typecheck`：通过。
- `pnpm --dir frontend test`：12 个测试文件、61 个测试通过。
- `pnpm --dir frontend exec playwright test --project=chromium`：26 个 Chromium 测试通过，覆盖 smoke 和 `visual-alignment.spec.ts` 的桌面与 390px 移动视口。
- `pnpm --dir frontend build`：通过，生成 `assets/main-DFMPJgHS.css` 和 `assets/main-DBahzC0E.js`。
- `.venv/bin/pytest tests/integration/admin_console tests/integration/portal`：202 个测试通过。
- 旧 token 扫描：无命中。
- 旧 Django 模板入口扫描：无命中。
- 旧表格 class 和旧包装组件扫描：实现代码无命中；仅组件测试和架构测试保留反向断言文本。
- 真实 HTTP：未登录 `GET /console/` 和 `GET /portal/` 返回 302 登录跳转；dev-login 后 `GET /console/` 和 `GET /portal/` 返回 200。
- 真实浏览器：`/console/` 渲染 React route `/console/`，`/portal/request` 渲染 React route `/portal/request`；两页均引用 `/static/easyauth/frontend/assets/main-DFMPJgHS.css` 和 `/static/easyauth/frontend/assets/main-DBahzC0E.js`。
- 桌面和 390px 移动视口：`visual-alignment.spec.ts` 未发现按钮中心点遮挡或可见文本横向溢出。
