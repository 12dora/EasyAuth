# 后端架构与代码异味审计

## 审计范围

- 审计日期：2026-07-27。
- 代码范围：`src/easyauth/` 下除自动生成迁移外的 Python 后端代码；测试只用于核对既有行为，不评价测试风格。
- 关注点：超大文件与函数、重复、深层嵌套、复杂分支、职责混杂、依赖环、过度耦合、魔法值、命名不清、无效抽象，以及偏离第一性原则的领域设计。
- 本文是只读审计结果，没有修改应用代码或测试。

## 结论摘要

本次确认 12 项问题，其中 4 项为高严重度、7 项为中严重度、1 项为低严重度。最优先处理的不是单纯拆文件，而是以下三个领域一致性问题：

1. 交接动作把本地授权转授与下游业务数据交接压进同一个状态，已经允许“动作显示失败、授权却已生效”的复合状态。
2. 访问申请在提交阶段与批准落地阶段各自维护一套“当前有效授权”算法，两套过滤条件已经发生漂移。
3. 授权事实写入口直接依赖连接器基础设施；连接器分发异常可以沿调用栈回滚授权事务，与代码注释声明的边界相反。

静态导入图未发现模块级强连通环，因此本次没有把“循环依赖”列为已确认问题。但多个领域模块直接导入连接器、外部集成、Webhook 和任务基础设施，边界方向仍然存在明显压力。

## 评级说明

- 严重度“高”：会造成领域事实不一致、事务语义失真，或使核心写路径受外围基础设施故障影响。
- 严重度“中”：当前已有确定的职责、契约或维护性缺陷，继续演进时很容易产生功能漂移。
- 严重度“低”：当前影响有限，但已经形成多事实源或魔法值扩散。
- 置信度“高”：可直接由现有代码路径或既有测试证明。
- 置信度“中”：代码中存在明确风险结构，但尚未通过运行时故障或完整写路径枚举证明实际后果。

## 已确认问题

### BAS-01：交接动作状态无法真实表达部分完成

- 严重度：高。
- 置信度：高。
- 类型：已确认的领域建模缺陷。
- 位置：
  - `src/easyauth/lifecycle/models.py:47-72`
  - `src/easyauth/lifecycle/models.py:157-224`
  - `src/easyauth/lifecycle/services.py:256-367`
  - `src/easyauth/lifecycle/services.py:1046-1109`
  - `src/easyauth/lifecycle/services.py:1011-1018`
  - `tests/unit/lifecycle/test_services.py:451-485`
- 证据：
  - `HandoverAppAction` 只有一个 `status`，同时表示本地授权转授和下游应用钩子的整体结果。
  - `_execute_action()` 先调用 `_transfer_selected_grants()`。该步骤通过 `GrantService` 提交接收人的授权，并把 `HandoverGrantItem` 更新为 `done`，随后才调用外部 `signed_hook_post()`。
  - 外部钩子失败时，`_finish_action_failure()` 只把动作状态改成 `failed`，不会撤销已经提交的授权。
  - 既有测试明确断言：第一次钩子失败后，授权项仍是 `done`，接收人的当前授权已经存在，动作则进入可重试失败态。这证明该状态并非理论上的并发窗口，而是当前被固化的行为。
- 影响：
  - `failed` 不再表示动作失败，只表示“至少钩子阶段失败”，调用方无法仅凭动作状态判断授权是否已经转授。
  - 运维重试、审计展示、任务完成判定和人工补偿都必须了解隐藏的步骤顺序，容易重复处置或误判数据。
  - 一个聚合状态承载两个不同一致性边界，后续增加更多下游步骤时会继续扩大状态组合爆炸。
- 根因：
  - 把“授权事实变更”和“下游业务资产交接”误建模为一个原子动作，但实现又无法提供跨数据库和 HTTP 的原子提交。
  - 用一组线性状态掩盖了实际上的流程编排和补偿语义。
- 直接修复建议：
  - 一次性重做数据结构和状态机，将本地授权转授与下游钩子执行建模为两个显式步骤，至少分别持久化 `grant_transfer_status`、`hook_status`、幂等键、尝试次数和最后错误。
  - 由交接编排器根据两个步骤的事实计算动作总览，不再把 `failed` 作为含义不完整的事实字段。
  - 为每个步骤建立独立审计事件和重试入口；删除现有复合状态解释，不保留旧 `status` 兼容映射。
  - 同步修改数据库约束、API 响应、前端展示、任务、测试和文档，使“部分完成”成为一等领域状态。

### BAS-02：交接预览在数据库行锁内执行最长 30 秒的网络请求

- 严重度：高。
- 置信度：高。
- 类型：已确认的事务边界缺陷。
- 位置：
  - `src/easyauth/lifecycle/services.py:213-245`
  - `src/easyauth/lifecycle/services.py:967-979`
  - `src/easyauth/webhooks/hooks.py:30-39`
  - `src/easyauth/webhooks/hooks.py:55-90`
- 证据：
  - `preview_action()` 进入 `transaction.atomic()` 后，通过 `_locked_action()` 对动作执行 `select_for_update()`。
  - 锁尚未释放时，函数直接调用 `signed_hook_post()`。
  - Webhook 策略允许总超时达到 30 秒，因此数据库行锁和事务可能跨越整个 DNS、连接、请求和响应周期。
  - 代码注释明确说明这是有意“持锁到响应落库”，从而确认不是偶然遗漏。
- 影响：
  - 同一交接动作的换接收人、跳过、执行或重试会被外部网络延迟阻塞。
  - 数据库连接和锁被不可控的下游延迟占用，容易放大为请求堆积、锁等待和事务超时。
  - 通过长事务解决旧响应覆盖问题，把并发控制与外部可用性错误地绑定在一起。
- 根因：
  - 缺少可持久化的预览代次、请求令牌或乐观并发版本，因而只能依赖悲观锁覆盖整个 I/O。
- 直接修复建议：
  - 改为三阶段流程：短事务内锁定并生成 `preview_generation` 与请求快照；事务外调用下游；第二个短事务以动作版本、代次和接收策略做条件更新。
  - 旧响应或并发变更导致条件不匹配时显式返回冲突，不写入过期预览。
  - 删除“网络调用期间持锁”的实现和注释，不保留旧事务路径。

### BAS-03：访问申请提交与批准落地复制了两套有效授权口径，且已发生语义漂移

- 严重度：高。
- 置信度：高。
- 类型：已确认的重复与领域规则漂移。
- 位置：
  - `src/easyauth/access_requests/submission_validation.py:235-301`
  - `src/easyauth/access_requests/submission_validation.py:304-345`
  - `src/easyauth/access_requests/application_grants.py:237-284`
  - `src/easyauth/access_requests/application_grants.py:287-399`
- 证据：
  - 两个模块都定义了 `_current_group_ids()`、`_current_direct_grants()`、`_grant_has_effective_membership()` 和 `_current_membership_expirations()`，并分别实现撤销与续期规则。
  - 提交阶段的 `_current_group_ids()`、`_current_direct_grants()` 和 `_current_membership_expirations()`读取全部成员关系，没有过滤已过期成员。
  - 批准落地阶段的同名函数统一使用 `expires_at IS NULL OR expires_at > now`，只读取当前有效成员。
  - 因此，包含“部分成员已过期、仍有其他成员有效”的当前授权记录会在两个阶段得到不同集合。一个续期或撤销申请可以通过提交校验，却在审批通过后的落地阶段失败。
- 影响：
  - 员工可能完成一次本不可能成功的审批，最后才得到授权应用失败。
  - 动态时间条件使问题具有时序性：提交与批准之间发生到期时，即使初始数据相同也可能触发漂移。
  - 两套错误类型和错误文案进一步掩盖了它们本应共享同一个领域判定。
- 根因：
  - 把“授权快照、有效成员集合、续期不变量、撤销子集”散落到申请模块的两个阶段，而不是由授权领域提供单一、可版本化的判定接口。
- 直接修复建议：
  - 在 `grants` 领域中建立唯一的 `EffectiveGrantSnapshot` 或等价值对象，由同一个查询函数一次性返回授权记录版本、有效授权组、有效直接权限及到期事实。
  - 提交和批准落地都调用同一组纯领域校验函数，并在申请中持久化被批准的授权记录版本；落地时版本不一致则明确判为已失效。
  - 删除两个申请模块中的重复查询与重复规则，不保留旧的“提交阶段包含过期成员”口径。

### BAS-04：授权核心写入口反向依赖连接器基础设施

- 严重度：高。
- 置信度：高。
- 类型：已确认的依赖方向和事务耦合缺陷。
- 位置：
  - `src/easyauth/grants/services.py:6-17`
  - `src/easyauth/grants/services.py:57-138`
  - `src/easyauth/connectors/dispatch.py:7-9`
  - `src/easyauth/connectors/dispatch.py:21-52`
  - `src/easyauth/accounts/services.py:8-17`
  - `src/easyauth/accounts/services.py:39-70`
- 证据：
  - `grants.services` 在模块顶层直接导入 `connectors.dispatch.notify_grant_mutation`。
  - 每个创建、变更、撤销和过期入口都在 `transaction.atomic()` 内调用该函数。
  - `notify_grant_mutation()` 并非轻量领域事件记录器；它直接查询 `ConnectorInstance`，推进连接器 `generation`，并写任务事务发件箱。
  - 任一连接器查询、状态更新或事务发件箱写入异常都会向上传播，使外围分发故障回滚授权事务。该行为与 `GrantService` 注释中的“连接器失败绝不回滚授权”声明冲突。
  - `accounts.services` 也直接依赖连接器离职分发，说明依赖倒置缺失不是单点现象。
- 影响：
  - 授权事实的可用性受可选连接器模块、连接器数据结构和任务基础设施影响。
  - 核心领域无法在不装载连接器实现的情况下独立测试或复用。
  - 增加新投影消费者时会继续把更多基础设施依赖塞进核心写事务。
- 根因：
  - 将“领域事件发布”实现为核心服务对具体消费者的同步调用，没有定义与消费者无关的领域事件端口。
- 直接修复建议：
  - 由 `grants` 在同一事务写入通用 `grant.mutated` 事务发件箱事件，事件内容只包含规范领域标识和版本。
  - 连接器作为事件消费者自行推进对账 `generation`；核心授权模块不再导入 `connectors`。
  - 用户离职同样发布规范的 `user.departed` 领域事件，连接器、生命周期和其他消费者分别订阅。
  - 删除现有同步分发调用，不保留从核心领域直达具体连接器的兼容钩子。

### BAS-05：CRM 试点命令建立了第二套 manifest 写入器

- 严重度：中。
- 置信度：高。
- 类型：已确认的重复写路径和无效抽象。
- 位置：
  - `src/easyauth/applications/management/commands/seed_crm_pilot.py:62-83`
  - `src/easyauth/applications/management/commands/seed_crm_pilot.py:86-257`
  - `src/easyauth/applications/permission_templates.py:55-77`
  - `src/easyauth/applications/manifest_import.py:46-83`
- 证据：
  - `seed_crm_pilot()` 直接依次新增或更新 App、scope、权限组、权限、授权组、组授权和审批规则。
  - 生产 manifest 主路径已经提供解析、引用校验、版本单调递增、内容哈希、缺失项停用、导入记录、审计、目录版本和生命周期 Webhook 同步。
  - seed 命令没有复用该入口，而是自己解析 `dict`、应用默认值和决定新增或更新行为。
  - 两条路径的语义已经不同：seed 路径不记录 `PermissionTemplateVersion`，不执行完整 manifest 关系校验，不停用清单中删除的对象，也不处理双语字段和生命周期配置。
- 影响：
  - 同一份 manifest 因入口不同产生不同数据库事实。
  - 试点环境可能掩盖生产导入路径的问题，或遗留生产路径永远不会产生的数据形态。
  - 每次扩展 manifest 数据结构都要同步维护两套写入逻辑。
- 根因：
  - 把管理命令当成可以绕过应用服务的特殊入口，而不是把它视为领域用例的适配器。
- 直接修复建议：
  - seed 命令只负责读取 fixture、创建最小 App 容器和输出一次性凭据；manifest 内容必须调用 `sync_app_manifest()` 或统一后的规范导入用例。
  - 试点成员、凭据和示例授权分别调用其正式领域服务。
  - 删除 `_upsert_manifest_*` 整套平行实现，并按规范导入结果重写测试，不保留 seed 专用数据语义。

### BAS-06：通知服务文件是跨六个边界的“上帝模块”

- 严重度：中。
- 置信度：高。
- 类型：已确认的超大文件与职责混杂。
- 位置：
  - `src/easyauth/notify/services.py:1-61`
  - `src/easyauth/notify/services.py:174-389`
  - `src/easyauth/notify/services.py:392-591`
  - `src/easyauth/notify/services.py:627-998`
  - `src/easyauth/notify/services.py:1003-1315`
  - `src/easyauth/notify/services.py:1318-1455`
- 证据：
  - 文件共 1455 行，包含 45 个顶层函数和 5 个类；最长函数达到 112 行。
  - 同一模块同时负责请求规范化、模板组装、幂等哈希、用户目录解析、通道范围校验、每日配额、消息与收件人落库、租约抢占、DingTalk 调用、退避排程、回执对账、聚合状态、审计和数据清理。
  - 导入同时跨越 `accounts`、`applications`、`audit`、`integrations.dingtalk`、`notify.models` 和 `outbox`。
  - `accept_notify_message()` 的文档字符串也直接列出“校验/组装/解析/幂等/配额/落库/入队”，证明单个入口聚合了多个可独立变化的职责。
- 影响：
  - 外部协议字段、领域状态机、持久化并发和产品配额互相污染，任何一类改动都需要理解整个文件。
  - 细粒度单元测试难以隔离，迫使测试围绕大型流程搭建大量数据库与集成上下文。
  - 类型边界退化为 `dict[str, object]` 和字符串状态，增加静默契约漂移风险。
- 根因：
  - 以“通知功能”作为模块边界，而没有继续按受理、投递、对账、外部适配和保留策略拆分领域职责。
- 直接修复建议：
  - 以用例和状态机重新划分模块：通知受理服务、收件人解析器、消息仓储、投递状态机、DingTalk 适配器、回执对账器、清理策略。
  - 受理入口只接收类型化命令并返回受理结果；外部适配器返回类型化 DTO；状态推进只能通过单一状态机方法。
  - 删除原文件中的跨层辅助函数搬运，不保留转发兼容层；调用方直接迁移到新的应用服务入口。

### BAS-07：生命周期服务把三个聚合和外部协议塞进一个文件

- 严重度：中。
- 置信度：高。
- 类型：已确认的超大文件、复杂分支和聚合边界混乱。
- 位置：
  - `src/easyauth/lifecycle/services.py:13-51`
  - `src/easyauth/lifecycle/services.py:111-619`
  - `src/easyauth/lifecycle/services.py:619-823`
  - `src/easyauth/lifecycle/services.py:831-1018`
  - `src/easyauth/lifecycle/services.py:1021-1386`
- 证据：
  - 文件共 1386 行，包含 50 个顶层函数和 3 个类。
  - 文件同时管理离职交接单、应用交接动作、团队负责人处置、转岗差异、入职模板、授权合并、审计、事务发件箱和同步 Webhook。
  - `_execute_action()` 为 112 行且嵌套深度达到 5；`confirm_transfer_grant_diff()` 为 88 行；`_transfer_selected_grants()` 的近似圈复杂度为 21。
  - 函数依赖 `accounts`、`applications`、`grants`、`teams`、`webhooks` 和 `outbox`，说明它实际上是多个应用服务和基础设施适配器的混合体。
- 影响：
  - 交接、转岗和入职的术语及状态容易互相借用，形成含义过载。
  - 事务边界只能按函数局部拼装，难以保证每个聚合拥有清晰的不变量和并发控制。
  - 任何授权模型或下游钩子变化都会触碰生命周期总文件。
- 根因：
  - 把“人员生命周期”当作一个可直接实现的单一领域，而没有识别入职授权、离职交接、转岗权限差异和下游资产交接是不同聚合。
- 直接修复建议：
  - 按聚合拆成 `offboarding`、`handover_actions`、`transfer_plans`、`onboarding` 四组应用服务，并把 Webhook 放入明确的端口与适配器。
  - 共享内容只保留真正稳定的值对象，例如授权目标键和到期规则；不要建立新的“生命周期公共辅助函数”大杂烩。
  - 先落新数据结构与状态机，再一次性迁移 API、任务和测试，删除原 `lifecycle/services.py` 总入口。

### BAS-08：`applications.models` 的桶式重导出使物理拆分失效

- 严重度：中。
- 置信度：高。
- 类型：已确认的无效抽象和过度耦合。
- 位置：
  - `src/easyauth/applications/models.py:1-50`
  - `src/easyauth/applications/models.py:103-730`
  - `src/easyauth/applications/ops_models.py:27-54`
  - `src/easyauth/admin_console/permissions_api.py:37-42`
  - `src/easyauth/portal/request_catalog.py:8-18`
- 证据：
  - `applications.models` 自身已有 730 行、10 个模型类，又导入并重导出 `IntegrationSettings`、`OAuthClientBinding`、`AppMembership`、`AuthorizationGroupAccessPolicy`、`PermissionGroup` 和 `PermissionTemplateVersion`。
  - `ops_models.py` 虽然是独立文件，但主要调用方仍从 `applications.models` 导入其中的模型，物理拆分没有形成依赖边界。
  - 静态导入统计中，`easyauth.applications.models` 被 89 个后端模块直接依赖，是全仓库入度最高的内部模块。
- 影响：
  - 调用方无法从导入语句判断模型真实所有权，任何桶模块调整都会波及大量文件。
  - `models.py` 成为事实上的全局服务定位器，促使控制台、门户、授权和集成都直接依赖整个应用目录模型集合。
  - 后续拆领域时会遇到巨大的隐式公共 API 面。
- 根因：
  - 把重导出当成“便于导入”的公共门面，却没有定义稳定的领域 API；最终门面只是在暴露全部 ORM 实现。
- 直接修复建议：
  - 按明确聚合建立模型模块，例如应用身份与凭据、权限目录、审批配置、运营成员关系、集成设置，并要求调用方从实际所有者导入。
  - 领域外调用优先依赖查询服务和值对象，不直接横跨多个模型模块拼 ORM。
  - 删除 `applications.models` 中的跨文件重导出；一次性更新所有调用方，不保留旧导入兼容别名。

### BAS-09：连接器映射整表写入静默吞掉重复授权组

- 严重度：中。
- 置信度：高。
- 类型：已确认的复杂分支与静默纠错缺陷。
- 位置：
  - `src/easyauth/admin_console/connectors_api.py:100-116`
  - `src/easyauth/admin_console/connectors_api.py:464-488`
  - `src/easyauth/admin_console/connectors_api.py:489-564`
- 证据：
  - `MappingsPutPayload` 只声明一个映射列表，没有模型级唯一性约束。
  - `_replace_mappings()` 发现重复 `authorization_group_key` 后直接 `continue`，没有返回校验错误。
  - 如果同一个授权组出现两次且 `external_ref` 不同，服务器接受整单并悄悄采用第一项，响应不会告诉调用方第二项被丢弃。
- 影响：
  - 客户端看到 HTTP 成功，却无法从响应得知提交载荷被修改。
  - 配置审计只记录最终数量，无法说明被忽略的冲突输入。
  - 该行为违反项目“契约或不变量被破坏时快速失败”的硬约束。
- 根因：
  - 把集合去重当成输入清洗，而没有把“一个授权组只能出现一次”建模为请求契约。
- 直接修复建议：
  - 在 Pydantic 请求模型中校验 `authorization_group_key` 唯一；重复项无论内容相同与否都整单返回明确的 422 语义错误和冲突键。
  - 删除 `seen_keys` 的静默 `continue` 分支。
  - 补齐重复键、冲突外部引用和顺序无关性的契约测试，不保留“首项优先”行为。

### BAS-10：连接器配置把损坏数据静默转换为空配置

- 严重度：中。
- 置信度：高。
- 类型：已确认的空结果兜底和无类型配置抽象。
- 位置：
  - `src/easyauth/connectors/models.py:52-70`
  - `src/easyauth/connectors/models.py:137-147`
  - `src/easyauth/connectors/base.py:67-95`
- 证据：
  - `ConnectorInstance` 以加密文本保存任意 JSON 配置。
  - `config` 属性在字段为空时返回 `{}`；解码后的 JSON 不是对象时也返回 `{}`，不抛出数据契约错误。
  - 配置的真实 JSON Schema 由运行时注册的连接器在更远的调用点校验，ORM 模型本身无法表达“某 `connector_key` 对应哪种配置”。
- 影响：
  - 损坏或错误形态的持久化数据被伪装成“尚未配置”，根因和错误位置丢失。
  - 不同调用方可能把 `{}` 分别解释为禁用、默认配置或校验失败，形成不一致行为。
  - 配置错误会延迟到对账或外部调用阶段才暴露。
- 根因：
  - 用通用加密 JSON 字段替代连接器配置值对象，并以空字典兜底解码失败后的形态校验。
- 直接修复建议：
  - 为每种 `connector_key` 定义类型化配置对象，在创建和更新时完成加密前校验，在读取时完成解密后严格反序列化。
  - 空配置若不是连接器 JSON Schema 的合法值，应直接判为数据损坏；非对象 JSON 必须抛出带实例 ID 的明确异常。
  - 清理数据库中的非法配置后删除 `{}` 兜底，不保留旧的宽松读取逻辑。

### BAS-11：DingTalk 回执适配器只校验最外层对象，领域服务静默忽略内部错误形态

- 严重度：中。
- 置信度：高。
- 类型：已确认的外部契约泄漏和静默降级。
- 位置：
  - `src/easyauth/integrations/dingtalk/api_client.py:221-243`
  - `src/easyauth/notify/services.py:564-588`
  - `src/easyauth/notify/services.py:1318-1425`
- 证据：
  - `DingTalkApiClient.get_send_progress()` 和 `get_send_result()` 只确认 `progress`、`send_result` 是 `dict`，随后把原始字典交给通知领域服务。
  - `_string_id_set()` 在字段不是列表时返回空集合，并跳过列表内的未知元素。
  - `_forbidden_userid_codes()` 在字段不是列表时返回空映射，列表元素不是对象或缺少 `userid` 时继续跳过。
  - 因此，外部响应字段缺失或类型变化不会快速失败，而会被解释成“本次没有任何收件人状态变化”。
- 影响：
  - 回执契约漂移会让收件人长期停在 `sent`，且没有准确的结构错误可观测信息。
  - 外部协议知识散落在通知领域服务中，适配器没有完成“外部响应转内部类型”的职责。
  - 数字用户 ID 被隐式转字符串、未知禁止码被统一归为拒绝，进一步扩大了未经显式建模的兼容行为。
- 根因：
  - 集成边界返回通用 JSON 字典，领域层再以宽松辅助函数逐字段猜测。
- 直接修复建议：
  - 在 DingTalk 适配器内定义严格的发送进度和发送结果 DTO，校验必需字段、元素类型、用户 ID 类型和已知结果分类。
  - 契约错误应抛出独立异常并记录原始任务 ID，调度器把它视为明确的依赖契约失败，而不是空结果。
  - 领域服务只消费类型化集合；删除 `_string_id_set()`、`_forbidden_userid_codes()` 的宽松解析分支，不新增旧响应兼容层。

### BAS-12：授权状态存在重复类型定义和跨模块魔法字符串

- 严重度：低。
- 置信度：高。
- 类型：已确认的魔法值和多事实源。
- 位置：
  - `src/easyauth/grants/models.py:16-36`
  - `src/easyauth/grants/status.py:7-15`
  - `src/easyauth/grants/services.py:26-26`
  - `src/easyauth/lifecycle/services.py:911-925`
  - `src/easyauth/lifecycle/services.py:1122-1140`
  - `src/easyauth/lifecycle/models.py:325-347`
- 证据：
  - 授权状态已在模型中定义常量集合，又在 `grants.status` 和 `grants.services` 分别手写同一个 `Literal["active", "revoked", "expired"]`。
  - `lifecycle.services` 不使用模型常量，直接比较 `"active"`；授权项种类也在模型约束、`clean()` 和服务中重复使用 `"group"`、`"permission"`。
  - 类型定义、数据库选项、检查约束和业务分支因此需要人工同步。
- 影响：
  - 新增或重命名状态时容易只修改部分事实源，静态类型仍可能错误地接受或拒绝值。
  - 字符串无法承载状态转换规则，调用方继续通过自由比较扩散领域知识。
- 根因：
  - 把状态视为数据库字符串常量，而不是带解析和转换规则的领域值。
- 直接修复建议：
  - 建立唯一的 `StrEnum` 或等价值对象作为 Python 状态事实源，由它生成数据库选项、合法值集合和解析逻辑。
  - 授权目标种类同样建立单一枚举；模型约束和服务分支都引用该定义。
  - 删除重复 `Literal` 和所有跨模块裸字符串比较，不保留字符串别名兼容层。

## 待验证假设

以下项目具有明确风险迹象，但本次没有足够证据把它们定性为已发生的功能缺陷。

### HYP-01：控制台写用例可能存在审计与目录版本推进不一致

- 严重度：中。
- 置信度：中。
- 类型：待验证的应用层边界风险。
- 位置：
  - `src/easyauth/admin_console/catalog_write_common.py:53-68`
  - `src/easyauth/admin_console/catalog_write_common.py:129-152`
  - `src/easyauth/admin_console/permissions_api.py:47-55`
  - `src/easyauth/admin_console/connectors_api.py:338-564`
- 证据：
  - `admin_console` 顶层共有 63 个 Python 文件、约 12638 行，至少 16 个文件自行建立事务。
  - 通用辅助函数只提供模型保存和审计记录，没有定义统一的“写模型 + 推进目录版本 + 审计 + 领域事件”事务模板。
  - 连接器、权限目录、生命周期和设置入口各自编排事务与响应。
- 潜在影响：
  - 某些写入口可能漏掉审计、目录版本推进或下游事件，也可能在事务外触发副作用。
- 根因假设：
  - HTTP 入口承担了应用服务职责，但共享层只抽取了响应和小型辅助函数，没有抽取真正的写用例。
- 直接修复建议：
  - 先建立全量写路径清单，逐个对照数据结构变化、审计、版本、事件和事务边界。
  - 将每类配置写入收口为明确应用服务，HTTP 层只做认证、解析和错误映射。
  - 一旦确认遗漏，直接统一所有调用方并删除 HTTP 视图内写逻辑，不建立双写兼容期。

### HYP-02：仅由 `full_clean()` 保护的跨对象不变量可被 ORM 批量写绕过

- 严重度：中。
- 置信度：中。
- 类型：待验证的数据完整性风险。
- 位置：
  - `src/easyauth/grants/models.py:118-137`
  - `src/easyauth/grants/models.py:165-194`
  - `src/easyauth/grants/operations.py:45-74`
  - `src/easyauth/admin_console/catalog_write_common.py:129-137`
- 证据：
  - 授权组必须属于授权记录的 App、权限和 scope 必须属于同一 App 等关键不变量主要位于模型 `clean()`。
  - 当前正式 `GrantService` 写路径会逐行 `full_clean()`，控制台通用保存辅助函数也会调用 `full_clean()`。
  - 但 Django 的 `bulk_create()`、`update()`、原始 SQL 和未来脚本不会自动调用这些校验；本次尚未发现正式授权写入口直接绕过该规则。
- 潜在影响：
  - 一旦出现新的批量导入或修复脚本，数据库可能接收跨 App 的非法授权关系，查询层无法安全解释。
- 根因假设：
  - 关键不变量依赖调用纪律，而不是由数据库或不可绕过的仓储边界保证。
- 直接修复建议：
  - 盘点所有 ORM 批量写和管理脚本；能用数据库触发器或结构性数据设计表达的跨行不变量应下沉数据库。
  - 其余写入只允许通过单一授权仓储，并用数据库级集成测试证明旁路写会失败。
  - 不为非法历史数据增加读取兼容；发现后应清理数据并收紧数据结构。

## 未确认的问题

- 静态导入图未发现两个及以上模块组成的强连通分量，因此没有确认 Python 模块循环依赖。
- AST 扫描没有发现超大类方法集合；主要规模问题集中在函数式 service 模块和桶式模型模块，而不是单个传统类。
- 本次没有把所有 `# noqa` 视为问题。只有当豁免对应的复杂结构已经造成职责或语义缺陷时，才在上文列入。

## 建议修复顺序

1. 先重做交接动作数据结构与两阶段状态机，处理 BAS-01 和 BAS-02。
2. 收口有效授权快照和申请规则，处理 BAS-03。
3. 建立通用领域事务发件箱，反转授权、用户与连接器依赖，处理 BAS-04。
4. 删除 CRM seed 平行写入器，处理 BAS-05。
5. 再拆通知和生命周期大模块；拆分必须围绕前述新领域边界，不能只机械移动函数。
6. 清理应用模型桶、严格外部 DTO、连接器配置和重复枚举。
7. 对两个待验证假设做写路径与数据库约束专项审计。

## 使用的命令与检查

以下命令均为只读检查；没有运行会修改数据库的管理命令。

```bash
git status --short
rg --files
find src/easyauth -name '*.py' -not -path '*/migrations/*' -print0 | xargs -0 wc -l | sort -nr
rg -n '^def |^class |^@transaction|^    def ' src/easyauth/notify/services.py
rg -n '^def |^class |^@transaction|^    def ' src/easyauth/lifecycle/services.py
rg -n 'AccessGrant(?:Group|Permission)?\.objects' src/easyauth -g '*.py' -g '!**/migrations/**'
rg -n 'transaction\.atomic' src/easyauth/admin_console/*.py
rg -n '# noqa:.*(C901|PLR091|PLC0415)|# noqa' src/easyauth -g '*.py' -g '!**/migrations/**'
.venv/bin/ruff check src/easyauth --select C901,PLR0911,PLR0912,PLR0913,PLR0915 --output-format concise
.venv/bin/ruff check src/easyauth --select PLC0415,F401 --output-format concise
nl -ba <目标文件> | sed -n '<起始行>,<结束行>p'
```

另使用 Python AST 只读脚本完成以下检查：

- 统计非迁移 Python 文件、顶层函数、类和函数行数。
- 以条件、循环、异常处理、布尔表达式和模式匹配近似计算圈复杂度与最大嵌套深度。
- 提取 `easyauth` 内部 import 边，以 Tarjan 算法搜索强连通分量。
- 统计模块出度、入度和重复函数名，随后逐项人工阅读，避免仅凭指标定性。

量化结果摘要：

- 非迁移后端 Python 共约 42305 行。
- `notify/services.py`：1455 行、45 个顶层函数、5 个类。
- `lifecycle/services.py`：1386 行、50 个顶层函数、3 个类。
- `applications/models.py`：730 行、10 个模型类。
- `admin_console` 顶层 Python：约 12638 行、63 个文件。
- 近似复杂度最高的函数包括：
  - `lifecycle/services.py:1046` `_transfer_selected_grants()`：21。
  - `admin_console/connectors_api.py:464` `_replace_mappings()`：20。
  - `lifecycle/services.py:666` `confirm_transfer_grant_diff()`：17。
  - `lifecycle/services.py:256` `_execute_action()`：最大嵌套深度 5。
- Ruff 定向检查额外报告 `api/manifest_sync_views.py:70` 有 8 个返回分支，并报告该文件一处函数内 import；这两项本身不足以证明领域缺陷，未单独列为问题。

## 验证边界

- 没有执行完整测试、构建或开发服务重启，因为本任务只产出审计文档，未修改后端、模板或前端运行代码。
- 没有提交 commit；提交由上层任务统一处理。
