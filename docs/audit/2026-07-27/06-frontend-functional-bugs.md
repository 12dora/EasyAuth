# 前端功能缺陷审计

审计日期：2026-07-27

## 审计范围与口径

本次审计覆盖 `frontend/src` 中的 Console、Portal、工作区、生命周期、国际化、通用组件和 API 客户端，并将关键交互与 Django API 的权限、校验及状态约束逐项对照。

“确认缺陷”指仅依据当前代码即可构造稳定的用户可见错误；“条件性风险”指需要特定浏览器、异常响应或边界数据才能触发，但代码中已经存在明确的失效路径。严重性分为中、低；本轮未发现能够直接造成系统整体不可用、权限绕过或不可逆数据损坏的高严重性前端缺陷。

## 结论摘要

| 分类 | 中严重性 | 低严重性 | 合计 |
| --- | ---: | ---: | ---: |
| 确认缺陷 | 12 | 3 | 15 |
| 条件性风险 | 6 | 1 | 7 |

最需要优先处理的是前后端能力模型不一致：普通 Console 用户、应用所有者和应用开发者会看到后端明确禁止的入口或写操作。其次是生命周期流程可以在前端生成必然被后端拒绝的请求，以及分页、并发请求和停用状态导致的可恢复性问题。

## 一、确认缺陷

### C-01 非超级管理员会看到并进入仅超级管理员可用的 Console 页面

- 严重性：中
- 置信度：高
- 证据：
  - `frontend/src/components/shell/Sidebar.tsx:22-49` 无条件展示团队、人员、交接、入职、审批模板和运维入口。
  - `frontend/src/App.tsx:85-95` 除“新建应用”外，其他 Console 路由都没有 `isSuperuser` 路由守卫。
  - 后端团队、人员、审批和运维 API 均执行超级管理员权限检查。
- 用户可见复现：以有权访问 Console、但不是超级管理员的应用所有者登录，点击“团队”“人员”“审批模板”或“运维”入口；页面可以进入，但核心查询返回 `403`，最终呈现加载失败或不可用页面。
- 根因：侧边栏和路由只判断“能否访问 Console”，没有根据页面级能力生成导航和路由。
- 直接修复：由服务端返回统一的 Console 能力集合；侧边栏、路由和页面操作全部消费同一个能力模型。对无权页面隐藏入口，并在深链访问时渲染明确的无权限页。

### C-02 应用列表向普通 Console 用户暴露超级管理员写操作，且部分失败无反馈

- 严重性：中
- 置信度：高
- 证据：
  - `frontend/src/pages/console/ConsoleAppList.tsx:117-160` 对每一行无条件展示启停、删除和继续接入操作。
  - `frontend/src/pages/console/ConsoleAppList.tsx:181-191` 无条件展示快速创建和接入向导按钮。
  - `frontend/src/pages/console/ConsoleAppList.tsx:63-80` 的启停和删除 mutation 没有 `onError` 或错误提示。
  - `src/easyauth/admin_console/apps_api.py:201-213`、`src/easyauth/admin_console/apps_api.py:309-321`、`src/easyauth/admin_console/apps_api.py:374-390` 将创建、删除和启停限制为超级管理员。
- 用户可见复现：普通应用所有者在应用列表点击“停用”或“删除”；后端返回 `403`，按钮短暂结束加载后页面不提示原因。点击“快速创建”也会进入最终无法成功的流程。
- 根因：列表没有接收或使用当前用户的写权限；mutation 也没有统一错误呈现。
- 直接修复：按服务端能力只向超级管理员渲染创建、启停、删除和接入入口；所有写 mutation 统一接入可见错误提示，并补充普通用户权限用例。

### C-03 应用工作区多处使用了错误的写权限粒度

- 严重性：中
- 置信度：高
- 证据：
  - `frontend/src/pages/console/ConsoleAppWorkspace.tsx:162-174` 只有凭据和集成页签接收 `app.can_manage`；目录、矩阵、托管范围、规则、清单、Webhook 和连接器页签没有能力参数。
  - `frontend/src/pages/console/workspace/tabs/OverviewTab.tsx:50-75` 以 `app.can_manage` 决定成员新增和停用操作。
  - `frontend/src/pages/console/workspace/tabs/ConnectorTab.tsx:363-390`、`frontend/src/pages/console/workspace/tabs/ConnectorTab.tsx:490-515` 无条件显示协调、删除、保存和测试操作。
  - `src/easyauth/admin_console/catalog_write_common.py:53-68` 要求所有者级写权限；`src/easyauth/admin_console/memberships_api.py:171-191` 和 `src/easyauth/admin_console/connectors_api.py:139-156` 则要求超级管理员。
- 用户可见复现：
  1. 以被委派的应用开发者进入目录、矩阵或规则页签，可以看到并触发写按钮，但请求返回 `403`。
  2. 以普通应用所有者进入“概览”，可以看到成员新增或停用操作，但成员 API 返回 `403`。
  3. 以普通应用所有者进入“连接器”，可以看到保存、测试、协调和删除操作，但相关 API 返回 `403`。
- 根因：前端把“可以进入工作区”“可以管理应用”和“超级管理员”混成了一个或没有判断，未映射后端的细粒度能力。
- 直接修复：在应用详情载荷中一次性返回目录写入、成员管理、连接器管理等明确能力；各页签只依赖对应能力，不再从角色名称或 `can_manage` 推断。

### C-04 Portal 的访问申请列表缺少撤回操作

- 严重性：中
- 置信度：高
- 证据：
  - `frontend/src/pages/portal/PortalPage.tsx:137-162` 的申请列表只有展示列，没有任何行操作。
  - `src/easyauth/portal/api.py:125-145` 已实现 `POST /portal/api/v1/me/access-requests/{id}/withdraw`。
- 用户可见复现：用户提交一条仍可撤回的访问申请后进入“我的申请”；只能查看状态，无法在产品界面撤回，只能直接调用 API。
- 根因：后端已提供完整能力，但 Portal 列表没有接入。
- 直接修复：根据后端返回的状态或显式 `can_withdraw` 能力渲染“撤回”按钮，加入确认对话框、进行中禁用、成功刷新和失败提示。

### C-05 交接向导允许提交既无接收人也不释放到池的任务

- 严重性：中
- 置信度：高
- 证据：
  - `frontend/src/pages/console/lifecycle/HandoverWizard.tsx:305-311` 的下一步禁用条件没有校验接收策略。
  - `frontend/src/pages/console/lifecycle/HandoverWizard.tsx:256-278` 在没有接收人时仍允许继续。
  - `frontend/src/pages/console/lifecycle/HandoverWizard.tsx:125-149` 会序列化 `to_user_id: null` 且 `release_to_pool: false`。
  - `src/easyauth/lifecycle/services.py:998-1008` 要求“指定接收人”和“释放到池”严格二选一。
- 用户可见复现：打开交接向导，选择来源用户和应用，不选择接收人，也不启用释放到池，然后继续并提交；前端允许走完整流程，后端最终拒绝。
- 根因：前端步骤校验没有表达后端的异或业务不变量。
- 直接修复：把接收策略建模为必选枚举，并在离开步骤和最终提交前共同校验；表单状态只允许生成两种合法载荷之一。

### C-06 交接任务列表对不可删除的任务也展示删除操作

- 严重性：中
- 置信度：高
- 证据：
  - `frontend/src/pages/console/lifecycle/HandoverTaskList.tsx:237-253` 为每条任务渲染删除按钮，没有状态限制。
  - `src/easyauth/lifecycle/services.py:575-581` 只允许删除已取消任务。
- 用户可见复现：对待处理、执行中或已完成任务点击“删除”并确认；后端稳定返回 `409`。
- 根因：列表操作没有使用任务状态机决定允许的动作。
- 直接修复：由后端返回 `allowed_actions`，前端只渲染允许的动作；至少应立即限定为 `cancelled` 状态才展示删除，并保持 `409` 的明确错误信息。

### C-07 在权限矩阵中停用授权组后，无法再从同一界面启用

- 严重性：中
- 置信度：高
- 证据：
  - `frontend/src/pages/console/workspace/tabs/MatrixTab.tsx:321-328` 编辑器允许切换 `is_active`。
  - 保存后该页签会失效并刷新授权组列表。
  - `src/easyauth/admin_console/permission_catalog_data.py:97-101` 的列表只返回活动授权组。
- 用户可见复现：在权限矩阵中编辑一个授权组，点击“停用”并保存；刷新后该组从列表消失，页面没有查看停用项或重新启用的入口。
- 根因：同一资源的“停用”写能力与“仅列活动项”的读模型不闭环。
- 直接修复：管理端列表必须支持显式包含停用项及状态筛选；默认展示范围可以收窄，但停用资源必须有可发现、可恢复的管理路径。

### C-08 入职模板只能选择前 100 个应用

- 严重性：中
- 置信度：高
- 证据：
  - `frontend/src/pages/console/lifecycle/OnboardingPage.tsx:424-428` 固定请求 `/console/api/v1/apps?page=1&page_size=100`。
  - 选择器没有继续分页、搜索或按标识精确加载的逻辑。
- 用户可见复现：系统存在 101 个以上应用时，尝试给入职模板配置排序落在第 101 位之后的应用；该应用永远不会出现在选择器中。
- 根因：把分页 API 的首 100 条结果误当成了完整应用字典。
- 直接修复：使用带服务端搜索的异步应用选择器，或遍历分页并明确加载完整结果；不得通过继续提高固定上限掩盖问题。

### C-09 权限查询测试允许并发提交，旧响应可覆盖新结果

- 严重性：中
- 置信度：高
- 证据：
  - `frontend/src/pages/console/workspace/tabs/QueryTestTab.tsx:34-49` mutation 从可变的当前输入闭包读取参数，并在任意成功响应中直接覆盖 `result`、清空 token。
  - `frontend/src/pages/console/workspace/tabs/QueryTestTab.tsx:92-94` 请求进行中时未禁用按钮。
- 用户可见复现：以用户 A 发起一次慢查询，立即改为用户 B 再发起快速查询；B 的结果先显示，随后 A 的旧响应到达并覆盖页面，页面却仍保留 B 的用户输入上下文。
- 根因：并发 mutation 没有请求身份或“仅最新响应生效”约束。
- 直接修复：将提交时的输入作为 mutation 变量快照；请求中禁用重复提交，或用递增请求序号/取消机制保证只有最新请求能更新结果。

### C-10 英文界面优先展示后端中文状态文本

- 严重性：中
- 置信度：高
- 证据：
  - `frontend/src/pages/portal/PortalPage.tsx:143-145` 和 `frontend/src/pages/portal/components/PortalApprovalsSection.tsx:388-390` 优先使用后端 `status_label`。
  - `src/easyauth/portal/status_text.py:17-24` 的状态文本固定为中文。
  - 前端已有按当前 locale 翻译状态码的实现。
- 用户可见复现：把界面语言切换为英文，打开“我的申请”或审批列表；标题和按钮为英文，但状态徽标仍显示中文。
- 根因：展示层优先信任不可本地化的服务端中文标签，而不是稳定状态码。
- 直接修复：API 只返回状态码，前端统一按当前 locale 翻译；若服务端确需返回描述，应返回结构化的翻译键，而不是中文正文。

### C-11 两步验证状态请求失败时，安全设置卡片被静默隐藏

- 严重性：中
- 置信度：高
- 证据：
  - `frontend/src/pages/console/TwoFactorSection.tsx:42-53` 把“未加载”“请求失败”和“不支持”都折叠为 `status` 不存在，并直接 `return null`。
- 用户可见复现：让两步验证状态接口返回 `500` 或网络错误后打开 Console 设置；安全设置区域直接消失，没有失败提示和重试入口，用户会误以为系统不支持两步验证。
- 根因：组件只根据 `data` 判定渲染，没有区分查询生命周期和业务上的 `supported: false`。
- 直接修复：分别渲染加载、错误、明确不支持和正常状态；错误状态必须保留卡片位置、错误原因和重试操作。

### C-12 删除最后一页唯一应用后，列表会停留在越界页

- 严重性：中
- 置信度：高
- 证据：
  - `frontend/src/pages/console/ConsoleAppList.tsx:42-47` 将当前页写入请求。
  - `frontend/src/pages/console/ConsoleAppList.tsx:71-79` 删除成功后只刷新查询，没有修正当前页。
  - `frontend/src/pages/console/ConsoleAppList.tsx:165-173` 使用服务端分页，但没有在 `total_pages` 变小时收敛 `pageIndex`。
- 用户可见复现：进入只有一条记录的最后一页并删除该应用；刷新后仍请求原页码，列表为空，页码可能显示为“第 2 页/共 1 页”，直到用户手动返回上一页。
- 根因：删除造成总页数变化时，分页状态与服务端结果没有重新协调。
- 直接修复：删除成功后根据删除前行数决定是否回退一页；同时对每次响应执行页码范围校验，越界时更新路由/状态并重新请求合法页。

### C-13 复制失败时仍显示“已复制”

- 严重性：低
- 置信度：高
- 证据：`frontend/src/components/CodeBlock.tsx:19-23` 不等待 `navigator.clipboard.writeText`，即使 API 不存在或 Promise 拒绝也立即设置成功状态。
- 用户可见复现：在剪贴板权限被拒绝或 Clipboard API 不可用的环境点击复制；按钮显示“已复制”，实际剪贴板内容没有变化。
- 根因：把异步操作的发起误当成成功完成。
- 直接修复：等待 `writeText` 成功后再显示成功；失败时显示明确错误，并避免产生未处理的 Promise 拒绝。

### C-14 审批意见缺少前端 2000 字符上限

- 严重性：低
- 置信度：高
- 证据：
  - `frontend/src/components/ApprovalDecisionDialog.tsx:44-51`、`frontend/src/components/ApprovalDecisionDialog.tsx:85-94` 没有 `maxLength`、字数提示或提交前校验。
  - `src/easyauth/portal/approvals_api.py:52-59` 拒绝超过 2000 字符的意见。
- 用户可见复现：在审批对话框输入超过 2000 字符并提交；用户直到请求结束后才收到后端校验错误，且界面事前没有任何限制提示。
- 根因：服务端字段约束没有同步到表单契约。
- 直接修复：表单与 API 共享同一最大长度常量或 schema；输入框设置上限并展示剩余字数，提交前快速失败。

### C-15 未知运维分区会静默显示访问申请内容

- 严重性：低
- 置信度：高
- 证据：
  - `frontend/src/App.tsx:92-94` 接受任意 `/console/operations/:section`。
  - `frontend/src/pages/console/OperationsPage.tsx:40-45` 定义合法分区。
  - `frontend/src/pages/console/OperationsPage.tsx:65-71` 对未知分区静默回退到访问申请配置，但保留错误 URL。
- 用户可见复现：访问 `/console/operations/not-real`；地址栏仍是不存在的分区，页面却显示访问申请，用户无法判断 URL 错误，书签和分享链接也继续传播坏地址。
- 根因：动态路由缺少合法枚举校验，并以无提示默认值掩盖错误。
- 直接修复：未知分区应重定向到规范 URL 或显示 404；不要在保留无效 URL 的情况下渲染另一业务页。

## 二、条件性风险

### R-01 列表载荷契约漂移会在生产环境被伪装成“空列表”

- 严重性：中
- 置信度：高
- 证据：`frontend/src/lib/api.ts:105-116` 在 `payload.data` 缺失或类型错误时返回共享空数组；只有开发环境且 `data` 已存在时才输出告警。
- 用户可见复现：任一列表 API 因后端回归返回 `{items: [...]}`、`{data: null}` 或其他错误形状；生产界面显示“暂无数据”，而不是契约错误。
- 根因：通用解析器把响应结构错误降级为合法空结果，掩盖了业务事实和接口回归。
- 直接修复：列表解析器对非约定结构抛出带端点上下文的契约错误；各页面进入明确错误态。合法空列表必须由 `{data: []}` 唯一表达。

### R-02 禁用或隔离 Web Storage 的浏览器会在首屏或切换语言时崩溃

- 严重性：中
- 置信度：高
- 证据：`frontend/src/i18n/I18nProvider.tsx:28-34` 和 `frontend/src/i18n/I18nProvider.tsx:57-60` 直接调用 `localStorage.getItem/setItem`，没有处理 `SecurityError`。
- 用户可见复现：在禁用持久化存储、受限 iframe 或部分隐私模式中打开页面；首次渲染可能抛异常白屏。若读取成功但写入被拒，切换语言时也会抛异常。
- 根因：把可拒绝访问的浏览器存储当成始终可用的内存 API。
- 直接修复：建立单一的平台存储适配器，在读取或写入被平台拒绝时保留当前内存 locale，并产生可诊断日志；补充抛出 `SecurityError` 的测试。

### R-03 缺少 `ResizeObserver` 的浏览器或 WebView 会导致应用壳崩溃

- 严重性：中
- 置信度：高
- 证据：`frontend/src/components/shell/Sidebar.tsx:116-140` 无条件执行 `new ResizeObserver(measure)`。
- 用户可见复现：在不支持 `ResizeObserver` 的旧 WebView 或裁剪运行环境中打开任意登录后页面；侧边栏 effect 抛出 `ReferenceError`，应用壳不可用。
- 根因：页面核心导航依赖浏览器能力，却没有明确的支持基线或启动期能力检查。
- 直接修复：明确最低浏览器基线；若必须覆盖该类 WebView，在统一平台层提供经测试的观察器实现，或在启动时给出明确的不支持页面。

### R-04 Portal 提交依赖未检查的 `crypto.randomUUID`

- 严重性：中
- 置信度：高
- 证据：`frontend/src/pages/portal/hooks/useAccessRequestForm.ts:275-289` 在 mutation 内直接调用 `crypto.randomUUID()` 生成幂等键。
- 用户可见复现：在不提供 `randomUUID` 的旧浏览器、旧 WebView 或不满足安全上下文要求的部署环境提交访问申请；异常发生在 `fetch` 之前，请求完全不会发出。
- 根因：幂等键生成直接绑定单一平台方法，没有对部署环境声明或验证能力。
- 直接修复：明确并验证浏览器与安全上下文基线；如产品必须覆盖更广环境，则在单一安全随机数模块中用 `crypto.getRandomValues` 生成符合格式的键，并对能力缺失快速显示可理解错误。

### R-05 顶层没有错误边界，任一渲染异常都可能变成整页白屏

- 严重性：中
- 置信度：高
- 证据：`frontend/src/main.tsx:24-35` 直接挂载 Provider 和 `App`，没有 React Error Boundary。
- 用户可见复现：任一页面因意外载荷、浏览器 API 或组件错误在渲染阶段抛异常；整个 React 树被卸载，用户没有错误说明、刷新或返回入口。
- 根因：应用只有查询错误态，没有组件树级故障隔离。
- 直接修复：在应用壳顶层加入错误边界，并在高风险工作区加入局部边界；展示关联 ID、刷新和返回安全页操作，同时将异常发送到现有可观测性链路。

### R-06 空 `supported_scopes` 会被矩阵前端解释为“支持全部范围”

- 严重性：中
- 置信度：中
- 证据：
  - `frontend/src/pages/console/workspace/tabs/MatrixTab.tsx:70-75` 在 `supported_scopes` 为空时使用全部范围。
  - `src/easyauth/admin_console/authorization_groups_api.py:260-275` 后端只接受明确出现在 `supported_scopes` 中的范围。
- 用户可见复现：如果权限目录出现 `supported_scopes: []` 的权限，矩阵编辑器会允许选择任意范围；保存时后端拒绝。
- 根因：前端把空集合解释为通配符，后端把空集合解释为不支持任何范围。
- 直接修复：统一领域语义：空数组只能表示空集合；若业务需要“全部范围”，使用明确的领域字段或枚举，不能复用空值。

### R-07 用户选择器的组合框无法向读屏器报告当前高亮项

- 严重性：低
- 置信度：高
- 证据：`frontend/src/components/UserSelect.tsx:58-103` 的 listbox 和 option 没有稳定 ID；对应 combobox 因而无法设置 `aria-controls` 和 `aria-activedescendant`。
- 用户可见复现：使用读屏器键盘浏览用户建议列表；视觉高亮会变化，但辅助技术无法可靠读出当前候选项及组合框与列表的关联。
- 根因：键盘状态只体现在 CSS 与 `aria-selected`，没有实现完整的 ARIA combobox 关系。
- 直接修复：为输入、列表和每个 option 生成稳定 ID；输入设置 `aria-controls`、展开时设置 `aria-activedescendant`，并用读屏器测试上下键、选择和关闭流程。

## 三、建议处理顺序

1. 先统一服务端能力模型并修复 C-01、C-02、C-03，消除大面积“看得见但做不了”的权限错觉。
2. 修复 C-05、C-06、C-07、C-08，使前端只能生成合法、可恢复、完整的业务操作。
3. 修复 C-09、C-11、C-12，补齐异步竞态、错误态和分页边界。
4. 接入 C-04，并清理 C-10、C-13、C-14、C-15 等明确体验错误。
5. 将 R-01 作为契约治理项优先落地，再按支持的浏览器基线处理其余平台风险。

## 四、验证记录

- `npm run typecheck`：通过。
- `npm run build`：通过；Vite 仅报告主包体积超过 500 kB 的性能警告。
- `npx vitest run --maxWorkers=1 --no-file-parallelism`：41 个测试文件、295 个测试全部通过。
- `.venv/bin/python -m pytest tests/integration/frontend/test_react_shell.py -q`：35 个测试全部通过。
- 默认并行 Vitest 首次运行出现 10 个超时失败；将对应 5 个文件以单 worker 独立复跑后 76 个测试全部通过，再以单 worker 全量复跑全部通过。因此这些超时不计为已确认产品缺陷，但说明当前测试在资源竞争下存在稳定性问题。

本轮只进行审计和文档记录，没有修改业务代码、测试或运行配置。
