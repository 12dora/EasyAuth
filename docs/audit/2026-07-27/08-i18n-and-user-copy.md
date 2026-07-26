# 简体中文国际化与用户文案审计

审计日期：2026-07-27

审计范围：`frontend/src/`、Django 模板、会被前端或浏览器直接展示的后端消息、相关测试与 `frontend/src/i18n/messages.ts`。本报告不把纯代码标识符、内部日志、协议示例中的必要字段名或未进入用户界面的异常文本单独列为问题。

## 结论摘要

当前消息目录以 `zh-CN` 为事实源，并通过 `Record<MessageKey, string>` 在编译期约束英文目录的键集合，未发现“字典键缺失导致取值为 `undefined`”的问题，证据见 `frontend/src/i18n/messages.ts:9`、`frontend/src/i18n/messages.ts:1180`、`frontend/src/i18n/messages.ts:1182`。

但这并不等于界面已经完整国际化。主要风险如下：

- English 模式仍会在工作台新页签、共享分页控件、通用错误提示、Django 模板和后端 API 错误中出现大量中文。
- 多个控制台页面会把下游网络错误、连接器错误、模型校验错误和内部状态枚举原样展示；这同时造成英文泄漏、内部实现泄漏和无法理解的技术文案。
- 员工门户把授权版本、目录版本、快照版本、权限 key、scope key、来源枚举等协议字段作为主信息展示给普通员工。
- 本地管理员密码页面对同一条 12 位密码策略给出 8 位和 12 位两种说明，已不只是措辞问题，而会直接误导操作。
- 现有 i18n 护栏采用文件白名单，新增文件默认不受检查；功能测试还会把硬编码中文固化成期望值。

建议优先处理 P0/P1：先建立统一的“错误码 + 本地化用户消息 + 仅日志保留诊断详情”边界，再补齐未接入 `t()` 的生产组件，最后收敛门户信息层级与中文术语。

## 严重性与置信度

- P0：直接泄露内部异常或导致用户按错误说明操作，需立即修复。
- P1：主要流程出现未翻译文案、协议字段或难以理解的错误，明显影响使用。
- P2：局部可理解但不一致、技术化或可访问性体验受损。
- P3：风格和维护性问题，短期不阻断任务。
- 置信度“高”表示从生产代码可直接追踪到用户界面；“中”表示是否出现取决于异常或数据状态。

## 发现明细

### I18N-01：工作台的“接入说明”和部分“清单”界面完全绕过消息目录

- 严重性：P1
- 置信度：高
- 表面/页面：应用工作台 → 接入说明；应用工作台 → 清单
- 证据：
  - `frontend/src/pages/console/workspace/tabs/GuideTab.tsx:20`、`:21` 将“模式”“活跃数量”硬编码为表头。
  - `frontend/src/pages/console/workspace/tabs/GuideTab.tsx:36`、`:39`、`:64`、`:73` 将加载失败、标题和空状态全部硬编码为中文。
  - `frontend/src/pages/console/workspace/tabs/ManifestTab.tsx:79`、`:80`、`:81` 将版本表头硬编码为中文。
  - `frontend/src/pages/console/workspace/tabs/ManifestTab.tsx:112`、`:126`、`:130` 将预览、导入结果 toast 硬编码为中文。
  - `frontend/src/pages/console/workspace/tabs/ManifestTab.tsx:161`、`:180`、`:188`、`:191`、`:219`、`:237`、`:240`、`:243`、`:268`、`:469` 继续硬编码上传、导出、字段、按钮、版本历史和空状态文案。
- 用户影响：切换到 English 后，整个页签仍是中文；同一“清单”页上方使用字典、下方直接写中文，形成明显的半国际化界面。
- 建议：
  - 为 `GuideTab`、`ManifestTab` 的标题、表头、按钮、空状态、toast 和无障碍名称补齐消息键，并全部改为 `t()`。
  - 中文建议统一用“权限清单”，首次出现时可写“权限清单（Manifest）”；之后不再混用 `Manifest`、`manifest` 和“清单”。
  - “模式”可改为“凭据类型”，“活跃数量”可改为“可用凭据数”，“版本历史”可保留。

### I18N-02：共享组件硬编码中文，影响所有复用页面及屏幕阅读器

- 严重性：P1
- 置信度：高
- 表面/页面：所有使用 `PaginationBar`、`CodeBlock` 和 `ShellNav` 的页面
- 证据：
  - `frontend/src/components/ui/PaginationBar.tsx:39`、`:43`、`:45`、`:59`、`:70` 硬编码分页摘要、“每页”、上一页/下一页的无障碍名称。
  - `frontend/src/components/CodeBlock.tsx:35`、`:38` 硬编码“复制”“已复制”。
  - `frontend/src/components/shell/ShellNav.tsx:21` 硬编码 `aria-label="主导航"`，而相同词条已存在于 `frontend/src/i18n/messages.ts:39`。
- 用户影响：English 模式的分页和复制反馈仍是中文；视觉界面即使看似已翻译，屏幕阅读器仍会读出中文。
- 建议：共享组件直接调用 `useI18n()`，或由调用方传入已翻译文案。分页建议增加 `table.pagination.summary`、`table.pagination.pageSize`、`table.pagination.previous`、`table.pagination.next`；复制按钮复用已有 `common.copy`、`common.copied`。

### I18N-03：前端语言只保存在浏览器，API 错误没有语言通道

- 严重性：P1
- 置信度：高
- 表面/页面：所有请求失败、保存失败、删除失败和提交失败提示
- 证据：
  - `frontend/src/i18n/I18nProvider.tsx:28`、`:32`、`:49`、`:57` 表明语言只存于 `localStorage` 和 React 状态。
  - `frontend/src/lib/api.ts:63` 至 `:100` 发送 API 请求时没有 `Accept-Language` 或等价语言信息。
  - `src/easyauth/config/settings/base.py:71` 至 `:81` 的中间件列表不含 `LocaleMiddleware`，并在 `src/easyauth/config/settings/base.py:179` 固定 `LANGUAGE_CODE = "zh-hans"`。
  - `src/easyauth/api/responses.py:10` 至 `:17` 直接把调用方传入的自然语言 `message` 写入错误信封。
  - 例如 `src/easyauth/admin_console/credentials_api.py:183`、`:190`、`:217` 返回固定中文，而 `frontend/src/pages/console/workspace/tabs/CredentialsTab.tsx:56`、`:64` 直接展示 `error.message`。
- 用户影响：即使页面标题和按钮已切到 English，任何后端业务错误仍会显示中文；前端也无法可靠地自行翻译动态自然语言。
- 建议：
  - API 以稳定 `error.code` 和结构化 `details` 为契约，用户文案在前端根据当前 locale 翻译。
  - 若必须由后端生成自然语言，则显式传递并验证 locale，再按请求语言生成 `message`；不要依赖 Django 全局默认语言。
  - 前端不要把后端自然语言当唯一可展示信息，应优先按错误码映射，未知码使用本地化通用提示。

### I18N-04：网络/服务异常原文进入用户界面，可能泄露主机、端口和底层英文

- 严重性：P0
- 置信度：高
- 表面/页面：自动接入、交接详情、审批实例、连接器状态和运行记录
- 证据：
  - `src/easyauth/admin_console/auto_onboarding_api.py:237` 至 `:242` 把 `URLError.reason` 或 `OSError` 原文拼入“无法连接下游应用”。
  - `src/easyauth/lifecycle/services.py:232` 至 `:234`、`:388` 至 `:393`、`:1011` 至 `:1018` 把 `str(error)` 写入 `last_error`。
  - `src/easyauth/admin_console/lifecycle_api.py:850` 返回 `last_error`；`frontend/src/pages/console/lifecycle/HandoverTaskDetail.tsx:321`、`:322`、`:339`、`:342` 原样展示。
  - `src/easyauth/workflows/services.py:177` 至 `:189`、`:295` 至 `:308` 把钉钉异常原文作为 API 消息和审批实例 `last_error`；`src/easyauth/admin_console/approval_instances_api.py:132`、`:133` 返回这些内容，`frontend/src/pages/console/ApprovalInstancesPage.tsx:238`、`:270` 放入可见悬浮提示。
  - `src/easyauth/connectors/services.py:233`、`:234`、`:334` 保存连接器异常；`src/easyauth/admin_console/connectors_api.py:602`、`:643` 返回；`frontend/src/pages/console/workspace/tabs/ConnectorTab.tsx:348` 至 `:355` 以及运行记录错误列原样展示。
  - `src/easyauth/admin_console/operations_retry_api.py:122` 至 `:125` 把数据库、Django 或授权应用异常原文放入授权重试响应。
  - `src/easyauth/accounts/views.py:95` 至 `:99` 把 OIDC 会话异常直接作为 `text/plain` 浏览器响应。
- 用户影响：可出现英文库错误、URL、主机名、端口、证书原因、HTTP 响应细节或外部账户信息；普通管理员难以据此行动，也扩大了内部拓扑暴露面。
- 建议：
  - 将异常转换为稳定业务错误，例如“无法连接下游应用，请检查地址、网络连通性和证书配置。”
  - 对外只返回 `code`、可执行的中文说明和必要的安全字段；完整异常仅写服务端日志，并用诊断编号关联。
  - `last_error` 不应同时承担诊断日志和 UI 文案职责；拆成 `failure_code`、安全的 `failure_summary` 与仅服务端保存的诊断详情。

### I18N-05：模型和参数校验存在纯英文文案，并通过原始校验详情外泄

- 严重性：P1
- 置信度：高
- 表面/页面：审批规则、审批模板、团队、权限目录和一键入职等表单错误
- 证据：
  - `src/easyauth/admin_console/approval_rule_payloads.py:12`、`:14`、`:16`、`:18` 的 Pydantic 自定义错误均为纯英文。
  - `src/easyauth/admin_console/approval_rules_api.py:134` 至 `:136` 把 `str(error)` 放进响应 `details.errors`。
  - `src/easyauth/workflows/models.py:138` 至 `:140` 使用 `Approval template requires a process code.`；`src/easyauth/workflows/services.py:533` 至 `:539` 又把完整 `ValidationError` 拼进对外 `ApprovalCreateError.message`。
  - 其他同类英文模型文案见 `src/easyauth/teams/models.py:97`、`:98`，`src/easyauth/applications/models.py:421`、`:424`、`:428` 至 `:432`、`:487`，`src/easyauth/lifecycle/models.py:500` 至 `:511`。
  - 多个接口把 Pydantic/Django 校验异常原样放入 `details.errors`，代表性证据为 `src/easyauth/admin_console/lifecycle_api.py:266` 至 `:268`、`:706` 至 `:723`。
- 用户影响：表单失败时可能出现纯英文、Python/Django 字段名、Pydantic 路径和内部模型术语；API 调用方也无法依赖稳定文案。
- 建议：
  - 模型层错误可以保留字段级错误码，但不要直接作为最终用户消息。
  - API 层把校验错误规范化为 `{field, code, params}`，前端用 locale 翻译并把字段定位到对应表单控件。
  - 建议文案示例：“请选择审批目标。”“请至少选择一名审批人。”“审批模板缺少钉钉流程码。”“限时授权必须填写有效天数。”

### I18N-06：未知状态直接回显内部枚举，新增状态必然造成英文泄漏

- 严重性：P1
- 置信度：高
- 表面/页面：门户授权和申请状态、控制台健康状态、审批状态、投递状态、交接状态、管理范围策略、连接器运行记录
- 证据：
  - `frontend/src/lib/status.ts:22`、`:53`、`:84`、`:99`、`:117`、`:133`、`:145` 未命中映射时直接返回后端值。
  - `frontend/src/pages/console/lifecycle/lifecycleLabels.ts:14`、`:39`、`:64`、`:79` 对人员、任务、类型和动作状态使用相同回退。
  - `frontend/src/pages/console/ConsoleAppWorkspace.tsx:401` 至 `:406` 对未知 resolver 返回 `policy.resolver`。
  - `frontend/src/pages/console/workspace/tabs/ConnectorTab.tsx:1045` 至 `:1052` 对未知运行状态和触发方式返回原始枚举。
- 用户影响：后端一旦新增状态，界面会显示 `async_pending`、`manual_retry`、`directory_sync` 等内部协议值；这既不是合格中文，也无法向用户解释下一步。
- 建议：
  - 所有状态映射都应快速识别已知值，UI 对未知值统一显示本地化的“未知状态”或“暂不支持的状态”。
  - 原始值可进入遥测和日志，不应作为主文案；如需管理员诊断，可放在明确标记的“技术详情”中并做权限控制。
  - 为每个枚举映射增加未知值测试，禁止 `return status`、`return kind` 一类回退。

### I18N-07：员工门户把内部版本、key、scope 和来源枚举当作主要信息

- 严重性：P1
- 置信度：高
- 表面/页面：员工门户 → 我的权限；员工门户 → 我的申请
- 证据：
  - `frontend/src/pages/portal/PortalPage.tsx:283` 至 `:288` 显示权限组 `kind`。
  - `frontend/src/pages/portal/PortalPage.tsx:290` 至 `:302` 把 `permission:scope` 和 `source_type:source_key` 直接展示给员工。
  - `frontend/src/pages/portal/PortalPage.tsx:304` 至 `:312` 显示授权版本、目录版本和快照版本；对应文案位于 `frontend/src/i18n/messages.ts:553`、`:562`。
  - `frontend/src/pages/portal/PortalPage.tsx:315` 至 `:321` 即使已有 `permission_name`，仍追加 permission key 和 scope key。
  - 这些列确实出现在门户主表，见 `frontend/src/pages/portal/PortalPage.tsx:84` 至 `:89`、`:155` 至 `:158`。
- 用户影响：普通员工需要理解 `GLOBAL`、`direct`、`group`、快照版本等内部概念才能读懂自己的权限；真正关心的“能做什么、覆盖哪些数据、来自哪个岗位/申请、何时到期”反而不突出。
- 建议：
  - 门户主表只显示业务名称：权限组名称、权限名称、范围名称、来源名称、有效期。
  - 来源类型翻译为“岗位授权”“单独申请”“管理员授予”等业务口径，并把 `source_key` 解析成名称。
  - 删除门户中的授权/目录/快照版本列；若审计确有需要，移动到受控的“技术详情”或控制台。
  - 后端应直接提供本地化名称或中英文显示字段，前端不应只拿 key 猜业务文案。

### I18N-08：门户把响应契约诊断直接展示给普通员工

- 严重性：P1
- 置信度：高
- 表面/页面：员工门户授权列表、申请记录、申请权限目录加载失败
- 证据：
  - `frontend/src/pages/portal/portalListPayload.ts:55` 至 `:76` 构造包含 `data`、`pagination.total_pages`、`total_items/page_size` 的技术错误。
  - `frontend/src/pages/portal/portalListPayload.ts:81` 至 `:104`、`:109` 至 `:131` 把数组索引和字段路径写入错误文本。
  - `frontend/src/pages/portal/PortalPage.tsx:103` 至 `:107`、`:175` 至 `:179` 把上述 `error.message` 直接放入页面错误状态。
  - 申请目录同样在 `frontend/src/pages/portal/hooks/useAccessRequestForm.ts:888` 至 `:900`、`:945` 至 `:1019` 构造 `申请目录.apps[0].app_key` 一类错误，并在 `frontend/src/pages/portal/hooks/useAccessRequestForm.ts:213`、`:337` 进入表单状态和提交错误。
- 用户影响：接口契约漂移时，员工会看到“pagination.total_pages 与 total_items/page_size 不一致”或具体 JSON 字段路径，不知道如何解决；English 模式下仍会出现硬编码中文。
- 建议：契约验证仍应快速失败，但 UI 只显示“权限数据加载失败，请刷新后重试；如持续出现，请联系管理员。”并附诊断编号。完整字段路径写入遥测或开发日志，不进入普通用户文案。

### I18N-09：前端通用 HTTP 兜底错误固定为中文

- 严重性：P1
- 置信度：高
- 表面/页面：网关返回 HTML、空响应或非标准 JSON 时的所有页面
- 证据：
  - `frontend/src/lib/api.ts:166` 至 `:181` 将 400、401、403、404、409、422、429、500、502、503 和未知状态的文案全部硬编码为中文。
  - `frontend/src/lib/api.ts:184` 至 `:195` 在后端错误信封缺失或非 JSON 时必然使用这些中文。
- 用户影响：English 模式在最常见的网关和服务异常中退回中文；状态码直接拼在句末，也没有告诉用户可执行的恢复动作。
- 建议：把状态码映射移入消息目录，或令 `buildApiError` 只产生 `http_error_503` 一类错误码，由展示层翻译。建议中文如“服务暂时不可用，请稍后重试。”；状态码放入技术详情，不作为主句的一部分。

### I18N-10：本地管理员密码策略文案和浏览器校验与真实规则冲突

- 严重性：P0
- 置信度：高
- 表面/页面：本地管理员 → 安全设置 → 修改密码
- 证据：
  - 真实密码最小长度为 12，见 `src/easyauth/config/settings/base.py:169` 至 `:176`。
  - 独立改密页正确写为 12 位，并设置 `minlength="12"`，见 `src/easyauth/accounts/templates/accounts/local_admin/change_password.html:226` 至 `:235`。
  - 安全设置页却写“至少 8 位”，并设置 `minlength="8"`，见 `src/easyauth/accounts/templates/accounts/local_admin/security.html:378` 至 `:394`。
- 用户影响：用户按页面提示输入 8 至 11 位密码，浏览器允许提交，但后端必然拒绝；造成“明明符合要求却保存失败”的直接困惑。
- 建议：模板不要复制策略常量。由后端上下文提供最小长度，或从单一配置生成提示和 HTML 属性；当前中文应统一为“新密码至少 12 位，且不能与当前密码相同、过于常见或全部为数字。”

### I18N-11：Django 登录、安全和错误页没有接入任何语言切换

- 严重性：P2
- 置信度：高
- 表面/页面：本地管理员登录、二次验证、修改密码、安全设置、403、404
- 证据：
  - `src/easyauth/accounts/templates/accounts/local_admin/login.html:3`、`:7`、`:236`、`:248` 至 `:265` 固定 `lang="zh-Hans"` 并直接写中文。
  - `src/easyauth/accounts/templates/accounts/local_admin/verify.html:3`、`:7`、`:242` 至 `:270` 同样固定中文。
  - `src/easyauth/accounts/templates/accounts/local_admin/change_password.html:3`、`:7`、`:210` 至 `:235` 与 `src/easyauth/accounts/templates/accounts/local_admin/security.html:3`、`:7`、`:366` 至 `:489` 均未使用 `{% trans %}`。
  - `src/easyauth/config/templates/403.html:3`、`:7`、`:68` 至 `:75` 和 `src/easyauth/config/templates/404.html:3`、`:7`、`:190` 至 `:194` 也固定为中文。
- 用户影响：从 English React 页面跳到登录、安全设置或错误页时，语言会突然切回中文；HTML `lang` 也不会反映用户选择。
- 建议：决定产品边界后统一处理。若这些页面属于双语产品范围，应启用请求级 locale、使用 Django `trans/blocktrans` 或共享中英文模板上下文，并同步 React 的语言选择；若明确只支持中文，应从 English 界面和产品说明中明确标注，而不是形成无提示的语言跳变。

### I18N-12：本地管理员 Passkey 和未知密码校验错误仍会透传底层文本

- 严重性：P1
- 置信度：中
- 表面/页面：通行密钥登录、注册、会话绑定、修改密码
- 证据：
  - `src/easyauth/accounts/local_admin_views.py:162` 至 `:171` 将 `PasskeyVerificationError` 和 `LocalAdminConfigurationError` 的 `str(error)` 直接作为 JSON `error`。
  - `src/easyauth/accounts/local_admin_views.py:329` 至 `:338` 对注册失败做同样处理。
  - `src/easyauth/accounts/local_admin_views.py:386` 至 `:393` 甚至以 `text/plain` 返回配置异常原文。
  - `src/easyauth/accounts/local_admin_views.py:453` 至 `:465` 对未知密码 validator 直接回退 `item.messages`。
- 用户影响：新增 validator、WebAuthn 库升级或配置异常时可能突然出现英文和内部实现原因；同一 JSON `error` 字段有时是错误码、有时是自然语言，前端无法稳定本地化。
- 建议：统一返回错误码和安全中文，如 `passkey_verification_failed` / “通行密钥验证失败，请重试。”、`local_admin_unavailable` / “当前登录配置不可用，请联系管理员。”；未知密码校验统一为“新密码不符合安全策略。”

### I18N-13：运营筛选器用协议字段名充当用户标签

- 严重性：P2
- 置信度：高
- 表面/页面：控制台 → 运营 → 审计、访问申请、授权明细
- 证据：
  - `frontend/src/pages/console/OperationsPage.tsx:387` 至 `:405` 直接使用 `app_key`、`actor_id`、`user_id` 作为 placeholder 和无障碍名称。
  - `frontend/src/pages/console/OperationsPage.tsx:408`、`:422`、`:428`、`:437` 至 `:443` 继续使用 `status`、`created_from`、`created_to`、`version`、`current`。
- 用户影响：视觉用户和屏幕阅读器用户都必须理解后端字段名；日期输入没有“开始时间/结束时间”的语义，`current` 也无法说明是当前授权版本。
- 建议：用“应用标识”“操作人/用户”“状态”“开始时间”“结束时间”“授权版本”“版本范围”等中文标签；技术字段名只可作为辅助说明或查询语法提示。

### I18N-14：后端用户文案要求管理员理解内部类型和枚举

- 严重性：P2
- 置信度：高
- 表面/页面：审批规则、管理范围策略、交接建单、自动接入错误
- 证据：
  - `src/easyauth/admin_console/approval_rule_handlers.py:35`、`:36` 和 `src/easyauth/admin_console/approval_rules_api.py:183` 至 `:187` 使用 `AuthorizationGroup`、`Permission`、`App` 模型名。
  - `src/easyauth/admin_console/managed_scope_policy_api.py:132` 至 `:140` 要求用户理解 `mode`、`override`、`disabled`；`:151` 至 `:176` 又使用 `active App owner/developer`。
  - `src/easyauth/admin_console/lifecycle_api.py:594` 至 `:600` 用 `offboard`、`transfer` 解释交接类型。
  - `src/easyauth/admin_console/auto_onboarding_api.py:257` 至 `:260` 使用 `JSON object`，`:270` 至 `:306` 直接展示 `descriptor_version`、`app_key`、`manifest.app.app_key`、`manifest.schema_version`。
- 用户影响：业务管理员必须掌握模型类名和接口枚举才能理解失败原因；中文句子中夹杂的实现名也无法告诉用户应修改哪个界面字段。
- 建议：
  - 主消息改为业务语言：“所选授权组不属于当前应用。”“模式必须选择‘覆盖’或‘停用’。”“交接类型必须选择‘离职交接’或‘转岗交接’。”
  - 字段名和允许值放入结构化 `details`，由前端定位并提示具体控件；只在管理员主动展开“技术详情”时显示协议字段。
  - 自动接入建议改为“集成描述符格式无效”“描述符版本不受支持”“应用标识与请求不一致”“清单版本必须是大于等于 1 的整数”。

### I18N-15：中文术语和书写风格没有统一口径

- 严重性：P3
- 置信度：高
- 表面/页面：导航、应用工作台、凭据管理、两步验证、应用创建
- 证据：
  - “概览”与“总览”并存：`frontend/src/i18n/messages.ts:57`、`:317`。
  - 同一动作使用“停用”和“禁用”：公共词条为“停用”，见 `frontend/src/i18n/messages.ts:23`、`:25`；凭据页却为“禁用”，见 `frontend/src/i18n/messages.ts:781`，接入向导也在 `frontend/src/i18n/messages.ts:508` 使用“禁用”。
  - 应用成员已经有“负责人/开发者”的稳定中文，见 `frontend/src/i18n/messages.ts:868`、`:889`、`:890`；创建应用却使用“Owner 用户 ID”“Developer 用户 ID”，见 `frontend/src/i18n/messages.ts:130`、`:131`，并在 `frontend/src/pages/console/ConsoleAppList.tsx:335`、`:338` 再次硬编码。
  - 两步验证文案混用半角逗号和问号，见 `frontend/src/i18n/messages.ts:259`、`:281`、`:291` 至 `:296`。
  - `Manifest`、`manifest` 与“清单”在 `frontend/src/i18n/messages.ts:298` 至 `:309`、`:322`、`:464` 至 `:473` 混用。
- 用户影响：不阻断操作，但会削弱产品一致性；“禁用/停用”在安全和凭据语境下还可能被误解为删除或暂时不可用。
- 建议：
  - 导航统一用“概览”。
  - 可恢复的状态切换统一用“停用/重新启用”；永久移除才用“删除”。
  - 角色统一用“负责人”“开发者”，必要时在帮助文本中补充 `(owner)`、`(developer)`。
  - 中文正文统一全角标点。
  - 建立术语表：权限清单（Manifest）、应用标识（`app_key`）、凭据、平台能力、负责人、开发者、停用。

### I18N-16：i18n 回归测试采用白名单，新页面默认漏检

- 严重性：P2
- 置信度：高
- 表面/页面：测试与持续集成
- 证据：
  - `frontend/src/i18n/noHardcodedChinese.test.ts:12` 至 `:43` 只检查固定 `GUARDED_FILES` 白名单。
  - 已确认存在问题的 `GuideTab.tsx`、`ManifestTab.tsx`、`PaginationBar.tsx`、`CodeBlock.tsx`、`ShellNav.tsx` 均不在该列表。
  - `frontend/src/i18n/I18nProvider.test.tsx:20` 至 `:47` 只验证 locale 状态和 `html lang`，没有验证业务页面在 English 下实际显示英文。
  - `frontend/src/pages/console/workspace/tabs/ManifestTab.test.tsx:34` 至 `:47` 直接用硬编码中文查询控件和按钮，反而把未国际化实现固化为测试基线。
- 用户影响：新增页面很容易在所有测试通过的情况下漏出中文；测试无法证明“切换语言后页面完整翻译”。
- 建议：
  - 将护栏改为扫描全部生产 `.ts/.tsx`，明确排除注释、测试、协议示例和允许列表，而不是枚举受保护文件。
  - 同时扫描硬编码英文用户文案；仅禁止中文无法发现 English 模式下的未接线，也无法发现中文模式出现英文。
  - 为每个一级页面增加至少一个 `zh-CN`/`en` 双语渲染冒烟测试；共享组件单独验证可见文本和 `aria-label`。
  - 增加错误场景测试，确保后端错误码在两种 locale 下均得到本地化文案，且不展示原始异常。

## 建议的修复顺序

1. 先修复 I18N-04、I18N-05、I18N-08、I18N-10：阻断原始异常和契约细节进入 UI，纠正密码策略误导。
2. 建立 I18N-03、I18N-09 的统一错误本地化架构，再迁移现有各处 `error.message` 展示点，避免逐页面反复修补。
3. 修复 I18N-01、I18N-02、I18N-06、I18N-16：补齐消息键、未知状态兜底和全量测试护栏。
4. 重构 I18N-07 的员工门户信息层级，让业务名称替代协议 key 和版本号。
5. 最后统一 I18N-11、I18N-13、I18N-14、I18N-15 的模板范围、表单标签和中文术语。

## 验收建议

- 切换到 English 后，遍历所有一级导航、工作台页签、弹窗、toast、空状态、分页和无障碍名称，不出现非专有名词中文。
- 切换到简体中文后，不出现未解释的内部枚举、Python/Django/Pydantic 错误、JSON 字段路径或纯英文模型错误。
- 模拟 400、401、403、404、409、422、429、500、502、503、非 JSON 网关响应、下游超时和未知枚举，验证用户只看到本地化且可执行的提示。
- 员工门户默认不展示 `source_type`、`source_key`、permission key、scope key、`grant_version`、`catalog_version`、`snapshot_version`。
- 本地管理员两个改密入口的提示、`minlength` 与后端验证器均来自同一 12 位策略源。
- CI 对新增生产组件默认启用硬编码可见文本检查，并至少有一个 English 渲染冒烟测试。
