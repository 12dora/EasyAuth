# 前后端跨层契约审计

审计日期：2026-07-27

审计范围：门户与管理控制台的 Django 路由、请求校验、响应序列化、错误信封、认证与 CSRF、React 请求封装、领域类型、运行时解析、React Query 缓存失效、分页和筛选，以及对应测试与 API 文档。

审计原则：以当前 schema、领域不变量和 API 事实为唯一权威；发现错误形态时一次性修正所有调用方，不保留兼容字段、兼容枚举、静默默认值或空结果兜底。

## 结论摘要

共发现 9 项跨层契约问题：3 项高严重度、5 项中严重度、1 项低严重度。

最高优先级问题是：

1. 后端领域和 API 已支持 `grant`、`change`、`revoke`、`renew` 四类申请，但门户只能生成 `grant`。
2. 成员、凭据等写操作会改变应用详情和配置就绪度，前端却只失效局部列表缓存，导致页面继续展示旧权限配置事实。
3. 通用列表响应在生产环境遇到缺失或错误的 `data` 时被转换成空数组，把契约破坏伪装成“没有数据”。

此外，撤回能力没有门户入口、查询参数校验口径不统一、应用选择器截断第 101 个及之后的应用、申请状态枚举漂移、会话过期后没有统一重新认证流程，以及公开的 `AppUpdatePayload` 与后端 PATCH schema 矛盾。

## 验证口径

- 本轮以源码、既有集成测试和前端测试为证据，未修改业务代码或测试。
- 已检查统一错误响应、非 JSON 响应处理、Cookie 会话、CSRF token 注入、列表与分页信封、主要写操作的缓存失效范围。
- 本报告中的复现场景是根据可达路由、请求构造、序列化和渲染路径进行的确定性代码推演；本轮未启动浏览器执行端到端验证。
- 每项发现都给出前端与后端的精确文件和行号。对“缺少入口”类问题，以后端可达路由和前端完整渲染区域作为两侧证据。

## 发现清单

### CTR-01：门户只会提交 `grant`，丢失后端已经实现的三类授权生命周期申请

- 严重度：**高**
- 置信度：**高**
- 受影响契约：申请类型枚举、申请表单状态、提交 payload、授权生命周期。
- 后端证据：
  - `src/easyauth/access_requests/models.py:16-31` 定义 `grant`、`change`、`revoke`、`renew` 四个正式领域值。
  - `src/easyauth/portal/access_request_payloads.py:17-42` 的请求 schema 接受四种 `request_type`。
  - `tests/integration/portal/test_portal_api_ops4.py:29-80` 逐一验证 `change`、`revoke`、`renew` 能创建对应申请且不会直接改写当前授权。
- 前端证据：
  - `frontend/src/pages/portal/hooks/useAccessRequestForm.ts:93-102` 的表单值模型没有 `requestType`，也没有当前授权目标。
  - `frontend/src/pages/portal/hooks/useAccessRequestForm.ts:498-514` 在构造 payload 时把 `request_type` 固定为 `"grant"`。
  - `docs/api/easyauth-portal-react-api.md:116-124` 已将四类值写成公开 API 契约，文档与门户能力不一致。
- 用户/API 复现场景：
  1. 员工已有某应用当前授权，需要变更权限、撤销授权或续期。
  2. 打开门户申请页，页面没有操作类型或当前授权选择。
  3. 无论用户如何选择权限和期限，浏览器都发送 `request_type: "grant"`；三个后端合法业务动作无法从正式门户触发。
- 根因：后端完成了授权生命周期领域扩展，但前端仍沿用“新申请”单一命令模型；枚举只存在于 Python 与文档，没有成为跨层共享契约。
- 第一性修复：
  - schema/领域：把四类申请建模为明确的生命周期命令，并定义每类命令所需的当前授权、目标授权、期限和空集合不变量。
  - API：保留一个权威请求 schema，但按 `request_type` 使用可判别联合校验，拒绝与类型无关或缺失的字段。
  - 前端：以用户意图选择对应流程；`change`、`revoke`、`renew` 必须从当前授权事实出发，而不是复用空白 `grant` 表单。
  - 测试：增加四类门户交互到真实 API payload 的契约测试，并验证当前授权归属、选择差异和提交后状态。
  - 文档：分别给出四类请求的字段、不变量和用户流程；删除“一个 grant 表单代表全部申请”的隐含口径。

### CTR-02：后端提供申请撤回端点，门户“我的申请”没有可执行入口

- 严重度：**中**
- 置信度：**高**
- 受影响契约：申请状态机、用户可执行动作、幂等写操作。
- 后端证据：
  - `src/easyauth/portal/urls.py:23-32` 注册 `POST /portal/api/v1/me/access-requests/{request_id}/withdraw`。
  - `src/easyauth/portal/api.py:125-169` 校验当前用户、方法和状态冲突，并返回更新后的 `access_request`。
  - `tests/integration/portal/test_access_request_withdraw.py:23-53` 验证申请人可幂等撤回 `submitted` 申请，结果为 `withdrawn`。
- 前端证据：
  - `frontend/src/pages/portal/PortalPage.tsx:123-171` 构建“我的申请”查询和全部表格列，只有状态、应用、权限、期限、时间和原因，没有动作列或撤回 mutation。
  - `frontend/src/pages/portal/PortalPage.tsx:173-193` 只处理读取失败、空状态和表格渲染，没有调用撤回端点的路径。
- 用户/API 复现场景：
  1. 员工提交申请后发现原因或授权范围填写错误。
  2. “我的申请”仍显示 `submitted`，但没有“撤回”动作。
  3. 同一用户直接调用后端端点可以成功撤回，说明是前端能力断层而非领域限制。
- 根因：撤回被实现为孤立 API，申请状态机没有同时投影为前端的“允许动作”契约。
- 第一性修复：
  - schema/领域：为申请状态定义唯一的动作能力，如 `submitted -> withdraw`，由领域规则决定，而不是页面自行猜测。
  - API：列表项返回基于当前操作者计算的明确动作集合，或提供同一来源的状态机元数据。
  - 前端：仅在权威动作允许时显示撤回，提交成功后原子更新该行并失效申请列表。
  - 测试：覆盖允许撤回、重复撤回、终态冲突、非本人不可见，以及成功后按钮与状态同步变化。
  - 文档：把端点说明与门户用户流程放在同一章节，明确可见条件和冲突语义。

### CTR-03：成员和凭据写入没有失效应用详情与配置就绪度缓存

- 严重度：**高**
- 置信度：**高**
- 受影响契约：React Query 缓存键、应用详情聚合、配置就绪度、写后读一致性。
- 后端证据：
  - `src/easyauth/admin_console/apps_api.py:412-437` 每次读取应用详情都会重新计算 owner、授权组数、权限数、有效凭据数和配置摘要。
  - `src/easyauth/admin_console/apps_api.py:452-462` 的 owner 列表直接来自有效成员关系；`src/easyauth/admin_console/apps_api.py:494-497` 的有效凭据数直接来自两类凭据记录。
  - `src/easyauth/applications/configuration.py:51-92` 把有效权限、授权组、owner 和凭据都作为配置就绪度事实。
  - `src/easyauth/admin_console/memberships_api.py:75-108`、`111-143` 会创建或更新上述成员事实。
- 前端证据：
  - `frontend/src/pages/console/ConsoleAppWorkspace.tsx:59-64` 把应用聚合详情缓存为 `["console", "app", appKey]`。
  - `frontend/src/pages/console/workspace/tabs/OverviewTab.tsx:35-48` 把就绪度和成员分别缓存为 `configuration-status` 与 `memberships`。
  - `frontend/src/pages/console/workspace/tabs/OverviewTab.tsx:49-68` 创建或停用成员成功后只失效 `memberships`。
  - `frontend/src/pages/console/workspace/credentials/useCredentialsActions.ts:36-55`、`84-118` 创建、轮换或停用凭据后只失效 `credentials`。
  - `frontend/src/lib/query.ts:3-8` 设置 30 秒 `staleTime` 且关闭窗口聚焦刷新，旧聚合值不会被其他机制立即纠正。
- 用户/API 复现场景：
  1. 打开一个因“缺少 owner”或“缺少有效凭据”而处于 `blocking` 的应用工作区。
  2. 在当前页面添加 owner 或创建凭据。
  3. 局部表格更新，但概览中的 owner、`active_credential_count`、阻断原因和配置状态继续显示旧值，直到缓存自然过期、手动刷新或重新挂载。
- 根因：前端以页面部件划分缓存失效范围，后端却把多个子资源聚合为同一个应用和就绪度事实；系统没有定义“某个命令会影响哪些查询投影”。
- 第一性修复：
  - schema/领域：列出应用配置聚合的全部事实来源，并把配置就绪度视为这些事实的派生读模型。
  - API：写操作成功后返回被改变的权威资源版本；若继续独立查询聚合，必须定义一致的资源版本或 ETag。
  - 前端：建立按领域影响而非按组件命名的失效函数；成员、凭据、权限、授权组和应用状态写入都必须失效应用根详情及 `configuration-status`。
  - 测试：使用真实 `QueryClient` 验证每种 mutation 后所有派生查询均被更新或失效，不能只断言局部列表刷新。
  - 文档：记录命令到读模型的影响矩阵，供新 mutation 和新缓存消费者共同遵守。

### CTR-04：列表响应契约破坏会在生产环境被伪装为空结果

- 严重度：**高**
- 置信度：**高**
- 受影响契约：列表信封、运行时解码、错误状态、空状态。
- 后端证据：
  - `src/easyauth/admin_console/api_payloads.py:11-20` 规定列表成功响应必须包含数组 `data`，分页列表还必须包含 `pagination`。
  - `src/easyauth/api/pagination.py:18-24` 规定分页对象四个必填字段。
- 前端证据：
  - `frontend/src/lib/api.ts:12-19` 的注释称其为统一信封，但类型把 `data` 和 `pagination` 都声明为可选。
  - `frontend/src/lib/api.ts:63-103` 对成功 JSON 只做泛型断言，没有运行时契约校验。
  - `frontend/src/lib/api.ts:105-117` 在 `data` 缺失或不是数组时返回共享空数组；警告只在开发环境触发。
  - `frontend/src/pages/console/ConsoleAppList.tsx:43-48` 使用该宽松路径读取应用；`frontend/src/pages/console/ConsoleAppList.tsx:225-246` 随后把空数组渲染成正常空状态。
  - `frontend/src/lib/api.test.ts:122-142` 明确把“缺少或错误 data 返回空数组”固化为预期行为。
- 用户/API 复现场景：
  1. 网关、后端重构或错误序列化返回 HTTP 200 和 `{ "items": [...] }`、`{}` 或 `{ "data": {} }`。
  2. 生产前端不抛出契约错误，把结果变成 `[]`。
  3. 用户看到“暂无应用/成员/权限”，无法区分真实空集合与服务端丢失数据。
- 根因：前端用宽松 TypeScript 类型和空数组兜底代替了边界解码；测试验证的是引用稳定性，而不是业务数据真实性。
- 第一性修复：
  - schema/领域：把列表成功响应定义为必填、不可歧义的 schema；分页端点与非分页端点使用不同的可验证类型。
  - API：所有列表只通过统一序列化器输出，并对响应 schema 进行契约测试。
  - 前端：在网络边界使用端点级运行时解码器；缺失、类型错误或分页字段不完整时抛出明确的契约错误并进入错误态。
  - 测试：把现有空数组兜底用例改为“畸形 200 响应必须失败”，并验证页面展示加载失败而不是空状态。
  - 文档：只记录唯一信封结构和字段必填性，不提供 `items`、缺失 `data` 等替代形态。

### CTR-05：查询参数校验口径分裂，非法参数可能被改写默认值或静默忽略

- 严重度：**中**
- 置信度：**高**
- 受影响契约：分页、筛选枚举、HTTP 422 错误语义。
- 后端证据：
  - `src/easyauth/portal/pagination.py:44-52` 读取门户分页参数；`79-94` 把非整数、非正数改成默认值，并把超上限值截断到上限。
  - `src/easyauth/admin_console/lifecycle_api.py:180-207` 仅在 `status` 和 `kind` 属于合法集合时应用筛选，非法值会被忽略并返回全量结果。
  - `src/easyauth/admin_console/apps_api.py:470-491` 对非法应用 `status` 同样返回未筛选集合。
  - 对比项目内已有正确口径：`src/easyauth/admin_console/operation_filters.py:219-254` 对非法分页值快速失败；`41-47` 将其转换为结构化 422。
- 前端证据：
  - `frontend/src/pages/portal/PortalPage.tsx:123-133` 直接把页码和页大小写入查询字符串，并相信响应中的分页事实。
  - `frontend/src/pages/console/lifecycle/HandoverTaskList.tsx:42-60` 把有限状态和类型写入 URL；服务端却没有对被篡改、旧书签或其他 API 客户端传入的非法枚举报错。
- 用户/API 复现场景：
  - 请求 `/portal/api/v1/me/access-requests?page=abc&page_size=0` 会以默认分页返回 200，而不是指出参数错误。
  - 请求 `/console/api/v1/lifecycle/handover-tasks?status=typo` 会返回所有任务，用户可能把未筛选结果当成 `typo` 状态结果。
- 根因：多个端点各自手写 query string 解析，把“缺失参数”和“出现但非法的参数”混为一谈。
- 第一性修复：
  - schema/领域：为分页和各筛选枚举建立统一的强类型查询 schema，明确缺失、空值、非法值和上限的不同语义。
  - API：所有端点复用同一解析器；参数出现但不合法时返回结构化 422，不截断、不忽略、不返回不可信结果。
  - 前端：只生成 schema 允许的查询值，并对 422 显示筛选错误；URL 恢复时先验证再请求。
  - 测试：为门户、应用列表和交接任务增加相同的非法值参数化测试，断言错误 code、field、value。
  - 文档：逐项写明默认值只适用于“参数缺失”，非法值一律 422。

### CTR-06：接入模板的应用选择器只读取第一页，超过 100 个应用时合法资源不可达

- 严重度：**中**
- 置信度：**高**
- 受影响契约：服务端分页、资源选择器、模板项创建。
- 后端证据：
  - `src/easyauth/admin_console/apps_api.py:136-152` 的应用列表始终经过分页并返回当前页。
  - `src/easyauth/admin_console/operation_filters.py:23-27` 把最大 `page_size` 定为 100；`100-121` 按页切片。
- 前端证据：
  - `frontend/src/pages/console/lifecycle/OnboardingPage.tsx:424-428` 固定请求 `page=1&page_size=100`，没有读取后续页。
  - `frontend/src/pages/console/lifecycle/OnboardingPage.tsx:468-486` 把这 100 条直接渲染成完整应用下拉框，没有分页或服务端搜索入口。
- 用户/API 复现场景：
  1. 系统存在 101 个及以上可见应用，目标应用按 `app_key` 排在第 101 位之后。
  2. 管理员创建接入模板并添加模板项。
  3. 目标应用永远不出现在选择器中；直接调用应用 API 第二页可以读取它。
- 根因：前端把“允许请求的最大页大小”误当成“全集大小”，忽略了分页响应的资源边界。
- 第一性修复：
  - schema/领域：把资源选择器定义为可搜索、可分页的数据源，而不是静态全集。
  - API：提供按 `app_key`/名称搜索且继续遵守统一分页的选择器查询。
  - 前端：使用服务端搜索与分页选择组件，或按分页元数据显式加载后续页；不得以固定 100 作为全集。
  - 测试：创建 101 个以上应用，验证末页应用可被选中并形成正确模板 payload。
  - 文档：说明选择器使用分页 API，不对应用总数作隐含上限承诺。

### CTR-07：申请状态枚举在后端、前端显示和筛选之间已经漂移

- 严重度：**中**
- 置信度：**高**
- 受影响契约：状态枚举、标签与色调、运营筛选、测试样例。
- 后端证据：
  - `src/easyauth/access_requests/models.py:33-57` 定义七个正式状态，包括 `grant_expired` 和 `withdrawn`。
  - `src/easyauth/portal/status_text.py:17-34` 为全部七个状态提供权威中文标签和色调。
- 前端证据：
  - `frontend/src/lib/status.ts:8-15` 的状态标签表缺少 `withdrawn`；`25-39` 的色调分支也缺少它。
  - `frontend/src/pages/console/OperationsPage.tsx:62-63` 的申请状态筛选缺少 `grant_expired` 和 `withdrawn`；`377-419` 只按该不完整数组渲染选项。
  - `frontend/src/pages/portal/portalListPayload.ts:109-133` 只验证 `status` 是字符串，没有验证它属于领域枚举。
  - `frontend/src/pages/portal/PortalPage.test.tsx:1856-1872` 仍使用后端不存在的 `"pending"` 作为申请状态测试样例。
- 用户/API 复现场景：
  1. 申请被撤回或批准后因超过期限变成 `grant_expired`。
  2. 门户在缺少后端 `status_label` 的任何响应路径中会显示原始 `withdrawn`，色调退化为中性；运营页无法从筛选器选择两种合法状态。
  3. 前端测试中的 `"pending"` 仍能通过解析，因此无法发现后端枚举变化。
- 根因：状态值在 Python 常量、前端映射、筛选数组和测试 fixture 中重复维护，没有单一 schema 来源。
- 第一性修复：
  - schema/领域：把申请状态定义为单一封闭枚举，并明确每个状态的终态、可执行动作和展示语义。
  - API：响应 schema 只输出该枚举；标签可作为展示辅助，但不能替代机器可验证状态。
  - 前端：从同一 schema 生成联合类型、筛选选项和穷尽映射；未知状态应触发契约错误，不显示原始内部值。
  - 测试：删除 `"pending"` fixture，参数化覆盖全部七个状态，并要求映射和筛选穷尽。
  - 文档：状态表从同一来源生成，记录状态迁移而不是手抄零散列表。

### CTR-08：API 会话过期只变成局部错误，前端没有进入重新认证流程

- 严重度：**中**
- 置信度：**高**
- 受影响契约：Cookie 会话生命周期、401、登录跳转、SPA 全局状态。
- 后端证据：
  - `src/easyauth/admin_console/request_guards.py:16-23` 在控制台 API 会话无效时返回结构化 `401 AUTHENTICATION_FAILED`。
  - `src/easyauth/admin_console/views.py:62-65` 对页面请求已有带 `next` 的登录跳转语义。
- 前端证据：
  - `frontend/src/lib/api.ts:63-102` 带 Cookie 发起请求，但所有非成功响应只被转换成 `ApiError`。
  - `frontend/src/lib/api.ts:166-195` 为 401 生成“请重新登录”文案，却没有发布认证失效事件、清空敏感缓存或跳转登录。
  - `frontend/src/components/AppShell.tsx:19-35` 的全局壳层没有认证失效边界，页面会继续保留失效会话下的旧内容。
- 用户/API 复现场景：
  1. 用户保持控制台或门户页面打开，服务端 session 到期。
  2. 用户执行刷新、翻页或写操作，API 返回 401。
  3. 当前组件显示错误，应用仍停留在原壳层；后续请求继续 401，用户只能自行刷新或手工访问登录页。
- 根因：后端定义了 401，但前端只把它当普通请求错误，没有把“身份已失效”建模为全局状态转换。
- 第一性修复：
  - schema/领域：把 `AUTHENTICATION_FAILED` 定义为全局认证状态事件，与业务 403 明确分离。
  - API：所有会话 API 统一返回同一 401 信封；页面路由统一保留安全的 `next`。
  - 前端：在单一网络边界捕获 401，停止后续受保护请求、清理身份相关查询缓存，并导航到登录页且保存当前内部路径。
  - 测试：覆盖读取和写入过程中 session 过期、并发多个 401 只触发一次重认证、403 不跳登录，以及登录后回到原路径。
  - 文档：明确 SPA 的 session 过期行为、`next` 语义和 401/403 区别。

### CTR-09：公开的 `AppUpdatePayload` 允许后端 PATCH 明确禁止的字段

- 严重度：**低**
- 置信度：**高**
- 受影响契约：应用更新命令、成员关系边界、TypeScript 领域类型。
- 后端证据：
  - `src/easyauth/admin_console/apps_api.py:111-116` 的 `AppPatchPayload` 只允许 `name`、`description`、`is_active`，并设置 `extra="forbid"`。
  - owner 和 developer 由独立成员关系 API 管理，相关写入入口见 `src/easyauth/admin_console/memberships_api.py:75-143`。
- 前端证据：
  - `frontend/src/lib/domain.ts:40-45` 的 `AppUpdatePayload` 额外声明 `owner_user_ids` 和 `developer_user_ids`。
  - `frontend/src/lib/api.ts:97-103` 的泛型断言无法阻止调用方把该类型直接发送给 PATCH 端点。
  - `frontend/src/lib/api.test.ts:145-160` 只扫描接口字段存在性，没有验证前后端写 schema 一致。
- 用户/API 复现场景：
  1. 新页面或重构代码按导出的 `AppUpdatePayload` 构造 `{ owner_user_ids: [...] }`。
  2. TypeScript 认为 payload 合法，但 `PATCH /console/api/v1/apps/{app_key}` 因额外字段返回校验错误。
  3. 同一操作必须改用成员 API，说明前端类型表达了不存在的能力。
- 根因：请求类型由前端手写并混合了应用属性与成员聚合展示字段，没有从后端命令 schema 生成。
- 第一性修复：
  - schema/领域：把应用属性更新与成员关系命令保持为两个明确边界。
  - API：继续快速拒绝额外字段，不扩展 PATCH 去迎合错误前端类型。
  - 前端：删除两个成员字段，调用成员 API 完成 owner/developer 变化；从权威 schema 生成写类型。
  - 测试：增加编译期契约测试和后端额外字段拒绝测试，确保生成类型与 Pydantic schema 同步。
  - 文档：把应用 PATCH 字段和成员端点分别列出，不把聚合详情字段描述为可写字段。

## 已确认一致的基础契约

下列实现当前前后端一致，修复上述问题时不应回退：

- 统一错误信封：`src/easyauth/api/errors.py:35-46` 输出 `{ error: { code, message, details } }`；`frontend/src/lib/api.ts:184-195` 按相同结构解析。
- CSRF：Django 壳层在 `src/easyauth/config/templates/easyauth/react_shell.html:12-17` 注入 token；`frontend/src/lib/api.ts:47-60` 读取，`90-95` 只对非安全方法附加 `X-CSRFToken`。
- Cookie 会话：`frontend/src/lib/api.ts:68-79` 使用 `credentials: "include"`；后端 API 通过 session actor 统一判定身份。
- 非 JSON 错误体：`frontend/src/lib/api.ts:151-195` 不把网关 HTML 或调试页原文展示给用户。
- 门户部分列表已使用严格运行时解析：`frontend/src/pages/portal/portalListPayload.ts:109-145` 会检查必填字段和数组结构。应把这种“边界失败”原则统一到全部端点，并进一步校验封闭枚举。

## 建议实施顺序

1. 先修 CTR-04，建立严格的成功响应解码和单一 schema 来源；这是其余契约修复可依赖的基础。
2. 同步修 CTR-01、CTR-02、CTR-07，完整打通申请类型、状态机、动作能力与门户交互。
3. 修 CTR-03，建立 mutation 到派生读模型的统一失效矩阵，覆盖成员、凭据、权限、授权组和应用状态。
4. 修 CTR-05、CTR-06，统一查询 schema，并让所有资源选择器真正遵守分页边界。
5. 修 CTR-08，在通用请求边界建立认证状态转换。
6. 最后清理 CTR-09 及 `frontend/src/lib/domain.ts:81-89`、`385-394` 等已经标明“历史兼容”的前端类型；项目尚未上线，应直接删除错误契约，不保留兼容路径。

## 跨层验收矩阵

| 层级 | 必须达到的验收结果 |
| --- | --- |
| schema | 请求、成功响应、错误响应、枚举、分页和筛选均有唯一权威定义，前后端类型由该定义生成或以契约测试锁定。 |
| 领域 | 四类申请、七个状态、允许动作、应用配置派生事实和成员边界均有明确不变量。 |
| API | 非法输入快速返回结构化错误；成功响应不缺字段；写操作后的资源版本和派生事实可确定读取。 |
| 前端 | 网络边界严格解码；未知枚举和畸形 200 响应进入错误态；分页不截断；401 进入全局重认证；mutation 失效全部受影响读模型。 |
| 测试 | 使用真实枚举和至少 101 条分页数据；覆盖四类申请、七个状态、撤回、session 过期、畸形响应和跨查询缓存一致性。 |
| 文档 | 只描述当前唯一契约，删除历史兼容形态；请求、响应、状态迁移、错误码和用户流程彼此一致。 |
