# 前端契约

控制台（`/console/*`）与员工门户（`/portal/*`）共用一套 React 前端。本文是改动这两处 UI 时
必须遵守的契约：视觉、组件、数据边界、反馈、国际化和运行环境。

不适用于下游业务应用的页面样式，也不改变公共授权查询 API 的响应语义。

---

## 1. 页面主线

React 是控制台和门户的唯一页面主线，Django 只负责认证、授权、API 和 React shell
（`render_react_shell()`）。旧控制台/门户的 POST 表单入口返回 405，并提示改用
`/console/api/v1/` 或 `/portal/api/v1/me/access-requests`。

不新增 Django HTML 页面承载业务 UI。发现 React 没覆盖的旧能力时，先补 API 和 React 调用，
再删旧入口。

> 改动 Django 响应、React 构建产物或 Vite manifest 后，必须重启 Django 开发服务并用真实
> HTTP 响应确认新代码已加载——构建成功不等于生效。

## 2. 视觉与组件

样式运行时是 Tailwind v4（`@tailwindcss/vite`）。全局入口 `frontend/src/styles/index.css`，
跨页面布局能力放 `layout-shell.css` / `responsive.css`，其余样式写在组件内的 Tailwind class。

### 色彩 token

使用 RGB 三元组 token，通过 `@theme inline` 暴露语义色，透明度写作
`rgb(var(--token) / alpha)`。

| 类别 | token |
| --- | --- |
| 背景 | `--paper`、`--paper-deep`、`--paper-soft` |
| 文本 | `--ink`、`--ink-soft`、`--ink-faint` |
| 边框 | `--hairline`、`--hairline-strong`、`--hairline-soft` |
| 强调 | `--amber`、`--bond` |
| 状态 | `--evergreen`、`--signal` |
| 业务状态 | `--status-draft`、`--status-pending`、`--status-active`、`--status-stop`、`--status-archive` |

新 token 必须有明确语义，不为单个页面临时造色。已废弃、不得恢复：`--bg`、`--surface`、
`--muted`、`--line`、`--brand`、`--accent`、`--danger`、`--success`、`--warning`。

### 基础组件

页面复用基础组件，不在页面内散落实现按钮、标签、表单、弹窗、页头、空态和页面状态。

| 能力 | 组件 | 契约 |
| --- | --- | --- |
| 按钮 | `Button` | `primary` / `secondary` / `outline` / `ghost` / `ghost-danger` / `danger`；默认 `outline`；尺寸 `sm` / `md` / `lg`；支持 `loading` |
| 标签 | `Badge` | tone：`neutral` / `faint` / `ink` / `amber` / `evergreen` / `signal` / `bond` |
| 表单 | `Field`、`TextInput`、`TextArea`、`SelectInput` | 统一 label、hint、error 与可访问描述关系 |
| 弹窗 | `Dialog` | `sm` / `md` / `lg` / `xl`，关闭按钮用图标按钮 |
| 页头 | `PageHeader` | 承载标题、描述、meta 和 actions |
| 面板 | `PanelSurface` | 业务面板容器，不再嵌套卡片 |
| 空态 | `EmptyState` | 局部空数据 |
| 页面状态 | `PageState` | 整页加载失败、无权限、阻塞、完成 |

### 表格

统一使用 `frontend/src/components/ui/TablePrimitives.tsx`：`TableFrame`、`TableRoot`、
`TableHead`、`TableBody`、`TableRow`、`TableHeaderCell`、`TableCell`、`TableEmptyRow`、
`TableSkeletonRows`。

- primitives 只负责视觉和结构，不持有远程分页、排序、筛选状态。
- 业务层可用 TanStack Table，但渲染结构必须落到 primitives。
- 横向滚动由 `TableFrame` 承担。
- 不恢复 `DataTable` / `CredentialTable` / `GrantTable` / `RequestTable` 等旧包装组件，
  也不恢复 `table-scroll` / `permission-table` / `matrix-table` 等旧 class。

`frontend/src/components/tableArchitecture.test.ts` 用禁止规则守住上述边界。

## 3. 网络与数据边界

- 浏览器 API 请求只把结构化 JSON 成功响应视为成功。除显式无正文的 `204` 外，`2xx` 非 JSON、
  损坏 JSON、列表信封缺 `data` 都必须快速失败。
- 稳定错误码：网络失败 `NETWORK_ERROR`；成功响应格式异常 `UNEXPECTED_RESPONSE_TYPE` 或
  `INVALID_JSON_RESPONSE`；列表信封异常 `LIST_PAYLOAD_CONTRACT_ERROR`。
- `401` 是全局会话失效事件而非普通业务错误：网络层发布 `easyauth:api-session-expired`，
  壳层只展示一次重新登录入口。
- 后端原始异常、HTML 错误页、JSON 字段路径和内部枚举不得作为用户主文案，只能进日志、诊断
  编号或受控技术详情。
- 未知枚举不当作合法业务行显示"未知状态"，解析直接失败并展示本地化契约错误。

## 4. 用户反馈

- **失败必须可见**，且出现在用户当前操作的上下文：字段错误用字段级提示，对话框错误留在对话
  框，区块加载失败用区块错误，后台轮询失败用区块陈旧警告。
- **成功反馈只用一个载体**：状态徽标、行消失、按钮旁"已保存"或 toast 皆可，按动作风险和界面
  变化选择。不为所有 mutation 机械加成功 toast。
- **异步动作真正完成才显示成功**：剪贴板复制必须等 `navigator.clipboard.writeText` 成功；
  任务触发要读返回的机器状态，`queued=false` 应显示"已合并"而不是"已入队"。
- 并发请求使用提交时快照 + 最新请求门禁，旧响应不得覆盖新输入的结果。
- 页面必须显式处理：加载中、空数据、请求失败、无权限/未登录（由后端页面壳跳转登录，React
  不伪造授权）、提交中（按钮进入 `loading` 或禁用，防重复提交）。

## 5. 国际化

前端提供 zh-CN / en 两种界面语言，顶栏"中 / EN"切换，选择持久化在 `localStorage` 的
`easyauth.locale`，默认 zh-CN。

- 消息目录在 `frontend/src/i18n/messages.ts`，zh-CN 是事实源，en 通过
  `Record<MessageKey, string>` 在编译期强制键集合一致。
- 用户可见文本、`aria-label`、placeholder、toast、错误标题、按钮内状态和空态都必须来自消息
  目录或明确的本地化函数。
- API 错误优先按稳定 `code` + 结构化参数在前端翻译；后端自然语言只作临时安全摘要，不是唯一
  契约。
- 目录数据（权限、权限组、范围、授权组）的英文名来自 `name_en` / `description_en`；en 下英文
  字段为空时回落中文主字段。
- 公共权限查询响应不含双语字段，下游展示名以下游本地目录为准。
- `localStorage` 被浏览器拒绝时，语言状态继续以内存值生效，不得白屏或中断切换。

## 6. 运行环境

### 支持矩阵

| 环境 | 最低口径 |
| --- | --- |
| Chrome / Edge / Safari / Firefox 桌面版 | 最近两个稳定大版本 |
| iOS Safari / WKWebView | iOS 最近两个主版本 |
| Android Chrome / Android System WebView | 最近两个稳定大版本 |

必需能力（全部环境相同）：`localStorage`、`ResizeObserver`、`crypto.randomUUID`、HTTPS 安全
上下文。`localhost` 与 `127.0.0.1` 仅作本地开发的安全上下文例外，正式部署必须 HTTPS。

启动期统一检查这些能力，任一缺失时不挂载业务路由，改为渲染 `UnsupportedBrowserPage` 并列出缺
失能力。不得在业务组件里用静默默认值、空数组或随机字符串替代缺失的平台能力。

### 未知路由

显示本地 404 页，保留原始地址并提供回到当前入口首页的操作。不静默重定向到 `/portal` 或
`/console`，避免坏链接被误认为有效页面。

### 响应式与无障碍

布局回归至少覆盖 `320px`、`390px`、`768px`、`900px`，验收需记录页头动作可见性、表格滚动宽
度、焦点可见性、复合控件键盘路径和动态状态播报语义。

Toast 在这四个断点必须：视口内完整可见不产生页面横向滚动；`320px` / `390px` 使用底部安全区
域，不遮挡顶栏、页头主操作和对话框关闭按钮；多条堆叠时容器高度受限可滚动；错误 toast 可关
闭且用 `role="alert"`，非错误用 `role="status"`；关闭按钮命中区不小于 `24×24 CSS px`。

受保护页面的浏览器验证结论必须说明取证方式：真实登录态、隔离渲染还是组件测试。

## 7. 本地验证

```bash
pnpm --filter @easyauth/frontend typecheck
pnpm --filter @easyauth/frontend test
pnpm --filter @easyauth/frontend build     # 含分包预算检查
```

涉及 Django 页面响应时，还需构建后重启服务并确认真实响应引用了新的资源哈希
（以 `src/easyauth/static/easyauth/frontend/.vite/manifest.json` 为准，本文不固定文件名）。

分包与体积预算见 [前端构建分包与体积预算](../operations/frontend-build-budget.md)。
