# EasyAuth 与 EasyTrade 视觉一致性审计记录

本记录服务于 `docs/plans/2026-07-02-easyauth-easytrade-visual-consistency-remediation-plan.md` 的任务 0，用于保存本轮修复前后的可核验证据。

## 工作区状态

执行时间：2026-07-02

命令：

```bash
git status --short
git branch --show-current
```

结果摘要：

- 当前分支：`codex/easyauth-easytrade-onboarding`
- 本轮实施前可见未跟踪文件：`docs/plans/2026-07-02-easyauth-easytrade-visual-consistency-remediation-plan.md`

## 初始偏差扫描

命令：

```bash
rg -n 'rounded-lg|rounded-md|slate-|bg-amber-ink|text-bond-strong|shadow-2xl|text-xs text-slate' frontend/src
```

结果摘要：

- 旧视觉类集中在基础组件：`Button`、`Field`、`Badge`、`Dialog`、`StatusBanner`、`Toast`、`PanelSurface`、`TablePrimitives`、`EmptyState`、`PageState`。
- 旧视觉类集中在页面：`ConsoleAppList`、`ConsoleAppWorkspace`、`PortalPage`、`PermissionSelector`、`workspace/tabs/*`、`RolePermissionMatrix`、`CreateCredentialForm`。
- 主要偏差类型：大圆角 `rounded-lg/rounded-md`、`slate-*` 色系、旧蓝色按钮类 `bg-amber-ink`、厚阴影 `shadow-2xl`、旧链接色 `text-bond-strong`。

## EasyTrade 基准文件

本轮对齐基准来自：

- `/Users/konata/code/EasyTrade/frontend/src/app/globals.css`
- `/Users/konata/code/EasyTrade/frontend/src/components/ui/button.tsx`
- `/Users/konata/code/EasyTrade/frontend/src/components/ui/field.tsx`
- `/Users/konata/code/EasyTrade/frontend/src/components/ui/badge.tsx`
- `/Users/konata/code/EasyTrade/frontend/src/components/ui/dialog.tsx`
- `/Users/konata/code/EasyTrade/frontend/src/components/ui/panel-surface.tsx`
- `/Users/konata/code/EasyTrade/frontend/src/components/ui/data-grid.parts.tsx`

## 截图记录

本轮通过 `frontend/e2e/visual-alignment.spec.ts` 对下列路径完成桌面 `1280x800` 与移动端 `390x844` 的浏览器验证，并检查可见控件未被遮挡、可见文本无横向溢出。`/console` 场景额外打开“新建应用”弹窗，覆盖弹窗、表单和提交按钮视觉。

- `console-desktop.png`
- `console-desktop-create-dialog.png`
- `console-mobile390.png`
- `console-mobile390-create-dialog.png`
- `console-operations-access-requests-desktop.png`
- `console-operations-access-requests-mobile390.png`
- `portal-desktop.png`
- `portal-mobile390.png`
- `portal-request-desktop.png`
- `portal-request-mobile390.png`

EasyTrade 本地服务本轮未启动，因此未新增 EasyTrade 对照截图；本轮基准来自源码级契约读取。

## 本轮验证记录

已通过：

```bash
pnpm --dir frontend typecheck
pnpm --dir frontend test
pnpm --dir frontend exec playwright test e2e/smoke.spec.ts --project=chromium
pnpm --dir frontend exec playwright test e2e/visual-alignment.spec.ts --project=chromium
pnpm --dir frontend build
```

构建产物：

- `src/easyauth/static/easyauth/frontend/.vite/manifest.json`
- `src/easyauth/static/easyauth/frontend/assets/main-Cu5N2CWW.css`
- `src/easyauth/static/easyauth/frontend/assets/main-wfsOZ_xe.js`

## Django 真实页面响应验证

服务重启命令：

```bash
.venv/bin/python manage.py runserver 0.0.0.0:8001 --noreload
```

验证端口：`8001`

由于 `/console/` 和 `/portal/request` 需要登录态，本轮通过 Django session 存储创建临时本地 session，并用真实 HTTP `Cookie: sessionid=...` 请求目标 URL。

验证结果：

```bash
curl -I -H 'Cookie: sessionid=...' http://127.0.0.1:8001/console/
curl -I -H 'Cookie: sessionid=...' http://127.0.0.1:8001/portal/request
```

- `/console/`：`200 OK`
- `/portal/request`：`200 OK`

真实 HTML 响应均包含：

```html
<link rel="stylesheet" href="/static/easyauth/frontend/assets/main-Cu5N2CWW.css">
<script type="module" src="/static/easyauth/frontend/assets/main-wfsOZ_xe.js"></script>
```
