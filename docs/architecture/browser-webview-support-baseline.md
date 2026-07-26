# 浏览器与 WebView 支持基线

## 1. 支持矩阵

EasyAuth 前端只支持具备以下能力的现代浏览器或内置 WebView：

| 环境 | 最低支持口径 | 必需能力 |
| --- | --- | --- |
| Chrome / Edge 桌面版 | 最近两个稳定大版本 | `localStorage`、`ResizeObserver`、`crypto.randomUUID`、HTTPS 安全上下文 |
| Safari 桌面版 | 最近两个稳定大版本 | `localStorage`、`ResizeObserver`、`crypto.randomUUID`、HTTPS 安全上下文 |
| Firefox 桌面版 | 最近两个稳定大版本 | `localStorage`、`ResizeObserver`、`crypto.randomUUID`、HTTPS 安全上下文 |
| iOS Safari / WKWebView | iOS 最近两个主版本 | `localStorage`、`ResizeObserver`、`crypto.randomUUID`、HTTPS 安全上下文 |
| Android Chrome / Android System WebView | 最近两个稳定大版本 | `localStorage`、`ResizeObserver`、`crypto.randomUUID`、HTTPS 安全上下文 |

`localhost` 与 `127.0.0.1` 仅作为本地开发安全上下文例外。正式部署必须使用 HTTPS。

## 2. 不支持环境策略

启动期统一检查必需能力。任一能力缺失时，React 不继续挂载业务路由，而是显示“不支持当前浏览器或
WebView”的明确页面，并列出缺失能力。不得在业务组件里用静默默认值、空数组、内存语言状态或
随机字符串替代缺失平台能力。

## 3. 未知路由策略

前端未知路由显示本地 404 页面，保留原始地址，并提供返回当前入口首页的操作。不得把未知路径静默
重定向到 `/portal` 或 `/console`，避免坏链接、拼写错误或过期通知链接被误认为有效业务页面。

## 4. 窄屏 Toast 验收基线

Toast 在 `320px`、`390px`、`768px`、`900px` 视口必须满足：

- 视口宽度内完整可见，不能产生页面级横向滚动。
- `320px` 与 `390px` 下使用底部安全区域，不遮挡顶栏、页头主操作或对话框关闭按钮。
- 多条 Toast 堆叠时容器高度受限并可滚动；错误 Toast 保持可关闭。
- 关闭按钮命中区不小于 `24×24 CSS px`。
- 错误 Toast 使用 `role="alert"`，非错误 Toast 使用 `role="status"`。

## 5. 响应式与无障碍断点

布局回归至少覆盖 `320px`、`390px`、`768px`、`900px`。验收必须记录页头动作可见性、表格滚动宽度、
焦点可见性、复合控件键盘路径和动态状态播报语义；受保护页面的浏览器验证需说明是真实登录态、
隔离渲染还是组件测试。
