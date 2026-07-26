# 契约与领域交叉复核

复核日期：2026-07-27

## 复核范围与口径

本复核交叉检查以下四份报告：

- `02-backend-functional-bugs.md`
- `03-domain-schema-invariants.md`
- `06-frontend-functional-bugs.md`
- `15-cross-layer-contracts.md`

复核沿模型、迁移、领域服务、API 入口、前端运行时解码、React Query 缓存键和页面能力展示逐项追踪。分类口径如下：

- **已确认**：当前源码已直接证明报告描述的错误路径或约束缺口。
- **降级**：底层事实存在，但报告的严重度、影响范围或复现场景包含尚未证明的推断。
- **重复**：与另一报告记录的是同一根因和基本相同的用户路径，不应重复计数。
- **相矛盾**：当前源码与报告结论相反。
- **未验证**：缺少外部契约、支持基线、真实数据或执行计划，静态源码不足以判定为缺陷。

共复核 56 个报告编号：已确认 36 个、降级 8 个、重复 8 个、未验证 4 个；没有整项应归为“相矛盾”，但有 3 个降级项包含与源码相矛盾的子结论。

## 报告 02 复核

| 报告编号 | 分类 | 复核结论与源码证据 |
| --- | --- | --- |
| BF-01 | 已确认 | `current_local_admin()` 同时检查专用标志和 `session_version`（`src/easyauth/accounts/local_admin.py:98-113`），控制台 `actor_from_request()` 却只按 `local-admin:` 前缀和账号 active 状态判断（`src/easyauth/admin_console/identity.py:16-39`）。旧版本会话可继续形成超级管理员 actor。 |
| BF-02 | 已确认 | 登录时把组声明写入 session（`src/easyauth/accounts/auth.py:149-180`），请求期超级管理员判断只读取该 session 快照（`src/easyauth/admin_console/identity.py:42-47`），没有服务端授权版本或重新取上游组的路径。 |
| BF-03 | 已确认 | TOTP 在验证前检查节流（`src/easyauth/accounts/local_admin_views.py:126-140`）；Passkey begin/complete 未检查，却在失败后累加同一计数（`src/easyauth/accounts/local_admin_views.py:143-167`）。 |
| BF-04 | 已确认 | `compute_payload_hash()` 的输入和规范化 JSON 均没有 `biz_tag`（`src/easyauth/notify/services.py:213-236`）；受理路径已规范化并持久化 `biz_tag`，但计算哈希时没有传入（`src/easyauth/notify/services.py:278-324`）。 |
| BF-05 | 已确认 | 通知视图把字段交给 `_as_str()`（`src/easyauth/api/notify_views.py:74-90`）；该函数把数值和布尔转为字符串，把对象和数组改为空串（`src/easyauth/api/notify_views.py:337-344`），与公开 API 的请求体级参数错误应返回 422 的契约冲突（`docs/api/easyauth-public-api.md:551-560,587`）。 |
| BF-06 | 重复 | 与 CTR-05 是同一类查询参数契约分裂。目录、审批和门户分页确实把非法值改成默认值或上限（`src/easyauth/api/directory_views.py:487-511`、`src/easyauth/api/approval_views.py:260-280`、`src/easyauth/portal/pagination.py:79-94`），应用状态非法值则被忽略（`src/easyauth/admin_console/apps_api.py:482-491`）。 |
| BF-07 | 降级 | 原始错误泄露部分成立：全局钉钉测试直接回传 `str(error)`（`src/easyauth/admin_console/settings_api.py:160-166`），而 HTTP 错误正文可进入异常文本（`src/easyauth/integrations/dingtalk/api_client.py:321-350`）。但仓库文档没有为全局钉钉测试和 Connector test 明定失败必须为 503；`docs/api/easyauth-console-api.md:186-195` 的净化说明位于每 App `notification-channel` 语境。故“泄露”已确认，“HTTP 200 必然违反既定契约”未被证明，整项从中严重度降级。 |
| BF-08 | 已确认 | OIDC callback 在 `bind_oidc_session()` 成功后直接跳转（`src/easyauth/accounts/views.py:77-103`）；绑定既有用户时不检查 `UserMirror.status`，仍写认证 session（`src/easyauth/accounts/auth.py:158-185`）；门户下一请求才按 active 查找并清 session（`src/easyauth/portal/views.py:16-27`）。 |
| BR-01 | 已确认 | 无第二因子时密码验证后直接建立 `SECOND_FACTOR_NONE` 会话（`src/easyauth/accounts/local_admin_views.py:96-115`）；这是已知产品选择，但单因素特权入口这一风险事实成立。 |
| BR-02 | 已确认 | Django admin 已启用并注册 `/admin/`（`src/easyauth/config/settings/base.py:44-52`、`src/easyauth/config/urls.py:103-110`），关键模型也注册到该平面；它没有复用 EasyAuth 的本地超管会话版本和第二因子守卫。 |
| BR-03 | 已确认 | OIDC HTTP 响应使用无界 `response.read()`，且网络异常只归一化 `HTTPError`、`URLError`（`src/easyauth/accounts/oidc_exchange.py:105-120`）；JWK 的 base64 和 RSA 构造位于统一异常包装之外（`src/easyauth/accounts/oidc_exchange.py:189-194,262-268`）。作为条件性风险成立。 |
| BR-04 | 已确认 | App 查询集明确忽略 actor 并返回全量（`src/easyauth/admin_console/apps_api.py:465-467`），列表载荷包含 owner 和就绪度（`src/easyauth/admin_console/apps_api.py:412-423`）。报告已正确标为产品选择待确认的风险，不应升级为越权缺陷。 |

## 报告 03 复核

| 报告编号 | 分类 | 复核结论与源码证据 |
| --- | --- | --- |
| DS-01 | 已确认 | `AccessRequest` 没有基础授权主键或修订字段（`src/easyauth/access_requests/models.py:77-138`）；提交只验证当前 active grant（`src/easyauth/access_requests/submission_validation.py:235-246`），执行 `change` 又重新读取当前 grant（`src/easyauth/access_requests/application_grants.py:96-111`）。审批命令没有绑定其前置授权事实。 |
| DS-02 | 已确认 | `TransferPlan` 只有自身 `revision` 和可变模板外键（`src/easyauth/lifecycle/models.py:514-557`）；确认只比较计划 revision，随后重新读取当前模板项（`src/easyauth/lifecycle/services.py:677-731`）。模板编辑删除并重建项目（`src/easyauth/admin_console/lifecycle_api.py:725-741`），预览内容与执行内容可以漂移。 |
| DS-03 | 已确认 | Passkey 在事务和行锁之外读取旧 `sign_count`，验证后普通 `save()` 覆盖（`src/easyauth/accounts/local_admin.py:392-420`）；字段本身也没有非负数据库约束（`src/easyauth/accounts/models.py:282-302`）。并发后写旧值可以回退计数。 |
| DS-04 | 已确认 | `UserMirror` 只覆盖实例 `delete()`（`src/easyauth/accounts/models.py:76-82`），而申请和授权外键仍为 `CASCADE`（`src/easyauth/access_requests/models.py:83-91`、`src/easyauth/grants/models.py:44-52`）。QuerySet 删除不会调用实例覆盖，数据库契约与“不可物理删除”相反。 |
| DS-05 | 降级 | `event_id` 命中后确实不比较 `event_type`、`corp_id`、`born_at`、`data`（`src/easyauth/integrations/dingtalk/stream.py:43-74`），并按正常重复 ACK（`src/easyauth/integrations/dingtalk/stream.py:85-117`）。但仓库没有给出钉钉会对不同事件复用同一 `event_id` 的外部契约或实际冲突样本，因此“无法识别冲突”的防御缺口成立，“高严重度业务事件必然丢失”应降级为依赖上游违约的条件风险。 |
| DS-06 | 已确认 | 创建时已计算 rejected，却在仍有 pending 时把 `recipient_failed` 写成 0（`src/easyauth/notify/services.py:934-971`）；失败明细同时落库（`src/easyauth/notify/services.py:972-987`），查询又同时返回汇总和明细（`src/easyauth/api/notify_views.py:171-190`），即时响应可自相矛盾。 |
| DS-07 | 已确认 | `AccessRequest` 的 applied 形状仅在 `clean()`（`src/easyauth/access_requests/models.py:168-187`）；`NotifyMessage` 约束只覆盖幂等和状态枚举（`src/easyauth/notify/models.py:175-194`）；Outbox、Pending callback 和 Stream event 也没有完整状态字段真值表约束。worker 使用 `QuerySet.update()` 的路径会绕过模型校验，数据库可接受报告所列坏形状。 |
| DS-08 | 已确认 | 授权组 grant 的同 App、scope 归属只在 `clean()`（`src/easyauth/applications/models.py:517-557`）；申请目标同样只在 `clean()`（`src/easyauth/access_requests/models.py:244-267,286-319`）。数据库唯一约束不能阻止跨 App 外键组合。 |
| DS-09 | 已确认 | `ManagedScopePolicy.target_id` 是普通整数（`src/easyauth/applications/models.py:566-606`），目标存在性和同 App 只在 `clean()` 查询（`src/easyauth/applications/models.py:618-646`）；读取也按裸整数匹配（`src/easyauth/applications/managed_scope_policy.py:38-52`）。参照完整性缺口成立。 |
| DS-10 | 已确认 | 钉钉企业和 userid 组合只有普通索引（`src/easyauth/accounts/models.py:63-70`）；通知解析使用 `.first()`（`src/easyauth/notify/services.py:787-830,859-863`），而另一解析器把多行当作歧义（`src/easyauth/accounts/directory_references.py:154-187`）。同一身份在不同调用链具有不同语义。 |
| DS-11 | 已确认 | 模型注释把 `(user, app, version)` 称为快照事实锚点（`src/easyauth/grants/models.py:68-84`），但变更就地递增版本并删除重建成员关系（`src/easyauth/grants/lifecycle.py:62-79`、`src/easyauth/grants/operations.py:45-74`）。报告已以中置信度描述“语义冲突”，该口径准确。 |
| DS-12 | 降级 | 四个迁移中的删除或清空操作均真实存在（`src/easyauth/access_requests/migrations/0009_access_request_idempotency.py:15-39`、`src/easyauth/grants/migrations/0005_membership_expiration.py:15-50`、`src/easyauth/accounts/migrations/0007_alter_localadminaccount_totp_secret.py:7-27`、`src/easyauth/applications/migrations/0015_alter_integrationsettings_authentik_api_token.py:7-27`）。但项目明确尚未上线，后两个迁移还在注释中声明重绑/重录策略；没有已部署数据库或数据丢失证据。因此破坏性升级链已确认，高严重度事故结论降级为上线基线前必须清除的发布阻断项。 |
| DS-13 | 未验证 | `AuditLog` 确实没有显式索引（`src/easyauth/audit/models.py:37-51`），查询和清理按时间、事件、actor、target 过滤（`src/easyauth/admin_console/operation_filters.py:91-97`）。但没有数据量、PostgreSQL `EXPLAIN`、延迟或清理批量策略证据，不能仅凭缺少索引确认“可预期性能退化”的严重度和索引组合。 |

## 报告 06 复核

| 报告编号 | 分类 | 复核结论与源码证据 |
| --- | --- | --- |
| C-01 | 已确认 | Console 侧栏无条件生成组织、审批和运维链接（`frontend/src/components/shell/Sidebar.tsx:22-49`），路由除新建应用外没有 `isSuperuser` 守卫（`frontend/src/App.tsx:78-96`）；后端相应入口使用 `require_superuser()` 返回 403（`src/easyauth/admin_console/authz.py:14-27`）。 |
| C-02 | 已确认 | App 列表无条件展示启停、删除、快速创建和接入入口（`frontend/src/pages/console/ConsoleAppList.tsx:117-160,181-191`），启停和删除 mutation 无 `onError`（`frontend/src/pages/console/ConsoleAppList.tsx:63-80`）；后端创建、删除和启停有超级管理员限制。 |
| C-03 | 已确认 | 工作区多数页签没有接收能力（`frontend/src/pages/console/ConsoleAppWorkspace.tsx:162-173`）；成员 UI 用 owner 级 `app.can_manage` 展示写操作（`frontend/src/pages/console/workspace/tabs/OverviewTab.tsx:49-74`），后端成员写却只允许超级管理员（`src/easyauth/admin_console/memberships_api.py:171-190`）。Connector 写同样由后端超级管理员守卫（`src/easyauth/admin_console/connectors_api.py:139-171`），前端仍展示写按钮。 |
| C-04 | 重复 | 与 CTR-02 完全相同。后端撤回入口存在（`src/easyauth/portal/api.py:125-169`），门户申请表只有展示列（`frontend/src/pages/portal/PortalPage.tsx:137-171`）。 |
| C-05 | 已确认 | 前端可以生成 `to_user_id: null` 且 `release_to_pool: false`（`frontend/src/pages/console/lifecycle/HandoverWizard.tsx:125-149`），步骤校验未阻止（`frontend/src/pages/console/lifecycle/HandoverWizard.tsx:256-311`）；后端要求两者严格二选一（`src/easyauth/lifecycle/services.py:998-1008`）。 |
| C-06 | 已确认 | 列表对所有状态都渲染删除按钮（`frontend/src/pages/console/lifecycle/HandoverTaskList.tsx:237-253`）；领域服务只允许删除 cancelled（`src/easyauth/lifecycle/services.py:570-582`）。 |
| C-07 | 已确认 | Matrix 可把组设为 inactive（`frontend/src/pages/console/workspace/tabs/MatrixTab.tsx:321-328`），刷新读取却只返回 active 授权组（`src/easyauth/admin_console/permission_catalog_data.py:97-102`），同一管理界面没有恢复路径。 |
| C-08 | 重复 | 与 CTR-06 完全相同。选择器固定读取 `page=1&page_size=100`（`frontend/src/pages/console/lifecycle/OnboardingPage.tsx:424-428`），API 最大页大小为 100 且真正分页（`src/easyauth/admin_console/operation_filters.py:23-27,100-121`）。 |
| C-09 | 已确认 | mutation 无变量快照，直接读取当前闭包并让任意成功响应覆盖 result（`frontend/src/pages/console/workspace/tabs/QueryTestTab.tsx:34-49`）；按钮未按 `isPending` 禁用（`frontend/src/pages/console/workspace/tabs/QueryTestTab.tsx:84-94`）。并发旧响应覆盖新结果的路径成立。 |
| C-10 | 已确认 | 门户列表和审批列表优先使用服务端 `status_label`（`frontend/src/pages/portal/PortalPage.tsx:137-145`、`frontend/src/pages/portal/components/PortalApprovalsSection.tsx:377-390`）；服务端标签固定中文（`src/easyauth/portal/status_text.py:17-35`）。 |
| C-11 | 已确认 | 两步验证查询的“加载中、错误、不支持”均因 `!status` 或 `!supported` 直接返回 null（`frontend/src/pages/console/TwoFactorSection.tsx:42-54`），真实请求失败没有错误态。 |
| C-12 | 已确认 | 删除成功只失效列表，不收敛 `pageIndex`（`frontend/src/pages/console/ConsoleAppList.tsx:71-80`）；表格使用手动分页并直接信任当前页（`frontend/src/pages/console/ConsoleAppList.tsx:165-173`），响应后也没有页码 clamp。 |
| C-13 | 已确认 | 复制函数不等待可选链 Promise 即设置成功（`frontend/src/components/CodeBlock.tsx:19-23`），Clipboard API 缺失或拒绝时仍显示“已复制”。 |
| C-14 | 已确认 | 审批输入没有 `maxLength` 或提交前长度校验（`frontend/src/components/ApprovalDecisionDialog.tsx:44-51,80-94`），后端 schema 限制 2000 字符（`src/easyauth/portal/approvals_api.py:52-59`）。 |
| C-15 | 已确认 | 路由接受任意 section（`frontend/src/App.tsx:92-94`），页面对未知值回退到 access requests 配置并保留错误 URL（`frontend/src/pages/console/OperationsPage.tsx:40-45,65-72`）。 |
| R-01 | 重复 | 与 CTR-04 完全相同。`itemsFromPayload()` 对缺失或非数组 `data` 返回共享空数组（`frontend/src/lib/api.ts:105-117`），现有测试还固化了该行为（`frontend/src/lib/api.test.ts:122-142`）。 |
| R-02 | 未验证 | `localStorage` 调用确实没有捕获 `SecurityError`（`frontend/src/i18n/I18nProvider.tsx:28-34,57-60`），但仓库没有声明需支持禁用 Web Storage、受限 iframe 或相应浏览器基线，也没有目标环境复现。保留为平台兼容待定项。 |
| R-03 | 未验证 | Sidebar 无条件实例化 `ResizeObserver`（`frontend/src/components/shell/Sidebar.tsx:116-140`），但仓库没有目标 WebView/浏览器支持矩阵。是否为产品缺陷取决于明确的运行基线。 |
| R-04 | 未验证 | 提交路径直接调用 `crypto.randomUUID()`（`frontend/src/pages/portal/hooks/useAccessRequestForm.ts:275-289`），但没有部署环境不满足安全上下文或缺少该 API 的证据；需先确定浏览器和 HTTPS 基线。 |
| R-05 | 降级 | 顶层确实没有 React Error Boundary（`frontend/src/main.tsx:24-35`），这是恢复能力缺口；但报告没有给出当前合法数据或已支持浏览器下可稳定触发的渲染异常，不能作为已复现整页白屏缺陷计数。 |
| R-06 | 降级 | 前端确实把空 `supported_scopes` 当成全范围（`frontend/src/pages/console/workspace/tabs/MatrixTab.tsx:70-75`），后端 grant 写入把空集解释为不支持任何 scope（`src/easyauth/admin_console/authorization_groups_api.py:260-275`）。但正常权限写 API 和模型均禁止 active permission 使用空集（`src/easyauth/admin_console/permissions_api.py:234-245`、`src/easyauth/applications/models.py:417-434`），未发现可达合法数据样本。故保留为坏数据下的 fail-fast 缺口，不作为常规用户缺陷。 |
| R-07 | 已确认 | listbox 和 option 没有稳定 ID，combobox 也无法建立 `aria-controls`/`aria-activedescendant`（`frontend/src/components/UserSelect.tsx:58-103`）。该项不属于领域契约核心，但源码证据完整。 |

## 报告 15 复核

| 报告编号 | 分类 | 复核结论与源码证据 |
| --- | --- | --- |
| CTR-01 | 已确认 | 后端正式接受四类 `request_type`（`src/easyauth/access_requests/models.py:16-31`、`src/easyauth/portal/access_request_payloads.py:17-42`），前端表单没有 request type，提交固定 `"grant"`（`frontend/src/pages/portal/hooks/useAccessRequestForm.ts:93-102,498-514`）。全仓门户提交路径没有另外三类命令。 |
| CTR-02 | 重复 | 与 C-04 相同，不应二次计数。撤回 API 和幂等测试存在（`src/easyauth/portal/api.py:125-169`、`tests/integration/portal/test_access_request_withdraw.py:26-53`），门户列表无动作列。 |
| CTR-03 | 已确认 | 后端 App 详情与 configuration status 都从成员、权限、授权组和凭据实时派生（`src/easyauth/admin_console/apps_api.py:412-437,452-497`、`src/easyauth/applications/configuration.py:46-92`）；成员 mutation 只失效 memberships（`frontend/src/pages/console/workspace/tabs/OverviewTab.tsx:49-68`），凭据 mutation 只失效 credentials（`frontend/src/pages/console/workspace/credentials/useCredentialsActions.ts:40-43,84-118`）。30 秒 fresh 窗口和关闭 focus 刷新会保留旧聚合（`frontend/src/lib/query.ts:3-8`）。 |
| CTR-04 | 重复 | 与 R-01 相同。后端列表信封要求 `data`，分页列表还要求 `pagination`（`src/easyauth/admin_console/api_payloads.py:11-20`）；前端类型却把二者设为可选且不做运行时验证（`frontend/src/lib/api.ts:12-19,63-117`）。 |
| CTR-05 | 重复 | 与 BF-06 是同一查询 schema 根因；本报告补充了生命周期 `status`/`kind` 非法值被忽略的路径（`src/easyauth/admin_console/lifecycle_api.py:180-207`）。两项应合并整改和计数。 |
| CTR-06 | 重复 | 与 C-08 相同，不应二次计数。 |
| CTR-07 | 降级 | 状态漂移主体成立：前端标签映射缺 `withdrawn`（`frontend/src/lib/status.ts:8-39`），Operations 筛选缺 `grant_expired`、`withdrawn`（`frontend/src/pages/console/OperationsPage.tsx:62-63,377-419`），测试 fixture 使用不存在的 `pending`（`frontend/src/pages/portal/PortalPage.test.tsx:1856-1872`）。但报告所述“门户在缺少 `status_label` 时回退显示原始 withdrawn”与当前契约相矛盾：后端总是输出该字段（`src/easyauth/portal/access_request_data.py:118-140`），前端解析器也要求其为字符串（`frontend/src/pages/portal/portalListPayload.ts:109-118`）。故保留枚举治理问题，缩小门户复现场景。 |
| CTR-08 | 降级 | 后端 401 与前端只抛局部 `ApiError` 的事实成立（`src/easyauth/admin_console/request_guards.py:16-23`、`frontend/src/lib/api.ts:63-103,166-195`），壳层也没有认证失效状态转换（`frontend/src/components/AppShell.tsx:19-35`）。但仓库没有写明 SPA 收到 401 必须自动跳转、清缓存或保留 `next`；因此应定性为明确的重新认证体验缺口，不宜称为已违反的既定跨层契约。 |
| CTR-09 | 降级 | 导出的 `AppUpdatePayload` 确实错误包含成员字段（`frontend/src/lib/domain.ts:40-46`），后端 PATCH 明确禁止额外字段（`src/easyauth/admin_console/apps_api.py:111-116,285-288`）。但该类型当前没有运行时调用方；实际工作区 PATCH 使用只含 `name`、`description` 的本地 `AppPatchPayload`（`frontend/src/pages/console/workspace/tabs/OverviewTab.tsx:244-290`），全仓除声明和字段扫描测试外无 `AppUpdatePayload` 引用。因此这是未使用公开类型的静态契约债，不是当前可复现 API 失败。 |

## 相矛盾的子结论

没有发现整项报告结论与源码完全相反。以下子结论需要从原报告的影响描述中剔除：

1. BF-07 引用的 `docs/api/easyauth-console-api.md:186-195` 只明确约束每 App notification channel 的错误净化，不能单独证明全局钉钉测试或 Connector test 必须返回 503。
2. CTR-07 的“门户缺少 `status_label` 后回退原始状态”不是当前合法响应路径；后端字段必出，前端也把它作为必填字段（`src/easyauth/portal/access_request_data.py:124-140`、`frontend/src/pages/portal/portalListPayload.ts:109-118`）。
3. CTR-09 描述的 PATCH 失败不是当前页面行为；实际调用使用独立且正确的 `AppPatchPayload`（`frontend/src/pages/console/workspace/tabs/OverviewTab.tsx:244-290`）。

## 复核中发现的具体遗漏

以下只记录能够由当前源码完整证明、且四份原报告未明确列出的具体问题。

### NEW-CD-01：Operations 的状态和申请类型过滤仍接受任意字符串

- 关联但未覆盖完整的原报告：BF-06、CTR-05、CTR-07。
- `filter_access_requests()` 把 `status`、`request_type` 直接交给通用 `_filter_text()`；`filter_access_grants()` 对 `status` 也相同（`src/easyauth/admin_console/operation_filters.py:59-88`）。
- `_filter_text()` 对任意非空字符串直接执行数据库过滤，没有封闭枚举校验（`src/easyauth/admin_console/operation_filters.py:125-135`）。
- Operations API 只捕获 `OperationFilterValidationError`，而上述文本过滤不会抛该错误（`src/easyauth/admin_console/operations_api.py:82-107,222-242`）。
- 因此 `status=typo`、`request_type=typo` 会返回 HTTP 200 空列表。与 CTR-05 已要求的“显式非法值返回结构化 422”同根，但原报告只列出门户、应用列表、审批列表和交接任务，没有覆盖运维申请/授权列表。

### NEW-CD-02：CTR-03 遗漏了 App 列表聚合缓存

- App 列表响应本身包含 `owners` 和 `configuration_status`，均由成员、权限、授权组和凭据事实派生（`src/easyauth/admin_console/apps_api.py:412-423`）。
- 列表缓存键是 `["console", "apps", pageIndex, pageSize]`（`frontend/src/pages/console/ConsoleAppList.tsx:42-48`）。
- 成员、权限、授权组和凭据 mutation 只失效各自的 App 子资源键（`frontend/src/pages/console/workspace/tabs/OverviewTab.tsx:49-68`、`frontend/src/pages/console/workspace/tabs/CatalogTab.tsx:106-154`、`frontend/src/pages/console/workspace/tabs/MatrixTab.tsx:94-108`、`frontend/src/pages/console/workspace/credentials/useCredentialsActions.ts:40-43,84-118`），都没有失效 `["console", "apps"]`。
- 在 30 秒 fresh 窗口内从工作区返回 App 列表时，owner 和就绪度仍可显示写入前的值（`frontend/src/lib/query.ts:3-8`）。CTR-03 已覆盖 App 详情和 `configuration-status`，但遗漏了同样消费这些派生事实的 App 列表查询。

## 综合判断

建议去重后的整改主线为：

1. 先统一会话授权事实与请求期撤权：BF-01、BF-02、BF-08。
2. 再修正会导致已批准命令作用于不同事实的领域模型：DS-01、DS-02、DS-03。
3. 建立数据库可执行的不变量：DS-04、DS-07、DS-08、DS-09、DS-10，并在上线基线前处理 DS-12。
4. 统一严格输入和响应解码：BF-04、BF-05、BF-06/CTR-05、R-01/CTR-04、NEW-CD-01。
5. 统一能力模型和动作状态机：C-01、C-02、C-03、C-05、C-06、C-07、CTR-01、C-04/CTR-02、CTR-07。
6. 建立命令到全部读模型的失效矩阵：CTR-03 与 NEW-CD-02。

R-02、R-03、R-04 和 DS-13 在补齐浏览器支持矩阵、部署基线、真实数据规模与查询计划之前，不应进入“已确认缺陷”统计。BF-07、DS-05、DS-12、R-05、R-06、CTR-07、CTR-08、CTR-09 应按本复核缩小后的范围整改，避免把条件风险或静态债务与当前可复现功能错误混为同一优先级。
