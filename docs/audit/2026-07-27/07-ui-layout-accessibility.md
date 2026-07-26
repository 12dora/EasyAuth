# UI 布局、响应式与无障碍审计

## 1. 审计结论

本次审计覆盖 React 页面与共享组件、全局样式、认证/错误 Django 模板，以及现有 Playwright 视觉回归场景。共确认 12 项问题：高严重度 4 项、中严重度 7 项、低严重度 1 项。

最优先处理的四项问题是：

1. 通用 `PageHeader` 在移动端会被多按钮动作区挤压，标题和描述逐字竖排，动作按钮被裁掉。
2. 通用表格只有滚动容器、没有可触发横向滚动的最小内容宽度，多列表格在手机上被强行压缩。
3. `ink-faint`、`amber`、`evergreen` 等全局颜色在实际小字号使用中不满足 WCAG AA 对比度。
4. 用户搜索组合框混用了“焦点停留在输入框”的 combobox 模式和可聚焦按钮选项，导致键盘选择及读屏活动项播报不完整。

严重度定义：

- **高**：主路径在常见手机视口已经出现内容不可读、操作不可见，或关键表单对键盘/读屏用户不可可靠完成。
- **中**：功能仍可能通过其他方式完成，但违反通用无障碍交互契约、显著降低可发现性，或影响一批共享组件的使用者。
- **低**：影响较轻、存在明确绕过方式，但仍造成持续的视觉或滚动噪声。

置信度定义：

- **高**：由真实页面、浏览器隔离渲染或源码直接确认。
- **中**：源码中的布局或语义条件已经成立，但受认证或数据条件限制，未在真实业务数据页面触发。

## 2. 验证范围与证据边界

### 2.1 真实页面验证

本机已有 EasyAuth Django 服务运行在 `http://localhost:8001`，`/health/` 返回正常。使用浏览器直接验证了：

| 页面 | 视口 | 结果 |
| --- | --- | --- |
| `/auth/local/` | `1280×800` | 页面真实响应与真实样式资源；无横向溢出；文档宽度 `1280px` |
| `/auth/local/` | `390×844` | 页面真实响应与真实样式资源；卡片宽 `358px`、左右各 `16px`；无横向溢出 |
| `/auth/local/` | 上述两种视口 | 文档高度都比视口多约 `1px`；工作账号入口在无障碍树中被宣告为“按钮” |

`/console/` 会跳转到外部 OIDC 登录页。本次审计没有使用真实账号、密码或生产登录态，因此没有把受保护业务页称为“真实后端数据验证”。

### 2.2 浏览器隔离渲染

使用仓库现有 `frontend/e2e/visual-alignment.spec.ts` 的文档注入和 API 隔离数据，在已安装的本机 Chrome 中渲染 React 页面。隔离数据只用于观察布局，不作为业务事实：

- `/portal`、`/portal/request` 在 `1280×800` 和 `390×844` 完成浏览器渲染；当前测试断言通过。
- `/console` 在 `1280×800`、`390×844` 完成页面截图与无障碍树采集，但现有测试随后因过期的“新建应用”定位器等待超时。
- `/console/operations/access-requests` 完成页面渲染，但现有测试仍查找旧文案“申请运营”，实际页面标题已是“待审批”。
- 移动端截图直接确认了本报告的页头挤压和表格压缩问题；门户测试虽然通过现有“可点击/无可见 overflow”断言，截图仍显示表头逐字换行，说明当前断言不足以判断可读性。

除以上页面外，其余页面的影响均明确标为“代码推断”。

## 3. 已确认问题

### EA-UI-01：移动端页头动作区把标题挤成逐字竖排，并裁掉主要操作

- **严重度**：高
- **置信度**：高
- **验证方式**：浏览器隔离渲染

**证据**

- `frontend/src/components/PageHeader.tsx:12-18` 始终使用单行 `flex`；标题区只有 `min-w-0`，动作区则是 `shrink-0` 且自身不换行。
- `frontend/src/pages/console/ConsoleAppList.tsx:177-192` 一次传入“刷新”“快速新建”“接入向导”三个不可收缩按钮。
- `frontend/src/styles/responsive.css:58-61` 在 `900px` 以下对主内容设置 `overflow-x: hidden`，超出部分不会提供横向滚动，而是直接裁掉。
- 在 `/console`、`390×844` 截图中，“应用列表”和描述被压缩为几乎一字一行；三个动作按钮完全不在可见区域。相同结构还出现在 `OnboardingPage`、`ConsoleTeamList`、`ApprovalTemplatesPage` 等多动作页头。

**复现**

1. 以控制台管理员身份打开 `/console`。
2. 将视口设为 `390×844`，保持中文界面。
3. 观察页头标题、描述和右侧三个操作按钮。

**影响**

- 手机用户无法从应用列表进入快速新建或接入向导。
- 标题与描述形成几十行的逐字竖排，破坏信息层级，并把表格推到首屏下方。
- `overflow-x: hidden` 掩盖了真实布局错误，自动化只检查“没有可见 overflow”时会得到假阴性。

**修复建议**

一次性修正共享 `PageHeader`：小视口改为纵向布局，动作区使用 `w-full flex-wrap` 或网格；按钮允许在窄屏占满可用宽度。到 `sm` 或 `md` 以上再恢复横向布局。删除主内容对布局错误的全局横向裁剪，横向滚动只交给明确需要滚动的局部容器。

### EA-UI-02：通用表格在手机上压缩所有列，而不是产生可用的横向滚动

- **严重度**：高
- **置信度**：高
- **验证方式**：浏览器隔离渲染

**证据**

- `frontend/src/components/ui/TablePrimitives.tsx:21-31` 虽然提供 `overflow-x-auto` 容器，但表格本身只使用共享 class。
- `frontend/src/components/ui/tableStyles.ts:5` 的表格根 class 只有 `min-w-full`，允许浏览器把全部列压进容器宽度。
- `frontend/src/components/ui/tableStyles.ts:11-14` 的表头和单元格没有最小宽度或防止中文逐字换行的约束。
- `/portal` 在 `390×844` 的浏览器截图中，7 列权限表被压进约 `350px` 内容宽度，“应用”“权限组”“展开授权”“过期时间”等表头逐字换行；`/console` 的 6 列应用表也出现同样压缩。
- `frontend/src/pages/portal/PortalPage.tsx:74-90`、`:137-162` 展示了门户表格的实际多列规模；这不是只有空态才会出现的结构。

**复现**

1. 打开 `/portal` 或 `/console`。
2. 将视口设为 `390×844`。
3. 查看表头：滚动容器没有获得比视口更宽的子内容，列宽缩到约一个汉字。

**影响**

- 表头和数据难以按行横向比较，日期、版本、权限范围等内容会形成高而窄的单元格。
- 表格骨架已经影响所有复用 `TableRoot` 的控制台和门户页面，属于共享组件级缺陷。
- 当前 Playwright 的文本 overflow 检查不会把“合法换行但不可读”判为失败。

**修复建议**

为通用表格建立明确的宽度策略：表格使用 `min-w-max` 或由页面传入语义化 `min-width`；表头默认 `whitespace-nowrap`；可换行内容在具体列显式开启。对手机主路径评估是否应把高频表格改为列表/卡片摘要，不能只依赖横向滚动。

### EA-UI-03：全局弱文本和多种状态色对比度不达标

- **严重度**：高
- **置信度**：高
- **验证方式**：源码颜色计算；真实/隔离页面目视交叉确认

**证据**

- `frontend/src/styles/index.css:15-29` 定义 `ink-faint=#94a3b8`、`amber=#d97706`、`evergreen=#059669`、`signal=#dc2626`。
- `frontend/src/styles/index.css:53-56` 又把这些颜色大量用于 `10.5px`、`11px`、`12px`、`13px` 小字号。
- 按 WCAG 相对亮度公式计算：

| 前景/背景 | 对比度 | 结果 |
| --- | ---: | --- |
| `ink-faint` / 白色 | `2.56:1` | 不满足普通文本 `4.5:1`，也低于大文本 `3:1` |
| `ink-faint` / `paper-deep` | `2.45:1` | 不满足 |
| `amber` / `amber 8%` 浅底 | `2.92:1` | 不满足 |
| `evergreen` / `evergreen 8%` 浅底 | `3.43:1` | 不满足普通文本 |
| `signal` / `signal 8%` 浅底 | `4.28:1` | 仍低于普通文本 `4.5:1` |

- `frontend/src/components/Badge.tsx:8-21` 把上述颜色用于 `text-micro` 状态标签。
- `frontend/src/components/StatusBanner.tsx:12-27` 把上述状态色用于提示标题。
- `frontend/src/components/Field.tsx:21`、`:61` 把 `ink-faint` 用于 placeholder 和字段帮助文案。
- 真实登录页和隔离渲染的申请页中，灰色说明及 placeholder 已肉眼呈现明显偏淡。

**影响**

- 低视力、弱对比敏感度用户难以读取 placeholder、帮助文案、时间、部门和状态标签。
- 状态色是跨页面 token，单点不达标会扩散到 Badge、Banner、Toast、表格元数据和导航标题。

**修复建议**

先定义通过 AA 的文本 token，再一次性替换消费方；背景浅色与前景深色必须作为成对 token 校验。把颜色对比度纳入自动测试，覆盖白底、`paper-deep`、各 tone 浅底和禁用态，不应在单个页面局部加深。

### EA-UI-04：用户搜索组合框的键盘模型和 ARIA 关系互相冲突

- **严重度**：高
- **置信度**：高
- **验证方式**：代码确认

**证据**

- `frontend/src/components/UserSelect.tsx:72-103` 把列表项渲染为可进入 Tab 顺序的 `<button role="option">`，但只有 `onPointerDown`，没有 `onClick`/键盘激活处理。
- `frontend/src/components/UserSelect.tsx:135-153`、`:235-260` 又实现了“焦点留在输入框、方向键改变活动项、Enter 选择”的 combobox 模式。
- `frontend/src/components/UserSelect.tsx:155-180`、`:271-298` 的输入框只有 `role="combobox"`、`aria-expanded` 和 `aria-autocomplete`，没有 `aria-controls`、`aria-activedescendant`；列表和选项也没有可引用的稳定 `id`。

**复现**

1. 在任一使用 `UserSearchInput` 或 `UserMultiSelect` 的接收人、审批人、成员表单输入搜索词。
2. 按 `Tab` 进入列表项，再按 `Enter` 或空格；按钮会产生 click，但没有选择处理。
3. 保持焦点在输入框并用方向键移动时，视觉高亮变化，但读屏无法通过 `aria-activedescendant` 得知当前活动项。

**影响**

- 键盘用户可能进入一个看似可激活、实际无效的选项按钮。
- 读屏用户不知道当前高亮的是哪个用户，难以可靠完成审批人、交接接收人等关键表单。

**修复建议**

选择一种完整模式并一次性实现：推荐焦点始终留在输入框，列表和选项提供稳定 `id`，输入框设置 `aria-controls` 与 `aria-activedescendant`，选项移出 Tab 顺序；鼠标使用 `onClick`/指针事件选择。补充方向键、Enter、Escape、Tab 和读屏属性测试。

### EA-UI-05：全局焦点环对比度不足，认证模板的焦点环更弱

- **严重度**：中
- **置信度**：高
- **验证方式**：源码颜色计算

**证据**

- `frontend/src/styles/index.css:137-139` 的全局焦点环是 `accent/50`；在白底合成后约为 `#93b1f5`，对比度仅 `2.13:1`，低于 WCAG 2.4.11 对焦点指示的 `3:1` 要求。
- `frontend/src/components/Button.tsx:15-16` 和多个组件重复使用同一 `focus-visible:outline-accent/50`。
- `src/easyauth/accounts/templates/accounts/local_admin/login.html:145-148` 使用 `rgba(15, 23, 42, 0.25)`，白底上的指示更弱。

**影响**

- 键盘用户在白色页面、白色卡片和浅色表格中难以定位当前焦点。
- 认证页是没有侧边导航辅助定位的入口页面，焦点不明显的影响更直接。

**修复建议**

定义一个不透明或足够深的统一焦点 token，保证与相邻背景至少 `3:1`；对按钮、输入、菜单项、深色代码块和状态浅底分别验证。认证模板与 React 共享同一焦点规格。

### EA-UI-06：ARIA tablist 缺少方向键和 roving tabindex

- **严重度**：中
- **置信度**：高
- **验证方式**：代码确认

**证据**

- `frontend/src/pages/console/ConsoleAppWorkspace.tsx:133-162` 使用 `role="tablist"`、`role="tab"`、`aria-selected`，但每个 tab 都保持默认 `tabIndex=0`，只处理鼠标/Enter click。
- `frontend/src/pages/portal/components/PortalApprovalsSection.tsx:232-273` 存在同样实现。
- 两处均没有 ArrowLeft、ArrowRight、Home、End 键处理，也没有在切换后把焦点移到新活动 tab。

**复现**

1. 用键盘聚焦工作台或审批页的 tab。
2. 按左右方向键，活动 tab 不变化。
3. 连续按 Tab，会逐一停留在每个 tab，而不是只保留一个 tab stop。

**影响**

组件宣告为 ARIA tabs，却不满足用户对 tabs 复合控件的标准键盘预期；tab 数较多的工作台尤其增加键盘遍历成本。

**修复建议**

建立共享 Tabs primitive：活动项 `tabIndex=0`，其余为 `-1`；实现方向键/Home/End 的循环移动与激活，并保持 `aria-controls`、`aria-labelledby` 一一对应。

### EA-UI-07：动态错误和状态提示默认不会被读屏播报

- **严重度**：中
- **置信度**：高
- **验证方式**：代码确认

**证据**

- `frontend/src/components/StatusBanner.tsx:20-30` 只渲染普通 `<div>`，没有 `role`、`aria-live` 或可由调用方指定的语义属性。
- 异步错误广泛使用该组件，例如 `frontend/src/pages/console/ConsoleAppList.tsx:195-196`、`frontend/src/pages/portal/PortalPage.tsx:103-107`、`frontend/src/pages/portal/components/AccessRequestForm.tsx:58-70`。
- 只有少数调用点额外包了 `role="status"`；组件本身的大多数错误路径没有播报语义。

**影响**

- 保存失败、加载失败、二次验证失败等内容在 DOM 中出现，但焦点没有移动时读屏用户可能完全不知道操作失败。
- 同一 `StatusBanner` 在不同页面有时被播报、有时静默，行为不一致。

**修复建议**

让组件显式接收语义用途，例如 `live="assertive|polite|off"` 或区分 `AlertBanner`/`StatusBanner`；错误默认 `role="alert"`，非紧急状态使用 `role="status"`，纯静态说明保持关闭。清理调用方零散包装，建立唯一口径。

### EA-UI-08：顶栏弹层宣告了菜单语义，却没有完整的复合控件键盘行为

- **严重度**：中
- **置信度**：高
- **验证方式**：代码确认

**证据**

- `frontend/src/components/shell/UserSummary.tsx:34-68` 的触发器使用 `aria-haspopup="menu"`，弹层使用 `role="menu"`/`role="menuitem"`，但打开后不把焦点移入菜单，也不处理 ArrowUp、ArrowDown、Home、End。
- `frontend/src/components/shell/Topbar.tsx:37-61` 只负责点击外部和 Escape 关闭；Escape 后没有显式恢复焦点。
- `frontend/src/components/shell/LanguageSwitcher.tsx:23-59` 和 `NotificationsButton.tsx:16-33` 设置 `aria-expanded`，却没有 `aria-controls`；通知弹层也没有 `role` 或标题关系。

**影响**

- 读屏用户听到“菜单”，但实际只能用 Tab 逐项浏览，方向键无效。
- 通知按钮的展开状态与新增内容没有程序化关系，读屏难以确定弹层出现位置和内容。

**修复建议**

使用共享 Popover/Menu primitive。真正的菜单按 ARIA Menu 模式实现焦点进入、方向键、Escape 和焦点归还；通知内容若不是菜单，应使用带标题关系的非模态 popover，而不是伪装成 menu。

### EA-UI-09：多个高频图标按钮的触控目标只有 12–15px

- **严重度**：中
- **置信度**：高
- **验证方式**：代码确认

**证据**

- `frontend/src/components/InfoTip.tsx:11-18` 的按钮没有 padding 或最小尺寸，唯一内容是 `13px` 图标。
- `frontend/src/components/UserSelect.tsx:313-323` 的 chip 删除按钮唯一内容是 `12px` 图标。
- `frontend/src/components/ui/Toast.tsx:261-268` 的关闭按钮唯一内容是 `15px` 图标。
- 三者的元素自身尺寸都小于 WCAG 2.5.8 的 `24×24 CSS px` 基准，代码也没有提供显式扩大命中区的尺寸约束；是否依靠目标间距满足例外只能随页面排列变化，不能作为组件契约保证。

**影响**

- 触屏和手部精细动作受限用户容易误触或无法稳定点击。
- 用户 chip 删除是表单编辑主操作，Toast 关闭和帮助提示也会在狭窄移动端高频出现。

**修复建议**

统一图标按钮 primitive，至少提供 `24×24px` 命中区；移动优先场景建议 `32×32px`。视觉图标可以保持 12–16px，但通过 padding 扩大点击区域。

### EA-UI-10：工作账号导航链接被错误宣告为按钮

- **严重度**：中
- **置信度**：高
- **验证方式**：真实页面浏览器验证

**证据**

- `src/easyauth/accounts/templates/accounts/local_admin/login.html:250` 使用 `<a href="..." role="button">`。
- 真实 `/auth/local/` 页面无障碍树把“使用工作账号登录”宣告为按钮。
- 元素仍是链接：Enter 会导航，空格不会按按钮惯例激活。

**影响**

- 读屏用户得到错误角色提示，并可能按空格尝试激活而无响应。
- 该操作本质是导航到 OIDC 登录流程，没有改写为按钮角色的必要。

**修复建议**

直接删除 `role="button"`，保留按钮外观的链接语义；如果未来改为表单动作，则使用真正的 `<button>` 并实现相应提交行为。

### EA-UI-11：固定宽度 tooltip 在手机边缘会被主内容裁掉

- **严重度**：中
- **置信度**：中
- **验证方式**：代码推断

**证据**

- `frontend/src/components/InfoTip.tsx:19-24` 把 tooltip 固定为 `w-64`，并始终以图标中心 `left-1/2 -translate-x-1/2` 定位，没有视口碰撞检测。
- `frontend/src/pages/console/onboarding/AppOnboardingWizard.tsx:996-1001` 在窄屏表单标签旁使用该组件；图标靠近左侧时，`256px` tooltip 的左半可能超出内容边界。
- `frontend/src/styles/responsive.css:58-61` 又在移动端隐藏主内容横向 overflow。

**复现视口/页面**

在 `/console/apps/new` 的验证步骤、`320px` 或 `390px` 视口，用键盘聚焦“用户 ID”旁的提示图标。

**影响**

tooltip 的开头或结尾可能不可见，且没有局部滚动方式取回被裁内容。

**修复建议**

使用支持 flip/shift 的浮层定位，最大宽度改为 `min(16rem, calc(100vw - 2rem))`；在窄屏优先左对齐标签或改为行内帮助文案。不要依赖页面级 `overflow-x:hidden` 掩盖浮层越界。

### EA-UI-12：认证与错误模板持续产生 1px 垂直滚动，且视觉 token 已与 React 分叉

- **严重度**：低
- **置信度**：高
- **验证方式**：真实页面浏览器验证与代码确认

**证据**

- `/auth/local/` 在 `1280×800` 时文档高度为 `801px`，在 `390×844` 时为 `845px`。
- `src/easyauth/accounts/templates/accounts/local_admin/login.html:41-54` 的 topbar 内容高 `56px`，外加 `1px` 下边框；`:93-100` 的主区仍按 `100vh - 56px` 计算，因此总高度多 `1px`。
- 相同公式出现在 `change_password.html:98`、`verify.html:99`、`403.html:33`、`404.html:96`。
- `login.html:9-23`、`security.html:9-24`、`403.html:9-18` 各自复制 `--bg`、`--surface`、`--faint`、`--brand` 等 token；例如登录/安全页 `brand=#0f172a`，403 页 `brand=#2563eb`，React 则在 `frontend/src/styles/index.css:11-29` 使用另一套 RGB token。

**影响**

- 页面在内容完全放得下时仍显示无意义的纵向滚动。
- 认证、错误与 React 页面在品牌色、圆角、焦点和弱文本上继续漂移，修复对比度时需要同步多份内联 CSS。

**修复建议**

将顶栏实际外框高度纳入布局，或用单个 `min-height:100dvh` 的网格壳分配 `56px auto`；同时抽取认证/错误页共享样式并映射到同一视觉 token，不保留多套独立色值。

## 4. 现有视觉回归的覆盖缺口

这部分是验证局限，不计入上述 12 项 UI 问题：

- `frontend/e2e/visual-alignment.spec.ts:3-8` 仍把运营页标记写成“申请运营”，当前文案已是 `frontend/src/i18n/messages.ts:66-67` 的“运营/待审批”。
- `frontend/e2e/visual-alignment.spec.ts:35-42` 等待“新建应用”，当前应用列表按钮是 `messages.ts:118-119` 的“快速新建/接入向导”。
- `frontend/e2e/visual-alignment.spec.ts:84-105` 的 API glob 没有覆盖页面实际携带分页查询参数的请求，本次隔离渲染中控制台列表因此落入 404/空骨架状态。
- `visual-alignment.spec.ts:200-221` 只把 `overflow-x:visible` 且 `scrollWidth` 超宽判为问题；逐字换行、标题被压成极窄列、按钮被父级裁掉都可能通过。
- 默认 Playwright Chromium 缓存缺失；使用本机 Chrome 显式执行后才完成本次浏览器验证。环境门禁应明确准备浏览器，而不是让 8 个用例都在启动阶段失败。

建议把视觉门禁改为：

1. 关键页头检查动作按钮可见、标题区宽度不低于合理阈值。
2. 多列表格检查表格 `scrollWidth > clientWidth` 或移动卡片结构，而不是只检查文本是否 overflow。
3. 增加 `320px`、`390px`、`768px`、`900px` 临界视口。
4. 增加键盘路径、焦点可见性、axe/WCAG 颜色对比和 ARIA composite widget 测试。

## 5. 建议修复顺序

1. 先修 `PageHeader` 与通用表格宽度策略，并覆盖所有消费页面。
2. 调整全局颜色和焦点 token，以组件级对比度测试锁定。
3. 重写 `UserSelect` 的 combobox 模式和共享 Tabs/Menu/Popover 键盘行为。
4. 统一动态 Banner 语义和图标按钮命中区。
5. 收敛认证/错误模板样式，修正 1px 高度计算。
6. 最后更新视觉回归夹具和断言，使上述缺陷能在 `320/390/768/900px` 自动失败。
