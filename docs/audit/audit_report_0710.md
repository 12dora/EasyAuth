# EasyAuth 全量前后端代码审计报告

- 审计日期：2026-07-10
- 审计对象：当前工作树，基线提交 `bef86d0b45162c7f842a079b9eda0da3227e4f15`
- 审计范围：`frontend/src/`、`src/easyauth/`、`sdk/python/`、相关 Django 模板、部署配置、前后端测试与项目文档
- 代码规模：前端 TypeScript/TSX/CSS 约 27,101 行；后端 Python/模板约 38,197 行；测试约 35,458 行；Python SDK 约 1,449 行
- 审计方式：按 Portal、Console、Workspace、认证授权、申请与授权、生命周期、应用配置、集成任务、Webhook、Connector、i18n、动效与无障碍拆成并行通道；静态调用链、现有测试、定向复现、真实 HTTP、依赖漏洞扫描和生产安全检查相互印证
- 工作树说明：审计时工作区已有未提交的 Connector 框架及其他用户修改。本报告将它们纳入“当前项目”审查，但没有改动或提交这些文件；Connector 结论应在相关代码合并前修复

## 一、结论摘要

当前项目没有发现可直接由匿名访问者利用的前端 DOM XSS、开放重定向或明显硬编码生产密钥，前端依赖与锁定的 Python 运行时依赖也没有命中已知漏洞。但是，项目尚不具备安全上线条件，首要原因不是单个普通页面 bug，而是以下几组跨层问题同时存在：

1. `docker-compose.deploy.yml` 将公网部署明确配置为 `DEBUG=1`，使用 Django `runserver` 和 SQLite，并因此关闭 Secure Cookie、HSTS 等生产保护。
2. App owner 可配置任意 Webhook/生命周期 URL；出站请求缺少 scheme、私网、DNS 重绑定、跳转和响应大小限制，形成 SSRF、凭据跨源泄露和 worker 内存耗尽链路。
3. 钉钉 Stream、审批完成、Webhook、离职禁号和 Connector 分发都把 `transaction.on_commit(send_task)` 当作持久事实。数据库已提交而 broker 发布失败时，安全事件可以永久丢失。
4. 生命周期和 Connector 存在多个非原子状态迁移与并发覆盖窗口，可复活已撤销或已过期权限，也可让离职用户被旧快照重新解封。
5. 本地超管 TOTP 节流可被正确密码循环清零；TOTP 绑定又不要求 step-up；改密不会撤销其他会话，三者可组成持久化账号接管链。
6. 前端多处在权威 GET 失败后仍允许全量 PUT/PATCH，可能清空 Webhook、Connector mapping 或 Managed Scope；工作台跨 `appKey` 还会复用旧应用的敏感状态。
7. Portal 服务端分页被当作客户端分页，第 21 条之后的授权、过期项和申请永久不可见；多个 Console 深链真实 HTTP 返回 404。
8. i18n 消息键本身完整，但目录双语数据在编辑时会被清空，很多界面直接硬编码中文或固定使用 `zh-CN`；英文模式不是完整可用状态。
9. 动效问题中最严重的不是“少一点动画”，而是 Dialog 重渲染抢焦点、隐藏菜单仍可 Tab 到达、权限树退出定时器竞态，以及 `prefers-reduced-motion` 覆盖不完整。

本报告按问题簇归并重复根因，共记录：前端功能 24 组、前端安全 5 组、后端功能 25 组、后端安全 17 组、i18n 9 组、动效与无障碍 10 组。一个问题簇可能覆盖多个调用点，数量不应被理解为互相独立的缺陷个数。

### 修复复核（2026-07-10）

本轮已完成全部后端功能问题，以及指定安全问题 BS-02、BS-05 至 BS-15、BS-17。实现按以下四批提交：

- `621b664`：后端领域模型、API、事务、并发、安全边界、迁移与回归测试。
- `8864547`：对应前端契约、幂等提交、逐项期限、异步状态与两步验证交互。
- `580814f`：出站 Webhook worker 网络隔离、依赖锁定、镜像摘要、SBOM、构建溯源与签名验证。
- Authentik `7120fbede1`：钉钉目录权威快照代次、合法空集清理、原子发布与回归测试。

| 问题 | 状态 | 修复结果 |
| --- | --- | --- |
| BF-01 | 已修复 | 新增事务 outbox、唯一事件键、租约 claim、失败退避和 5 秒周期扫描；安全关键链路不再直接 `on_commit(send_task)`。 |
| BF-02 | 已修复 | 外部审批改为持久提交状态机、载荷摘要、超时转 `ambiguous` 和显式锁重试；钉钉不提供调用方 correlation 查询参数，因此不确定结果禁止盲目重发，并由持久早到 callback 自动恢复。 |
| BF-03 | 已修复 | 删除旧 Role 模型、关联、API、迁移路径和兼容字段，统一使用 AuthorizationGroup/Permission。 |
| BF-04 | 已修复 | 授权唯一写边界重新校验当前时间，过期申请进入 `grant_expired`，不再生成伪 active grant。 |
| BF-05 | 已修复 | 手工交接只读取当前有效授权；自动离职在撤权前显式快照有效 grant ID。 |
| BF-06 | 已修复 | 期限下沉到授权组和直接权限成员事实，支持同一 App 内永久、限时和混合期限，不再取最大值。 |
| BF-07 | 已修复 | 合并前统一按成员级有效期判定，过期授权不再参与合并或被复活。 |
| BF-08 | 已修复 | 仅同 kind 任务幂等，不同 kind 明确冲突。 |
| BF-09 | 已修复 | 执行开始后冻结接收策略和接收人，禁止产生内部权限与外部资产分属不同人员的事实。 |
| BF-10 | 已修复 | 转岗确认增加行锁、版本栅栏、整批事务、同载荷幂等和异载荷冲突。 |
| BF-11 | 已修复 | 接收人与释放公海严格 XOR，并禁止当事人接收自己的交接。 |
| BF-12 | 已修复 | 模板替换、批量入职和接收人更新均先完整校验，再在单一事务中提交。 |
| BF-13 | 已修复 | Lifecycle action 使用闭合状态迁移和行锁；空 action 集合可正确收敛。 |
| BF-14 | 已修复 | 保存不可变目录快照；Hook 200/202 分流，202 持久化状态 URL 并有界轮询；前端不再把 `async_pending` 误报为完成。 |
| BF-15 | 已修复 | AccessRequest 强制客户端幂等键和 SHA-256 载荷摘要；同键同载荷返回原单，异载荷返回 409。 |
| BF-16 | 已修复 | 模板保存和实例创建严格执行 `form_schema` 与 `form_mapping`；前端提供同契约编辑和校验。 |
| BF-17 | 已修复 | 外部 process ID 非空条件唯一；早到 callback 持久化待匹配，并在实例关联后自动恢复。 |
| BF-18 | 已修复 | parser、model、readiness 使用一致的 active scope 不变量，Manifest 可正常收缩 scope。 |
| BF-19 | 已修复 | Manifest 管理字段按权威快照清理，重复 target 拒绝，所有入口统一 canonical hash。 |
| BF-20 | 已修复 | 自动接入新 App 时在同一事务中把 actor 建为 active owner。 |
| BF-21 | 已修复 | EasyAuth 将 generation、成功状态和精确计数作为强契约；Authentik 合法空快照会软删除旧用户和非根部门，并在同一事务内发布镜像、精确计数和新代次。畸形响应会在破坏性写入前失败。 |
| BF-22 | 已修复 | EasyAuth 按 source/corp 串行化并持久化 generation fencing；Authentik 在镜像事务提交时单调递增 generation，失败保留上一代。线程交错和连续成功同步测试确认旧 active 快照不能覆盖新 departed 事实。 |
| BF-23 | 已修复 | Connector 使用数据库 generation/dirty/lease 状态机，安全收缩优先，保留 tombstone 和不可变外部身份。 |
| BF-24 | 已修复 | 审批人规范化为关系表并数据库过滤/count/slice；筛选参数严格解析，非法输入返回 422。 |
| BF-25 | 已修复 | Authentik 完整分页和严格 envelope；钉钉 token 按凭据指纹缓存并遵从真实 TTL；响应大小和总时限受限。 |
| BS-02 | 已修复 | Webhook 仅允许 HTTPS/443、公网固定 IP 和 App 精确域名；配置与发送双校验、禁跳转；独立 worker 的 egress 防火墙仅放行 DNS、Redis 和公网 443。 |
| BS-05 | 已修复 | Webhook、Hook、NetBird、Authentik、DingTalk 客户端均增加 Content-Length/分块上限、总 deadline 和 Celery time limit。 |
| BS-06 | 已修复 | 正确密码不再提前清零二因子失败计数，只有完整登录成功才清零。 |
| BS-07 | 已修复 | TOTP begin/confirm 绑定短 TTL 密码 step-up、账号会话版本和一次性 enrollment nonce，并在行锁内原子启用。 |
| BS-08 | 已修复 | 本地超管会话绑定单调 session version；改密、重置、停用和因子变更撤销其他会话。 |
| BS-09 | 已修复 | App detail 与 configuration-status 强制对象级可见权限，未授权统一 404。 |
| BS-10 | 已修复 | 人员分页和独立选人接口均为 superuser-only；选人拒绝空查询并仅返回最小字段。 |
| BS-11 | 已修复 | Connector reconcile 强制 superuser，并按 actor/instance 去重限速。 |
| BS-12 | 已修复 | offboard 与 reconcile 进入同一 generation/lease 状态机；非 active 用户永不解封，外部清理前保留 tombstone。 |
| BS-13 | 已修复 | 保存并探测不可变 account ID，禁止不同 App 重复绑定同一 NetBird account。 |
| BS-14 | 已修复 | Authentik 原子发布权威 generation 与精确计数；EasyAuth 要求完整分页、成功状态、起止代次一致和单调 fencing，任何半成品或不完整快照禁止写入。 |
| BS-15 | 已修复 | Webhook delivery 增加 generation、claim token 和 lease，只有当前 claim 可发送和写终态。 |
| BS-17 | 已修复 | `/health/` 真实上报数据库、broker、beat/worker、关键任务、Stream 进程和 ACK；镜像与 uv/Redis 固定摘要，gunicorn 进入 lock，CI 生成 SBOM/provenance 并用 Cosign 签名后验证。 |

修复后验证结果：Django/Python 全量测试 `1093 passed`；前端 `40` 个测试文件、`249 passed`；前端生产构建、`tsc -b`、`manage.py check`、迁移一致性检查、Dockerfile 检查和 deploy compose 解析均通过。Ruff 从原报告的 23 项降为 5 项，剩余均位于本轮未修改的既有 `teams_api.py` 和 `manifest_sync_views.py`。

上线复核结果：Authentik 定向测试 `12 passed`，迁移一致性检查和完整镜像构建通过；部署前备份保存于 `/tmp/authentik-before-generation-20260710.dump`。Authentik worker/server 已重建并通过本机与 `https://auth.jiefakj.com/-/health/live/` 健康检查。真实钉钉同步发布 `generation=1`，状态计数与活动镜像均为 `40` 个部门、`134` 个用户；EasyAuth 严格同步成功消费相同计数，`org_fetch_failed_count=0`，`https://iam.jiefakj.com/health/` 返回 `200`。

### 严重级别

- **Critical**：可造成远程代码/网络边界突破、认证绕过、大范围权限破坏或生产敏感信息暴露，必须阻断上线。
- **High**：核心安全控制或主业务流程可被绕过、永久丢失或写入错误事实，应作为近期最高优先级修复。
- **Medium**：确定存在且有实际影响，但前提、影响面或可恢复性相对受限。
- **Low**：健壮性、可维护性、供应链、无障碍或体验缺口；不应以兼容分支掩盖。

---

## 二、前端：功能性

### FF-01　Portal 三个列表只展示服务端第一页

- **级别**：High
- **位置**：`frontend/src/pages/portal/PortalPage.tsx:96-100,118-123,148-152,181-186,258`
- **问题**：当前授权、即将过期授权、申请历史都不发送 `page/page_size`，忽略响应 `pagination`，再对默认返回的 20 行做客户端分页。
- **影响**：第 21 条之后永久不可达；“即将过期”漏项会让用户错过续期或撤权处理。
- **修复**：统一为受控服务端分页；页码和页大小进入 query key 与 URL，表格开启 `manualPagination`，总数只取服务端元数据。
- **测试缺口**：`PortalPage.test.tsx:1544-1620` 只用单行且省略分页元数据；另一个翻页测试把核心操作放在条件分支里，按钮错误禁用时测试仍会通过。

### FF-02　多个 Console React 路由无法刷新或新标签打开

- **级别**：High
- **位置**：`frontend/src/App.tsx:76-89`、`src/easyauth/admin_console/urls.py:516-520`
- **问题**：前端声明了 `/console/teams`、`/console/people`、生命周期、审批模板和 `/console/apps/new` 等路由，Django 只为 operations、settings 和 app detail 提供 SPA 壳。
- **证据**：真实请求 `/console/teams`、`/console/people`、`/console/lifecycle/handover-tasks`、`/console/lifecycle/onboarding`、`/console/approval-templates` 均返回 404；`/console/apps/new` 经尾斜杠重定向后会被当作 `app_key=new`。
- **影响**：刷新、复制链接、中键打开和浏览器恢复会话失败。
- **修复**：在 API 路由之后提供受认证的明确 SPA 壳路由或安全 catch-all，同时保留对象级权限校验。

### FF-03　保存钉钉设置会清空 Authentik URL 覆盖值

- **级别**：High
- **位置**：`frontend/src/pages/console/ConsoleSettingsPage.tsx:169-185`、`src/easyauth/admin_console/settings_api.py:31-40,89-104`
- **问题**：钉钉保存 payload 不含 `authentik_base_url`；后端把缺失字段解析为 `""` 并无条件赋值。
- **影响**：一次无关保存即可破坏目录同步或健康检查配置。
- **修复**：更新 schema 区分“缺失”和“显式清空”；只更新 `fields_set` 中的字段，并以事务或字段级更新避免 lost update。

### FF-04　工作台状态跨应用复用

- **级别**：High
- **位置**：`frontend/src/pages/console/ConsoleAppWorkspace.tsx:160-171` 及各 Workspace Tab 的本地状态
- **问题**：从应用 A 的同一 tab 导航到应用 B 时，React 复用组件实例；query key 虽改变，本地 state、旧请求回调和一次性明文不重置。
- **影响**：B 页面可显示 A 的 Webhook URL、QueryTest 结果/token、Connector 草稿/测试通过状态、Manifest preview 或凭据明文，并可能把 A 的草稿写入 B。
- **修复**：以 `${appKey}:${activeTab}` keyed remount；取消或按请求身份丢弃旧响应；补 A→B 同路由回归测试。

### FF-05　读取权威配置失败后仍允许破坏性写入

- **级别**：High
- **位置**：
  - Managed Scope：`ConsoleAppWorkspace.tsx:201-241,299-302`
  - Connector mapping：`ConnectorTab.tsx:407-485`、`connectors_api.py:401-410`
  - Webhook：`WebhookTab.tsx:38-63,111-117,187-202`、`webhook_config_api.py:110-126`
- **问题**：三处都把 GET error 与“合法空配置”混为一谈，加载结束后重新启用 Save。空本地草稿随后会删除 Managed Scope、整表清空 mapping、覆盖空 Webhook URL，或绕过轮换密钥确认。
- **修复**：只有成功取得并校验权威快照后才允许写；`loading/error/unconfigured/configured` 必须是互斥状态，错误态提供重试且 fail closed。

### FF-06　Manifest 与 Onboarding 的预览 ID 可脱离当前文本

- **级别**：High
- **位置**：`ManifestTab.tsx:74-89,120,140-153`、`AppOnboardingWizard.tsx:399-419,431-466`
- **问题**：预览内容 A 后编辑为 B，旧 `preview_id` 仍可确认；预览在途时编辑也可能让旧结果覆盖新文本。Onboarding 成功后继续编辑还不清理已导入版本。
- **影响**：界面展示 B，却导入 A，可能错误改写整套权限目录。
- **修复**：预览绑定内容规范化 hash；任何输入变化立即废弃 preview/import result；确认时再次核对 hash；解决文件读取乱序。

### FF-07　Onboarding 对畸形配置状态 fail-open

- **级别**：High
- **位置**：`AppOnboardingWizard.tsx:538-548,750-783`
- **问题**：`configuration-status.data` 缺失或类型错误时被 `?? []` 当成“零问题”，页面显示绿色 ready。
- **影响**：契约漂移或后端故障会被伪装为应用已就绪。
- **修复**：运行时严格校验 envelope 和 issue 数组；缺失、错型必须进入明确错误态。
- **测试证据**：现有测试仍返回旧形态 `{items: []}` 且通过，说明测试在固化 fail-open。

### FF-08　Matrix 无损编辑会删除团队/并集管理范围策略

- **级别**：High
- **位置**：`workspace/matrix/grantDraft.ts:108-115`、`MatrixTab.tsx:446-460`、`permission_catalog_data.py:302-307`
- **问题**：后端返回 `easyauth_team` 或 `union`，前端只识别 `override/disabled`，其余统一归一化为 `inherit`。
- **影响**：打开授权组直接保存，就会删除 grant override，改变 `MANAGED_USERS` 权限边界。
- **修复**：前端完整保留并展示所有 resolver；为四种模式增加读取—原样保存 round-trip 测试。

### FF-09　相同权限选择因操作顺序生成不同载荷

- **级别**：High
- **位置**：`PermissionSelector.tsx:100-105,160-165,542-556`、`useAccessRequestForm.ts:336-338,414-419`
- **问题**：先选直接权限再选覆盖它的 authorization group，隐藏 direct grant 会残留；反向操作则不允许再选 direct。
- **影响**：相同最终界面可生成不同授权事实，造成重复或非预期权限。
- **修复**：状态层持续维护 `selectedDirect ∩ coveredByGroups = ∅`，构造 payload 前再次断言不变量。

### FF-10　`MANAGED_USERS` 审批路径双向错判

- **级别**：High
- **位置**：`useAccessRequestForm.ts:630-647,664-693`
- **问题**：authorization group 实际在 `grants[].scope_key` 表达范围，代码却检查不存在的 `target.scopes`；direct permission 又把“支持的 scope”误当“本次选择的 scope”。
- **影响**：缺直属主管时可错误回退 App owner；反之只选 `SELF` 也可能被阻断并强制补主管。
- **修复**：group 依据实际 grants，direct 依据本次选择的 scope 判断；补两条对称测试。

### FF-11　审批应用失败后的 UI 与真实状态分裂

- **级别**：High
- **位置**：`PortalApprovalsSection.tsx:72-79,104-107,207-210`；后端链路 `access_requests/approvals.py:69-96`、`application.py:46-64,106-126`、`portal/approvals_api.py:146-159`
- **问题**：后端已提交审批并把申请写成 `grant_failed`，但返回 422；前端按“无副作用失败”保留旧待办和弹窗。再次提交得到 409，又被误报为“其他审批人处理”。
- **修复**：正本清源定义复合结果：返回最新 `grant_failed` 状态和 `decision_committed` 语义；前端关闭决策弹窗、刷新 pending/processed，并明确提示需重试授权落地。

### FF-12　审批决策界面信息不足且在途可关闭

- **级别**：High
- **位置**：`PortalApprovalsSection.tsx:197-210,255,303-314`
- **问题**：列表与确认框只显示“直接权限 N 项”，不展示 permission、scope、期限和理由；提交中仍能通过取消、遮罩、X 或 Escape 关闭，POST 不会取消。
- **影响**：审批人无法作出知情决策；用户会把关闭误认为取消不可逆操作。
- **修复**：决策前加载并展示完整授权事实，失败时禁审批；pending 时禁用所有关闭通道，并提供页面级最终结果。

### FF-13　交接向导可绕过加载、预览和执行边界

- **级别**：High
- **位置**：`HandoverWizard.tsx:93-112,139-151,170-213,262-264,385-410,502-505`
- **问题**：权限清单加载失败可继续；部分 preview 未完成或失败可进入执行；执行中可关闭并重开；成功后动态 actionable 集合缩为空，完成态反而无法稳定结束。
- **影响**：管理员可能未审阅影响面就执行，或误以为关闭已停止后台交接；并发重入还会重复外部 hook。
- **修复**：每一步用明确状态机守卫；冻结本批 app keys；执行中禁止关闭或改成真正后台 job；后端同步提供幂等锁。

### FF-14　转岗选择可能被 refetch 重置，批量接收人更新又非原子

- **级别**：High
- **位置**：`HandoverTaskDetail.tsx:386-410,423-491`、`HandoverWizard.tsx:114-129`、`lifecycle_api.py:556-586`
- **问题**：任意详情 refetch 会重建勾选状态；已取消任务仍展示差异确认；多 App 接收人 PATCH 逐项提交，后项失败时前项已保存。
- **影响**：管理员取消勾选的权限可被静默重新选中；界面显示失败但数据库处于混合状态。
- **修复**：以 plan version 初始化一次并维护 dirty；终态只读；服务端先完整验证，再在一个事务中锁任务并批量写入。

### FF-15　通用分页组件与若干列表的服务端分页不一致

- **级别**：Medium
- **位置**：`components/ui/TablePagination.tsx:13-25`、`HandoverTaskList.tsx:53-82,139-176`、`lifecycle_api.py:167-185`
- **问题**：manual pagination 仍用当前页行数当总数，第二页会显示“共 1 条”；交接单后端直接 `[:200]` 且没有分页，第 201 条后不可达。Manifest versions 和 Connector runs 也只取固定第一页。
- **修复**：组件显式接收 `total_items`；所有列表统一标准分页契约，禁止静默硬截断。

### FF-16　成员列表契约缺少操作所需 ID

- **级别**：Medium
- **位置**：`OverviewTab.tsx:398-402`、`memberships_api.py:53-60`
- **问题**：前端只有 `membership.id` 存在才显示停用按钮，真实 GET 默认 `include_id=False`；前端测试却伪造了 ID。
- **影响**：生产界面无法停用任何成员。
- **修复**：canonical list response 返回稳定 ID；以后端真实序列化结果做跨层契约测试。

### FF-17　Connector UI 的测试门槛可绕过或被旧结果污染

- **级别**：High
- **位置**：`ConnectorTab.tsx:71-80,100-121,187-200,263-329`
- **问题**：连通性测试结果只是全局布尔值，不绑定 connector key 和配置指纹；测试期间可编辑，旧响应会放行新配置。已有 disabled 实例启用、已启用实例修改配置都可绕过测试。页面还只取 `data[0]`，其余合法多实例不可达。
- **修复**：测试结果绑定规范化配置 hash；输入变化废弃旧响应；所有启用或启用态改配置都要求当前候选通过；对多实例建列表，或从 schema/API 根改为单实例。

### FF-18　高风险行操作缺少确认或串行化

- **级别**：Medium
- **位置**：`ConsoleAppList.tsx:124-130`、`apps_api.py:300-328`、`CredentialsTab.tsx:66-77`、`useCredentialsActions.ts:63-72`
- **问题**：应用单击即硬删除；凭据轮换按钮不受 pending 状态控制，双击会生成多个 active token，一次性明文互相覆盖。
- **修复**：删除应用必须显示 app name/key 的二次确认；按 credential ID 串行化 rotate/disable，并立即展示唯一结果。

### FF-19　审批模板测试、映射和重投状态不可靠

- **级别**：High
- **位置**：`ApprovalTemplatesPage.tsx:33-40,134-135,243-304,376-418`、`approval_templates_api.py:125-145,171-218`、`workflows/services.py:205-240`、`ApprovalInstancesPage.tsx:63-84,230-248`
- **问题**：平台模板测试按 key 二次解析，可能实际测试同 key 的 App 专属模板；`form_mapping` 非字符串值可保存并在运行时静默忽略；重投成功后旧 failed 行仍可重复点击，后端又无原子 `failed→pending` 守卫。
- **修复**：测试精确 template ID；两端严格 `dict[str,str]`；重投采用锁/CAS，前端立即写回响应并按实例禁用。

### FF-20　团队详情和弹窗存在旧响应覆盖新状态

- **级别**：High
- **位置**：`ConsoleTeamDetail.tsx:57-141,179-241,284-299,512-522`、`ApprovalTemplatesPage.tsx:85-94,219-225,307-318`
- **问题**：多个 mutation 和在途 GET 全量覆盖同一缓存；旧响应可在新 mutation 后到达并永久回滚 UI。pending 弹窗关闭再打开时，旧 Promise 的 `onSuccess` 会关闭新弹窗并丢草稿。
- **修复**：取消旧 query、按版本/请求 ID 接受响应、串行化写入；pending 时禁关闭，不能把 mutation `reset()` 当作取消。

### FF-21　运营看板缺失失败恢复与紧急撤权主路径

- **级别**：High
- **位置**：`OperationsPage.tsx:38-43,70-77,360-415`、`operation_filters.py:34-77`
- **问题**：后端已有 app/user/status/time/version 筛选、`retry-grant` 和 `emergency-revokes`，前端只提供分页和 submitted 审批动作，也不展示 grant version/is_current。
- **影响**：管理员无法定位或恢复 `grant_failed`，也无法通过产品界面完成紧急撤权。
- **修复**：以 URL 承载筛选；展示失败原因和版本；为重试/紧急撤权增加带 reason 的确认对话框与验收测试。

### FF-22　Onboarding 多个异步结果没有绑定输入快照

- **级别**：Medium
- **位置**：`AppOnboardingWizard.tsx:295-370,617-735,753-761`
- **问题**：自动接入结果、查询验证结果和 token 清理不绑定当前 base URL、app key、user 或 request；慢旧响应可覆盖新输入。OAuth client 创建后没有 token exchange 步骤，完成页却统一假设已有 `$APP_TOKEN`。
- **修复**：mutation variables 携带快照/序号，输入变化立即失效；按 credential kind 分流并补 `client_credentials` 换 token 链路。

### FF-23　前端大量依赖静态类型而缺少运行时契约校验

- **级别**：Medium
- **位置**：`PortalPage.tsx:98-100,150-152,298-336`、`PortalApprovalsSection.tsx:54-60,82`、`useAccessRequestForm.ts:188-202,339-355,414-448`
- **问题**：HTTP 200 的 `{}`、`{data:null}` 会被伪装成“暂无数据”；direct grants 50、审批人 20、理由 1000 的服务端上限未落到 UI；`permission::scope::...` 字符串拼接还会误解析合法 key。
- **修复**：在 queryFn 边界严格解析 envelope/行结构；共享契约常量；选择状态改用结构化二元组，不用未转义分隔符。

### FF-24　Portal 次级路由、分页与历史展示存在一致性缺陷

- **级别**：Medium
- **位置**：`PortalPage.tsx:78,163-177,267-280`、`PortalApprovalsSection.tsx:50,67-102,193`
- **问题**：尾斜杠路由会误落到 grants；审批分页使用当前页数量当总数，末页收缩后可出现“2 / 1”；同意意见和限时申请的具体到期时间不展示。
- **修复**：路由直接传 view；使用服务端总数并 clamp page；只要有 `decision_comment` 就展示，并显示 `grant_expires_at`。

---

## 三、前端：安全性

### FS-01　可复制命令存在 shell 注入

- **级别**：High
- **位置**：`AppOnboardingWizard.tsx:39-43,71,743-788`、`ConsoleAppWorkspace.tsx:45-51,161-171`、`GuideTab.tsx:14-31,72-75`、`CodeBlock.tsx:19-23,41-42`
- **问题**：未经 canonical App 成功加载的 `app_key`、路由参数和 descriptor name 被直接拼入 shell/curl 片段。
- **复现**：`/console/apps/new?step=done&app_key=%24%28id%29` 会生成 `EASYAUTH_APP_KEY=$(id)`；编码后的 `foo";id;#` 可闭合 curl 参数。
- **影响**：管理员复制执行页面生成的命令时，可在本机执行攻击者注入的命令。不是浏览器内 XSS，但属于可信 UI 诱导的代码执行。
- **修复**：只从成功加载并验证的 canonical 对象生成命令；路径使用 `encodeURIComponent`；变量做可靠 shell quoting；去除控制字符，失败时不生成兜底命令。

### FS-02　Descriptor token 可随输入变更泄露到另一 origin

- **级别**：Medium
- **位置**：`AppOnboardingWizard.tsx:292-313,323-339`
- **问题**：向 URL A 自动接入成功后，token A 保留；修改 base URL 为 B 再运行时会把 A 的 token 发给 B。
- **修复**：token 与 origin、app key、请求 generation 绑定；任一目标输入变化立即清除，跨 origin 永不复用。

### FS-03　审批界面隐藏权限事实会放大误授权风险

- **级别**：High
- **位置**：同 `FF-12`
- **问题**：`finance.admin @ GLOBAL` 和普通权限在确认前都只显示“直接权限 1 项”。
- **影响**：权限决策事实不完整，审批人无法识别高危 scope。
- **修复**：完整事实加载失败时 fail closed；权限 key/name/scope、期限、理由必须在批准按钮前可见。

### FS-04　一次性明文会留在 mutation cache

- **级别**：Medium
- **位置**：`WebhookTab.tsx:65-85,237-243`、`useCredentialsActions.ts:51-72,101-105`、`AppOnboardingWizard.tsx:617-629`、`frontend/src/lib/query.ts:3-9`
- **问题**：Webhook secret、client secret、token 等一次性明文成为 TanStack mutation data，关闭弹窗后仍可在内存和开发工具中保留一段时间。
- **修复**：展示层消费后主动清空；避免把 secret 放进长期 cache；必要时使用短生命周期的组件 state，并在路由/app 变化时擦除。

### FS-05　剪贴板写入失败仍显示“已复制”

- **级别**：Medium
- **位置**：`CodeBlock.tsx:19-23,30-42`、`SecretDialog.tsx:36-42`
- **问题**：可选链和 `void` 忽略 `navigator.clipboard.writeText` 不存在或 reject，UI 仍切换成功态。
- **影响**：用户可能以为一次性 secret 已保存而关闭弹窗，或粘贴剪贴板中旧的敏感内容。
- **修复**：等待 Promise；失败时保留 secret、显示明确错误并提供可访问的手工选择方案。

### 前端安全正向结论

- 未发现 `dangerouslySetInnerHTML`、`innerHTML`、`eval`、`srcDoc` 等可达危险 sink。
- React 动态内容按文本渲染；统一 API helper 使用相对路径与 CSRF 头；未发现可确认的前端开放重定向。
- `localStorage` 只用于 locale，没有发现将 access token 或一次性 secret 写入持久浏览器存储。

---

## 四、后端：功能性

### BF-01　多个安全关键异步链路没有真正的 durable outbox

- **级别**：High
- **位置**：
  - 钉钉 Stream：`integrations/dingtalk/stream.py:42-71,90-113`
  - 审批完成：`workflows/services.py:146-189`
  - Webhook：`webhooks/delivery.py:82-99,153-168`
  - 离职禁号：`lifecycle/services.py:131-150,605-610`
  - Connector：`connectors/dispatch.py:47-79`
- **问题**：这些路径先提交 DB，再通过 `on_commit(send_task)` 发布。发布失败时 DB 已是新状态，但没有 dispatcher 扫描和补偿事实。
- **实证**：全量后端测试中的钉钉 Stream 用例在 Redis 不可用时返回 500；事件行已存在。相同 event 重投命中 `created=False` 后直接 ACK，不再入队，永久停在 `received`。
- **修复**：统一事务 outbox：业务事实与唯一事件行同事务；独立 dispatcher 持续 claim/lease/retry；周期扫描 pending/超时 in-flight；同态重试修补缺事件。

### BF-02　创建外部钉钉审批存在不可恢复的模糊状态

- **级别**：High
- **位置**：`workflows/services.py:81-137,205-217`、`api/approval_views.py:65-77`
- **问题**：远端已创建但响应超时、本地保存 process ID 前崩溃，或首次远端失败后，本地行会停在 `created/failed`。同 `biz_key` 重试直接返回旧行并可能以 200 表示成功，不会重发或对账。
- **修复**：持久命令状态机 `pending/submitting/submitted/ambiguous`；保存 payload hash；同 key 异载荷 409；按 provider correlation key 对账；failed 只能通过显式、带锁重试恢复。

### BF-03　旧 Role schema 仍可写但授权主链完全忽略

- **级别**：High
- **位置**：`access_requests/models.py:173-209`、`grants/models.py:124-160`、`access_requests/application_grants.py:340-355`、`grants/query.py:159-279`
- **问题**：`AccessRequestRole`/`AccessGrantRole` 仍存在且测试仍写入，新应用与查询只读取 AuthorizationGroup/Permission。
- **影响**：申请可显示 `grant_applied` 却生成空授权；change 可清空现有成员；旧授权查询永远不可见。
- **修复**：遵守项目无兼容分支约束，一次性删除旧 schema、模型、测试和调用方，统一到新模型。

### BF-04　限时申请审批时可以已经过期

- **级别**：High
- **位置**：`access_requests/submission_validation.py:170`、`application_grants.py:59`、`grants/models.py:113`、`grants/lifecycle.py:50`
- **问题**：只在提交时校验未来时间；审批和 GrantService 写入时不校验 `expires_at > now`。
- **影响**：申请进入 `grant_applied`，数据库产生 active grant，但权限查询立即为空。
- **修复**：在唯一授权写边界重验当前时间；已过期申请明确进入不可应用状态，不得“成功但无权限”。

### BF-05　交接会重新转授历史 revoked/expired 权限

- **级别**：High
- **位置**：`lifecycle/services.py:529,568-580`
- **问题**：`_latest_grants_per_app()` 只取每个 App 历史最高版本，不过滤当前有效状态。
- **影响**：数月前已撤销的权限可在后来的手工交接中重新授予接收人。
- **修复**：手工任务只快照当前有效授权；自动离职必须在撤权前保存本次明确 grant IDs，不能从历史猜测。

### BF-06　岗位模板逐项期限被折叠并扩大

- **级别**：High
- **位置**：`lifecycle/models.py:384`、`lifecycle/services.py:473,757,877`
- **问题**：同 App 的 30 天与 365 天取最大值；任一 permanent 会把全部 timed 提升为永久；transfer diff 新增 timed 项还可能使用 permanent 默认值。
- **修复**：正本清源领域模型。若期限属于权限项，应在 membership/grant fact 粒度持久化，不能在 App grant 层静默合并。

### BF-07　接收人已过期授权会被合并复活

- **级别**：High
- **位置**：`lifecycle/services.py:701`
- **问题**：合并只看 `status == active`，不看 timed grant 是否已过期。beat 尚未改状态的窗口内，旧成员会并入新 grant 并获得新期限或永久期限。
- **修复**：所有写/读复用同一“当前有效”判定；合并前先过期化，过期事实不得参与成员合并。

### BF-08　不同 kind 的进行中交接单被错误视为同一幂等任务

- **级别**：High
- **位置**：`lifecycle/services.py:99`
- **问题**：查询只按 subject/open status，不比较 `kind`。offboard 可被当作 transfer 返回，或 transfer 被离职流程复用。
- **修复**：只有同 kind 才幂等；不同 kind 明确冲突，或实现完整、原子的类型转换。

### BF-09　hook 失败后改接收人会让权限和外部资产分属两人

- **级别**：High
- **位置**：`lifecycle/services.py:153,206,649`
- **问题**：内部权限先转给 A，hook 后失败；把 action 接收人改成 B 后重试，done grant items 不再执行，但外部资产交给 B。
- **修复**：持久化 saga 阶段和每次执行接收人；已有处理 item 时禁止直接换人，或执行明确撤销/重转补偿。

### BF-10　转岗差异确认可在终态后重复执行且非原子

- **级别**：High
- **位置**：`lifecycle/services.py:382-469`
- **问题**：不校验 task kind/open/confirmed，不锁 task/plan，也没有覆盖全部 App 的事务。取消/完成后仍可改权限；重复确认继续递增版本；第二个 App 失败时第一个已提交。
- **修复**：锁 task/plan；要求 transfer+open+未确认；相同重复返回既有结果、异载荷冲突；所有 App 变更一个外层事务；未知 key 快速失败。

### BF-11　接收人与释放公海没有 XOR 约束

- **级别**：High
- **位置**：`lifecycle/services.py:212,620-631`、`admin_console/lifecycle_api.py:562`
- **问题**：可同时提交 `to_user_id=B` 和 `release_to_pool=true`。
- **影响**：EasyAuth 把权限转给 B，下游 hook 却释放业务资产，形成相反事实。
- **修复**：两种策略严格二选一，并禁止接收人为 subject 自己。

### BF-12　模板替换、入职与批量交接存在部分提交

- **级别**：High
- **位置**：`admin_console/lifecycle_api.py:589`、`lifecycle/services.py:473`、`lifecycle_api.py:556-586`
- **问题**：模板先删旧 items 再逐条写；多 App onboarding/receiver 更新逐项提交，没有覆盖整批的事务。
- **影响**：接口返回失败，但旧模板已丢、部分 App 已授权或前几项接收人已变更。
- **修复**：先完整解析和校验，随后在一个外层事务中锁相关对象并批量提交；提交后统一分发。

### BF-13　Lifecycle action 状态机不闭合

- **级别**：Medium
- **位置**：`lifecycle/services.py:206,350,613-617`
- **问题**：`skipped` 仍可 preview/execute，`executing` 未被拒绝，执行无锁；没有 App action 的任务因 `if actions and ...` 永远不能完成。
- **修复**：定义显式不可逆迁移表，锁行/CAS；空 action 集合按 vacuous truth 收敛，结合 team items 与 transfer plan 判断完成。

### BF-14　交接“快照”可被目录变更篡改，hook 202 又被当同步成功

- **级别**：Medium
- **位置**：`lifecycle/models.py:222`、`webhooks/hooks.py:49-95`、`lifecycle/services.py:219`
- **问题**：快照只保存可变 FK 且 CASCADE，重命名/删除会改写历史；`signed_hook_post` 丢弃 HTTP status，202 也把 action 直接标 done。
- **修复**：保存不可变 key/name/version 快照，FK 使用 PROTECT/SET_NULL；区分 200/202，202 持久化状态 URL 并轮询，有界重试且可恢复。

### BF-15　AccessRequest 缺提交幂等键

- **级别**：Medium
- **位置**：`access_requests/models.py:70`、`access_requests/services.py:68`
- **问题**：双击或网络重试会创建两张 submitted 单；grant 一张成功后另一张可 `grant_failed`，change 可重复增版本。
- **修复**：保存客户端 idempotency key 与规范化载荷摘要；同 key 同载荷返回原单，异载荷冲突。

### BF-16　审批输入 schema 和幂等载荷没有执行

- **级别**：Medium
- **位置**：`workflows/models.py:70`、`workflows/services.py:72,231-240`
- **问题**：`form_schema` 被存储却从未校验 required、类型或未知字段；同 biz_key 不比较 originator/form；`form_mapping` 非字符串值会静默退回原字段名。
- **修复**：模板保存时校验 schema/mapping，创建时严格执行；保存规范化 payload hash 并拒绝同 key 异载荷。

### BF-17　外部 process ID 与 callback 关联缺少唯一性和恢复机制

- **级别**：Medium
- **位置**：`workflows/models.py:144`、`workflows/services.py:147`
- **问题**：process ID 只有普通索引，callback 用 `.first()`；相同 ID 可推进错误实例，另一条永久卡住。远端 callback 早于本地保存 ID 时也无法可靠关联。
- **修复**：非空 process ID 条件唯一；保存 provider correlation key；无法关联事件进入持久待匹配队列而非永久 skipped。

### BF-18　Manifest 无法正常收缩 scope，配置完整性又漏掉 inactive scope

- **级别**：High
- **位置**：`applications/permission_template_storage.py:407-420,477-492`、`applications/models.py:440-451`、`applications/configuration.py:118-131`
- **问题**：更新 Permission scope 后，旧 inactive grant 的 `full_clean()` 仍要求 scope 被新 permission 支持，事务回滚；反向地，active grant 引用 inactive AppScope 时 readiness 仍返回 ready，真实展开会过滤为空。
- **修复**：定义明确更新顺序和只针对 active 关系的不变量；active grant 必须引用 active scope；parser、model、readiness 同时校验。

### BF-19　Manifest 不是权威快照且 hash 语义不一致

- **级别**：Medium
- **位置**：`permission_templates.py:84-119`、`permission_template_parsing.py:272-286`、`permission_template_storage.py:66-85,501-516`、`manifest_import.py:59-68`
- **问题**：删除 lifecycle URL 不会清旧值；重复审批规则按 target 静默 last-wins；手工入口按原始文本 hash，自动入口按 canonical JSON hash，同语义同版本会冲突。
- **修复**：manifest 管理字段按权威快照清除；解析阶段拒绝重复 target；所有入口统一 canonical hash 并一次性迁移语义。

### BF-20　自动接入新应用后必然缺 owner

- **级别**：Medium
- **位置**：`admin_console/auto_onboarding_api.py:122-168`、`applications/configuration.py:74-79`
- **问题**：创建 App 但不创建 AppMembership，随后 readiness 必报 blocking `active_owner_missing`。
- **修复**：同事务把 actor 建为 active owner，或请求必须提供并校验 owners；测试最终 readiness，而非只测 App/manifest 存在。

### BF-21　目录同步把合法空集忽略，并对畸形计数 fail-open

- **级别**：High
- **位置**：`integrations/authentik/directory_sync.py:292-325,381-424`、`directory_payloads.py:80-84,182-191`
- **问题**：`users_total=0` 被丢弃，最后一名员工永不离职；反之 status 计数缺失/错型时跳过完整性检查，却仍按截断用户列表做破坏性 prune/depart。department 畸形 200 也会被当权威空集并全删镜像。
- **修复**：为每个 corp 要求合法 success status、非负 total、generation 和精确数量；明确区分合法零与缺失响应；任何契约错误在写入前 fail-fast。

### BF-22　定时同步与 Stream refresh 可让旧快照覆盖新离职事实

- **级别**：High
- **位置**：`tasks/authentik.py:57-67`、`tasks/dingtalk_stream.py:120-134`、`directory_sync.py:91-120,207-222,328-367`
- **问题**：两个同步可并发；先抓到旧 active 快照的任务可在新 departed 任务撤权后晚提交，把用户重新设为 active。
- **修复**：按 source/corp 串行化；引入持久单调 generation/fencing，旧 generation 禁止写；锁必须有 owner token 和续租。

### BF-23　Connector 对账状态机存在锁、顺序和身份建模缺陷

- **级别**：High
- **位置**：`connectors/services.py:28-29,81-94,147-152`、`tasks/connectors.py:35-43,78-114`、`connectors/netbird/connector.py:128-160,176-196,217-299`
- **问题**：锁竞争直接 ACK 丢事件；600 秒租约不足且无 owner token，旧持有者可删除新锁；offboard 不与 reconcile 共锁；新增/解封先于撤权，永久 provisioning 错误或 API budget 可饿死所有 revoke。
- **修复**：以数据库持久 generation/dirty 状态驱动单实例串行 worker；token 化 lease 和 compare-delete；安全收缩优先并预留预算；瞬态错误有界重试，永久错误按对象记录后继续撤权。

### BF-24　Portal 与运营 API 存在线性扫描和过滤 fail-open

- **级别**：Medium
- **位置**：`portal/approvals_api.py:162-186`、`portal/request_catalog.py:42-78,345-362,497-523`、`admin_console/operation_filters.py:80-178`
- **问题**：pending approvals 先加载全局全部 submitted 后 Python 过滤/切片；request catalog 每次加载全部活跃员工；非法 page/int/bool/datetime 被静默默认或当作未筛选，可能扩大结果集。
- **修复**：审批参与人关系规范化并数据库过滤/count/slice；候选 ID 定向查询；过滤参数严格解析并返回 400/422。

### BF-25　外部集成分页、缓存和响应契约会制造假成功

- **级别**：Medium
- **位置**：`integrations/authentik/admin_client.py:125-146`、`integrations/dingtalk/api_client.py:19-22,87-108`
- **问题**：Authentik session revoke 固定只取前 500 条且畸形 envelope 当 0；DingTalk token cache key 不绑定 app key/secret，轮换后测试仍可能使用旧租户 token，短有效期还可能被错误缓存 3600 秒。
- **修复**：完整分页至零并严格校验；缓存键加入凭据不可逆指纹/版本，更新时失效，连通性测试强制新取 token。

---

## 五、后端：安全性

### BS-01　公网部署使用 DEBUG、runserver 和 SQLite

- **级别**：Critical
- **位置**：`docker-compose.deploy.yml:1-21,29-41,66-72`、`config/settings/base.py:15,22-41,114-125,187-195`、`config/settings/deploy.py:1-12`
- **问题**：标注公网域名的 deploy compose 明确设置 `DJANGO_DEBUG="1"`，使用 `runserver`，并允许开发 secret/SQLite 回退。Secure Cookie、HSTS、nosniff 等只在 `not DEBUG` 时启用。
- **证据**：`manage.py check --deploy` 产生 6 项警告，包括 HSTS、SSL redirect、secret、Session/CSRF Secure Cookie 和 DEBUG。
- **修复**：部署入口强制 `DEBUG=0` 并启动时断言；PostgreSQL + gunicorn；反代 HTTP→HTTPS；deploy 设置无条件安全 cookie/HSTS/nosniff。不要保留公网开发模式分支。

### BS-02　App owner 可通过任意 Webhook URL 发起 SSRF 和本地文件探测

- **级别**：Critical
- **位置**：`admin_console/webhook_config_api.py:30-42,110-126,179-195`、`applications/permission_templates.py:84-119`、`webhooks/delivery.py:75-79,102-128`、`webhooks/hooks.py:49-95`
- **问题**：只做长度校验，任意 scheme/主机原样落库；`urlopen` 可访问 localhost、云元数据、内网和 `file://`。无界读取 `file:///dev/zero` 可稳定耗尽 worker 内存。
- **修复**：只允许 HTTPS；拒 userinfo/fragment/非预期端口和所有非 HTTP(S) scheme；配置时与发送时都解析并拒绝 private/loopback/link-local/reserved；按 App 配域名 allowlist，并用 egress firewall 阻断内网/元数据。

### BS-03　跨域重定向可泄露上游凭据

- **级别**：High
- **位置**：`connectors/netbird/client.py:138-152`、`integrations/authentik/admin_client.py:156-173`、`directory_client.py:172-197`、`integrations/dingtalk/api_client.py:158-171`、Webhook sinks
- **问题**：urllib 默认跟随 30x，并会把 Authorization/token/自定义签名头复制到新 origin；301/302/303 还会把 POST 改为 GET。
- **修复**：带凭据客户端默认禁重定向；确需跟随时只允许相同 scheme/host/port，origin 变化时剥离全部凭据，并逐跳重做 SSRF 检查。

### BS-04　`assert_public_host` 可被 DNS rebinding 和跳转绕过

- **级别**：High
- **位置**：`config/net.py:39-55`、`admin_console/auto_onboarding_api.py:189-210`
- **问题**：检查时解析一次，`urlopen` 建连时再次解析，没有 IP pinning；跳转目标也不校验。deploy 的 DEBUG 又让 `allow_local=True` 直接放行私网。
- **修复**：让实际 socket 连接已校验 IP，Host/SNI 保持域名；或统一走具备 SSRF 防护的 egress proxy；逐跳验证且生产永不 DEBUG。

### BS-05　所有主要出站客户端都无响应大小与总时限上限

- **级别**：High
- **位置**：`webhooks/delivery.py:124-128`、`hooks.py:75-79`、NetBird/Authentik/DingTalk client 的 `.read()` 路径
- **问题**：socket timeout 不是总 deadline；对方可慢滴字节长期占 worker，或返回超大 body 导致 OOM。DingTalk 错误体也是全读后才截 500 字符。
- **修复**：统一 HTTP transport；检查 Content-Length 并分块最多读取 N+1；JSON/错误体设硬上限；connect/read/total deadline、跳数和 Celery time limit 同时约束。

### BS-06　正确密码可循环清零 TOTP 爆破计数

- **级别**：High
- **位置**：`accounts/local_admin_views.py:100-137`、`accounts/local_admin.py:128-129`
- **问题**：密码正确后、二因子完成前即 `reset_login_failures`。攻击者每猜错 4 次 TOTP，重新提交一次正确密码即可无限清零，永不触发 5 次锁定。
- **修复**：删除提前清零；只在完整绑定登录会话后清零。补“4 次错码→重提正确密码→继续累计并锁定”集成测试。

### BS-07　TOTP 绑定不要求 step-up，可把被盗 session 变成长期因子

- **级别**：High
- **位置**：`accounts/local_admin_views.py:236-265`、`admin_console/two_factor_api.py:63-113`
- **问题**：HTML 与 JSON 两套 begin/confirm 只需现有本地管理员 session；对照 passkey complete、TOTP disable 都要求当前密码。
- **影响**：窃取 session 后可生成攻击者掌握的 secret 并启用 TOTP，形成持久超管接管；旧 enrollment 还能并发覆盖后来设置。
- **修复**：begin 与 confirm 都绑定短 TTL、一次性的密码 step-up 与 enrollment nonce；锁行检查当前因子状态并原子消费。

### BS-08　改密不会撤销其他本地超管会话

- **级别**：High
- **位置**：`accounts/auth.py:174-183`、`accounts/local_admin.py:96-105`、`local_admin_views.py:204-209`
- **问题**：session 没有 credential/session version；鉴权只查账号仍 active。管理员改密后，攻击者旧 session 继续有效，并可结合 BS-07 植入 TOTP。
- **修复**：增加单调 `session_version`；改密、停用、管理员重置和高风险因子变更时递增；当前合法会话显式更新版本并 `cycle_key`，其余失效。

### BS-09　App 详情和配置状态存在对象级读 IDOR

- **级别**：Medium
- **位置**：`admin_console/apps_api.py:154-188,331-340,418-428`
- **问题**：`_visible_app` 明确丢弃 actor，只按 app key 查。任意登录员工可读取非成员 App 的 owner/developer、角色/权限数量、活动凭据数量、导入者和 blocking 配置项。
- **修复**：非 superuser 强制 `can_view_app`，未授权统一 404；覆盖 detail 与 configuration-status 两端点。

### BS-10　人员分页 API 允许普通登录用户枚举全员与离职信息

- **级别**：Medium
- **位置**：`admin_console/users_api.py:38-45,59-110`、`admin_console/urls.py:204`
- **问题**：只要求 `require_console_actor`，返回全员 ID、姓名、邮箱、部门、状态和 open handover task 元数据。
- **修复**：人员管理分页至少 superuser-only；若保留选人搜索，按具体 App/角色收窄字段、空查询、速率并记录审计。

### BS-11　普通 App owner 可触发真实 Connector reconcile

- **级别**：Medium
- **位置**：`admin_console/connectors_api.py:250-272,535-565`
- **问题**：create/update/delete/test/mapping write 都要求 `_superuser_required`，唯独 reconcile 只走 `can_manage_app`，随后立即入队修改外部系统，且可无限重复。
- **修复**：入队前强制 superuser；按 actor/instance 去重限速；补 owner 403 测试。

### BS-12　Connector 并发可重新解封离职用户，并遗留外部权限

- **级别**：High
- **位置**：`tasks/connectors.py:35-43,78-114`、`connectors/services.py:81-94`、`connectors/netbird/connector.py:133-196,217-299`
- **问题**：offboard 不与 reconcile 共锁，旧 desired 可在 block 后写回 `is_blocked=False`；锁竞争直接丢撤权事件。mapping 改名/删除、group/instance 删除会先忘记 managed identity，旧外部组随后被当 unmanaged 永久保留。
- **修复**：同实例串行状态机与 lifecycle generation fencing；非 active 用户永不允许解封；外部清理成功前保留 tombstone/ownership；映射 immutable external group ID，不用可变名称作身份。

### BS-13　多个 App 对同一 NetBird account 的状态互相覆盖

- **级别**：High
- **位置**：`connectors/models.py:87-93`、`connectors/services.py:51-55`、`connectors/netbird/connector.py:139-160,317-335`
- **问题**：每 App 实例独立计算 desired，但 `is_blocked` 是 account 级字段；执行顺序可让合法用户断连或无授权用户解封。一个永久 provisioning 错误还会在撤权前中断整轮。
- **修复**：保存/探测 immutable account ID 并跨 App 聚合 desired，或 schema 禁止重复绑定；对账先安全收缩，单对象永久错误不得阻断其余 revoke。

### BS-14　目录同步的破坏性路径对异常响应 fail-open

- **级别**：High
- **位置**：同 `BF-21`、`BF-22`
- **问题**：缺失 total/generation 或截断分页仍可批量标记 departed；合法空集又完全不处理。与并发旧快照结合，可在“批量误撤”和“离职不撤”之间双向失效。
- **修复**：破坏性同步需要权威 generation、完整计数、单调 fencing 和异常阈值；任何不完整快照禁止写入。

### BS-15　Webhook delivery 缺少 claim/CAS，可重复投递并覆盖终态

- **级别**：Medium
- **位置**：`webhooks/models.py:82-100`、`webhooks/delivery.py:104-149`、`docker-compose.deploy.yml:74-83`
- **问题**：两个 worker 可同读同发；A 保存 delivered 后，B 可用陈旧对象覆盖为 failed，并丢 attempts。迟到的 failed 任务仍会再次 POST。
- **修复**：条件更新或 `select_for_update(skip_locked)` claim；lease token/generation；只有当前 token 能写终态，manual retry 使旧 generation 失效。

### BS-16　依赖健康摘要脱敏不足，敏感值可先明文落库

- **级别**：Medium
- **位置**：`applications/dependency_health.py:107-118`、`dependency_health_checks.py:69-76`
- **问题**：只剥 URL userinfo 和 Bearer；`?token=SECRET`、Basic、`api_key`、password 字段仍原样持久化。展示层整段隐藏也无法消除 DB/备份泄露。
- **修复**：写入边界对结构化 URL query/header/常见键值做值级替换；未知外部异常使用固定摘要；补“数据库中不含 secret”的断言。

### BS-17　后台安全任务无有效健康信号，供应链构建不可复现

- **级别**：Low
- **位置**：`config/urls.py:11-12,29`、`config/settings/base.py:321-345`、`Dockerfile:9,25,35-46`、`docker-compose.deploy.yml:61-63`
- **问题**：web health 只返回常量 ok，beat/stream 停摆时限时授权回收、离职同步仍看似健康；镜像使用 `uv:latest`、浮动 Redis tag，并在锁文件外安装 gunicorn。
- **修复**：上报 beat 最近 tick、关键任务最近成功、stream ACK、broker/DB readiness；基础镜像和工具 pin digest，gunicorn 纳入 lock，生成 SBOM 并验证签名。

---

## 六、i18n 专项

### I18N-01　授权组编辑会永久清空英文名称和描述

- **级别**：High
- **位置**：`MatrixTab.tsx:94-101`、`workspace/matrix/grantDraft.ts:24-32,56-65`、`authorization_groups_api.py:84-95,314-329`
- **问题**：payload 不含 `name_en/description_en`，后端默认空字符串并无条件覆盖。
- **修复**：表单、draft、API schema 完整覆盖双语字段，并补原样保存 round-trip 测试。

### I18N-02　目录数据虽有英文，UI 仍只展示主名称

- **级别**：Medium
- **位置**：`CatalogTab.tsx:28-53,159-220,417-535`、`MatrixTab.tsx:133-136`、`RequestTargetPicker.tsx:73`、`AppOnboardingWizard.tsx:448-519`
- **问题**：权限、授权组、Connector mapping 直接读 `.name/.description`，没有使用现有 `localizedName(locale, item)`；Catalog UI 也无法输入英文名称/描述。
- **修复**：领域对象统一提供 locale-aware selector；写入界面完整编辑双语字段；英文缺失时按明确规则回退，而不是永远用中文主字段。

### I18N-03　多组可见文本完全绕过消息系统

- **级别**：Medium
- **位置**：`ManifestTab.tsx:64-186,322-377`、`GuideTab.tsx:20-75`、`AccessRequestFields.tsx:43-116`、`RequestTargetPicker.tsx:54-82`、`PaginationBar.tsx:39-70`、`CodeBlock.tsx:35-38`、`Dialog.tsx:37,60` 等
- **问题**：按钮、提示、aria label、空状态和“静态 token”等直接硬编码中文；英文模式混入中文。
- **修复**：全部进入统一 key；共享组件必须由调用方传翻译文案或自己使用 i18n，不允许在底层组件固定中文。

### I18N-04　后端中文标签和错误正文覆盖前端翻译

- **级别**：Medium
- **位置**：`PortalPage.tsx:153-161`、`PortalApprovalsSection.tsx:224-230`、`portal/access_request_data.py:124-134`、`status_text.py:15-33`、`frontend/src/lib/api.ts:166-195`
- **问题**：前端优先展示后端固定中文 `status_label`；大量错误/健康 issue 直接返回中文或不稳定正文，英文客户端无法按机器码翻译。
- **修复**：API 只把稳定 code、参数和结构化 facts 当契约；前端按 locale 负责文案，日志另存诊断摘要。

### I18N-05　日期、列表分隔符和数字格式固定为中文

- **级别**：Medium
- **位置**：`frontend/src/lib/status.ts:145-159` 及其 26 个调用页、Portal 中固定顿号、`TwoFactorSection.tsx:542-550`
- **问题**：公共日期 helper 固定 `Intl.DateTimeFormat("zh-CN")`，另一些位置又使用浏览器默认 locale；英文界面仍出现中文顺序和顿号。
- **修复**：I18nProvider 暴露统一 locale 与 formatter；日期、相对时间、列表、数字都从该上下文生成。

### I18N-06　插值器没有复数规则

- **级别**：Medium
- **位置**：`frontend/src/i18n/I18nProvider.tsx`
- **问题**：只做简单变量替换，英文会产生 `1 days`、`1 item(s)` 等文案。
- **修复**：至少实现按 locale 的 `Intl.PluralRules` 消息分支；不要用括号复数伪装完整翻译。

### I18N-07　Django 页面没有接入服务端 i18n

- **级别**：Medium
- **位置**：Django settings/middleware、403/404、本地管理员模板及 `local_admin_views.py`
- **问题**：未配置 `LocaleMiddleware`/项目语言选择，服务端模板和校验提示固定中文；React locale 不会影响这些页面。
- **修复**：确定单一 locale 来源并在 Django/React 间同步；模板使用翻译标签，错误只传稳定码。

### I18N-08　文档语言元数据不会随 locale 完整更新

- **级别**：Low
- **位置**：React shell 模板、`I18nProvider.tsx:80-84`
- **问题**：provider 会更新 `<html lang>`，但默认 title 和部分页面标题仍固定中文；无 provider 时默认上下文静默中文。
- **修复**：页面元数据也进入路由级翻译；缺 provider 视为开发错误而非静默回退。

### I18N-09　现有守护测试覆盖面不足，但消息字典本身完整

- **级别**：Medium（测试缺口）
- **证据**：`zh` 与 `en` 各 983 个 key；未发现缺 key、额外 key、空值、重复 key 或 placeholder 不一致。
- **问题**：`noHardcodedChinese.test.ts` 只扫描约 25 个文件，并主要搜中文字符，漏掉 Manifest、Guide、共享组件、后端固定正文和 `zh-CN` 格式器。
- **修复**：扫描所有用户可见前端源文件并维护最小白名单；增加英文 locale 渲染、双语数据 round-trip、API machine-code 测试。

---

## 七、过渡动画与无障碍专项

### MOTION-01　Dialog 输入时会反复抢走焦点

- **级别**：High
- **位置**：`frontend/src/components/Dialog.tsx:85-93,124-132`
- **问题**：focus effect 依赖调用方常见的内联 `onClose`；受控输入每次重渲染都会先把焦点还给背景，再把焦点移到第一个按钮。
- **复现**：在 Dialog 输入一个字符后，`document.activeElement` 变为“关闭弹窗”。
- **影响**：键盘用户无法连续输入，屏幕阅读器上下文跳动。
- **修复**：`onClose` 用稳定 ref/useEffectEvent；focus trap 与 restore 只绑定真实 mount/unmount；补输入不丢焦点测试。

### MOTION-02　关闭的用户菜单仍可被键盘和读屏访问

- **级别**：High
- **位置**：`UserSummary.tsx:52-64`、`layout-shell.css:253-274`
- **问题**：菜单始终挂载，关闭仅设置 opacity 和 pointer-events；Tab 仍可进入不可见链接，Escape 后焦点也可能停在隐藏元素。
- **修复**：关闭时卸载，或正确使用 `hidden/inert`；打开后建立 roving focus，关闭时把焦点还给触发器。

### MOTION-03　PermissionSelector 进入定时器会留下永久 `entering` 行

- **级别**：Medium
- **位置**：`PermissionSelector.tsx:721-747`、相关 CSS `:226-228,401-410`
- **问题**：快速展开 A 再展开 B，旧 timer 只清理当前集合，A 可永久停留 entering 状态。
- **修复**：每个 row key 独立 token/timer，状态迁移按 generation 校验；卸载时清理全部 timer。

### MOTION-04　重开操作不会取消旧退出 timer

- **级别**：Medium
- **位置**：`PermissionSelector.tsx:755-788`
- **问题**：收起后迅速重开，旧 timeout 仍会提前结束第二轮动画并清状态。
- **修复**：每次反向操作取消对方 timer，或使用显式 presence 状态机。

### MOTION-05　退出中的行仍可 Tab 到达和被读屏读取

- **级别**：Medium
- **位置**：`PermissionSelector.tsx:258-285`、CSS `:247-250`
- **问题**：exiting 只禁 pointer-events，160ms 内仍处于可访问树；reduced motion 下也继续等待 timer。
- **修复**：退出开始即 `aria-hidden/inert` 并移除 tabbability；reduced motion 路径同步完成状态。

### MOTION-06　`prefers-reduced-motion` 只关闭少量 shimmer

- **级别**：Medium
- **位置**：`frontend/src/index.css:188-197`、`layout-shell.css:168-183,253-273,323-333,416-430`、`Button.tsx:52-57`、workspace tab CSS
- **问题**：侧栏/菜单/指示器/旋转 spinner/权限树等仍动画；部分组件只是缩短视觉动画，却保留延时状态。
- **修复**：建立全局 motion token；reduced 模式将非必要 duration 归零，并同步取消依赖动画时长的 JS timer。

### MOTION-07　19/20 个 TanStack 表格没有稳定 `getRowId`

- **级别**：Medium
- **位置**：例如 `ConsoleTeamList.tsx:123-127,175-180`
- **问题**：默认 index key 在删除、排序和刷新后会把 DOM/focus 状态复用到另一业务实体，也让安全的行级进入/退出动画无法实现。
- **修复**：所有表格使用领域稳定 ID；再考虑添加删除/刷新动画。

### MOTION-08　加载、错误、空状态和按钮 pending 缺少实时语义

- **级别**：Medium
- **位置**：`TablePrimitives.tsx:91-111`、`Button.tsx:47-63`、`StatusBanner.tsx:20-29`、`PageState.tsx:24-40`、`EmptyState.tsx:10-17`
- **问题**：主要状态缺 `aria-live`、`role=status/alert` 或容器 `aria-busy`，视觉变化不会可靠通知辅助技术。
- **修复**：区分非打断状态与错误告警；表格/区域加载时设置 busy；避免重复朗读。

### MOTION-09　Toast 计时不会因交互或页面隐藏暂停

- **级别**：Medium
- **位置**：`Toast.tsx:53-59,75-81,136-157`
- **问题**：固定 4–6 秒关闭，hover、键盘 focus、浏览器切后台均不暂停；较长错误也没有阅读时间适配。
- **修复**：hover/focus/visibility 暂停并续计；关键错误提供手工关闭或持久 Banner。

### MOTION-10　确认缺失的过渡与不应强行增加的动画

- **级别**：Low（产品体验缺口，不作为功能 bug）
- **确认缺失**：Dialog 和 Toast 都是瞬时挂载/卸载；Language/notification menu 只有进入没有退出；Workspace tab panel、Portal approval tab 内容、表格增删刷新没有 presence 过渡。
- **建议**：先修复焦点、inert、稳定 row ID 和 reduced-motion，再为 Dialog/Toast/menu 增加 120–180ms 的淡入/位移；tab panel 可选短淡入，表格只做有稳定身份的局部高亮/收缩。
- **明确不判缺陷**：空状态、普通错误页没有动画本身不是 bug；桌面固定侧栏不是抽屉，不需要强行添加抽屉动画。

---

## 八、验证结果与质量门禁

### 已通过

- 前端：32 个测试文件、182 项测试全部通过；`tsc -b` 通过。
- Python SDK：31 项通过，2 项跳过。
- Django：`manage.py check` 通过；`makemigrations --check --dry-run` 显示无模型变更遗漏。
- 依赖漏洞：`pnpm audit --prod` 未发现已知漏洞；按锁文件审计 Python 运行时依赖未发现已知漏洞。
- 密钥扫描：跟踪文件中未发现明显私钥、生产 token 或高置信硬编码凭据。
- i18n 消息字典：中英文 key 和 placeholder 完全对齐。

### 未通过或有警告

- 后端全量 pytest：909 项通过，2 项失败，1 项警告。
  - `tests/integration/auth/test_local_admin_login.py:531` 仍断言口令最短 8 位，而当前策略和 UI 已是 12 位，属于测试契约陈旧。
  - DingTalk Stream handler 用例在 Redis broker 不可用时失败；事件已落库而发布抛错，直接验证 BF-01 的可靠性缺陷。
- Ruff：23 项错误，主要为 import/order/line/complexity，当前 lint 门禁不绿。
- basedpyright：973 项错误，说明严格类型检查尚未形成可信门禁，不能把 `tsc` 或 Python 单测通过理解为跨层契约安全。
- `manage.py check --deploy`：6 项生产警告，详见 BS-01。
- Bandit：9 项 Medium 均集中在 `urlopen` 出站路径；其中 Webhook/manifest SSRF 已人工确认，不是单纯静态误报。
- Portal 动效测试存在未被 `act(...)` 收口的异步更新警告；测试可能存在偶发性和假阳性。

### 测试为何没有发现这些问题

现有测试对正常首屏和单请求路径覆盖较好，但主要缺少以下模型：

1. 服务端第二页、末页收缩、真实 pagination envelope 和 200 畸形响应。
2. deferred Promise、响应乱序、跨 `appKey` 导航、弹窗关闭后旧回调。
3. broker 在 DB commit 后失败、worker 丢失、重复事件、claim 竞争和周期补偿。
4. 生命周期跨时间、跨状态、重复/并发确认、第二个 App 失败回滚。
5. 目录合法空集、截断快照、generation 逆序和 Connector revoke 优先级。
6. 英文 locale 渲染、双语字段原样保存、Django 模板 locale。
7. 键盘焦点、隐藏元素 tabbability、reduced motion 和 timer 反向竞态。

---

## 九、建议修复顺序

### P0：阻断部署与外部网络边界

1. 立即修正 deploy：`DEBUG=0`、生产 WSGI、PostgreSQL、Secure Cookie/HSTS、真实 readiness。
2. 建立统一出站 HTTP transport：HTTPS allowlist、逐跳 SSRF 校验、禁跨源重定向、凭据剥离、响应大小和总 deadline。
3. 暂时禁止普通 App owner 写任意 Webhook/lifecycle URL，直到上述传输层保护完成。

### P0：修复认证与安全事件耐久性

1. 修复 TOTP 节流、绑定 step-up 和 session version，覆盖三者组合攻击测试。
2. 用 transactional outbox + dispatcher + scanner 替换所有裸 `on_commit(send_task)`。
3. 为 Connector、目录同步和 Webhook 引入 generation/claim/lease/CAS；撤权和 block 永远优先于扩权/解封。

### P1：修复授权和生命周期领域模型

1. 删除旧 Role schema；统一授权唯一写边界和“当前有效”判定。
2. 决定期限的真实粒度并迁移 schema，禁止最大期限/permanent 合并。
3. 重写 transfer confirm、onboarding、模板替换为原子、幂等状态机；持久化不可变快照与 saga 阶段。
4. 对 manifest、目录和 Connector payload 做严格运行时校验，契约错误在任何破坏性写入前快速失败。

### P1：修复前端 fail-closed 与跨层契约

1. 权威 GET 未成功前禁用全量写；工作台按 app key 隔离状态并丢弃旧响应。
2. 统一服务端分页和真实 response parser；修复 Console 深链壳路由。
3. 预览/测试/验证结果全部绑定内容或配置 hash；在途操作锁定不可逆对话框。
4. 审批前展示完整权限事实，明确 `grant_failed` 复合结果。
5. 所有可复制命令从 canonical 数据生成并做 shell/path 安全编码。

### P2：完成 i18n、动效和质量门禁

1. 先修双语字段数据丢失，再迁移硬编码文案、日期/复数/后端错误码。
2. 先修 Dialog 焦点、隐藏菜单、稳定 row ID 和 reduced motion，再补适量进入/退出过渡。
3. 把 Ruff、basedpyright、真实分页/竞态/故障注入测试纳入 CI；禁止条件分支静默跳过核心断言。

## 十、最终判断

EasyAuth 的正常路径已有较多单元与集成测试，认证、CSRF、凭据哈希和前端文本转义等基础做法总体正确。但当前实现仍把缓存、broker、外部 HTTP 和前端本地 state 当成可靠事实源，且多个破坏性流程在读取失败、并发或部分提交时 fail-open。按项目“尚未上线、无需保留错误形态”的硬约束，建议不要逐项添加兼容兜底；应优先统一领域不变量、事务 outbox、状态机、严格 API schema 和前端 fail-closed 交互，再补 i18n 与过渡动画。
