# 动效与交互状态审计

审计日期：2026-07-27
审计范围：`frontend/src` 中的路由与页面切换、弹窗和弹出层、展开收起、加载状态、列表变更、操作反馈、悬停与焦点反馈、`prefers-reduced-motion` 处理。
审计原则：只评价帮助用户理解状态变化、空间关系和操作结果的功能性动效，不要求装饰性动画。

## 结论摘要

未发现需要判为“高”严重度的问题。当前实现已有较好的基础能力：页面路径变化有入场动效，表格普遍使用统一骨架屏，按钮有按压/悬停/焦点反馈，权限选择树对展开与收起都保留了完整的进入/退出生命周期，并且全局提供了 `prefers-reduced-motion` 降级。

仍有 4 项中等、2 项低严重度缺口。优先级最高的是：查询参数驱动的长页面切换绕过路由动效、所有模态弹窗瞬时出现/消失、破坏性列表操作缺少行级过渡状态，以及减弱动效模式下按钮加载指示退化为缺少语义的静止圆环。

## 验证口径与限制

- **代码推断**：已逐项检查 React 条件渲染、状态更新、CSS 动画、过渡类和媒体查询。下述每项发现均给出精确文件与行号。
- **运行时验证**：本轮未能完成可信的页面交互实测。`127.0.0.1:8000` 当前由无关的 Uvicorn 容器服务响应，访问 EasyAuth 路径均为 `404`；已连接的 Chrome 对新开的 `localhost` 与 `127.0.0.1` 页面返回客户端拦截。因此，不能把源码生命周期推断表述为浏览器实测事实。
- 本报告不以“看起来更活泼”为目标；若状态本身已经清楚，未列为缺陷。

## 发现清单

### MOT-01：查询参数驱动的工作区标签页与接入向导步骤绕过页面入场过渡

- 严重度：**中**
- 置信度：**高**
- 验证类型：**代码推断，未完成运行时验证**
- 受影响界面：应用工作区 12 个标签页；新建应用/接入向导各步骤。
- 证据：
  - `frontend/src/components/AppShell.tsx:19-31`：路由过渡容器只以 `location.pathname` 作为 `key`，未纳入 `location.search`。
  - `frontend/src/styles/layout-shell.css:406-420`：`.route-transition` 只有在容器重新挂载时才会执行 `route-enter`。
  - `frontend/src/pages/console/ConsoleAppWorkspace.tsx:133-175`：标签页通过 `setSearchParams({ tab })` 切换；指示条会移动，但标签面板直接条件替换。
  - `frontend/src/pages/console/onboarding/AppOnboardingWizard.tsx:45-65`、`104-144`：向导步骤写入 `?step=`，步骤面板直接卸载/挂载。
- 用户影响：指示条或步骤状态发生变化时，大块、结构差异明显的内容会瞬时替换。用户尤其在前进/后退向导时难以确认内容变化方向，也容易把新面板误认作原面板局部刷新。
- 实现方向：
  - 不要简单把整个 `location.search` 加入 `AppShell` 的 `key`，否则筛选、分页、搜索等普通查询参数也会反复触发整页动效。
  - 在 `ConsoleAppWorkspace` 和 `AppOnboardingWizard` 内为语义化的 `activeTab` / `activeStep` 增加局部过渡容器；优先采用 120–180ms 的淡入配合 4–6px 位移，并依据前后索引确定方向。
  - 切换期间保持容器最小高度或使用短暂的尺寸过渡，避免长短面板之间发生突兀布局跳变。
  - 在 `prefers-reduced-motion: reduce` 下直接替换内容，保留活动标签、`aria-current` 和焦点管理等非动效信号。

### MOT-02：模态弹窗没有进入或退出生命周期，顶栏弹出层只有进入动画

- 严重度：**中**
- 置信度：**高**
- 验证类型：**代码推断，未完成运行时验证**
- 受影响界面：所有 `Dialog` / `ConfirmDialog`，包括审批决定、删除确认、凭据密钥、双因素认证和五步交接向导；顶栏通知、语言、用户菜单。
- 证据：
  - `frontend/src/components/Dialog.tsx:45-88`：遮罩与面板直接通过 Portal 渲染，遮罩和面板类中均无进入/退出动画。
  - `frontend/src/pages/console/ConsoleAppList.tsx:250-267`：创建和删除确认弹窗以布尔条件直接挂载/卸载，代表全项目常见调用方式。
  - `frontend/src/styles/layout-shell.css:167-183`：`.topbar-popover` 只有 `topbar-popover-enter`。
  - `frontend/src/components/shell/NotificationsButton.tsx:26-34`、`LanguageSwitcher.tsx:33-60`、`UserSummary.tsx:55-69`：关闭时立即从 DOM 移除，不存在退出阶段。
- 用户影响：模态弹窗会在整个视口上瞬时覆盖或消失，缺少“从触发点进入临时任务、再返回原上下文”的空间提示；提交成功后弹窗和背景内容同步突变时尤为明显。弹出菜单的进入与退出节奏也不对称。
- 实现方向：
  - 在公共 `Dialog` 内集中实现存在状态，避免每个调用方自建计时器。遮罩仅做 120–160ms 透明度变化，面板仅做透明度和 4–8px 位移；不建议缩放大型表单。
  - 关闭时先进入 `closing`，动画结束后再真正卸载；关闭期间立即禁用交互。滚动锁可保持到卸载，焦点应在退出结束后返还触发元素。
  - 顶栏菜单和其他轻量弹出层采用相同的短退出阶段；若统一存在管理成本过高，至少让关闭反馈通过触发按钮的 `aria-expanded`、选中态和焦点返还保持清楚。
  - `prefers-reduced-motion: reduce` 下跳过等待并立即卸载，避免“视觉已经静止但逻辑仍等待动画时长”。

### MOT-03：破坏性列表操作缺少行级“处理中 → 已移除”状态，弹窗关闭与数据刷新脱节

- 严重度：**中**
- 置信度：**高**
- 验证类型：**代码推断，未完成运行时验证**
- 受影响界面：应用列表删除、团队列表删除、门户审批待办处理，以及采用相同“关闭弹窗后失效查询”模式的列表。
- 证据：
  - `frontend/src/pages/console/ConsoleAppList.tsx:71-79`：删除成功后先关闭确认弹窗，再仅调用 `invalidateQueries`。
  - `frontend/src/pages/console/ConsoleAppList.tsx:224-238`：普通表格行没有退出状态或布局过渡；行级样式只提供颜色悬停，见 `frontend/src/components/ui/tableStyles.ts:5-14`。
  - `frontend/src/pages/console/ConsoleTeamList.tsx:48-55`、`176-189`：删除采用相同刷新模式，虽然有成功 toast，但行仍没有处理中或退出状态。
  - `frontend/src/pages/portal/components/PortalApprovalsSection.tsx:152-177`、`299-314`：审批成功后关闭弹窗并失效列表查询，待办行由新响应直接消失。
- 用户影响：React Query 背景刷新期间旧行可能短暂保留，之后又瞬时消失；用户会先看到弹窗关闭，却不能立即确认具体哪一行已完成。相邻行突然上移时，视线容易落到错误对象。应用删除还没有成功 toast，反馈最弱。
- 实现方向：
  - 把目标行标记为 `pending`，保留稳定高度，显示文本状态或小型进度标记并禁用该行操作。
  - 服务端确认成功后先更新权威查询缓存，再对被移除行执行短暂透明度/高度退出；失败则恢复该行并保留明确错误反馈。
  - 成功反馈应包含被操作对象的名称或标识，不能只依赖“行不见了”。
  - 减弱动效模式下可以立即移除行，但仍必须保留成功提示、行级处理中语义和焦点落点；删除按钮消失后把焦点移动到同表格的合理位置或结果提示。

### MOT-04：减弱动效模式会把按钮加载旋转器冻结，但组件没有非动效的加载语义

- 严重度：**中**
- 置信度：**高**
- 验证类型：**代码推断，未完成运行时验证**
- 受影响界面：所有使用公共 `Button loading` 的提交、重试、保存、删除、审批和执行操作。
- 证据：
  - `frontend/src/components/Button.tsx:36-64`：加载时只插入 `aria-hidden="true"` 的旋转圆环并禁用按钮；按钮没有 `aria-busy`，可见文案通常保持不变。
  - `frontend/src/styles/index.css:188-196`：`prefers-reduced-motion: reduce` 把所有动画持续时间压缩为 `0.01ms` 且只执行一次，`animate-spin` 因此成为静止圆环。
- 用户影响：普通模式可通过持续旋转理解请求仍在执行；减弱动效用户只看到一个静止、对读屏隐藏的圆环和降低透明度的禁用按钮，难以区分“正在处理”与“不可用”。耗时审批、导入、交接执行场景影响更明显。
- 实现方向：
  - `loading` 时给按钮增加 `aria-busy="true"`，并允许调用方提供 `loadingLabel`，例如“正在保存”“正在执行”；至少提供视觉隐藏的状态文本。
  - 不要只靠运动表达进度。减弱动效模式可保留静态等待图标，但必须有文本、`aria-live` 状态或页面内任务状态。
  - 对长任务优先使用靠近结果区域的 `role="status"`，而不是反复播报按钮本身。

### MOT-05：Toast 瞬时加入、移除并重排，短时反馈的来源和去向不够清楚

- 严重度：**低**
- 置信度：**高**
- 验证类型：**代码推断，未完成运行时验证**
- 受影响界面：全局保存、删除、测试连接、凭据、Webhook 等 toast 反馈。
- 证据：
  - `frontend/src/components/ui/Toast.tsx:77-83`：关闭直接从数组过滤。
  - `frontend/src/components/ui/Toast.tsx:126-135`：新增直接追加到数组。
  - `frontend/src/components/ui/Toast.tsx:209-225`、`246-270`：toast 列表和卡片没有进入、退出或布局过渡类。
- 用户影响：多个 toast 连续出现或一个自动关闭时，整个堆栈会瞬时跳位；用户可能错过刚完成的操作反馈，或把剩余 toast 与错误操作关联。单条 toast 的影响较低，因此不建议引入复杂动画库。
- 实现方向：
  - 使用 120–180ms 的淡入/轻微纵向位移和退出，保留关闭中的条目直到退出结束；相邻项仅做短布局过渡。
  - 错误 toast 继续保持持久化，现有悬停/聚焦暂停计时逻辑应保留。
  - 减弱动效模式下立即出现/移除，但 `aria-live`、错误的 `role="alert"` 和持久化策略保持不变。

### MOT-06：展开/收起动效只在权限树完整实现，交接长列表仍会瞬时跳变

- 严重度：**低**
- 置信度：**高**
- 验证类型：**代码推断，未完成运行时验证**
- 受影响界面：交接向导的“按应用分别设置”；交接任务应用卡片的详情。
- 证据：
  - `frontend/src/pages/console/lifecycle/HandoverWizard.tsx:382-386`：`perAppOpen` 直接条件渲染可能较长的应用列表，没有 `aria-expanded` 或过渡阶段。
  - `frontend/src/pages/console/lifecycle/HandoverTaskDetail.tsx:331-346`：错误详情使用原生 `<details>`，内容按浏览器默认行为瞬时展开/收起。
  - 对比正向实现：`frontend/src/pages/portal/components/PermissionSelector.tsx:734-831` 为展开与收起都维护存在阶段和减弱动效时长；对应 CSS 在 `frontend/src/styles/features/permission-selector.css:226-250`、`401-435`。
- 用户影响：长应用列表展开时会把后续按钮突然推离原位置；错误详情反复查看时缺少内容边界变化提示。该问题局限在少数区域，且原生语义仍可用，所以定为低严重度。
- 实现方向：
  - “按应用分别设置”按钮补充 `aria-expanded` 和关联容器标识；内容使用短透明度与高度/网格轨道过渡，或至少在展开后把焦点/滚动位置保持在标题附近。
  - 原生 `<details>` 可保留；如增加动画，应由公共折叠组件处理，并保留 `<summary>` 语义，避免复制权限树的复杂计时状态。
  - 减弱动效模式下直接展开/收起。

## 已确认的良好实现

以下项目不应在修复时被回退：

- `frontend/src/components/AppShell.tsx:19-31` 与 `frontend/src/styles/layout-shell.css:406-420` 已为真正的 `pathname` 页面导航提供统一入场动效。
- `frontend/src/components/ui/TablePrimitives.tsx:91-111` 与 `frontend/src/styles/index.css:168-186` 提供统一表格骨架和加载闪烁；减弱动效下骨架仍以静态形状保留加载占位。
- `frontend/src/styles/index.css:137-140` 提供全局 `:focus-visible`，按钮、导航、工具栏和提示组件还补充了悬停/按压反馈。
- `frontend/src/styles/index.css:188-205` 已建立全局 `prefers-reduced-motion` 基线，不需要另起一套用户偏好系统。
- `frontend/src/pages/portal/components/PermissionSelector.tsx:734-831` 与 `frontend/src/styles/features/permission-selector.css:226-250` 对树形行进入、退出、快速反向操作和减弱动效均有明确处理，是本项目可复用的功能性动效参考。
- `frontend/src/components/ui/Toast.tsx:54-60`、`98-123`、`140-160` 已正确区分反馈停留时间，并在悬停、聚焦和页面隐藏时暂停自动关闭。

## 建议实施顺序

1. 先修复 `Button loading` 的非动效语义和减弱动效状态；改动集中、收益覆盖全站。
2. 在公共 `Dialog` 建立完整存在生命周期，并同步验证焦点返还、滚动锁和连续打开场景。
3. 为应用工作区标签与两个向导步骤增加局部、语义化的内容切换，不扩大到所有查询参数。
4. 建立表格行 `pending/removing` 约定，先覆盖应用删除、团队删除和门户审批。
5. 最后补充 toast 和少数折叠区域的轻量过渡。

## 后续运行时验收要点

- 普通动效与 `prefers-reduced-motion: reduce` 各跑一遍。
- 快速连续开关弹窗、菜单和折叠区域，确认没有残留遮罩、错误焦点、重复滚动锁或旧计时器。
- 在网络延迟下验证删除/审批：确认弹窗关闭、行级处理中、缓存刷新、成功提示和行退出顺序一致。
- 连续触发 3 条以上 toast，检查自动关闭时剩余卡片不会突跳或被误读。
- 标签页和向导前进/后退时检查内容方向、容器高度、键盘焦点与滚动位置；减弱动效模式下不得保留无意义等待。
