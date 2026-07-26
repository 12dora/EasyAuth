# EasyAuth 独立全量审计

审计日期：2026-07-27

## 一、审计范围与方法

本次审计独立覆盖 Django 后端、React 前端、单元/集成测试、端到端测试、国际化、交互反馈、文案、动效、响应式布局及仓库卫生。审计结论按“已确认问题”和“待验证假设”分开记录；普通格式、命名和低价值 lint 噪声未列入问题清单。

执行结果：

- 后端测试：`pytest -q`，结果为 `1291 passed, 1 skipped`。
- 前端生产构建：`pnpm --dir frontend build`，构建成功；Vite 同时报出主 JavaScript 文件 `826.08 kB`、超过 `500 kB` 的分块告警。
- 前端全量测试：`pnpm --dir frontend test -- --run`，结果为 6 个测试文件、10 个用例失败，主要为默认 5 秒超时；将其中 4 个失败文件分别以单 worker 独立重跑后全部通过。因此这里确认的是测试并发稳定性问题，而不是把失败断言直接认定为产品回归。
- 静态检查：`ruff check src tests` 未通过，共 15 项；其中多数为导入位置、类型注解和未使用导入等低价值问题，未逐项占用本报告篇幅。

严重度口径：

- 严重：会隐瞒数据/契约错误、阻断核心操作，或使关键测试失去有效性。
- 中等：明确影响可用性、一致性、国际化或交付可靠性，但存在可绕行路径。
- 较低：不会阻断主流程，但会持续积累维护成本、认知负担或体验损耗。

## 二、结论摘要

| 编号 | 严重度 | 结论 | 信心 |
| --- | --- | --- | --- |
| C-01 | 严重 | 列表响应契约错误被静默转换为空列表，端到端假数据已与真实契约漂移且测试仍可通过 | 高 |
| C-02 | 严重 | 应用启停、删除失败没有任何用户反馈 | 高 |
| C-03 | 中等 | 核心管理写操作缺少统一成功反馈，交互完成状态不可预测 | 高 |
| C-04 | 中等 | 顶栏通知与门户安全设置是可点击的占位功能，并存在不可达占位分支 | 高 |
| C-05 | 中等 | 后端英文领域错误被直接展示在简体中文门户，测试还固化了英文句子 | 高 |
| C-06 | 中等 | 语言切换不控制大量日期格式，英文界面仍按 `zh-CN` 格式输出 | 高 |
| C-07 | 中等 | Manifest 页签大量硬编码中文，现有国际化护栏未覆盖该文件 | 高 |
| C-08 | 中等 | 前端全量测试在默认并发下不稳定，独立重跑却通过 | 高 |
| C-09 | 中等 | 所有页面同步打入主包，门户也下载管理控制台代码 | 高 |
| C-10 | 中等 | 移动端将多组管理导航压成无分组的长横向滚动条 | 中高 |
| C-11 | 较低 | 明确标注“历史兼容”的未使用类型和状态分支仍留在生产代码 | 高 |
| C-12 | 较低 | 面向用户的文案直接暴露内部字段名和流水线术语 | 高 |
| C-13 | 较低 | 对话框和 Toast 缺少进入/退出动效，关闭时直接卸载 | 高 |

## 三、已确认问题

### C-01 列表契约错误被静默转换为空列表，端到端测试也未发现

严重度：严重
信心：高

证据：

- `frontend/src/lib/api.ts:97-102` 对成功响应仅执行 `return payload as T`，没有运行时结构校验。
- `frontend/src/lib/api.ts:105-116` 的 `itemsFromPayload` 只接受 `payload.data`；当字段缺失或响应不是对象时直接返回共享的 `EMPTY_ITEMS`。只有 `data` 字段存在但不是数组时才在开发环境告警，生产环境仍静默返回空列表。
- `frontend/e2e/visual-alignment.spec.ts:84-120` 给应用列表和申请运营接口提供的是 `{ items: [...] }`，而生产 helper 只读取 `{ data: [...] }`。
- `frontend/e2e/visual-alignment.spec.ts:17-31` 只断言页面标题、路由标记、控件可点击和文字不溢出，没有断言伪造的 `Demo App` 或申请行实际出现。
- `frontend/e2e/visual-alignment.spec.ts:200-221` 的布局检查只把 `overflow-x: visible` 的元素列为问题；可滚动或被截断的容器不会失败。
- `frontend/e2e/smoke.spec.ts:277-298` 的凭据和 Manifest 版本历史、`frontend/e2e/smoke.spec.ts:334-370` 的授权组、权限和范围也继续使用 `{ items: [...] }`。

用户/业务影响：

- 后端字段改名、序列化器错误或测试桩过期时，界面会显示“没有数据”，而不是暴露契约故障。
- 运维人员可能把真实数据缺失误判为业务空状态；视觉和冒烟测试也会在核心数据行根本没有渲染时给出假绿灯。
- 这违反项目“不用空结果兜底掩盖真实问题、违反数据契约时快速失败”的硬约束。

根因：

- 泛型请求 helper 依赖 TypeScript 强制断言，没有为 API envelope 建立运行时验证。
- 列表 helper 把“响应非法”和“合法空数组”合并为同一结果。
- 端到端测试只覆盖外壳存在，不覆盖假数据是否成功穿过真实解析链路。

直接修复：

1. 为列表 envelope 建立单一运行时解析器；`data`、`pagination` 或元素结构不合法时抛出带接口路径和错误码的明确异常。
2. 删除 `EMPTY_ITEMS` 契约兜底，合法空列表只能来自明确的 `data: []`。
3. 将所有端到端 mock 迁移到真实 `{ data, pagination }` 契约。
4. 每个 mock 至少断言一个种子业务值可见，例如 `Demo App`、`invoice.read`，防止只验证页面骨架。

### C-02 应用启停、删除失败没有任何用户反馈

严重度：严重
信心：高

证据：

- `frontend/src/pages/console/ConsoleAppList.tsx:63-70` 的启停 mutation 只有 `onSuccess`，没有 `onError`、错误横幅或 Toast。
- `frontend/src/pages/console/ConsoleAppList.tsx:71-80` 的删除 mutation 同样只有成功路径；失败时删除确认目标不会被清理，也没有失败原因展示。

用户/业务影响：

- 权限不足、冲突、网络失败或后端校验拒绝时，用户点击后看不到任何解释，只能猜测操作是否生效。
- 删除属于高风险、不可逆倾向操作；无反馈会促使重复点击、重复请求或错误升级工单。

根因：

- 页面按“刷新查询即反馈”的局部写法实现 mutation，没有统一的写操作反馈约定。

直接修复：

1. 为启用、停用和删除分别增加国际化的成功与失败 Toast。
2. 失败时保持确认对话框和目标上下文，并显示后端可安全展示的错误原因。
3. 对当前行设置 pending/disabled，避免同一应用重复提交；用组件测试覆盖 4xx、5xx 和网络失败。

### C-03 核心管理写操作的成功反馈不一致

严重度：中等
信心：高

证据：

- `frontend/src/pages/console/ConsoleAppWorkspace.tsx:65-75` 保存应用基本信息后只刷新缓存并关闭编辑状态。
- `frontend/src/pages/console/ConsoleAppWorkspace.tsx:215-227` 保存托管范围策略后只写查询缓存；失败在 `frontend/src/pages/console/ConsoleAppWorkspace.tsx:274-275` 显示横幅，但成功没有反馈。
- `frontend/src/pages/console/ConsoleTeamDetail.tsx:75-113` 保存团队信息和添加成员后只更新缓存、关闭对话框；相邻的团队状态失败路径却已有 Toast（`frontend/src/pages/console/ConsoleTeamDetail.tsx:87-100`）。
- `frontend/src/pages/console/workspace/tabs/MatrixTab.tsx:94-111` 和 `frontend/src/pages/console/workspace/tabs/RulesTab.tsx:51-90` 都只在失败时 Toast，成功后仅关闭表单或刷新数据。

用户/业务影响：

- 对话框关闭可以间接暗示成功，但页内保存、启停和后台刷新没有稳定的完成信号。
- 同一产品内相似操作的反馈规则不同，用户难以确认远端状态是否真正持久化，尤其是在列表刷新不明显时。

根因：

- 各页面自行决定 mutation 的完成体验，没有共享的“写操作成功/失败/pending”交互契约。

直接修复：

1. 建立统一的 mutation 反馈规范：高风险动作必须成功/失败 Toast；页内保存至少提供持久的“已保存”状态或 Toast。
2. 将标题、详情、操作对象和失败原因纳入国际化消息模板。
3. 提取小型 helper 或 hook 统一反馈，但不要吞掉原始错误，也不要用默认成功状态代替服务端确认。

### C-04 顶栏通知与门户安全设置是可点击占位功能

严重度：中等
信心：高

证据：

- `frontend/src/components/shell/NotificationsButton.tsx:10-33` 明确把通知中心标为“占位”，组件没有请求任何通知数据，打开后固定展示空状态。
- `frontend/src/components/shell/Topbar.tsx:73-76` 无条件渲染通知按钮；即使 `currentUser` 不存在，铃铛也仍显示。
- `frontend/src/components/shell/UserSummary.tsx:28-60` 把用户菜单的“安全设置”链接到普通 console/portal settings 路由。
- `frontend/src/App.tsx:67` 的 `/portal/settings` 实际渲染 `SettingsPlaceholder`。
- `frontend/src/App.tsx:131-145` 的设置页只显示空状态；其中 `mode === "console"` 分支不可达，因为控制台设置已经在 `frontend/src/App.tsx:95` 使用 `ConsoleSettingsPage`。
- `frontend/src/components/shell/Sidebar.tsx:105-106`、`frontend/src/components/shell/Sidebar.tsx:151-156` 还把相同设置入口作为固定导航项暴露。

用户/业务影响：

- 铃铛和“安全设置”是高预期、强信任入口；用户点击后只看到永远为空或“以后再做”的页面，会误以为系统漏收通知或安全配置已经存在但不可用。
- 公共/未登录顶栏显示通知按钮尤其容易产生错误产品承诺。

根因：

- 设计壳层先于领域能力上线，临时占位未在发布边界前移除。
- 设置占位组件保留了已经被真实页面取代的 console 分支。

直接修复：

1. 若当前版本没有通知事实来源，移除铃铛和相关状态；有来源时再实现未读数、列表、已读及错误状态。
2. 门户“安全设置”要么链接到真实的本地账户安全入口，要么在能力完成前从用户菜单和侧栏移除。
3. 删除不可达的 `SettingsPlaceholder` console 分支，不保留“以后可能用”的生产代码。

### C-05 英文领域错误会直接出现在简体中文门户

严重度：中等
信心：高

证据：

- `src/easyauth/access_requests/target_validation.py:78-126` 生成多条英文业务校验错误，例如授权组不可申请、权限不活跃、范围不受支持。
- `src/easyauth/access_requests/submission_validation.py:135-175` 对用户状态、有效期、应用状态和空目标继续生成英文句子。
- `src/easyauth/portal/api.py:209-214` 把上述异常的 `str(exc)` 直接放进 API 的 `error.message`。
- `frontend/src/lib/api.ts:184-192` 优先把后端 `error.message` 原样构造为前端异常，因此中文界面会显示英文。
- `tests/integration/portal/test_access_request_s14.py:142-170` 直接断言响应包含 `Authorization group must be requestable`，把英文展示形式固化为测试契约。

用户/业务影响：

- 简体中文用户在核心申请失败时会看到英文和内部领域术语，难以判断该联系谁或如何修复。
- 未来若需要真正双语，测试对整句英文的依赖会阻碍稳定错误码和本地化。

根因：

- 领域层把面向开发者的自然语言句子同时当作机器契约和用户文案。
- API 没有把稳定错误码、结构化字段和显示文案分离。

直接修复：

1. 为每个语义校验建立稳定的领域错误码及结构化参数，例如 `authorization_group_not_requestable` 与 `group_key`。
2. 前端按当前 locale 映射为可行动文案；后端日志保留开发者细节，不把内部异常句子直接呈现给用户。
3. 测试改为断言错误码和详情结构，不再绑定某种语言的整句文本。

### C-06 语言切换没有控制大量日期格式

严重度：中等
信心：高

证据：

- `frontend/src/i18n/I18nProvider.tsx:49-69` 已维护当前 locale，并提供随 locale 变化的 `formatDateTime`。
- `frontend/src/lib/status.ts:149-163` 又定义了一个独立日期 formatter，默认 locale 固定为 `zh-CN`。
- `frontend/src/pages/portal/PortalPage.tsx:89`、`frontend/src/pages/portal/PortalPage.tsx:149-160` 直接调用固定默认值版本，没有传入当前语言。

用户/业务影响：

- 切换到英文后，标题和按钮会变成英文，但授权到期时间、审批时间和提交时间仍按中文地区格式排列，造成混合语言体验。
- 日期是审计和权限有效期判断的关键字段；地区格式不一致会增加误读风险。

根因：

- 项目存在两个同名职责的 formatter，调用方绕过了国际化上下文。

直接修复：

1. 删除或禁止无 locale 的 `status.ts` formatter，统一使用 `useI18n().formatDateTime`。
2. 若纯函数场景必须保留 helper，则要求 locale 为必填参数，不能默认 `zh-CN`。
3. 增加切换到 `en` 后对日期实际输出的组件测试。

### C-07 Manifest 页签大量绕过国际化，护栏又未覆盖它

严重度：中等
信心：高

证据：

- `frontend/src/pages/console/workspace/tabs/ManifestTab.tsx:108-130` 硬编码预览失败、内容变化、导入成功和导入失败文案。
- `frontend/src/pages/console/workspace/tabs/ManifestTab.tsx:155-240` 硬编码上传 aria-label、上传文件、导出清单、Manifest 内容、预览差异、确认导入和版本加载失败等用户可见文字。
- `frontend/src/pages/console/workspace/tabs/ManifestTab.tsx:242-243` 继续硬编码“版本历史”标题。
- `frontend/src/i18n/noHardcodedChinese.test.ts:7-43` 采用人工文件白名单，只保护列出的组件；该列表没有 `ManifestTab.tsx`。

用户/业务影响：

- 英文模式进入 Manifest 页签后会看到整块中文，且无障碍名称也不会随语言变化。
- 当前“禁止硬编码中文”测试为绿色却漏掉真实生产组件，给团队造成覆盖完整的错觉。

根因：

- 国际化回归护栏采用易腐烂的正向白名单，而不是扫描所有生产组件并显式排除确有理由的文件。

直接修复：

1. 将该页所有可见文字、Toast 和 aria-label 迁移到消息表。
2. 把护栏改为遍历 `frontend/src` 下所有生产 `.tsx` 文件；仅对品牌名、测试夹具等明确场景设置最小排除。
3. 增加英文模式渲染 Manifest 页签的测试，验证文本和 aria-label。

### C-08 前端全量测试存在并发稳定性问题

严重度：中等
信心：高

证据：

- 默认全量命令实际出现 6 个测试文件、10 个用例失败，主要报错为 5 秒超时；对应长流程包括 `frontend/src/pages/console/ApprovalTemplatesPage.test.tsx:60`、`frontend/src/pages/console/ConsoleAppWorkspace.test.tsx:707`、`frontend/src/pages/console/ConsoleAppWorkspace.test.tsx:796`、`frontend/src/pages/portal/PortalPage.test.tsx:1322`。
- `frontend/src/pages/console/ConsoleAppWorkspace.test.tsx:707-795` 一个用例连续执行加载、新建、异步搜索、编辑、移除、再次搜索、保存和启用，等待链很长。
- `frontend/package.json:10` 只是把参数透传给 Vitest，没有项目级 worker、超时或资源隔离策略。
- 将 `ConsoleAppWorkspace`、`IntegrationTab`、`ConsoleTeamDetail` 和 `PortalPage` 四个失败文件分别以单 worker 独立重跑时，共 68 个用例全部通过。

用户/业务影响：

- CI 结果受机器负载和并发调度影响，团队容易形成“失败就重跑”的习惯，最终掩盖真实回归。
- 过长的端到端式组件测试定位成本高，任何一步变慢都会让整个用例超时。

根因：

- 多个长交互旅程共享默认 5 秒预算，并在全量并发下争抢 CPU。
- 测试把多个独立行为合并到一个用例，等待和 `userEvent` 输入成本累积。

直接修复：

1. 把长用例按“新建、编辑、启停”等业务行为拆分，保留少量真正需要的整段旅程。
2. 对不关心逐键输入的场景减少昂贵交互，明确等待业务完成条件，而不是依赖固定时序。
3. 根据 CI 资源设置可重复的 worker 上限；只对确实需要的流程设置合理局部超时，不用全局超大超时掩盖问题。
4. 在合并门禁中至少连续执行若干次全量测试，确认无偶发失败。

### C-09 所有路由页面同步打入主包

严重度：中等
信心：高

证据：

- `frontend/src/App.tsx:11-24` 在入口同步导入审批实例、审批模板、应用工作区、设置、团队、运营、生命周期、入职向导和门户等全部页面。
- 生产构建测得主 JavaScript 文件为 `826.08 kB`（gzip 后 `217.92 kB`），Vite 明确发出超过 `500 kB` 的分块告警。

用户/业务影响：

- 只访问员工门户的用户也要下载和解析大量控制台页面代码，增加首屏等待、移动网络流量和低端设备主线程开销。
- 新增控制台功能会继续线性推高所有用户的启动成本。

根因：

- 路由没有使用动态导入和 `React.lazy`，构建器无法按页面边界拆包。

直接修复：

1. 以 portal、console 及大型工作区页签为边界使用动态导入。
2. 为延迟页面提供轻量、可访问且国际化的加载状态。
3. 在构建门禁记录主包和关键路由分包大小，先设基线，再逐步收紧预算。

### C-10 移动端把多组管理导航压成无分组长横条

严重度：中等
信心：中高

证据：

- `frontend/src/components/shell/Sidebar.tsx:22-49` 的控制台导航包含应用、团队、人员、交接、入职、审批模板和 4 个运营入口，共 10 个主链接；设置又在 `frontend/src/components/shell/Sidebar.tsx:151-156` 单独渲染。
- `frontend/src/styles/responsive.css:16-21` 在 900px 以下把整个导航改为单行横向滚动。
- `frontend/src/styles/responsive.css:27-35` 让各分组横向排列并隐藏所有分组标题。
- `frontend/src/styles/responsive.css:54-56` 设置入口仍保留为下一块 footer，而不是进入统一的移动导航。
- `frontend/e2e/visual-alignment.spec.ts:3-13` 只检查 4 条主路径和一个 390px 移动视口；没有验证后部导航项是否可发现或可达。

用户/业务影响：

- 390px 屏幕一次只能看到少量入口，审批实例、依赖健康等后部功能需要盲目横向滑动才能发现。
- 分组标题消失后，导航的信息架构退化成无语义的长标签带；设置又占第二行，挤压内容首屏。

根因：

- 桌面侧栏仅通过 CSS 改成横向 flex，没有为移动端重新设计导航模型。

直接修复：

1. 改为可展开抽屉或分组菜单，保留“组织、审批中心、运营”等层级。
2. 若短期保留横向导航，至少自动将当前项滚入视野、显示可滚动提示，并把设置纳入同一导航层。
3. 增加 320px/390px 下对末尾入口可达性、当前项可见性和键盘操作的测试。

### C-11 生产代码仍保留未使用的历史兼容形态

严重度：较低
信心：高

证据：

- `frontend/src/lib/domain.ts:81-89` 定义了明确标注“历史兼容”的 `RoleItem`。
- `frontend/src/lib/domain.ts:385-394` 定义了明确标注“历史兼容”的 `PortalCatalogRole`。
- 全仓库符号搜索显示这两个类型没有任何调用方。
- `frontend/src/lib/status.ts:48-51` 同时接受当前 `blocking` 和历史 `blocked` 状态，注释也明确说明后者仅为历史兼容。

用户/业务影响：

- 旧名继续出现在类型提示和代码补全中，容易诱导新代码恢复已经废弃的 role/blocked 形态。
- 无期限兼容分支扩大状态空间，降低前后端契约错误被及时发现的概率。

根因：

- 模型重构后只增加了新类型，没有完成旧类型和旧状态的删除。

直接修复：

1. 删除两个无引用的历史类型。
2. 删除 `blocked` 分支，让未知状态按明确错误或可观察的未知状态处理。
3. 以当前 schema 生成或集中定义状态联合类型，防止自由字符串继续扩散。

### C-12 用户文案直接暴露内部字段名和流水线术语

严重度：较低
信心：高

证据：

- `frontend/src/i18n/messages.ts:201-218` 在审批模板表单中直接使用“模板 Key”“`form_schema`”“`form_mapping`”“`type`”“`required`”“字段契约”等实现术语。
- `frontend/src/i18n/messages.ts:298-309` 把 `schema_version`、`preview_id` 和 “import pipeline” 放进用户错误提示。
- `frontend/src/i18n/messages.ts:337-350` 直接展示 `approval_callback_url`、`handover_url`、`onboard_url`，测试事件成功文案则以 `delivery_id` 和内部状态为核心。
- `frontend/src/pages/console/workspace/tabs/ManifestTab.tsx:124-127` 导入成功仅告诉用户原始目录版本值，没有说明后续影响或可执行动作。

用户/业务影响：

- 平台管理员被迫理解数据库/API 字段和内部流水线，错误文案没有优先说明“发生了什么、如何修复”。
- 技术标识符本身有排障价值，但作为唯一主文案会提高配置错误和支持成本。

根因：

- API/schema 词汇直接复用为 UI 信息架构，缺少“业务说明 + 可选技术详情”两层表达。

直接修复：

1. 主标签改为业务语言，例如“表单结构”“字段映射”“审批回调地址”；字段名放进次级帮助文本或代码样式。
2. 错误先给出补救动作，例如“预览已失效，请重新生成”，再在可展开详情里显示 `preview_id`。
3. 测试事件结果优先表达“已加入发送队列/发送失败”，投递 ID 作为复制型排障信息。

### C-13 对话框和 Toast 缺少进入/退出动效

严重度：较低
信心：高

证据：

- `frontend/src/components/Dialog.tsx:45-57` 在条件满足时直接 portal 挂载静态背景与面板，没有进入/退出状态类。
- `frontend/src/components/ui/Toast.tsx:77-84` 关闭时立即从数组过滤。
- `frontend/src/components/ui/Toast.tsx:209-250` Toast 卡片直接插入或移除，没有进入、退出或堆栈位移动效。

用户/业务影响：

- 高频浮层和临时反馈瞬间出现、瞬间消失，缺少空间连续性；自动消失的 Toast 尤其容易让用户误以为内容闪烁。
- 这里缺少的是帮助理解状态变化的功能性动效，而非装饰性动画。

根因：

- 组件状态只有“存在/不存在”，没有短暂的 entering/exiting 生命周期。

直接修复：

1. 对话框使用约 140–200ms 的背景淡入淡出与面板轻微位移/缩放；退出完成后再卸载。
2. Toast 增加进入、退出和列表重排过渡；关闭时先标记退出，再删除数据。
3. 所有动效遵守 `prefers-reduced-motion`，减少动效模式下保留即时但稳定的状态变化。

## 四、待验证假设

以下问题从静态结构看存在风险，但在没有真实设备任务测试或产品口径前，不提升为已确认缺陷。

### H-01 通配路由重定向可能掩盖坏链接

严重度候选：较低
信心：中

证据：

- `frontend/src/App.tsx:68` 把所有未知门户路径静默重定向到 `/portal`。
- `frontend/src/App.tsx:96` 把所有未知控制台路径静默重定向到 `/console`。

风险与验证方式：

- 收藏链接、通知链接或代码中的拼写错误会表现成“回到首页”，用户无法区分无权限、资源不存在和链接损坏。
- 应用真实通知/邮件深链做一次无效路径测试，并确认产品是否有明确的 404/无权限设计。如果没有，应增加保留原 URL 的错误页和返回入口。

### H-02 固定右上角 Toast 在复杂窄屏表单上可能遮挡关键控件

严重度候选：较低
信心：中

证据：

- `frontend/src/components/ui/Toast.tsx:209-215` 将 Toast 固定在视口右上角，宽度为 360px、最大宽度仅减去 2rem。
- 同一容器允许多条 Toast 纵向堆叠（`frontend/src/components/ui/Toast.tsx:210-225`）。

风险与验证方式：

- 在 320px/390px 视口连续触发 3 条持久错误 Toast，检查是否遮住顶栏、对话框关闭按钮或表单首个错误字段，并验证屏幕阅读器播报顺序。
- 如确认遮挡，应限制堆栈高度、提供汇总/折叠，并在窄屏改为底部安全区或不覆盖当前焦点的布局。

## 五、建议修复顺序

1. 先修复 C-01：严格响应契约、迁移端到端 mock、增加真实数据行断言。它会影响后续所有测试结论的可信度。
2. 随后修复 C-02、C-05：保证关键写操作失败可见，并把机器错误码与用户语言分离。
3. 并行完成 C-07、C-06：消除国际化断层并扩大自动护栏覆盖。
4. 再处理 C-08、C-09：稳定全量测试并拆分主包，建立持续的交付门禁。
5. 最后集中收敛 C-03、C-04、C-10 至 C-13，统一反馈、导航、占位能力、文案和功能性动效。

## 六、未发现与边界说明

- 后端全量测试通过，未在本轮静态与自动化检查中确认新的后端崩溃、越权或数据破坏路径；这不等于完成了专门的渗透测试。
- 前端生产构建成功；主包过大作为 C-09 单独记录。
- 本报告没有把 15 个 Ruff 问题拆成审计项，避免用低价值 lint 数量掩盖产品与契约风险。
- 本次仅新增审计文档，没有修改源码、测试、配置或构建产物，也没有提交 commit。
