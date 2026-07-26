# Toast 与用户反馈链路审计

## 1. 审计结论

本次审计覆盖 React 全局入口、`apiRequest`、TanStack Query 默认配置、Toast 容器、路由页面、表单提交、行级 mutation、文件/剪贴板操作、轮询任务，以及后端错误和复合结果到前端的传播链路。

当前项目已经形成一套基本可用的反馈习惯：

- 首屏或区块查询失败通常使用 `PageState` 或 `StatusBanner`；
- 对话框内提交失败通常留在对话框中以内联方式展示；
- 行级、跨区块和后台动作大多使用 toast；
- 错误 toast 默认持久显示，成功和提示 toast 自动消失；
- 后端大部分控制台 API 使用统一 `{ error: { code, message, details } }` 信封。

但仍有 12 个高严重度问题会造成“失败完全静默”“失败被显示为空数据”“没有实际变更却提示成功”或“操作已经提交却允许用户重复提交”。此外，传输层、Toast 去重、字段错误映射和重新登录路径缺少统一策略，使局部页面很容易再次漏接错误。

建议优先修复：

1. 所有“2xx 即成功”的假成功链路，特别是紧急撤权、控制台审批复合失败和非 JSON 2xx；
2. 应用启停/删除、Scope 启停、用户搜索、两步验证状态和连接器运行记录的静默失败；
3. 剪贴板“未复制却显示已复制”和凭据旧错误遮蔽新错误；
4. 全局错误边界、传输错误归一化、Toast 去重和字段错误契约。

## 2. 反馈方式判定原则

本报告使用以下口径：

| 场景 | 首选反馈 |
| --- | --- |
| 输入字段本身有误，用户可在原位置修正 | 字段级 inline error |
| 对话框提交失败，用户仍需在对话框内修正或重试 | 对话框内 `StatusBanner` |
| 页面或区块数据无法加载 | 区块级 `StatusBanner` / `PageState`，并提供重试 |
| 行级开关、删除、复制、后台排队等瞬时动作 | toast，或动作控件旁的短暂 inline 状态 |
| 后台轮询失败但仍有旧数据 | 区块内 warning，明确“数据可能已过期”；禁止周期性 toast |
| 重要安全状态变更成功 | success toast，并让页面状态同步变化 |
| React 运行时崩溃 | 错误边界的可恢复页面；toast 只能作为补充 |

同一次失败不应同时由全局 toast、局部 toast 和 inline banner 重复播报。全局兜底只能处理“调用方没有消费”的错误。

## 3. 高严重度缺口

### TF-01：非 JSON 的 2xx 响应会进入成功分支

- **严重度：高**
- **置信度：高**
- **证据：** `frontend/src/lib/api.ts:97-103` 在 `response.ok` 时直接返回解析结果；`frontend/src/lib/api.ts:151-164` 把所有非 JSON、非 204 响应转换为内部 `Symbol`，但不会抛错。以设置保存为例，`frontend/src/pages/console/ConsoleSettingsPage.tsx:71-74` 会把该值写入缓存并显示保存成功 toast。
- **用户操作与失败场景：** 用户保存设置、配置或其他 mutation；反向代理、登录页重定向或错误网关返回 `200 text/html`。
- **当前行为：** 调用方进入 `onSuccess`，可能显示成功 toast、关闭对话框或写入无效缓存；实际业务操作是否成功未知。
- **期望反馈：** 需要 JSON 的 API 收到非 JSON 2xx 时应作为协议错误失败，并通过原调用点的 inline error 或 error toast 告知“服务响应格式异常，请刷新后重试”。
- **重复提示风险：** 中。若传输层同时直接弹 toast，而 mutation 又有 `onError`，会双报。
- **干净修复：** 给 `apiRequest` 增加明确的响应类型契约；除显式声明的 `204`、文本或 Blob 下载外，2xx 必须是合法 JSON，否则抛出带稳定 code 的 `ApiError`。只在调用方决定使用 inline 还是 toast。

### TF-02：接入向导把应用详情加载失败显示成绿色“已有应用”

- **严重度：高**
- **置信度：高**
- **证据：** `frontend/src/pages/console/onboarding/AppOnboardingWizard.tsx:67-72` 查询应用但不读取 `appQuery.error`；`frontend/src/pages/console/onboarding/AppOnboardingWizard.tsx:104-143` 继续把 `undefined` 的应用快照传给各步骤；`frontend/src/pages/console/onboarding/AppOnboardingWizard.tsx:267-276` 只要 URL 有 `app_key` 就显示 evergreen “已有应用”，缺失字段显示 `-`。
- **用户操作与失败场景：** 用户通过“继续接入”深链打开向导；应用详情请求 404、403、断网或返回无效载荷。
- **当前行为：** 页面展示成功色“已有应用”，允许继续，后续凭据数量还会按 0 处理。
- **期望反馈：** 在步骤顶部显示 inline error 和重试按钮；未取得权威应用快照前禁用依赖该快照的继续操作。
- **重复提示风险：** 低。此处应使用步骤内 inline，不需要 toast。
- **干净修复：** 在向导根组件建立 `loading/error/ready` 三态，只在 `ready` 时渲染已有应用摘要和后续步骤。

### TF-03：应用启用/停用失败完全静默

- **严重度：高**
- **置信度：高**
- **证据：** `frontend/src/pages/console/ConsoleAppList.tsx:63-70` 的 `updateStatusMutation` 只有 `onSuccess`；`frontend/src/pages/console/ConsoleAppList.tsx:121-128` 直接触发 mutation，页面未渲染其 error。
- **用户操作与失败场景：** 管理员启用或停用应用；请求因权限、并发冲突、网络或后端校验失败。
- **当前行为：** 按钮结束忙碌状态，Badge 保持原值，没有任何解释。
- **期望反馈：** 显示“应用状态更新失败”的 error toast，并带后端安全文案；成功可由 Badge 更新承担。
- **重复提示风险：** 低。不要再增加常驻页面 banner。
- **干净修复：** 为该行级 mutation 增加唯一 `onError` toast，并以 app key 作为去重键。

### TF-04：应用删除失败完全静默

- **严重度：高**
- **置信度：高**
- **证据：** `frontend/src/pages/console/ConsoleAppList.tsx:71-80` 的 `deleteMutation` 没有 `onError`；`frontend/src/pages/console/ConsoleAppList.tsx:258-266` 的确认框也没有错误属性。
- **用户操作与失败场景：** 管理员确认删除应用；后端因关联数据、权限、并发或网络问题拒绝。
- **当前行为：** 确认框仍然打开，但没有错误说明，用户只能猜测是否需要重试。
- **期望反馈：** 首选在确认框内显示错误，因为用户仍停留在该决策上下文；也可选择单一持久 error toast。
- **重复提示风险：** 高。确认框 inline 与 toast 必须二选一。
- **干净修复：** 让确认框支持 `errorMessage`，将 `deleteMutation.error` 传入；成功后关闭确认框并刷新列表。

### TF-05：Scope 启用/停用失败完全静默

- **严重度：高**
- **置信度：高**
- **证据：** `frontend/src/pages/console/workspace/tabs/CatalogTab.tsx:133-142` 的 `toggleScopeMutation` 没有 `onError`；触发入口位于 `frontend/src/pages/console/workspace/tabs/CatalogTab.tsx:198-205`。页面只渲染创建/编辑表单错误，没有读取开关错误。
- **用户操作与失败场景：** 管理员切换某个 Scope 状态；请求失败。
- **当前行为：** 状态不变，没有提示。
- **期望反馈：** 使用行级 error toast；成功由 Badge 更新承担。
- **重复提示风险：** 低。
- **干净修复：** 增加带 scope key 的去重 toast，并在 mutation pending 时只禁用目标行或明确当前目标。

### TF-06：用户搜索失败被误报为“没有结果”

- **严重度：高**
- **置信度：高**
- **证据：** `frontend/src/components/UserSelect.tsx:22-39` 发起候选用户查询；`frontend/src/components/UserSelect.tsx:58-81` 的 `OptionList` 不接收 error，查询结束且数组为空时一律显示空结果。单选在 `frontend/src/components/UserSelect.tsx:123-180`，多选在 `frontend/src/components/UserSelect.tsx:204-207` 使用同一路径。
- **用户操作与失败场景：** 用户在应用所有者、审批人、交接接收人等选择器中搜索；搜索 API 失败。
- **当前行为：** 下拉框显示“无结果”，把系统故障伪装成业务空集合。
- **期望反馈：** 下拉框内显示 inline error 和重试入口；保留手输 ID 能力时也应明确“候选列表加载失败”。
- **重复提示风险：** 高。搜索会随输入和去抖重复请求，不应每次失败都弹 toast。
- **干净修复：** `OptionList` 接收 `error` 和 `onRetry`，错误态优先于空态；搜索 query 禁止接入全局逐次 toast。

### TF-07：两步验证状态加载失败时整个安全卡片消失

- **严重度：高**
- **置信度：高**
- **证据：** `frontend/src/pages/console/TwoFactorSection.tsx:45-53` 把 `!status` 和权威 `supported=false` 合并为 `return null`，完全不读取 `statusQuery.error`。
- **用户操作与失败场景：** 本地管理员进入设置页；两步验证状态 API 失败。
- **当前行为：** 两步验证卡片完全不出现，和“不支持此功能”无法区分。
- **期望反馈：** 查询失败显示区块级 inline error 与重试；只有成功响应明确 `supported=false` 才隐藏卡片。
- **重复提示风险：** 低。此处不应再弹 toast。
- **干净修复：** 把状态拆为 `loading/error/unsupported/ready` 四态，并为 error 提供重试按钮。

### TF-08：连接器运行记录加载或轮询失败被显示为空数据/旧数据

- **严重度：高**
- **置信度：高**
- **证据：** `frontend/src/pages/console/workspace/tabs/ConnectorTab.tsx:935-950` 每 30 秒查询一次；`frontend/src/pages/console/workspace/tabs/ConnectorTab.tsx:951-958` 无条件把缺失数据降为空数组；`frontend/src/pages/console/workspace/tabs/ConnectorTab.tsx:989-992` 空数组直接显示“无运行记录”，从未读取 `runsQuery.error`。
- **用户操作与失败场景：** 用户查看同步记录；初次请求失败，或已有数据时后台轮询失败。
- **当前行为：** 初次失败显示假空态；后台失败继续展示陈旧数据且无“已过期”警告。
- **期望反馈：** 首次失败使用区块 inline error；有旧数据时显示“刷新失败，以下数据可能已过期”的 inline warning。
- **重复提示风险：** 极高。禁止每 30 秒产生 toast。
- **干净修复：** 显式区分 `initialLoading`、`initialError`、`ready`、`staleError`，保留旧数据但标出最后成功更新时间。

### TF-09：凭据旧错误会遮蔽后续新失败

- **严重度：高**
- **置信度：高**
- **证据：** `frontend/src/pages/console/workspace/credentials/useCredentialsActions.ts:147` 用固定优先级 `create ?? rotate ?? disable` 合并三个 mutation 错误；`frontend/src/pages/console/workspace/credentials/useCredentialsActions.ts:149-153` 只在关闭密钥弹窗时 reset 创建和轮换，且创建失败时没有密钥弹窗可关闭；`frontend/src/pages/console/workspace/tabs/CredentialsTab.tsx:61-66` 只监听合并后的 `operationError`。
- **用户操作与失败场景：** 创建凭据失败后，再轮换或停用凭据且第二次也失败；或轮换失败后再停用失败。
- **当前行为：** 旧错误对象持续占据合并结果，后一次错误不会触发新的 effect，用户收不到本次失败反馈。
- **期望反馈：** 每个 mutation 的每次失败都对应一次准确 toast，且包含操作类型和目标凭据。
- **重复提示风险：** 高。改成各 mutation `onError` 后必须移除现有聚合 effect。
- **干净修复：** 删除固定 `??` 错误聚合；在各 mutation 内发出带 operation key 的错误事件，或在每次操作开始前精确 reset 该 mutation。

### TF-10：剪贴板失败或不可用时仍显示“已复制”

- **严重度：高**
- **置信度：高**
- **证据：** `frontend/src/components/CodeBlock.tsx:19-24` 不等待也不捕获 `writeText`，即使 `navigator.clipboard` 不存在也立即 `setCopied(true)`；`frontend/src/components/CodeBlock.tsx:33-38` 随即显示“已复制”。
- **用户操作与失败场景：** 用户复制一次性密钥、令牌、curl 或配置片段；浏览器拒绝剪贴板权限、页面不是安全上下文或 Clipboard API 不存在。
- **当前行为：** UI 明确宣称已复制，但剪贴板可能完全没有变化。对一次性秘密尤其危险。
- **期望反馈：** 仅 Promise 成功后显示按钮内“已复制”；失败时显示 error toast 或按钮旁 inline error。
- **重复提示风险：** 中。成功已经有按钮内状态，不要再弹 success toast。
- **干净修复：** `await navigator.clipboard.writeText`；不存在或 reject 时进入失败分支，不改变 copied 状态，并提供安全的手动复制提示。

### TF-11：紧急撤权没有撤销任何授权时仍提示成功

- **严重度：高**
- **置信度：高**
- **证据：** `src/easyauth/admin_console/operations_api.py:155-180` 在 `GrantService.revoke_grant()` 返回 `None` 时令 `revoked_count=0`，仍返回 `status: "accepted"`；`src/easyauth/grants/services.py:78-96` 明确允许 `None`。前端 `frontend/src/pages/console/OperationsPage.tsx:168-181` 不读取返回值，任何 2xx 都显示“紧急撤权完成”。
- **用户操作与失败场景：** 列表数据陈旧、并发撤权或用户重复提交后，目标当前授权已经不存在。
- **当前行为：** 没有任何状态变化，却显示 success toast。
- **期望反馈：** 后端快速失败并返回 409/422“当前授权已不存在”；前端显示 warning 或 conflict toast 并刷新列表。
- **重复提示风险：** 低。不得同时保留现有 success toast。
- **干净修复：** 从后端正本清源：`revoked_count=0` 不应使用 accepted 成功语义；前端按结构化结果决定 success/warning。

### TF-12：控制台审批“决定已提交但授权落库失败”被当成普通失败

- **严重度：高**
- **置信度：高**
- **证据：** `src/easyauth/access_requests/approvals.py:271-291` 在决定已提交后，把授权失败包装为 `decision_committed=true`；`src/easyauth/access_requests/application.py:27-28` 的对外消息仍是英文技术文案。控制台 `src/easyauth/admin_console/operations_approvals_api.py:123-144` 把该复合结果落入普通 422，未附最新实体；门户已有正确先例，见 `src/easyauth/portal/approvals_api.py:165-180`。前端 `frontend/src/pages/console/OperationsPage.tsx:123-141` 只特殊处理 409，`frontend/src/pages/console/OperationsPage.tsx:309-320` 因而保留旧弹窗。
- **用户操作与失败场景：** 管理员批准申请，审批决定已经持久化，但授权落库失败或在落库前过期。
- **当前行为：** 弹窗显示英文普通失败并保持可提交，列表不刷新，用户可能重复批准已经决定的申请。
- **期望反馈：** 关闭弹窗、刷新列表，显示持久 error/warning：“审批决定已提交，但授权落库失败/已过期”，并引导到“重试授权”。
- **重复提示风险：** 高。复合结果只能由专门分支消费，不能再走普通 mutation error。
- **干净修复：** 控制台 API 对齐门户的 `application_error` 契约，返回稳定 code、中文 message、`decision_committed` 和最新申请快照；前端显式处理该 code。

## 4. 中严重度缺口

### TF-13：网络错误和损坏 JSON 未被统一成稳定用户文案

- **严重度：中高**
- **置信度：高**
- **证据：** `frontend/src/lib/api.ts:97-100` 直接 `await fetch`，不包装网络 `TypeError`；`frontend/src/lib/api.ts:154-160` 对 JSON 直接调用 `response.json()`，解析失败会在 `buildApiError` 前抛出 `SyntaxError`；中文状态文案只在 `frontend/src/lib/api.ts:166-195` 的正常错误构建路径生效。
- **用户操作与失败场景：** 断网、DNS、CORS、请求被浏览器阻止，或网关返回声明为 JSON 但内容损坏的响应。
- **当前行为：** 现有 inline/toast 会显示浏览器原生英文，如 `Failed to fetch` 或 JSON 解析器错误，并丢失 HTTP status。
- **期望反馈：** 下游继续沿用各自的 inline/toast，但收到稳定中文：“网络连接失败，请检查网络后重试”或“服务响应格式异常”。
- **重复提示风险：** 中。传输层只归一化错误，不直接 toast。
- **干净修复：** 在 `apiRequest` 内分别捕获 fetch 和解析异常，构造带 `cause`、status、code 的 `ApiError`；原始异常仅用于日志和监控。

### TF-14：根节点没有 React 错误边界

- **严重度：中高**
- **置信度：高**
- **证据：** `frontend/src/main.tsx:24-35` 直接在 Provider 中渲染 `App`；`frontend/src/App.tsx:55-99` 的路由树没有错误边界，全仓无 `ErrorBoundary` / `componentDidCatch`。
- **用户操作与失败场景：** 任一路由组件 render、响应解析或状态派生抛出异常。
- **当前行为：** React 子树可能整体卸载或显示空白，仅浏览器控制台有错误。
- **期望反馈：** 使用路由或 AppShell 级 `PageState`，提供刷新、回列表和重新登录入口；toast 只用于补充说明。
- **重复提示风险：** 低。边界按一次崩溃进入回退界面；不要在每次重渲染重复 toast。
- **干净修复：** 增加根级边界和页面级边界，记录关联标识，在降级页面中保留壳层导航和恢复动作。

### TF-15：字段级校验信息被困在 `details`，表单只显示“参数无效”

- **严重度：中高**
- **置信度：高**
- **证据：** `src/easyauth/admin_console/apps_api.py:215-218,522-528` 把 Pydantic 原因序列化为 `details.errors` 字符串，顶层只有“应用参数无效”；前端 `frontend/src/lib/api.ts:184-192` 虽保存 `ApiError.details`，创建应用却只把 `error.message` 传入表单，见 `frontend/src/pages/console/ConsoleAppList.tsx:248-255`。`frontend/src/` 中除门户复合审批外几乎没有消费 `ApiError.details`。
- **用户操作与失败场景：** `app_key` 格式、长度、名称或成员字段校验失败。
- **当前行为：** 对话框底部只显示泛化 banner，用户不知道应修改哪个字段。
- **期望反馈：** 这是字段级 inline error 场景，不应使用 toast；每个字段显示可行动中文错误，表单顶部可保留摘要。
- **重复提示风险：** 高。字段 inline、表单摘要和 toast 不应三重播报。
- **干净修复：** 一次性统一后端 `details.field_errors` 结构，不再返回 `str(ValidationError)`；前端提供公共字段错误映射器。

### TF-16：手动对账返回 `queued=false` 仍宣称“已入队”

- **严重度：中**
- **置信度：高**
- **证据：** `src/easyauth/admin_console/connectors_api.py:286-307` 返回真实 `queued`；`src/easyauth/connectors/dispatch.py:35-52` 表明 `false` 代表没有新投递。前端 `frontend/src/pages/console/workspace/tabs/ConnectorTab.tsx:244-260` 不解析 payload，任何 202 都显示“对账任务已入队”。
- **用户操作与失败场景：** 用户在已有活跃/已合并任务时再次点手动对账。
- **当前行为：** UI 声称新任务已入队，实际可能只是合并到既有 generation，或没有新增投递。
- **期望反馈：** `queued=true` 用 success；合并到既有任务用 info：“已合并到进行中的对账”。
- **重复提示风险：** 中。两种结果必须互斥，且刷新运行记录不应再弹第二个 toast。
- **干净修复：** 后端改为清晰的 `dispatch_state: queued|coalesced`，前端解析并选择 tone；不要长期保留含混布尔语义。

### TF-17：应用通知通道测试只返回泛化失败，无法指导修复

- **严重度：中**
- **置信度：高**
- **证据：** `src/easyauth/admin_console/notification_channel_api.py:124-131` 捕获所有 `DingTalkApiError` 后统一返回“连通性测试失败”；`frontend/src/pages/console/workspace/tabs/IntegrationTab.tsx:254-265` 只能把该句放进 error toast。
- **用户操作与失败场景：** 管理员测试通道，实际原因可能是凭据拒绝、权限不足、超时或上游不可用。
- **当前行为：** 反馈存在，但没有任何可行动诊断。
- **期望反馈：** toast 标题说明测试失败，正文根据安全的稳定 code 提示“检查凭据”或“上游暂不可用，请稍后重试”。
- **重复提示风险：** 低。仍只保留一个 toast。
- **干净修复：** 后端将异常分类为有限诊断 code/details，不回显敏感原始异常；前端按 code 选择中文行动建议。

### TF-18：上传文件读取失败没有反馈

- **严重度：中**
- **置信度：高**
- **证据：** `frontend/src/pages/console/onboarding/AppOnboardingWizard.tsx:622-634` 和 `frontend/src/pages/console/workspace/tabs/ManifestTab.tsx:163-176` 都只有 `file.text().then(...)`，没有 catch。
- **用户操作与失败场景：** 用户选择 Manifest 文件，但浏览器读取失败、文件句柄失效或读取 Promise reject。
- **当前行为：** 内容框不变化，并产生未处理 Promise rejection；用户不知道文件没有读入。
- **期望反馈：** 文件控件附近显示 inline error；也可使用单一 error toast。
- **重复提示风险：** 中。两种反馈二选一。
- **干净修复：** 用 `try/catch` 等待 `file.text()`，仅在当前 file request id 匹配时更新成功或错误状态，并允许重新选择同一文件。

### TF-19：Manifest 导出使用页面导航，失败会把用户带离工作台

- **严重度：中**
- **置信度：高**
- **证据：** `frontend/src/pages/console/workspace/tabs/ManifestTab.tsx:182-189` 直接调用 `window.location.assign` 请求导出 API。
- **用户操作与失败场景：** 用户导出清单；API 返回 401、403、404 或 5xx。
- **当前行为：** SPA 被替换成 JSON/错误页，原页面无法提供进行中、失败或重试反馈。
- **期望反馈：** 在原页面显示下载中；失败用 error toast；成功由浏览器下载行为本身反馈，无需 success toast。
- **重复提示风险：** 低。
- **干净修复：** 使用 `apiRequest` 的 Blob/下载专用分支获取文件，校验响应后通过临时链接下载；401 交给统一会话失效流程。

### TF-20：交接权限明细失败后静默降质，仍允许确认

- **严重度：中**
- **置信度：高**
- **证据：** `frontend/src/pages/console/lifecycle/HandoverTaskDetail.tsx:384-390` 查询 grant items 并用空数组构建名称映射；页面只展示 templates query 错误，见 `frontend/src/pages/console/lifecycle/HandoverTaskDetail.tsx:447-449`，未展示 grant-items 错误；后续构建和确认仍可操作，见 `frontend/src/pages/console/lifecycle/HandoverTaskDetail.tsx:463-515`。
- **用户操作与失败场景：** 用户审阅转岗授权差异；grant-items 请求失败。
- **当前行为：** 权限名称可能退化为 key，用户不知道审阅信息不完整，仍可确认。
- **期望反馈：** 面板内 inline warning/error 与重试；若该数据是确认依据，应在权威查询成功前禁用确认。
- **重复提示风险：** 低。不要使用页面级 toast。
- **干净修复：** 把 `templatesQuery` 和 `grantItemsQuery` 合并为明确的“名称解析数据就绪”门禁。

### TF-21：Toast 对持久错误没有去重、替换或数量上限

- **严重度：中**
- **置信度：高**
- **证据：** `frontend/src/components/ui/Toast.tsx:54-60` 让 error toast 永久保留；`frontend/src/components/ui/Toast.tsx:126-136` 每次都无条件 append；`frontend/src/components/ui/Toast.tsx:209-225` 渲染全部队列。
- **用户操作与失败场景：** 用户反复重试同一个失败动作，或批量操作多项失败。
- **当前行为：** 相同错误无限堆叠；后续操作成功后，旧错误仍停留并与新状态冲突。
- **期望反馈：** 同一操作和目标的错误替换或去重；设置可见数量上限；成功时可关闭同 operation key 的旧错误。
- **重复提示风险：** 本项本身就是重复提示根因。
- **干净修复：** Toast API 增加稳定 key、`replace` 和 `dismissByKey`；error 保持持久语义，但队列需要上限或折叠。

### TF-22：全局没有“仅处理未消费 mutation 错误”的兜底

- **严重度：中**
- **置信度：高**
- **证据：** `frontend/src/lib/query.ts:3-9` 只设置 query staleTime 和窗口聚焦策略，没有 `QueryCache`/`MutationCache` 错误钩子，也没有默认 mutation 错误策略。TF-03、TF-04 和 TF-05 因此可以完全静默。
- **用户操作与失败场景：** 新增 mutation 时开发者遗漏 `onError` 和 error 渲染。
- **当前行为：** 没有架构级检查或运行时最后防线。
- **期望反馈：** 未被局部消费的交互 mutation 至少有一个通用 error toast；查询错误仍由页面 inline 处理。
- **重复提示风险：** 极高。无条件全局 `onError` 会与现有几十个局部 toast/inline 双报。
- **干净修复：** 优先通过封装和测试强制 mutation 声明反馈策略；若增加全局钩子，mutation meta 必须标注 `feedback: inline|toast|silent-background`，全局只处理未声明或未消费项。

### TF-23：登录失效只有错误文字，没有统一恢复动作

- **严重度：中**
- **置信度：高**
- **证据：** 后端 `src/easyauth/admin_console/request_guards.py:16-23` 对 API 返回结构化 401“控制台登录已失效”；前端 `frontend/src/lib/api.ts:184-195` 只构造普通 `ApiError`，`frontend/src/lib/query.ts:3-9` 没有 401 策略。`frontend/src/App.tsx:49-75` 的跳转只处理首次渲染时没有用户，不处理运行中会话过期。
- **用户操作与失败场景：** 用户编辑较久后提交，服务端会话已经过期。
- **当前行为：** 局部 banner 或 toast 只显示“登录已失效”，没有“重新登录”按钮；不同页面表现不一致。
- **期望反馈：** 全局只显示一个持久的会话失效提示，提供“重新登录并返回当前页”；有未保存内容时避免无提示强制跳转。
- **重复提示风险：** 极高。多个并发 query 可能同时返回 401，必须合并为单次提示。
- **干净修复：** 在 API 层发出统一的会话失效事件，由壳层展示单一 modal/banner 和登录动作；不要让每个 query 各弹 toast。

### TF-24：管理范围策略保存成功缺少明确确认

- **严重度：中**
- **置信度：高**
- **证据：** `frontend/src/pages/console/ConsoleAppWorkspace.tsx:215-227` 的保存成功只更新 query cache；`frontend/src/pages/console/ConsoleAppWorkspace.tsx:254-275` 有保存按钮和失败 inline banner，没有成功反馈。
- **用户操作与失败场景：** 用户保存与当前有效值相同或视觉差异很小的策略。
- **当前行为：** 按钮结束 loading，但没有明确“已保存”，用户难以确认请求是否落库。
- **期望反馈：** success toast；失败继续留在当前面板 inline。
- **重复提示风险：** 低。不要再增加长期成功 banner。
- **干净修复：** `onSuccess` 更新 cache 后发单一 success toast，并清理同 operation key 的旧错误。

### TF-25：重要的两步验证变更成功只关闭对话框

- **严重度：中**
- **置信度：高**
- **证据：** TOTP 启用 `frontend/src/pages/console/TwoFactorSection.tsx:220-225`、停用 `frontend/src/pages/console/TwoFactorSection.tsx:301-306`、Passkey 新增 `frontend/src/pages/console/TwoFactorSection.tsx:471-481`、删除 `frontend/src/pages/console/TwoFactorSection.tsx:560-565` 均只更新状态并关闭对话框。
- **用户操作与失败场景：** 用户完成高风险安全设置变更。
- **当前行为：** 页面行状态会变化，但缺少明确、短暂的操作确认。
- **期望反馈：** 显示具体动作的 success toast，例如“验证器已启用”“通行密钥已移除”；失败继续在对话框内 inline。
- **重复提示风险：** 低。状态行更新不算重复播报，不需要再加成功 banner。
- **干净修复：** 在成功回调中传递操作结果给父组件，由父组件统一发安全设置 success toast。

## 5. 低严重度缺口

### TF-26：门户待审批角标失败被当成 0 条

- **严重度：低**
- **置信度：高**
- **证据：** `frontend/src/components/shell/Sidebar.tsx:72-84` 不读取 query error，并用 `total_items ?? 0` 生成空角标。
- **用户操作与失败场景：** 门户侧边栏加载待审批数量失败。
- **当前行为：** 角标消失，和真实 0 条无法区分。
- **期望反馈：** 角标显示未知/警告态，悬停提示“待审批数量获取失败”；通常不需要 toast。
- **重复提示风险：** 高。该查询可能后台重取，不应重复 toast。
- **干净修复：** 为角标增加 `unknown` 状态和 tooltip；进入审批页后由页面查询提供完整错误反馈。

## 6. 已有反馈链路与不应误改的场景

以下路径已经采用合理反馈方式，不建议为了“统一用 toast”而改成重复提示：

- `frontend/src/pages/console/OperationsPage.tsx:122-155,309-363`：普通审批/改派/重试/紧急撤权的对话框错误已以内联方式展示，409 另用 warning toast；
- `frontend/src/pages/portal/components/PortalApprovalsSection.tsx:152-183,223-269`：门户审批能识别决定已提交的复合结果，并通过页面内状态更新；
- `frontend/src/pages/console/lifecycle/HandoverWizard.tsx:181-245,429-460`：预览、执行和步骤保存错误均在对应应用或步骤内展示；
- `frontend/src/pages/console/workspace/tabs/ConnectorTab.tsx:162-193`：连接测试会区分 `ok=true/false`，成功和失败 tone 正确；
- `frontend/src/pages/console/ConsoleSettingsPage.tsx:57-77,173-215`：集成设置保存和钉钉测试均有成功/失败 toast；
- `frontend/src/pages/console/workspace/tabs/OverviewTab.tsx:49-69,141-192`：成员创建错误在对话框内展示，停用错误在区块内展示，属于合理 inline；
- `frontend/src/pages/console/ApprovalTemplatesPage.tsx:511-633` 和 `frontend/src/pages/console/workspace/tabs/QueryTestTab.tsx:39-103`：测试动作的结果长期留在当前工作区，inline 比 toast 更合适；
- `frontend/src/components/ui/Toast.tsx:54-60,209-250`：错误持久、成功短暂以及 `aria-live`/`role` 基础语义已经存在，应保留。

## 7. 建议的统一修复顺序

### 第一批：消除假成功和完全静默

1. 修复 TF-01、TF-11、TF-12、TF-16 的后端/前端结果契约；
2. 修复 TF-03、TF-04、TF-05、TF-07、TF-09；
3. 修复 TF-06、TF-08 的“错误伪装为空数据”；
4. 修复 TF-10 的剪贴板假成功。

### 第二批：统一错误基础设施

1. 在 `apiRequest` 中实现 TF-13 的网络、JSON 和响应类型归一化；
2. 增加 TF-14 错误边界和 TF-23 会话失效单次提示机制；
3. 按 TF-22 为 mutation 声明反馈策略；
4. 按 TF-21 给 toast 增加 key、替换和上限。

### 第三批：提高可行动性和重要状态确认

1. 统一 TF-15 的 `details.field_errors`；
2. 补齐 TF-17、TF-18、TF-19、TF-20；
3. 增加 TF-24、TF-25 的重要成功确认；
4. 最后处理 TF-26 的角标未知态。

## 8. 验收要求

修复后至少应满足：

- 每个 mutation 必须声明 `inline`、`toast` 或 `silent-background` 反馈策略；
- 任何失败都不能被渲染为正常空态、成功色或成功 toast；
- 复合结果必须区分“动作未提交”和“动作已提交但后续步骤失败”；
- 后台轮询失败不得周期性刷 toast；
- 字段校验优先字段 inline，不把 Pydantic 原始字符串直接交给用户；
- 401 并发响应只能产生一个重新登录提示；
- 相同 operation key 的持久错误 toast 不得无限堆叠；
- 文件读取、剪贴板和下载都必须等待真实结果后再显示成功；
- 重要安全设置变更完成后有明确成功确认；
- 新增反馈必须补充成功、失败、重复触发和可访问性回归测试。
