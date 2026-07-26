# 前端架构与代码异味审计

## 1. 审计结论

本次审计聚焦 `frontend/src` 的 React/TypeScript 生产代码、相关样式和架构约束测试。共确认 10 项问题，其中高严重度 5 项、中严重度 4 项、低严重度 1 项。

最需要优先处理的不是单纯的文件行数，而是以下三类结构性风险：

1. 交接向导和访问申请把状态机、请求编排、领域规则及渲染集中在单个组件或 Hook 中。
2. 权限树遍历和门户契约在多个位置重复定义，已经出现“唯一口径”名义存在、实现却分叉的情况。
3. 若干抽象和质量门禁走向两个极端：表格测试禁止建立合适的渲染抽象，而 Hook 依赖规则又没有真实 ESLint 门禁。

严重度定义：

- **高**：已违反项目硬约束，或修改业务流程时很容易造成错误提交、规则漂移、竞态和大范围回归。
- **中**：当前功能可以工作，但结构显著扩大修改面，并使跨页面一致性依赖人工维护。
- **低**：局部重复或语义分叉，短期风险有限，但应在相关区域下一次改动时收敛。

置信度定义：

- **高**：由源码、配置、静态统计或可复现命令直接确认。
- **中**：结构事实已确认，但实际用户影响还依赖运行时触发条件。

## 2. 规模与复杂度盘点

以下行数和函数范围由 `wc -l` 与 TypeScript AST 扫描交叉取得；分支数是审计用近似指标，不等同于正式圈复杂度。

| 文件/函数 | 规模 | 观察 |
| --- | ---: | --- |
| `pages/console/lifecycle/HandoverWizard.tsx` / `HandoverWizard` | 文件 801 行；主组件 530 行；约 81 个分支节点；15 个 Hook 调用 | 主组件本身就是流程引擎、请求层和五步视图 |
| `pages/console/workspace/tabs/ConnectorTab.tsx` / `ConnectorTab` | 文件 1082 行；主组件 505 行；约 60 个分支节点；17 个 Hook 调用 | 主组件之外还同文件承载 259 行映射面板和同步历史 |
| `pages/portal/hooks/useAccessRequestForm.ts` | 文件 1028 行；10 个独立表单状态 | Hook 文件同时定义契约、解码器、选择算法、联动副作用和提交协议 |
| `pages/portal/components/PermissionSelector.tsx` | 文件 971 行；主组件 244 行 | 展示、树算法、批量选择、分页、弹层和动画状态同文件维护 |
| `styles/features/permission-selector.css` | 437 行 | 与上面的 971 行 TSX 形成一个约 1400 行的紧耦合变更面 |
| `pages/console/workspace/tabs/CatalogTab.tsx` / `CatalogTab` | 文件 584 行；主组件 423 行；约 42 个分支节点；16 个 Hook 调用 | 三类资源、四个查询、五个 mutation、三张表和三个弹窗集中在一个组件 |
| `pages/console/onboarding/AppOnboardingWizard.tsx` | 文件 1263 行 | 已拆成多个步骤组件，未发现与 `HandoverWizard` 同等级的单函数问题，但文件级变更面仍偏大 |

文件大并不自动构成缺陷。例如 `AppOnboardingWizard.tsx` 虽然总行数最高，但主编排组件只有约 106 行，步骤已有函数边界；因此本报告没有仅凭总行数将其定为高严重度问题。

## 3. 已验证问题

### EA-FE-01：交接向导是以整数和条件分支实现的巨型隐式状态机

- **严重度**：高
- **置信度**：高
- **状态**：已验证

**证据**

- `HandoverWizard` 从 `frontend/src/pages/console/lifecycle/HandoverWizard.tsx:61` 延续到 `:590`，单函数 530 行。
- 九组本地状态集中在 `:69-95`，其中 `step` 只是裸整数。
- 预览流程由依赖不完整的 effect 驱动，并显式压制 Hook 依赖规则：`:197-219`。
- 前进规则、保存规则和按钮禁用规则分别在 `:256-311` 以 `step === 1/2/3` 重复编码。
- 五步视图在 `:318-551` 用连续条件分支展开；底部导航又在 `:557-579` 重复解释步骤语义。
- 单项执行/重试协议存在两份实现：批量执行在 `:221-246`，行内重试在 `:507-537`。两处都负责设置运行态、拼接 URL、解析响应、捕获错误和刷新详情。
- 另一个 effect 在 `:111-123` 同样压制依赖规则。

**影响**

- 新增、删除或重排步骤时，必须同步修改步骤数组、数字比较、前进逻辑、保存逻辑、禁用条件和渲染分支；遗漏任一处都可能产生不可达状态或允许非法跳转。
- 执行协议的两份实现会随重试语义、异步状态或响应契约变化而分叉。
- effect 依赖通过注释压制后，闭包中 `selectedAppKeys`、`runPreview`、`invalidateDetail` 等变化是否安全只能依赖人工推理。
- 状态机与 JSX 互相穿插，使流程级测试难以覆盖全部状态转换。

**根因**

组件同时承担了状态机、服务端草稿同步、预览/执行命令、派生状态、错误处理和五步视图，没有明确的流程控制边界。

**整洁修复**

一次性建立显式的交接流程模型：

1. 用带名称的判别联合表示步骤和状态，例如 `apps | receivers | grants | preview | execute`，禁止继续使用裸整数作为领域状态。
2. 将合法转换及其前置条件放入 reducer 或独立状态机模块；按钮只派发事件，不再自行解释步骤数字。
3. 提取唯一的 `executeAppAction` 命令，批量执行和单项重试调用同一实现。
4. 将服务端同步和命令封装为 `useHandoverWizardController`，五个步骤各自成为只接收明确输入/事件的组件。
5. 删除两个依赖压制注释，令 effect 依赖可由真实 lint 规则验证。

不应保留原数字步骤或旧执行函数的兼容分支。

### EA-FE-02：访问申请 Hook 已演变为契约、领域、状态和传输层的聚合点

- **严重度**：高
- **置信度**：高
- **状态**：已验证

**证据**

- `frontend/src/pages/portal/hooks/useAccessRequestForm.ts` 共 1028 行。
- 文件先从共享领域模块导入权限类型（`:9-14`），随后又定义门户专用的 `AuthorizationGroupItem`、`ApproverOption`、`ScopeOption` 和带 scope 的权限类型（`:20-80`）。
- 返回接口从 `:133` 到 `:173`，暴露近 40 个状态、列表、错误字段和命令，调用方实际依赖的是一个“页面服务定位器”而不是聚焦的 Hook。
- `useAccessRequestFields` 在 `:216-250` 维护 10 个相互关联的 `useState`。
- 顶层 Hook 在 `:175-213` 同时完成目录请求、目录投影、三个联动 Hook、提交 mutation 和完整可提交性判断。
- 提交幂等、草稿 revision 和成功清理在 `:252-305`；全部交互命令在 `:394-474`；权限范围及树算法在 `:498-704`；联动副作用在 `:707-767`；运行时契约验证在 `:888-1028`。
- `PermissionSelector` 反向从这个 Hook 文件导入领域类型及选择键编解码函数：`frontend/src/pages/portal/components/PermissionSelector.tsx:27-30`。展示组件因此与表单 Hook 的内部组织方式耦合。
- 共享领域中又存在另一套相关定义：`frontend/src/lib/domain.ts:169-180`、`:396-427`。

**影响**

- 目录响应、权限选择、审批人默认规则或提交协议的任意变化都会波及同一个千行文件。
- 领域类型归属不清，`lib/domain.ts`、Hook 本地类型和组件消费类型可能独立漂移。
- 十个独立状态依靠动作函数和三个 effect 维持不变量，非法中间组合仍可在一次渲染中出现。
- Hook 难以复用，也难以只测试某一条纯领域规则；测试会被迫围绕完整 Hook 建立大夹具。

**根因**

以“页面表单”为边界聚合所有代码，而没有按 API 契约、纯领域选择模型、表单状态机和 React 适配层分层。

**整洁修复**

1. 建立门户目录的唯一契约模块，集中定义并解码 `PortalRequestCatalog`，删除 Hook 内的平行类型。
2. 将选择键、scope 级联、授权组覆盖、默认审批人计算和树查询拆为无 React 依赖的纯领域模块。
3. 用 reducer 表达表单草稿和明确事件，让清空应用、切换授权组、选择 scope 等不变量在一个转换函数内完成。
4. Hook 仅组合查询、mutation 与 reducer，返回按 `catalog`、`draft`、`validation`、`actions` 分组的窄接口。
5. `PermissionSelector` 直接依赖领域模块，不得再依赖 Hook 文件。

不应通过重新导出旧类型或维持两套字段名来过渡。

### EA-FE-03：权限树“唯一口径”实际存在三套遍历实现，且防御语义已经分叉

- **严重度**：高
- **置信度**：高
- **状态**：已验证

**证据**

- `frontend/src/pages/portal/permissionTree.ts:3-5` 明确声明权限/应用判定是“唯一口径”。
- 该模块在 `:15-35`、`:73-88` 实现权限收集、子组提取和直接权限去重，并带 `visited` 防环。
- `frontend/src/pages/portal/hooks/useAccessRequestForm.ts:652-668` 再次实现带 `visited` 的 scope 权限收集，`:861-877` 又重复子组提取和直接权限去重。
- `frontend/src/pages/portal/components/PermissionSelector.tsx:943-970` 第三次实现同样的三组函数，但这一版没有 `visited`。
- 表单使用这套算法决定提交及默认审批人，选择器使用另一套算法计算计数、选中态和批量选择：`useAccessRequestForm.ts:447-460`、`PermissionSelector.tsx:637-723`、`:835-914`。

**影响**

- 同一棵权限树可能在展示计数、批量选择、授权组覆盖和最终提交时得到不同结果。
- 新增树节点形态、去重规则或防御规则时必须人工同步三处。
- 当前就已经出现是否携带 `visited` 的实现差异，证明漂移不是假设。

**根因**

`ScopedPermissionItem` 被定义在 Hook 内，阻止共享树模块直接表达带 scope 的节点；各消费方随后复制算法以绕开类型边界。

**整洁修复**

1. 将 scope 权限节点提升到唯一领域模型。
2. 在 `permissionTree.ts` 或新的纯领域模块中提供唯一的遍历、直接子项、后代组、去重和查找实现。
3. 让遍历函数对统一节点模型工作，选择器和表单只能导入这些函数。
4. 以同一组契约样例验证展示计数、批量选择和提交 payload，删除三处重复实现。

不得保留旧遍历函数作为包装层。

### EA-FE-04：连接器同步间隔使用魔法值和静默默认，违反快速失败约束

- **严重度**：高
- **置信度**：高
- **状态**：已验证

**证据**

- 默认字符串 `"300"` 分散在初始状态和新建重置逻辑：`frontend/src/pages/console/workspace/tabs/ConnectorTab.tsx:100`、`:143`。
- 保存时使用 `Number(intervalDraft) || 300`：`:195-201`。空字符串、`NaN` 等无效值都会被静默转换为 `300`。
- 输入范围又以独立魔法值写在 JSX：`:464-468` 的 `min={60}`、`max={86400}`。
- 输入没有 `required`，因此空值可以进入提交处理并被悄悄替换为 `300`。

**影响**

- 用户清空字段后提交，界面没有说明地保存为 300 秒；输入错误被伪装成成功配置。
- 默认值和边界分别散落，修改产品规则时容易只改一处。
- 这直接违反项目“不使用静默默认值掩盖真实问题”和“违反数据契约时快速失败”的硬约束。

**根因**

表单草稿被建模为无约束字符串，传输层再用 JavaScript truthy 规则完成隐式纠错。

**整洁修复**

1. 定义唯一的 `DEFAULT_RECONCILE_INTERVAL_SECONDS`、最小值和最大值。
2. 在提交前显式解析并验证整数、必填和范围；失败时在字段上显示明确错误并禁止 mutation。
3. 请求体只接收已验证的数值类型。
4. 删除 `|| 300`，不增加任何空值兼容路径。

### EA-FE-05：共享领域文件保留了明确标注的历史兼容类型

- **严重度**：高
- **置信度**：高
- **状态**：已验证

**证据**

- `frontend/src/lib/domain.ts:81-89` 保留 `RoleItem`，注释明确写为“历史兼容类型”。
- 同文件 `:385-394` 保留 `PortalCatalogRole`，注释同样明确写为“历史兼容类型”。
- 全仓 `frontend/src` 搜索只命中这两个声明本身，没有生产代码或测试消费它们。

**影响**

- 旧的 role 术语继续污染授权组领域语言，为后续代码提供错误的可选类型。
- 无消费者的兼容类型会误导开发者以为旧契约仍受支持，并鼓励新增转换或分支。
- 这与项目“尚未上线，不保留历史错误形态”的硬约束直接冲突。

**根因**

领域重命名只新增了正确模型，没有完成旧模型的删除和调用方审计。

**整洁修复**

直接删除两个未使用类型，以 `AuthorizationGroupItem` 和 `PortalCatalogAuthorizationGroup` 作为唯一模型，并执行全量类型检查。不得增加 type alias、重导出或兼容转换。

### EA-FE-06：表格渲染样板已大范围复制，架构测试反而禁止建立合适抽象

- **严重度**：中
- **置信度**：高
- **状态**：已验证

**证据**

- 静态扫描在 `frontend/src/pages` 找到 20 个含 `getHeaderGroups().map` 的文件、26 个表头渲染循环和 25 个行渲染循环。
- `CatalogTab` 单文件就复制三套表头、加载、行和空态结构：`frontend/src/pages/console/workspace/tabs/CatalogTab.tsx:267-303`、`:316-352`、`:367-403`。
- 现有 `TablePrimitives` 只包装 HTML 标签和样式：`frontend/src/components/ui/TablePrimitives.tsx:21-70`，没有统一 TanStack 行/表头渲染、加载态和空态。
- `frontend/src/components/tableArchitecture.test.ts:8-13` 扫描全部源码并禁止一批名称；`:16-33` 进一步要求 `PermissionSelector` 必须直接使用 TanStack Table 和原生 `<table>`，并明确禁止 `TablePrimitives`、`TablePagination`。
- 同测试 `:74-96` 以源码正则而不是行为契约判断架构，连 `DataTable`、`CredentialTable`、`GrantTable`、`RequestTable` 等命名也一并全局禁止。

**影响**

- 调整可访问性、骨架屏、空态、操作列或行属性时需要修改大量页面。
- 各表格已出现客户端分页、服务端分页、手写分页和直接原生表格多种渲染路径，一致性依赖人工检查。
- 测试把一次历史重构的实现选择永久固化，阻止后续建立更小、更准确的共享抽象。

**根因**

为了避免旧的万能 `DataTable`，项目采用了“禁止任何同类抽象”的负面约束，但没有补上轻量、可组合的 TanStack 渲染适配层。

**整洁修复**

1. 删除基于名称和源码片段的全局禁止测试，改为验证语义表格、可访问名称、加载/空态和分页行为。
2. 建立两个小而明确的渲染器：客户端分页表和服务端分页表；列定义、特殊单元格和行属性仍由页面提供。
3. `PermissionSelector` 如需 sticky/tree 行能力，可提供专用行渲染插槽，而不是复制整套表格骨架。
4. 一次性迁移现有调用方并删除重复循环，不保留旧新两套渲染路径。

### EA-FE-07：运行时 API 契约校验散落在页面文件，并依赖强制类型断言收尾

- **严重度**：中
- **置信度**：高
- **状态**：已验证

**证据**

- 门户列表在 `frontend/src/pages/portal/portalListPayload.ts:47-166` 自建一组 `require*` 校验器，并在 `:106`、`:133` 使用 `as unknown as` 转成目标行类型。
- 访问申请目录在 `frontend/src/pages/portal/hooks/useAccessRequestForm.ts:888-1028` 自建另一组 `contract*` 校验器，并在 `:901` 强制断言。
- 审批列表及详情又在 `frontend/src/pages/portal/components/PortalApprovalsSection.tsx:609-680` 使用 `hasExactKeys` 和一套独立 type guard。
- 通知渠道在 `frontend/src/pages/console/workspace/tabs/IntegrationTab.tsx:460-536` 内联解码。
- 连接器授权组和映射在 `frontend/src/pages/console/workspace/tabs/ConnectorTab.tsx:873-923` 再次内联解码，并在 `:891`、`:918` 使用 `as unknown as`。

**影响**

- 相同的对象、数组、字符串、分页和可空字段规则被重复实现，错误消息和严格程度不一致。
- 页面组件同时负责传输契约，进一步扩大组件文件和测试夹具。
- `as unknown as` 使“校验字段集合”和“TypeScript 类型字段集合”之间没有编译期绑定；新增类型字段时，解码器可以不变但仍宣称返回完整类型。

**根因**

`apiRequest<T>` 只提供静态泛型，没有统一的运行时解码边界；各页面为满足快速失败要求临时补写校验器。

**整洁修复**

1. 按端点建立独立契约模块，类型从运行时 schema 推导，或由同一契约源生成类型和解码器。
2. 让 `apiRequest` 的调用方显式传入 decoder，响应在离开 API 层前完成校验。
3. 提取分页等真正共享的 schema 组合件，但保留端点级严格字段定义。
4. 删除页面内 `require*`、`contract*`、`isRecord` 重复实现及所有收尾强制断言。

不得以放宽字段为可选或返回空数组的方式“统一”校验。

### EA-FE-08：权限选择器的动画生命周期由 JS 定时器和 CSS 魔法时长共同维护

- **严重度**：中
- **置信度**：高
- **状态**：已验证

**证据**

- JS 时长常量为 `160`：`frontend/src/pages/portal/components/PermissionSelector.tsx:79`。
- 进入动画用定时器清理状态：`:734-765`；退出动画还维护 timer map 和 generation map：`:768-832`。
- CSS 在 `frontend/src/styles/features/permission-selector.css:226-249` 分别硬编码 `160ms` 的进入和退出动画，多个工具栏 transition 也重复使用 `160ms`，例如 `:63`、`:124`、`:169-177`、`:268-290`。
- 减少动态效果在 JS 通过 `matchMedia` 判定（`PermissionSelector.tsx:81-85`），在 CSS 又通过媒体查询判定（`permission-selector.css:423-437`）。
- TSX 971 行、专用 CSS 437 行；静态搜索在两份文件中得到 112 个包含 `permission-selector__*` 的命中行，两份文件必须同步维护 DOM 结构、类名和动画协议。

**影响**

- CSS 动画时长变更但 JS 常量未同步时，行可能过早移除或在视觉结束后继续保留。
- 快速展开/折叠需要 generation、map、两个 effect 和数组去重共同维持，局部样式改动也可能触发状态错误。
- 选择器已经同时承担树算法和动画控制，继续增加交互会快速放大复杂度。

**根因**

把视觉动画结束当成固定毫秒的业务事件，并让 React 状态镜像 CSS 生命周期。

**整洁修复**

1. 以 `animationend`/`transitionend` 驱动退出状态完成，移除与 CSS 时长相等的 JS 定时器。
2. 将树行、scope 选择、工具栏和动画层拆成独立组件；纯树算法移到 EA-FE-03 的共享领域模块。
3. 动效数值只保留在设计 token/CSS 中，减少动态效果由 CSS 负责。
4. 删除不再需要的 timer map、generation map 和镜像状态，不保留旧计时路径。

### EA-FE-09：前端质量门禁缺少 ESLint，测试脚本参数透传也可复现失败

- **严重度**：中
- **置信度**：高
- **状态**：已验证

**证据**

- `frontend/package.json:6-11` 只有 `build`、`typecheck`、`test` 和 `e2e`，没有 `lint`。
- `frontend/package.json:23-37` 的开发依赖没有 ESLint 或 React Hooks lint 插件；`npm ls eslint --depth=0` 返回空。
- 源码却在 `HandoverWizard.tsx:122`、`:218` 写有 `eslint-disable-next-line react-hooks/exhaustive-deps`。当前这些注释没有任何实际门禁可压制。
- `frontend/package.json:10` 用 `node -e`、`spawnSync` 和 `shell: true` 包装 Vitest。
- 实际执行 `npm test -- --run src/components/tableArchitecture.test.ts`、对应访问申请 Hook 测试和连接器测试时，Node 将测试路径解释为 package script，并报 `Missing script`；改用 `npx vitest run <file>` 后三组测试均通过。

**影响**

- Hook 依赖、未使用代码、危险断言等规则不受自动检查，复杂组件只能靠审查者人工发现。
- 开发者和自动化工具使用标准 Vitest `--run` 参数时得到误导性的 package script 错误，降低定向回归效率。
- `shell: true` 的自定义转发层增加了不必要的命令解析差异。

**根因**

质量脚本以临时包装解决路径参数问题，但没有使用测试工具自身的参数能力；同时源码保留 lint 指令却未配置 lint 工具。

**整洁修复**

1. 增加 TypeScript、React 和 React Hooks 的 ESLint 配置及 CI `lint` 门禁。
2. 修复所有现有 Hook 依赖问题后删除压制注释。
3. 将测试脚本改为直接调用 `vitest run`（CI）和可选的 `vitest`（本地 watch），路径规范化放到调用方或独立无 shell 脚本中。
4. 删除当前 `node -e`/`shell: true` 包装，不保留旧参数兼容分支。

### EA-FE-10：弹层关闭逻辑重复，键盘和焦点语义已经不一致

- **严重度**：低
- **置信度**：高
- **状态**：已验证

**证据**

- 用户选择器自己实现全局 `pointerdown` 监听：`frontend/src/components/UserSelect.tsx:42-55`，Escape 则分散在输入框 `onKeyDown` 中，例如 `:135-150`。
- 顶栏菜单再次实现外部点击和全局 Escape：`frontend/src/components/shell/Topbar.tsx:37-61`。
- 权限选择器工具栏第三次实现相同的两类监听：`frontend/src/pages/portal/components/PermissionSelector.tsx:356-379`。
- 三处对事件目标、是否监听 Escape、焦点恢复和打开条件的处理不同。

**影响**

- 修复 portal、事件传播、嵌套弹层或焦点恢复问题时必须同步多处。
- 同类下拉菜单对键盘用户表现不同，后续可访问性问题难以统一修复。

**根因**

项目有 `Dialog`，但没有可复用的非模态 Popover/Menu 行为层。

**整洁修复**

建立一个可访问的 `Popover`/`Menu` 原语或窄的 `useDismissibleLayer`，统一外部交互、Escape、焦点返回和嵌套层处理，然后删除三处原生 document 监听。不要保留旧监听作为兜底。

## 4. 尚未提升为正式问题的假设

以下风险有源码迹象，但本次没有足够运行证据确认实际用户影响，因此不计入上述 10 项问题。

### H-01：长时间打开访问申请表单后，过期时间校验可能显示陈旧状态

- `frontend/src/pages/portal/components/AccessRequestFields.tsx:37` 只在挂载时计算一次 `datetime-local` 的 `min`，实现位于 `:80-83`。
- `frontend/src/pages/portal/hooks/useAccessRequestForm.ts:196-210` 用渲染时的 `new Date()` 计算 `canSubmit`，没有时钟触发器。
- 如果页面长时间无任何重渲染，已选择的未来时间跨过当前时刻后，按钮状态理论上可能仍沿用上一次渲染结果。
- 已检查 `PortalPage.test.tsx`、`useAccessRequestForm.test.ts` 和 `AccessRequestFields.test.tsx`；现有测试覆盖未来/过去输入切换，但没有覆盖时间自然跨界。
- 建议增加假时钟跨界测试后再决定使用定时重校验还是在 `submit` 入口再次强校验。

### H-02：成功重新读取映射可能覆盖未保存草稿

- `frontend/src/pages/console/workspace/tabs/ConnectorTab.tsx:677-693` 在每次 `mappingsQuery.data` 变化时整体重建 `drafts`。
- 全局查询配置已关闭窗口聚焦刷新：`frontend/src/lib/query.ts:3-8`，因此常见的切回窗口场景不会触发。
- 显式“重新加载”、其他失效操作或未来新增轮询仍可能在成功响应后覆盖本地编辑；当前连接器测试只验证失败/畸形响应不清空草稿，见 `ConnectorTab.test.tsx:188-259`。
- 建议先补“编辑后成功 refetch”的产品期望测试，再决定采用脏字段合并、明确放弃确认，还是编辑期间禁止刷新。

## 5. 核验记录

已执行以下检查：

1. `rg --files`、`wc -l`：盘点生产 TS/TSX/CSS 文件规模。
2. TypeScript AST 扫描：统计生产函数行数、近似分支节点、JSX 节点和 Hook 调用；用于区分“大文件”与“大函数”。
3. `rg` 交叉搜索：核对重复权限树函数、document 事件监听、查询键、表格渲染循环、lint 压制、历史类型和魔法值。
4. `npm run typecheck`：通过。
5. `npx vitest run src/components/tableArchitecture.test.ts`：5 项通过。
6. `npx vitest run src/pages/portal/hooks/useAccessRequestForm.test.ts`：12 项通过。
7. `npx vitest run src/pages/console/workspace/tabs/ConnectorTab.test.tsx`：9 项通过。
8. `npm ls eslint --depth=0`：未安装 ESLint。
9. 三次 `npm test -- --run <测试文件>`：均可复现 `Missing script`；随后以直接 Vitest 命令确认测试本身通过。

测试和类型检查通过只能证明当前已覆盖行为没有失败，不能消除本报告确认的重复口径、隐式状态机、静默默认和实现锁定风险。

## 6. 建议修复顺序

1. 先修 EA-FE-04 和 EA-FE-05：它们直接违反项目硬约束，改动边界清晰。
2. 合并处理 EA-FE-02、EA-FE-03、EA-FE-07：先建立唯一门户契约和权限领域模块，再缩小 Hook 和选择器。
3. 重构 EA-FE-01：在现有行为测试基础上引入显式状态机和唯一执行命令。
4. 处理 EA-FE-09，使后续重构具备真实 Hook lint 和稳定的定向测试入口。
5. 再处理 EA-FE-06、EA-FE-08、EA-FE-10，收敛表格、动画和非模态弹层的跨页面实现。
6. 最后按步骤拆分 `AppOnboardingWizard.tsx` 等仅文件级过大的模块；拆分时不改变领域模型，也不建立兼容导出层。
