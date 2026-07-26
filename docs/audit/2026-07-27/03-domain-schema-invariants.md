# EasyAuth 领域模型、数据模式与业务不变量审计

审计日期：2026-07-27

## 审计结论

本次审计发现 13 项问题，其中高严重度 9 项、中严重度 4 项。最需要优先处理的不是单个字段，而是四条贯穿领域、持久化和接口的事实边界：

1. `change`、`revoke`、`renew` 申请没有绑定审批时所见授权版本，已批准命令可能覆盖后续授权事实。
2. 转岗差异确认只校验计划版本，不校验岗位模板版本，确认时会读取并应用已变化的模板内容。
3. 多个状态机和跨应用归属关系只依赖 `choices` 或 `clean()`，数据库仍可保存业务上不可能的状态。
4. 用户不可物理删除、事件幂等、WebAuthn 计数器等安全不变量只在局部代码路径成立，并未形成事务或数据库级保证。

建议先修复 DS-01、DS-02、DS-03、DS-04，再处理 DS-05、DS-07、DS-08 和 DS-12。项目尚未上线，适合直接收敛到唯一正确模型；下述修复均不建议增加兼容字段、兼容读取或静默修复分支。

## 范围与方法

审计覆盖 Django 模型、迁移、申请与授权持久化、交接和转岗、通知、Outbox、审批回调、钉钉 Stream、目录身份、本地管理员 WebAuthn、审计日志及相关 API/服务代码。审计以静态数据流、事务边界、数据库约束和状态迁移为主，并执行了文末列出的只读或非写入检查。

严重度含义：

- 高：可造成权限事实错误、审批内容与实际执行不一致、安全不变量失效、业务事件丢失或批量数据破坏。
- 中：会形成持久化矛盾、审计语义错误、孤儿数据或可预期的规模化性能退化，但通常还需要额外触发条件。

置信度含义：

- 高：代码路径与模式直接证明问题，无需依赖未知外部行为。
- 中：模式存在明确语义冲突，但最终影响取决于产品是否承诺历史快照等尚未完全形式化的契约。

## 发现概览

| 编号 | 严重度 | 置信度 | 主题 |
| --- | --- | --- | --- |
| DS-01 | 高 | 高 | 生命周期申请未绑定基础授权版本 |
| DS-02 | 高 | 高 | 转岗计划未冻结岗位模板版本 |
| DS-03 | 高 | 高 | WebAuthn `sign_count` 存在并发回退 |
| DS-04 | 高 | 高 | `UserMirror` 不可删除不变量可被绕过 |
| DS-05 | 高 | 高 | 钉钉 Stream 幂等键冲突被当作正常重复 |
| DS-06 | 中 | 高 | 通知汇总计数落库即与明细矛盾 |
| DS-07 | 高 | 高 | 核心状态机缺少数据库形状约束 |
| DS-08 | 高 | 高 | 跨应用权限归属只由 `clean()` 保护 |
| DS-09 | 中 | 高 | 托管范围策略使用无外键的多态目标 |
| DS-10 | 中 | 高 | 钉钉身份绑定不唯一且通知任取首行 |
| DS-11 | 中 | 中 | 授权“版本”与历史快照语义冲突 |
| DS-12 | 高 | 高 | 历史迁移静默清空业务事实和凭据 |
| DS-13 | 中 | 高 | 追加型审计表缺少查询与清理索引 |

## DS-01：生命周期申请未绑定基础授权版本

- 严重度：高
- 置信度：高

### 证据

- `AccessRequest` 保存了用户、应用、申请类型、目标和载荷摘要，但没有基础 `AccessGrant` 的主键或版本字段：`src/easyauth/access_requests/models.py:77-138`。
- 提交 `change`、`revoke`、`renew` 时只查询“当前有效授权”，查询结果没有写入申请事实：`src/easyauth/access_requests/submission_validation.py:235-246`。
- 执行 `change` 时再次读取当时的当前授权，随后直接调用覆盖式变更：`src/easyauth/access_requests/application_grants.py:96-111`、`src/easyauth/access_requests/application_grants.py:144-157`。
- 执行前校验只确认授权当前、有效以及目标集合关系，没有比较审批时版本：`src/easyauth/access_requests/application_grants.py:237-284`。
- 授权变更、撤销和到期会原地递增 `version`：`src/easyauth/grants/lifecycle.py:62-79`、`src/easyauth/grants/lifecycle.py:133-144`、`src/easyauth/grants/expiration.py:77-93`。

### 失效场景

授权 v5 包含权限 A。申请 R1 基于 v5 提交，将其改为 B；R1 审批期间，另一申请或管理员操作将授权改为 v6，即 A+C。R1 随后通过，执行代码读取“最新当前授权”，并以 B 替换成员关系，未经重新审批便丢失 C。`revoke` 和 `renew` 也没有绑定审批时事实，可能作用于审批人未见过的新版授权。

### 根因

申请模型只表达期望结果，没有表达命令的前置条件。`version` 存在于授权聚合，却没有进入申请、幂等摘要、审批展示或执行时的乐观并发检查。

### 第一性修复

将 `change`、`revoke`、`renew` 建模为“针对确定授权版本的命令”：

1. 模式层新增非空的基础授权外键和基础版本；仅 `grant` 申请允许二者为空，并用数据库约束固定申请类型与字段形状。
2. 提交事务中锁定当前授权，保存其主键和版本，并把它们纳入 `payload_digest`。
3. API、审批表单、审核页面和审计事件必须展示该基础版本及其快照。
4. 执行和重试时锁定同一授权，主键或版本不一致即以明确“申请已过期”状态失败，不得回退到最新授权。
5. 同步修改 domain service、schema、迁移、API 契约、前端审核体验、并发测试和中文文档；不要保留“缺版本时使用最新授权”的兼容路径。

## DS-02：转岗计划未冻结岗位模板版本

- 严重度：高
- 置信度：高

### 证据

- `TransferPlan` 只保存可变的 `new_template` 外键、差异 JSON 和自身 `revision`，没有模板版本或内容摘要：`src/easyauth/lifecycle/models.py:514-557`。
- 生成计划时读取当前模板项，然后只递增计划自身的 `revision`：`src/easyauth/lifecycle/services.py:625-663`。
- 确认时仅比较 `plan.revision`，随后重新读取当前模板项并据此执行：`src/easyauth/lifecycle/services.py:677-731`。
- 模板项身份键不包含 `grant_type` 或 `duration_days`，而实际到期时间在确认时根据当前模板项计算：`src/easyauth/lifecycle/services.py:1316-1321`、`src/easyauth/lifecycle/services.py:1340-1345`。
- 管理员编辑模板会锁定模板后删除全部模板项并重建：`src/easyauth/admin_console/lifecycle_api.py:725-741`。
- 生成差异要求模板启用，但确认接口不重新校验模板是否启用：`src/easyauth/admin_console/lifecycle_api.py:445-474`、`src/easyauth/admin_console/lifecycle_api.py:477-511`；模板可以独立停用：`src/easyauth/admin_console/lifecycle_api.py:545-558`。

### 失效场景

管理员预览的模板项是永久授权。另一管理员在确认前将同一项改为 1 天限时授权，或者停用模板。由于项键和计划版本均未变化，旧页面提交仍通过，并按修改后的模板执行；被确认的内容与管理员实际审核内容不一致。

### 根因

可变模板同时承担“当前配置”和“审批证据”两种职责。计划版本只保护计划行，不保护计划依赖的模板内容。

### 第一性修复

建立不可变的 `OnboardingTemplateRevision` 及其模板项，模板编辑应创建新修订而不是删除重建现有事实。`TransferPlan` 必须保存确切模板修订或规范化内容摘要，并冻结包含期限信息的差异载荷。确认时锁定并比较计划与模板修订，按冻结修订执行；模板已停用或修订变化时返回明确 `409`，要求重新生成和复核。同步更新模板写入 API、前端修订令牌、审计日志、并发测试、迁移和中文文档，不增加“修订缺失时读当前模板”的兼容分支。

## DS-03：WebAuthn `sign_count` 存在并发回退

- 严重度：高
- 置信度：高

### 证据

- `LocalAdminPasskey.sign_count` 是普通 `IntegerField`，没有非负约束：`src/easyauth/accounts/models.py:282-302`。
- 验证流程在事务和行锁之外读取通行密钥及旧计数：`src/easyauth/accounts/local_admin.py:398-415`。
- 验证后以普通 `save()` 写回新计数，没有比较并交换条件：`src/easyauth/accounts/local_admin.py:416-420`。

### 失效场景

两个并发登录都读取计数 9，分别得到新计数 10 和 11。计数 11 先保存，计数 10 后保存，数据库最终回退到 10，削弱 WebAuthn 对克隆认证器或异常计数的检测能力。此入口是本地超级管理员认证，影响边界高。

### 根因

安全计数器被实现为普通读—验证—写流程，未把“新值必须严格基于当前持久化值”放入同一串行化边界。

### 第一性修复

在事务中使用 `select_for_update()` 锁定凭据并针对锁定值验证，或使用带 `sign_count__lt=new_count` 条件的原子更新并检查影响行数；竞争失败必须重新验证或明确拒绝。按 WebAuthn 规范单独定义始终为零的认证器行为，并增加 `sign_count >= 0` 数据库约束。同步调整认证错误、审计事件、并发测试、模型迁移和中文安全文档。

## DS-04：`UserMirror` 不可删除不变量可被绕过

- 严重度：高
- 置信度：高

### 证据

- 模型声明物理删除错误，并只覆盖实例 `delete()`：`src/easyauth/accounts/models.py:20-28`、`src/easyauth/accounts/models.py:76-82`。
- `QuerySet.delete()` 不调用每个模型实例的 `delete()`，因此该覆盖不能保护批量删除、级联收集器或原始 SQL。
- 申请、授权和团队成员对用户使用 `CASCADE`：`src/easyauth/access_requests/models.py:83-86`、`src/easyauth/grants/models.py:44-47`、`src/easyauth/teams/models.py:62-65`。
- 交接单对用户使用 `PROTECT`：`src/easyauth/lifecycle/models.py:103-117`，使物理删除能否成功偶然取决于用户是否恰有某类关联数据。

### 失效场景

管理脚本执行 `UserMirror.objects.filter(...).delete()`，绕过实例方法。如果没有 `PROTECT` 关联，申请、授权和团队成员会被级联删除；如果存在交接单，则同一操作又突然失败。业务事实保留策略由偶然的关联集合决定。

### 根因

领域不变量被放在 ORM 实例钩子里，而数据库外键表达的却是允许级联删除，两层契约互相矛盾。

### 第一性修复

先确定用户为持久身份事实：所有需要保留的业务事实外键改为 `PROTECT` 或 `RESTRICT`，离职与停用只通过显式状态迁移和 tombstone 服务完成。自定义 QuerySet/manager 的删除保护只能作为纵深防御；若“任何入口绝不可删除”为硬要求，还应增加 PostgreSQL 触发器或撤销表级删除权限。同步更新管理员入口、目录同步、API、领域服务、删除与级联测试、迁移和中文数据保留文档，不保留物理删除兼容路径。

## DS-05：钉钉 Stream 幂等键冲突被当作正常重复

- 严重度：高
- 置信度：高

### 证据

- 收件箱仅以 `event_id` 唯一，虽保存事件类型、企业、时间和数据，但没有规范化载荷摘要：`src/easyauth/integrations/models.py:26-61`。
- `record_stream_event()` 使用 `get_or_create(event_id=...)`；命中既有行时不比较其他不可变字段，仍返回重复收据：`src/easyauth/integrations/dingtalk/stream.py:43-74`。
- 处理器对该情况返回成功 ACK 和“重复”消息：`src/easyauth/integrations/dingtalk/stream.py:85-117`。

### 失效场景

上游错误复用 `event_id`，或链路中的载荷发生冲突。第一条事件已落库后，第二条不同事件命中相同主键，被系统 ACK 为正常重复；后一个业务事实永久丢失，也没有冲突记录或告警。

### 根因

实现把“去重键相同”等同于“事件事实相同”，却没有验证幂等请求的不可变载荷。

### 第一性修复

对事件类型、企业、发生时间和数据生成规范化摘要并持久化。原子 `get_or_create` 后必须比较摘要：完全一致才是重投；不一致应保存显式冲突事实和安全审计，返回可重试或需人工介入的失败，不得 ACK 为成功。同步更新模型、迁移、收件入口、指标告警、运维处置、冲突测试和中文文档。

## DS-06：通知汇总计数落库即与明细矛盾

- 严重度：中
- 置信度：高

### 证据

- 创建通知时已经计算出失败收件人数 `rejected`：`src/easyauth/notify/services.py:934-951`。
- 只要仍有待发送收件人，消息行就把 `recipient_failed` 强制写成 0，而失败明细同时通过 `bulk_create()` 落库：`src/easyauth/notify/services.py:953-987`。
- 汇总只有后续投递阶段才会从明细重算：`src/easyauth/notify/services.py:1131-1162`。
- 查询 API 直接返回消息行的 `recipient_failed`，同时返回收件人明细：`src/easyauth/api/notify_views.py:171-190`。

### 失效场景

一次请求包含一个无法解析的收件人和一个有效收件人。创建成功后，失败明细已存在，但 `recipient_failed=0`；调用方立即查询时，同一响应的汇总与明细互相矛盾。如果 Outbox 或投递任务延迟、卡住或永久失败，矛盾可长期存在。

### 根因

代码把“受理阶段已拒绝”与“投递阶段失败”混为一套计数，却又为了待处理状态刻意抹掉已知失败数，去范式化汇总没有单一事实来源。

### 第一性修复

最小正确修复是创建时无条件写入 `recipient_failed=rejected`，并保证消息与明细在同一事务完成；更稳健的模型是明确区分受理拒绝数与投递失败数，或删除可漂移汇总、按明细聚合。数据库增加 `sent + failed <= total` 等计数约束，API 契约明确每个计数含义，并同步更新服务、前端展示、状态测试、迁移和中文文档。

## DS-07：核心状态机缺少数据库形状约束

- 严重度：高
- 置信度：高

### 证据

- `AccessRequest` 的数据库约束只覆盖枚举和期限形状，`grant_applied ↔ applied_at` 仅在 `clean()` 中校验：`src/easyauth/access_requests/models.py:140-187`；`approved_at`、`decided_at`、决定人和决定类型也没有状态形状约束。
- `NotifyMessage` 包含状态、claim、lease、计数和 `completed_at`，约束却只检查幂等和状态枚举：`src/easyauth/notify/models.py:134-194`。
- `OutboxEvent` 包含状态、租约和 `published_at`，只有索引，没有状态枚举或依赖字段约束：`src/easyauth/outbox/models.py:19-48`。
- `PendingApprovalCallback` 包含状态、处理阶段、实例和 `applied_at`，`Meta` 只有排序：`src/easyauth/workflows/models.py:256-295`。
- 钉钉 Stream 事件的 `processed_at`、错误和状态同样没有形状约束：`src/easyauth/integrations/models.py:43-65`。
- 实际状态迁移大量使用 `bulk_update()` 和 `QuerySet.update()`，会绕过 `clean()` 与模型 `save()`：`src/easyauth/outbox/services.py:105-169`、`src/easyauth/notify/services.py:1083-1162`、`src/easyauth/notify/services.py:1256-1282`。

### 失效场景

数据库可保存 `grant_applied` 但 `applied_at=NULL`、`published` 但 `published_at=NULL`、已完成通知仍带租约、回调已应用却没有实例或应用时间等状态。worker 可能永远跳过这些行，API 和审计又会把它们解释为成功或终态。

### 根因

`choices` 被误当成数据库约束，`clean()` 被误当成所有写入都会执行的校验；但 Django 的 `save()` 默认不调用 `full_clean()`，批量更新更会绕过所有模型钩子。

### 第一性修复

为每个状态机先写出合法状态与依赖字段真值表，再建立数据库 `CheckConstraint`：枚举、终态时间、claim/lease 配对、错误字段、计数边界、应用实例等都必须由数据库拒绝非法组合。状态迁移集中到领域服务，使用带旧状态和租约令牌条件的原子更新并检查影响行数。跨行计数应以明细为事实源或通过事务内锁定维护。迁移必须先检查并拒绝现有坏数据，不能静默填默认值；同步更新模型、服务、worker、API、前端、负向测试和中文状态机文档。

## DS-08：跨应用权限归属只由 `clean()` 保护

- 严重度：高
- 置信度：高

### 证据

- 授权组授予权限的数据库只保证三字段唯一；权限、范围与授权组属于同一应用只在 `clean()` 中查询验证：`src/easyauth/applications/models.py:490-557`。
- 申请目标组和目标权限的数据库只保证行内唯一；跨应用和范围支持校验只在 `clean()`：`src/easyauth/access_requests/models.py:230-267`、`src/easyauth/access_requests/models.py:270-319`。
- 已生效授权目标也采用同样结构：`src/easyauth/grants/models.py:93-137`、`src/easyauth/grants/models.py:140-194`。
- 权限组的父级是普通自外键；数据库检查深度范围，但父子同应用、无环和深度一致依赖 Python 校验：`src/easyauth/applications/ops_models.py:137-190`。
- `ApprovalInstance` 同时保存应用和模板外键，但模式不保证模板属于该应用：`src/easyauth/workflows/models.py:144-163`；`NotifyMessage` 的应用和通道也没有同应用约束：`src/easyauth/notify/models.py:92-111`。

### 失效场景

批量导入、数据迁移、Django admin、shell 或后续新服务绕过 `full_clean()`，可把应用 A 的申请或授权连到应用 B 的权限和范围。后续权限查询可能把跨租户事实当作有效授权，或在不同 API 中得到互相冲突的归属。

### 根因

模式在父表和目标表重复保存应用归属，却没有数据库可执行的关系；写路径的 Python 校验只是惯例，不是持久化不变量。

### 第一性修复

重新设计可由数据库表达归属的键：优先让关联通过应用内目标实体建立，或使用包含 `app_id` 的唯一键和 PostgreSQL 可验证的复合外键；层级无环等无法用普通约束表达的规则应使用封闭写服务及数据库触发器。`ApprovalInstance` 和 `NotifyMessage` 应消除重复应用来源，或用复合关系强制一致。同步修正 schema、domain、所有写路径、API 序列化、前端选择器、迁移、原始 SQL/批量写负向测试和中文文档，不增加读取时“纠正到父应用”的兼容层。

## DS-09：托管范围策略使用无外键的多态目标

- 严重度：中
- 置信度：高

### 证据

- `ManagedScopePolicy` 以 `target_type + target_id` 表示应用默认策略或 `AuthorizationGroupGrant`，`target_id` 只是整数，不是外键：`src/easyauth/applications/models.py:566-606`。
- 目标存在性和同应用关系仅在 `clean()` 中查询：`src/easyauth/applications/models.py:618-646`。
- 读取授权组覆盖策略时按裸 `grant.id` 查询：`src/easyauth/applications/managed_scope_policy.py:38-52`。
- 正常管理路径需要显式查找并删除策略，证明数据库不会随目标删除自动维护：`src/easyauth/admin_console/authorization_groups_api.py:360-409`。

### 失效场景

任何未配套调用策略清理的授权组授予删除都会留下孤儿策略。它会静默停止生效，但仍出现在管理或健康数据中；目标类型扩展后，同一个整数还可能产生难以察觉的错误绑定。

### 根因

两个语义完全不同的目标被压进一个无参照完整性的多态表，以应用代码模拟外键。

### 第一性修复

拆分应用默认策略和授权组授予覆盖策略。覆盖表应以真实 `OneToOneField` 或外键指向 `AuthorizationGroupGrant`，应用从目标派生或由复合约束保证；明确采用 `CASCADE` 还是 `PROTECT`。一次性迁移所有调用方和数据，删除旧多态列及读取分支，同时更新 API、前端、测试和中文文档。

## DS-10：钉钉身份绑定不唯一且通知任取首行

- 严重度：中
- 置信度：高

### 证据

- `UserMirror` 的 `(dingtalk_corp_id, dingtalk_userid)` 只有普通索引，没有唯一约束：`src/easyauth/accounts/models.py:31-70`。
- 通知解析到企业目录用户后，通过该二元组查询 `UserMirror` 并调用 `.first()`；结果只受模型默认的 `authentik_user_id` 排序影响，而不是身份绑定语义：`src/easyauth/accounts/models.py:63-70`、`src/easyauth/notify/services.py:787-830`、`src/easyauth/notify/services.py:859-863`。
- 另一条用户引用解析路径已明确把多行视为歧义并抛错：`src/easyauth/accounts/directory_references.py:154-187`，与通知路径语义不一致。

### 失效场景

两个 Authentik 用户错误绑定到同一个钉钉身份。通知实际发送给正确钉钉用户，但收件人事实会按与外部身份无关的用户编号排序关联首行，导致审计主体、用户查询和后续授权联动归到错误账户。

### 根因

外部目录身份被重复嵌入用户镜像字符串字段，没有独立的、可唯一约束且包含来源作用域的绑定实体；不同调用方自行决定如何处理重复。

### 第一性修复

建立规范化 `UserDirectoryBinding`，以 `source_slug + corp_id + external_user_id` 唯一，并只允许一个活动的 `UserMirror` 关联。通知收件人保存绑定外键而非再按字符串猜测。迁移前必须扫描重复并明确失败，人工解决后再加约束；同步修改目录同步、解析器、通知、API、审计、测试和中文身份模型文档，不以 `.first()` 或旧字段回退掩盖重复。

## DS-11：授权“版本”与历史快照语义冲突

- 严重度：中
- 置信度：中

### 证据

- `AccessGrant` 同时使用 `is_current`、`version` 和 `(user, app, version)` 唯一约束，注释称版本为事实锚点：`src/easyauth/grants/models.py:54-85`。
- 变更并未创建新版本行，而是原地递增同一行并替换全部成员关系：`src/easyauth/grants/lifecycle.py:62-79`、`src/easyauth/grants/operations.py:45-74`。
- 撤销和到期也原地递增版本；到期还会先删除成员关系：`src/easyauth/grants/lifecycle.py:133-144`、`src/easyauth/grants/expiration.py:77-93`。
- 查询又把版本最高的行称为最新授权：`src/easyauth/grants/query.py:102-103`。

### 失效场景

授权从 v1 变为 v2 后，v1 行并不存在，且原成员关系已删除。使用 `(user, app, version)` 作为审计事实锚点的调用方无法重建 v1；同一个主键随时间代表不同内容，版本字段既像乐观锁又像历史快照编号。

### 根因

模型混合了“可变聚合修订号”和“不可变历史版本”两套概念，但没有明确选择其一。

### 第一性修复

先确定领域契约。如果需要审计和回放，采用稳定 `AccessGrant` 聚合根加不可变 `AccessGrantRevision`/成员快照，并用当前修订指针；每次变更追加修订。如果只需要可变当前状态，则字段应明确命名为 `revision`，历史事实另存事件，并删除暗示历史行存在的结构和文案。无论选择哪种，都要一次性更新申请版本绑定、查询、审计、API、前端版本展示、迁移、测试和中文领域文档，不并存两套兼容语义。

## DS-12：历史迁移静默清空业务事实和凭据

- 严重度：高
- 置信度：高

### 证据

- 申请幂等迁移在加字段前执行 `AccessRequest.objects.all().delete()`，反向迁移为空操作：`src/easyauth/access_requests/migrations/0009_access_request_idempotency.py:15-39`。
- 授权期限迁移执行 `AccessGrant.objects.all().delete()`，然后移除父级期限字段，反向迁移为空操作：`src/easyauth/grants/migrations/0005_membership_expiration.py:15-50`。
- TOTP 加密字段迁移把所有种子清空并关闭 TOTP，且标记为 `elidable=True`：`src/easyauth/accounts/migrations/0007_alter_localadminaccount_totp_secret.py:7-27`。
- Authentik 管理令牌迁移把所有令牌清空，反向迁移为空操作且同样可省略：`src/easyauth/applications/migrations/0015_alter_integrationsettings_authentik_api_token.py:7-27`。

### 失效场景

试点、验收或长期开发数据库沿历史链升级时，迁移命令成功退出，却清空全部申请、授权历史、本地管理员第二因素或 Authentik 管理令牌。部署表面成功，权限事实已丢失，集成则在运行时才暴露缺凭据。

### 根因

历史迁移被当作环境重置工具，依赖“尚未上线”的注释代替可执行前置条件；破坏性操作既不检查数据为空，也不要求操作员明确授权。

### 第一性修复

既然项目尚未上线，应在上线基线前直接压平或重建正确的初始 schema，并明确要求使用全新数据库，不把静默删除留在可重复执行的升级链。任何需要保留的环境必须改为数据保持型迁移；若确实只能重置，迁移应在发现数据时快速失败，导出与人工确认放入独立、显式的运维流程。凭据改造应采用受控轮换或明确的部署前置检查，不能默认为空。同步更新迁移基线、部署检查、恢复演练、测试和中文运行手册。

## DS-13：追加型审计表缺少查询与清理索引

- 严重度：中
- 置信度：高

### 证据

- `AuditLog` 是持续增长的只追加表，字段包括事件、参与者、目标、JSON 元数据和创建时间，但 `Meta` 只有排序，没有任何索引：`src/easyauth/audit/models.py:37-51`。
- 唯一合法的保留期清理按 `created_at` 过滤：`src/easyauth/audit/models.py:30-34`。
- 管理端按 `metadata.app_key`、`event_type`、`actor_id`、`target_id` 和时间范围过滤：`src/easyauth/admin_console/operation_filters.py:91-97`。

### 失效场景

随着审计表增长，最常用的时间分页和保留期删除均需全表扫描；按参与者或目标查询也无法有效定位。清理任务会占用更长事务和 I/O，最终拖慢管理端及同库业务请求。

### 根因

模型定义了访问模式和保留策略，却未把访问路径映射为索引；应用归属藏在 JSON 中，难以形成稳定、可验证的租户过滤键。

### 第一性修复

基于 PostgreSQL `EXPLAIN` 和实际基数建立最小索引集合，至少评估 `(created_at, id)`、`(event_type, created_at)`、`(actor_id, created_at)`、`(target_type, target_id, created_at)`。若应用归属是一级查询维度，应将 `app_id` 或 `app_key` 规范化为类型化列，而非依赖 JSON。同步修改模型、迁移、分页与清理查询、性能基准、容量告警和中文运维文档。

## 安全检查

以下检查均未修改代码、迁移或测试：

- `.venv/bin/python manage.py check`：通过，`0 silenced`。
- `.venv/bin/python manage.py makemigrations --check --dry-run`：通过，未检测到模型与迁移漂移。
- `.venv/bin/python manage.py migrate --plan`：当前数据库无待执行迁移。
- `.venv/bin/python manage.py migrate --check`：通过。
- `.venv/bin/pytest -q tests/unit/grants tests/unit/access_requests tests/unit/lifecycle tests/unit/workflows tests/unit/outbox tests/unit/webhooks tests/unit/notify tests/unit/accounts`：`332 passed in 6.07s`。
- `git diff --check`：报告写入前通过；报告完成后对新增报告另行执行尾随空白和文件行号引用边界检查，71 个引用均存在且未越界，也未发现尾随空白。
- 只读数据库核对：`access_request_applied_shape=0`、`grant_current_shape=0`、`duplicate_dingtalk_bindings=0`、`notify_channel_app_mismatch=0`、`duplicate_template_targets=0`。

当前 Django 连接为本地 SQLite（`db.sqlite3`），而仓库部署配置包含 PostgreSQL 16。因此，上述结果只能证明当前样本库和所选单元测试没有暴露这些问题，不能证明 PostgreSQL 约束、锁、隔离级别、并发执行或从零迁移链正确。本次未执行 PostgreSQL 全新建库迁移回放、并发压力测试或全量测试套件。

本次只新增本审计文档，未修改代码、迁移、测试、模板或前端构建产物；按任务要求未创建 commit。由于运行时代码和页面响应均未变化，未重建前后端，也未重启 Django 开发服务。

## 建议修复顺序

1. 先统一授权修订/快照语义，并让生命周期申请绑定基础版本；这是 DS-01 和 DS-11 的共同前置。
2. 引入不可变模板修订，修复转岗预览—确认边界。
3. 修复 WebAuthn 计数器事务、用户删除外键语义和 Stream 冲突幂等。
4. 形式化全部状态机真值表及跨应用归属，集中补齐数据库约束和负向测试。
5. 规范化目录身份绑定与托管范围策略目标。
6. 在上线前重建干净迁移基线，最后按 PostgreSQL 实际查询计划补齐审计索引。
