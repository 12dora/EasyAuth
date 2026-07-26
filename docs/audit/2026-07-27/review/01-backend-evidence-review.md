# 后端审计证据交叉复核

复核日期：2026-07-27

## 复核范围与口径

本复核只核验以下四份报告，不重新进行一轮无边界的主审计：

- `01-backend-architecture-smells.md`
- `02-backend-functional-bugs.md`
- `03-domain-schema-invariants.md`
- `04-backend-reliability-performance.md`

复核逐项对照当前源码、调用入口、事务边界、数据库约束及相邻报告，重点检查：

1. 引用行是否支持结论，而不只是出现了相关名称。
2. 报告描述的失败路径是否可从正式入口到达。
3. 严重度是否建立在已证明的影响上。
4. 不同报告是否重复计数或使用互相矛盾的证据口径。
5. 修复建议是否符合项目“不保留错误兼容形态、违反不变量时快速失败”的硬约束。

分类含义：

- **已确认**：当前源码足以证明核心事实和影响。
- **需降级或限定**：局部事实成立，但严重度、影响范围、产品前提或修复方案被报告说得过满。
- **重复**：与另一报告的发现实质相同，应合并计数和修复。
- **矛盾**：核心结论被当前源码直接否定。
- **未验证**：只有风险结构或假设，没有证明正式路径可触发相应后果。

## 总结结论

四份报告共列出 65 个编号项。按本次复核口径：

| 分类 | 数量 |
| --- | ---: |
| 已确认 | 46 |
| 需降级或限定 | 12 |
| 重复 | 4 |
| 未验证 | 3 |
| 完全矛盾 | 0 |

最重要的校正如下：

- `BAS-02` 与 `REL-PERF-08`、`DS-03` 与 `REL-PERF-03`、`BF-06` 与 `REL-PERF-24` 是明确重复；`BR-03` 的主要风险也已被 `REL-PERF-17` 覆盖。
- `BAS-04` 确实存在反向依赖，但报告把“同库事件写入失败导致事务回滚”解释成“连接器故障回滚授权”不准确。当前调用没有执行连接器外部 I/O，而是在同一数据库事务中推进 generation 并写 outbox；这类持久化失败按项目的快速失败原则本就不应静默提交授权。
- `DS-08` 把仅有结构性旁路风险的证据定为“高严重度已确认”，而 `HYP-02` 又基于同一组事实明确承认未发现正式写入口绕过 `full_clean()`，两份报告的确认口径矛盾。数据库归属约束不足成立，但当前可达越权路径尚未证明。
- `DS-12` 引用的破坏性迁移真实存在，但两个凭据迁移明确写明“项目尚未上线”的一次性重置前提；在当前全新建库路径上表为空。应保留“迁移必须快速失败或压平基线”的整改方向，但不能把它无条件表述为当前生产数据丢失。
- `BAS-08` 的主要结论成立，不过复核用 `rg` 得到直接导入 `easyauth.applications.models` 的源码文件为 88 个，而不是报告写的 89 个；这是无关结论的轻微计数偏差。

## 逐项分类

### 01 后端架构与代码异味

| 编号 | 分类 | 复核结论与源码证据 |
| --- | --- | --- |
| BAS-01 | 需降级或限定 | 授权项确实先变为 `done`，钩子失败后动作变为 `failed`，见 `src/easyauth/lifecycle/services.py:290-342`、`:1011-1018`、`:1046-1109`。但“无法表达部分完成”过于绝对：授权项拥有独立状态，见 `src/easyauth/lifecycle/models.py:74-86`，读取 API 也单独序列化授权项，见 `src/easyauth/admin_console/lifecycle_api.py:318-329`、`:870-895`。这是总览状态语义不够自足，应按中等领域建模缺陷处理，不足以仅凭现有证据定为高严重度事实不一致。 |
| BAS-02 | 已确认 | `preview_action()` 在 `transaction.atomic()` 内锁行后执行外部钩子，见 `src/easyauth/lifecycle/services.py:213-245`、`:967-979`；钩子总时限为 30 秒，见 `src/easyauth/webhooks/hooks.py:30-39`。 |
| BAS-03 | 已确认 | 提交阶段的成员集合查询没有期限过滤，见 `src/easyauth/access_requests/submission_validation.py:304-345`；落地阶段同名查询统一过滤 `expires_at`，见 `src/easyauth/access_requests/application_grants.py:287-305`、`:389-399`。同一授权会得到不同集合，语义漂移证据充分。 |
| BAS-04 | 需降级或限定 | 依赖方向成立：`GrantService` 顶层导入并在事务内调用 `notify_grant_mutation()`，见 `src/easyauth/grants/services.py:6-17`、`:57-138`。但被调用路径只更新同库连接器状态并写 outbox，见 `src/easyauth/connectors/dispatch.py:21-52`，没有同步执行连接器外部调用。因此“外围连接器故障回滚授权”不准确；真正成立的是领域对具体投影实现的编译期和 schema 耦合。通用领域事件是合理整改，但 outbox 持久化失败必须继续使授权事务失败，不能按报告措辞将其降级为提交成功。 |
| BAS-05 | 已确认 | seed 命令自行写 App、scope、权限组、权限、授权组和规则，见 `src/easyauth/applications/management/commands/seed_crm_pilot.py:62-257`；规范导入入口另行处理版本、哈希和缺失项停用，见 `src/easyauth/applications/manifest_import.py:46-83`。平行写入语义成立，删除 seed 专用写法符合无兼容层要求。 |
| BAS-06 | 已确认 | `src/easyauth/notify/services.py` 当前为 1455 行，受理、配额、投递、对账和清理均在同一模块，代表性边界见 `:174-389`、`:486-605`、`:934-1162`、`:1318-1455`。严重度“中”合理；拆分必须直接迁移调用方，不应留下转发兼容模块。 |
| BAS-07 | 已确认 | `src/easyauth/lifecycle/services.py` 当前为 1386 行，交接、转岗、入职及 Webhook 编排集中在 `:111-619`、`:619-823`、`:831-1018`、`:1021-1386`。职责混杂成立，但具体拆成多少聚合仍是设计决策，不能把报告给出的四模块名称当成唯一方案。 |
| BAS-08 | 已确认 | 桶式重导出直接存在于 `src/easyauth/applications/models.py:19-50`，`ops_models.py` 的模型所有权见 `src/easyauth/applications/ops_models.py:27-54`。复核统计为 88 个源码文件直接导入该桶模块，报告的 89 有一项轻微偏差，不影响结论。删除重导出并一次性修改调用方符合项目约束。 |
| BAS-09 | 已确认 | 请求模型没有列表内唯一性校验，见 `src/easyauth/admin_console/connectors_api.py:100-116`；整表替换在重复键时直接 `continue`，见 `:464-488`。重复输入被静默改写，明确违反快速失败要求。 |
| BAS-10 | 已确认 | `ConnectorInstance.config` 对解密后非对象 JSON 返回 `{}`，见 `src/easyauth/connectors/models.py:137-144`；真实 schema 延后到连接器运行时校验，见 `src/easyauth/connectors/base.py:67-90`。空密文本身可由某些无配置连接器合法解释，但非对象 JSON 必须作为损坏数据失败，报告的修复方向正确。 |
| BAS-11 | 已确认 | API 客户端只确认外层是对象，见 `src/easyauth/integrations/dingtalk/api_client.py:221-243`；领域层对内部错误类型返回空集合或跳过，见 `src/easyauth/notify/services.py:1384-1425`。外部契约错误被解释为无变化，违反快速失败。 |
| BAS-12 | 已确认 | 授权状态在模型常量、`Literal` 和服务字符串中重复，见 `src/easyauth/grants/models.py:16-36`、`src/easyauth/grants/services.py:26`、`src/easyauth/lifecycle/services.py:1065-1068`。严重度“低”合理。 |
| HYP-01 | 未验证 | `admin_console` 写入口分散以及辅助函数只负责局部保存，见 `src/easyauth/admin_console/catalog_write_common.py:53-68`、`:129-152`，只能证明审计难度，不能证明已有入口漏审计、漏版本或在事务外执行副作用。应先建立写路径矩阵再形成缺陷编号。 |
| HYP-02 | 未验证 | 正式授权写路径确实逐行 `full_clean()`，见 `src/easyauth/grants/operations.py:45-74`；报告也承认没有找到正式旁路。它与 `DS-08` 使用相同结构证据却给出不同确认级别，后续应合并为一个“数据库归属约束专项验证”，不能同时作为已确认高危和待验证风险计数。 |

### 02 后端功能缺陷

| 编号 | 分类 | 复核结论与源码证据 |
| --- | --- | --- |
| BF-01 | 已确认 | 权威解析器校验专用标志和 `session_version`，见 `src/easyauth/accounts/local_admin.py:98-113`；控制台 actor 路径只检查账号 active 和用户镜像 active，见 `src/easyauth/admin_console/identity.py:16-39`，统一守卫直接依赖它，见 `src/easyauth/admin_console/request_guards.py:16-24`。旧本地超管会话可继续进入控制台，严重度“严重”成立。修复时还应让 `_clear_console_session()` 清除全部本地管理员会话键；当前只清两个 OIDC 键，见 `src/easyauth/admin_console/identity.py:50-52`。 |
| BF-02 | 需降级或限定 | OIDC 组只在登录时写入 session，见 `src/easyauth/accounts/auth.py:175-180`；控制台每次只读取该 session 快照，见 `src/easyauth/admin_console/identity.py:42-47`。撤组不会立即影响既有会话的事实成立，但仓库中没有查到“必须实时撤销上游组会话”的明确时限契约。应把严重度与会话有效期、后端回调能力和产品撤权目标绑定；在这些前提未定义前，宜列为高风险设计缺口而不是已复现功能错误。修复不得在权威源不可用时回退旧 session 组。 |
| BF-03 | 已确认 | TOTP 在验证前检查节流，见 `src/easyauth/accounts/local_admin_views.py:126-140`；passkey begin/complete 没有检查，但 complete 失败仍累计计数，见 `:143-167`。文档承诺包括二次验证，见 `docs/guides/local-admin-login.md:63-65`，契约违背成立。 |
| BF-04 | 已确认 | 幂等哈希未接收 `biz_tag`，见 `src/easyauth/notify/services.py:213-236`；受理流程已规范化并持久化该字段但计算哈希时遗漏，见 `:278-342`、`:953-970`。相同键、不同业务标签被错误当成同一请求。 |
| BF-05 | 已确认 | API 对布尔、数字强制 `str()`，对对象和数组返回空串，见 `src/easyauth/api/notify_views.py:319-344`；这些值继续进入受理服务，见 `:74-91`。明确违反严格 schema 和快速失败。 |
| BF-06 | 已确认 | 目录分页静默默认或截断，见 `src/easyauth/api/directory_views.py:487-511`；审批过滤和值分页同样宽松，见 `src/easyauth/api/approval_views.py:238-280`；控制台未知 App 状态返回全集，见 `src/easyauth/admin_console/apps_api.py:470-491`。项目已有严格解析反例，见 `src/easyauth/admin_console/operation_filters.py:219-265`。 |
| BF-07 | 需降级或限定 | 原始上游错误正文回显成立：全局钉钉测试直接返回 `str(error)`，见 `src/easyauth/admin_console/settings_api.py:160-164`，而文档要求不回显底层原文，见 `docs/api/easyauth-console-api.md:186-195`。但“探测失败必须使用非 2xx”不是普遍 HTTP 不变量；连接器端点明确返回 `{ok, message}`，见 `src/easyauth/admin_console/connectors_api.py:177-189`。因此应确认并修复信息泄露和三套端点契约不一致，是否统一为 503 需先固定 API 契约，不能只凭相邻端点行为定为功能缺陷。 |
| BF-08 | 已确认 | 既有 `UserMirror` 登录绑定不检查本地状态便写 session，见 `src/easyauth/accounts/auth.py:158-180`；callback 返回成功重定向，见 `src/easyauth/accounts/views.py:77-103`；门户随后才清会话，见 `src/easyauth/portal/views.py:16-27`。登录循环和假成功路径成立。 |
| BR-01 | 需降级或限定 | 无第二因子时直接绑定超管会话，见 `src/easyauth/accounts/local_admin_views.py:96-115`，而文档明确把它写成当前设计，见 `docs/guides/local-admin-login.md:45-52`。这是高风险产品选择，不是实现偏离现有契约；若安全基线要求强制第二因子，应一次性修改流程和文档。 |
| BR-02 | 需降级或限定 | Django admin 确实启用并注册路由，见 `src/easyauth/config/settings/base.py:44-52`、`src/easyauth/config/urls.py:103-110`，关键模型也已注册。实际风险还取决于生产是否存在 Django staff/superuser、网络暴露和独立认证配置；报告没有证明这些运行条件。建议保留为部署前高风险决策，而非已发生越权。 |
| BR-03 | 重复 | 无界读取和部分外部异常未归一化的证据见 `src/easyauth/accounts/oidc_exchange.py:105-120`、`:151-177`。这些内容被 `REL-PERF-17` 更完整覆盖，后者还证明每次登录重取 JWKS；应合并到 `REL-PERF-17`。 |
| BR-04 | 需降级或限定 | 所有控制台用户可看全部 App 的事实成立，见 `src/easyauth/admin_console/apps_api.py:412-423`、`:465-467`，测试也把它固定为当前产品行为。仓库没有证明列表必须按成员隔离，因此只能列为待确认的信息披露边界；一旦产品决定不公开，应直接收紧查询，不保留“旧全量列表”。 |

### 03 领域模型、schema 与业务不变量

| 编号 | 分类 | 复核结论与源码证据 |
| --- | --- | --- |
| DS-01 | 已确认 | `AccessRequest` 没有基础授权主键或修订字段，见 `src/easyauth/access_requests/models.py:77-138`；提交和落地分别重取当前授权，见 `src/easyauth/access_requests/submission_validation.py:235-246`、`src/easyauth/access_requests/application_grants.py:237-248`。批准内容可能作用于后来版本，属于高严重度并发语义缺陷。修复不得在缺少基础版本时回退最新授权。 |
| DS-02 | 已确认 | `TransferPlan` 只保存可变模板外键和自身 revision，见 `src/easyauth/lifecycle/models.py:514-557`；生成与确认分别读取模板，确认只比较 plan revision，见 `src/easyauth/lifecycle/services.py:625-731`；模板编辑会删除并重建项，见 `src/easyauth/admin_console/lifecycle_api.py:725-741`。预览和执行内容可漂移。报告修复文字有一处需澄清：若计划绑定不可变模板修订，后来产生新修订不应自动让旧计划 409，而应继续按已冻结修订执行；只有绑定修订被停用或计划前置条件失效才应冲突。 |
| DS-03 | 已确认 | passkey 在锁外读取旧 `sign_count` 并无条件保存新值，见 `src/easyauth/accounts/local_admin.py:392-420`；并发回退成立。修复应优先使用带旧值和单调条件的原子更新，竞争失败明确拒绝。 |
| DS-04 | 需降级或限定 | 实例 `delete()` 禁止物理删除，见 `src/easyauth/accounts/models.py:76-82`，而多个业务外键使用 `CASCADE`，例如 `src/easyauth/access_requests/models.py:83-91`、`src/easyauth/teams/models.py:57-65`；`QuerySet.delete()` 确实可绕过实例方法。但复核未找到应用正式入口调用 `UserMirror` 批量删除，accounts 也未注册 Django admin。数据库不变量缺失应修复，现有证据不足以定为已可达的高严重度数据丢失。原始 SQL 永远可绕过 ORM 不能单独作为应用缺陷证明。 |
| DS-05 | 未验证 | `event_id` 是唯一键且重复时不比较其他字段，见 `src/easyauth/integrations/models.py:26-61`、`src/easyauth/integrations/dingtalk/stream.py:43-74`。但模型和入口注释都把 DingTalk 的 `event_id` 定义为重投幂等身份，报告没有给出上游允许同一 ID 对应不同不可变业务事件的契约证据。按项目“不为罕见、未定义场景堆叠投机分支”的约束，在证明供应商契约或实际冲突前不应定为高危；如契约明确要求载荷一致，再把摘要比较作为严格幂等不变量。 |
| DS-06 | 已确认 | 创建时已计算拒绝数，但只要仍有 pending 就把汇总失败数写 0，见 `src/easyauth/notify/services.py:934-987`；后续投递才重算，见 `:1131-1162`。明细与汇总落库即矛盾，证据充分。 |
| DS-07 | 需降级或限定 | 多个状态机的数据库形状约束确实不完整，例如 `AccessRequest` 只约束枚举和期限，见 `src/easyauth/access_requests/models.py:140-161`，`grant_applied ↔ applied_at` 仅在 `clean()`，见 `:169-187`；outbox 状态和租约也只有字段与索引，见 `src/easyauth/outbox/models.py:19-48`。但这是把五个状态机合并成一个高危编号，报告未逐一证明正式迁移函数可写出所举非法组合。应拆成状态机真值表，按可达性和后果分别定级；数据库约束迁移必须先扫描坏数据并在发现时失败，不能静默填值。 |
| DS-08 | 需降级或限定 | 跨 App 归属主要由 `clean()` 保护，见 `src/easyauth/access_requests/models.py:253-319`、`src/easyauth/grants/models.py:118-194`，schema 设计缺陷成立。但当前正式写路径调用 `full_clean()`，且 `HYP-02` 明确承认没有找到正式旁路。应保留高影响、待验证可达性的定性，不能与 `HYP-02` 同时按“高危已确认”计数。第一性修复应改变可由数据库表达的键结构，不增加读取时纠错。 |
| DS-09 | 已确认 | `ManagedScopePolicy.target_id` 是无外键整数，存在性和同 App 关系只在 `clean()`，见 `src/easyauth/applications/models.py:566-646`；读取按裸 grant id 查询，见 `src/easyauth/applications/managed_scope_policy.py:38-52`。孤儿数据风险是结构上确定的，拆表并删除多态兼容列符合约束。 |
| DS-10 | 已确认 | `(dingtalk_corp_id, dingtalk_userid)` 只有普通索引，见 `src/easyauth/accounts/models.py:63-70`；通知解析使用 `.first()`，见 `src/easyauth/notify/services.py:859-863`，而另一解析器会把多行判为歧义。持久化和读取不变量不一致成立。迁移前必须扫描并对重复数据快速失败。 |
| DS-11 | 需降级或限定 | 同一 `AccessGrant` 原地递增 version 并替换成员关系，见 `src/easyauth/grants/lifecycle.py:62-79`、`src/easyauth/grants/operations.py:45-74`，所以它当前更像 revision。报告也承认影响取决于是否承诺历史快照；在找到将 `(user, app, version)` 当成可重建历史的正式调用方前，不应按已发生的历史丢失定性。应先选定 revision 或不可变快照语义，再一次性改名或重构。 |
| DS-12 | 需降级或限定 | 两个迁移无条件删除申请和授权，见 `src/easyauth/access_requests/migrations/0009_access_request_idempotency.py:15-30`、`src/easyauth/grants/migrations/0005_membership_expiration.py:15-30`；两个凭据迁移清空值，见 `src/easyauth/accounts/migrations/0007_alter_localadminaccount_totp_secret.py:7-27`、`src/easyauth/applications/migrations/0015_alter_integrationsettings_authentik_api_token.py:7-27`。问题真实，但注释明确限定未上线重置，当前从零迁移时表为空。严重度应限定为“携带旧开发/试点数据升级时高”；在上线基线前压平迁移，或遇非空数据直接失败，不应保留静默删除链。 |
| DS-13 | 已确认 | `AuditLog` 持续追加且 `Meta` 只有排序，见 `src/easyauth/audit/models.py:30-51`；唯一清理按 `created_at` 过滤，常用查询还按事件、actor 和 target 过滤。缺索引事实成立，但具体索引组合应由 PostgreSQL `EXPLAIN` 和基数决定，不能直接照抄候选列表。 |

### 04 后端可靠性与性能

| 编号 | 分类 | 复核结论与源码证据 |
| --- | --- | --- |
| REL-PERF-01 | 已确认 | Webhook worker 认领后仍有配置解析、JSON 编码、HTTP 和完成写入，见 `src/easyauth/webhooks/delivery.py:125-178`；任务只处理两类预期异常，见 `src/easyauth/tasks/webhooks.py:19-35`；租约过期没有 scanner，手工重投只接受 `failed`，见 `src/easyauth/webhooks/delivery.py:198-217`、`:228-250`。未预期异常或 worker 丢失会留下不可恢复 pending，严重度“严重”成立。 |
| REL-PERF-02 | 已确认 | 离职禁号任务捕获未配置和用户不存在后返回成功结果，见 `src/easyauth/tasks/lifecycle.py:16-50`；用户扫描最多固定页数，越过上限仍抛 not found，见 `src/easyauth/integrations/authentik/admin_client.py:119-152`。安全动作假成功成立。修复建议中的“优先精确 UID 查询”需限定：源码注释明确标准 API 不支持 UID 过滤，见 `:119-121`；当前可立即实施的是区分页数上限与真实不存在，并让未完成动作持久失败和重试。 |
| REL-PERF-03 | 重复 | 与 `DS-03` 是同一 `sign_count` 无锁读写路径，证据均为 `src/easyauth/accounts/local_admin.py:392-420`。保留 `DS-03` 作为 schema/并发不变量主项即可。 |
| REL-PERF-04 | 已确认 | 单用户 org 拉取异常被记录后继续，只有全部失败才中止，见 `src/easyauth/integrations/authentik/directory_sync.py:175-192`；随后仍把可写 corp generation 标为 success，见 `:371-393`。同 generation 后续会被跳过，见 `:326-341`。部分旧组织事实被固化为成功代次，证据充分。 |
| REL-PERF-05 | 已确认 | 目录客户端直接无界 `read()`，且只捕获 `HTTPError`、`URLError`，见 `src/easyauth/integrations/authentik/directory_client.py:190-209`；任务只对 `AuthentikDirectoryError` 自动重试，见 `src/easyauth/tasks/authentik.py:57-67`。大小和异常归一化缺口成立。 |
| REL-PERF-06 | 已确认 | 每轮先物化全部用户并逐个远端查询 org，见 `src/easyauth/integrations/authentik/directory_sync.py:164-189`；直到末尾才再次读取状态并比较 generation，见 `:193-196`。即使代次未变化也已完成 N 次外部调用，任务又无总时限或单实例租约。 |
| REL-PERF-07 | 已确认 | URL 解析保留 Unicode path/query，见 `src/easyauth/config/net.py:182-223`；HTTP request-target 异常只归一化 `TimeoutError`、`HTTPException` 和 `OSError`，见 `src/easyauth/webhooks/transport.py:145-175`，不包含 `UnicodeEncodeError`。保存成功、投递期异常逃逸的路径成立。 |
| REL-PERF-08 | 重复 | 与 `BAS-02` 完全相同，均指向 `src/easyauth/lifecycle/services.py:213-245`、`:967-979` 和 `src/easyauth/webhooks/hooks.py:30-39`。应只保留一个缺陷编号。 |
| REL-PERF-09 | 已确认 | `direct_grants` 无 `max_length`，见 `src/easyauth/portal/access_request_payloads.py:32-39`；逐项 scope 查询与错误累积见 `src/easyauth/access_requests/target_validation.py:49-59`、`:107-126`；落库逐项 `full_clean()` 和 `save()`，见 `src/easyauth/access_requests/services.py:244-255`。认证用户可制造无界数据库工作量。批量化前仍必须做等价严格校验，不能用 `bulk_create` 绕开 DS-08 所述归属不变量。 |
| REL-PERF-10 | 已确认 | 列表每行调用恢复函数，见 `src/easyauth/api/approval_views.py:192-211`；恢复函数无条件开启事务并 `select_for_update()`，见 `src/easyauth/workflows/services.py:376-404`；单页上限 100，见 `src/easyauth/api/approval_views.py:42-45`。普通 GET 的逐行写锁放大成立。 |
| REL-PERF-11 | 已确认 | App 列表逐项调用 readiness 和 owner 查询，见 `src/easyauth/admin_console/apps_api.py:148-152`、`:412-423`；readiness 内含多组 `.exists()`、逐组规则查询和逐 grant 策略查询，见 `src/easyauth/applications/configuration.py:46-107`、`:119-195`、`:202-240`。嵌套 N+1 成立。 |
| REL-PERF-12 | 已确认 | 授权组预取 grants，见 `src/easyauth/admin_console/permission_catalog_data.py:97-101`，序列化却重新过滤相关管理器并逐 grant 查策略，见 `:149-220`；GET 返回全集且无分页，见 `src/easyauth/admin_console/authorization_groups_api.py:98-100`。 |
| REL-PERF-13 | 已确认 | 健康检查确实写入 connectors 结果，见 `src/easyauth/applications/dependency_health_checks.py:67-89`；统一读取枚举遗漏 connectors，见 `src/easyauth/applications/dependency_health.py:20-26`、`:65-81`。监控盲区可直接证明。 |
| REL-PERF-14 | 已确认 | 健康解析器对缺失 `source_slug` 回退配置，并把缺失或错误的 `sync` 变成空元组，见 `src/easyauth/integrations/authentik/directory_payloads.py:84-88`；健康检查只要解析不抛错就标 healthy，见 `src/easyauth/applications/dependency_health_checks.py:126-146`。同一仓库的正式同步契约要求非空 sync，见 `src/easyauth/integrations/authentik/directory_sync.py:213-219`，因此 `{}` 假健康不是产品歧义。 |
| REL-PERF-15 | 已确认 | 每次 DNS 解析新建 daemon 线程，超时只停止等待，见 `src/easyauth/config/net.py:125-156`。`getaddrinfo()` 无法取消，重复超时可累积遗留线程。修复应使用有界 resolver 资源和拒绝策略，不能在超载时静默回退无 DNS 校验。 |
| REL-PERF-16 | 已确认 | 心跳线程循环没有异常边界，见 `src/easyauth/integrations/management/commands/run_dingtalk_stream.py:30-48`；每轮调用可能抛错的 cache 写，见 `src/easyauth/config/runtime_health.py:37-42`；stream 容器禁用 healthcheck，见 `docker-compose.deploy.yml:165-174`。缓存异常会杀死辅助线程而主进程继续存活。 |
| REL-PERF-17 | 已确认 | token/JWKS 响应均经无界 `response.read()`，网络异常只捕获两类，见 `src/easyauth/accounts/oidc_exchange.py:105-120`；每次 ID token 验证都调用 `_jwks_public_key()` 并重新请求，见 `:123-167`。资源和可用性问题成立，也是 `BR-03` 的规范合并项。 |
| REL-PERF-18 | 已确认 | `latest_items()` 排序后在 Python 中遍历整张快照表，见 `src/easyauth/applications/dependency_health.py:65-81`；每轮健康检查继续追加六行，见 `src/easyauth/applications/dependency_health_checks.py:67-89`。仓库未见该表保留期清理，线性增长成立。 |
| REL-PERF-19 | 已确认 | 过期授权查询无 limit/游标并由普通 QuerySet 迭代，见 `src/easyauth/tasks/grants.py:29-55`；每项再执行独立授权事务和多次关系写，见 `src/easyauth/grants/expiration.py:77-122`；beat 每 60 秒调度，见 `src/easyauth/config/settings/base.py:338-341`。严重度“中”合理。 |
| REL-PERF-20 | 已确认 | 部门接口直接 `list(queryset)`，见 `src/easyauth/api/directory_views.py:268-302`；团队接口一次返回全部团队和成员，见 `src/easyauth/admin_console/teams_api.py:96-116`；模板列表逐模板查询 items，见 `src/easyauth/admin_console/lifecycle_api.py:514-523`、`:913-950`。三个无界或 N+1 路径均有直接证据。 |
| REL-PERF-21 | 已确认 | 普通 GET 同步调用远端 `list_external_groups()` 并全量序列化，见 `src/easyauth/admin_console/connectors_api.py:214-240`；NetBird 每次调用总时限 30 秒，见 `src/easyauth/connectors/netbird/client.py:19-23`、`:172-190`。请求 worker 阻塞和无界响应成立。 |
| REL-PERF-22 | 已确认 | 对账在配置缺失或远端调用失败后仍无条件 `_mark_task_reconciled()`，见 `src/easyauth/notify/services.py:486-528`；远端错误被 `_reconcile_one_task()` 转为空集合，见 `:564-588`。空结果同时表示成功无变化和依赖失败，明确违反快速失败。 |
| REL-PERF-23 | 已确认 | 聚合计数执行 `cache.get()`、Python 自增、`cache.set()`，且只在下一次请求观察到小时翻转时冲刷，见 `src/easyauth/api/directory_views.py:547-580`。并发丢更新和尾桶不落库均成立。 |
| REL-PERF-24 | 重复 | 是 `BF-06` 中分页参数问题的严格子集，证据仍为 `src/easyauth/api/approval_views.py:260-280` 和 `src/easyauth/api/directory_views.py:487-511`。应并入 `BF-06`。 |
| REL-PERF-25 | 已确认 | 认证拒绝 inactive App，见 `src/easyauth/applications/services.py:170-193`；签发路径先生成 secret 并直接创建 credential，没有重新锁定或检查 App 状态，见 `:218-235`。从生成起不可用的凭据仍返回成功，修复必须在生成 secret 前失败。 |
| REL-PERF-26 | 已确认 | 目录异常和 stale 都被映射到 `_bad_request()`，见 `src/easyauth/admin_console/managed_users_preview_api.py:169-184`；辅助函数固定返回 `VALIDATION_ERROR`/400，见 `:241-247`。依赖故障被误分类且异常链丢失。 |

## 可证明的高风险遗漏

### OMIT-BE-01：连接器任务时限长于租约，旧 worker 可在失去租约后继续执行外部撤权

- 严重度：高。
- 置信度：高。
- 01–04 覆盖情况：未覆盖。

证据链：

1. 连接器数据库租约固定为 600 秒，queue claim 超时也为 600 秒，见 `src/easyauth/connectors/services.py:36-38`。
2. worker 认领时把 `reconcile_lease_expires_at` 设置为当前时间加 600 秒并清除 dirty，见 `src/easyauth/connectors/services.py:178-219`。
3. Celery soft/hard 时限分别为 840/900 秒，允许 worker 在租约失效后继续运行最多约 300 秒，见 `src/easyauth/tasks/connectors.py:29-45`。
4. 周期调度器每 60 秒检查实例；租约过期且队列标记 stale 后会重新请求对账，见 `src/easyauth/tasks/connectors.py:48-79`。正在运行的 worker 在 claim 时已清掉 `reconcile_worker_queued`，见 `src/easyauth/connectors/services.py:190-191`，因此新 worker 可以重新入队并取得同一实例。
5. NetBird 单轮最多允许 500 次 API 调用，每次总时限 30 秒，见 `src/easyauth/connectors/netbird/connector.py:28-31`、`src/easyauth/connectors/netbird/client.py:19-23`，执行超过 600 秒不是不可达场景。
6. 只有扩权/解封前调用 `expansion_allowed()` 校验并续租，见 `src/easyauth/connectors/netbird/connector.py:245-300`、`src/easyauth/connectors/services.py:257-277`。安全收缩和无授权用户封禁阶段直接执行外部更新，没有 lease token 或 generation fence，见 `src/easyauth/connectors/netbird/connector.py:308-388`。

失效路径：

旧 worker 基于 generation N 构建 desired state，在列举远端用户或执行大量收缩时运行超过 600 秒；调度器随后排队新 worker，后者取得 generation N+1 的租约并按更新后的授权事实开始外部写入。旧 worker仍可继续按旧快照删除组或封禁用户，因为收缩路径不检查租约。即使 `_finish_generation()` 最终拒绝旧 token，外部副作用已经发生，数据库 fencing 无法撤回。

第一性修复：

- 让租约时长严格覆盖任务 hard limit 并留出 broker/调度裕量，同时在所有外部副作用前续租和比较 `lease_token + generation`，包括撤组、封禁、加组、创建和解封。
- 更稳健的方案是在每个有限批次前续租，租约丢失立即中止，不再执行任何外部动作；任务 hard limit、租约、API 预算和批次 deadline 由同一配置事实源推导。
- 新 worker 只能在确认旧租约失效且旧执行无法继续产生外部副作用后接管；若外部 API 不支持 fencing，单批最大执行时间必须严格小于租约并采用可恢复游标。
- 不得通过“忽略旧 worker 的 `_finish_generation()` 失败”或事后再跑一轮对账掩盖并发外部写；这两种做法不能保证撤权和扩权顺序。

## 修复建议的约束复核

四份报告的大多数整改方向符合项目约束，尤其是严格输入、删除平行写路径、重建可由数据库表达的关系、以及遇版本冲突明确失败。实施时需保留以下边界：

1. `BAS-04` 的领域事件解耦不能把 outbox 持久化失败吞掉。授权事实与“必须投影”的事件要么同事务提交，要么整体失败。
2. `DS-01`、`DS-02` 不得在缺少基础修订时读取最新事实作为兼容；旧计划和旧申请应明确失效。
3. `DS-07`、`DS-08` 的约束迁移不得静默修复非法历史行；先扫描、发现即失败、人工清理后再加约束。
4. `REL-PERF-09` 使用 `bulk_create` 前必须完成与现有 `full_clean()` 等价且不可遗漏的集合校验，不能以性能修复重新打开跨 App 写入旁路。
5. `REL-PERF-14`、`REL-PERF-22`、`REL-PERF-26` 的外部依赖错误必须保留故障类别和异常链，不能转为空集合、客户端 400 或成功状态。
6. 所有重复项应先合并主编号再排期，避免同一根因被四份报告重复计入优先级。

## 复核边界

- 本复核没有修改应用代码、测试或原始审计报告。
- 未进行生产规模压测，也未把“理论上可由 raw SQL 绕过”单独当作正式应用路径。
- 对并发问题采用源码时序、事务和租约条件核验；当前本地数据库为 SQLite，未用它声称 PostgreSQL 行锁行为已被运行时复现。
- 本文只新增复核文档；未创建 commit。
