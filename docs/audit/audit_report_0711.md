# EasyAuth、Authentik 钉钉适配与下游权限链审计报告

- 审计日期：2026-07-11
- 审计方式：源码静态调用链、历史审计与修复提交复核、现有测试定向运行、跨仓库授权契约核对
- 基线：EasyAuth `759bc5c86002`、Authentik `7120fbede1df`、EasyTrade `9fdf9617ff66`、NetBird `a598d4cee8f0`、NetBird Dashboard `5ee857968fd7`
- 范围：Authentik 钉钉登录、白名单、目录同步与管理前端；EasyAuth 登录、申请、审批、授权、Connector、前端、Python SDK；EasyTrade、NetBird 与 NetBird Dashboard 的对应消费链
- 工作树说明：审计开始前，EasyAuth 已有 2 份未跟踪计划文档，Authentik 已有未跟踪的 `dingtalk-frontend-review.md`。本次未改动这些用户文件。
- 运行时边界：当前会话没有可用的内置浏览器实例，因此未对 `auth.jiefakj.com`、`iam.jiefakj.com` 做登录后页面操作；前端结论来自当前源码、测试与构建类型检查。

## 一、结论摘要

当前申请审批主状态机、期限复核、幂等提交、目录 generation 消费、离职 fencing、NetBird Dashboard 默认拒绝等既往高风险问题已有明确修复，本报告不重复列入。

当前仍有 8 组应优先处理的问题：

1. Authentik 钉钉多企业场景没有把 `corpId`、`unionId`、`userid` 和部门信息绑定为同一可信身份上下文，目录同步又接受任意 `corp_id`，可能形成跨企业白名单和组织权限事实污染。
2. Authentik 目录同步的 generation 只在发布时递增，没有 run fencing；旧任务可以在新任务之后发布并成为“更新的一代”。
3. Authentik 允许钉钉 source 使用通用 `EMAIL_LINK`，但钉钉 profile 邮箱没有已验证事实，存在错误链接既有高权限账号的风险。
4. EasyAuth 把 Authentik 管理组复制到 session 后长期信任；上游移除管理组不会撤销既有 EasyAuth 超管会话。
5. EasyAuth 前端把整个 Console 硬编码为仅 `EasyAuth Admins` 可用，与后端允许 app owner/developer 委派管理的权限模型冲突。
6. NetBird Connector 构建 desired state 时不检查授权组是否 active，也不检查成员期限；停用授权组后，EasyAuth 权限查询已经拒绝，但 VPN 权限仍会被 Connector 保留或恢复。
7. EasyAuth Python SDK 的 Bearer 客户端默认跟随重定向且无界读取响应，FastAPI 生命周期入口又在验签前无界读取匿名请求体，风险会扩散到每一个接入 SDK 的下游应用。
8. EasyAuth 授权组编辑仍会清空英文名称与描述；EasyAuth 的英文 UI、动效降级和可访问状态仍不完整。

上线判断：在处理 Authentik 企业上下文、目录同步乱序、EasyAuth 管理员降权、NetBird Connector 有效授权口径和 SDK 网络边界之前，不建议把现状视为权限链已达到生产安全基线。

### 严重度

- **High**：可导致账号错误绑定、跨企业权限事实污染、管理员降权不生效、已撤权限继续生效、凭据泄露或匿名拒绝服务。
- **Medium**：会破坏核心流程可靠性、造成短时授权滞留、错误写入或显著的国际化/可访问性缺陷。
- **Low**：局部一致性、语义或测试覆盖问题，不直接突破权限边界。

## 二、Authentik

### 2.1 后端

#### AK-BE-01　钉钉 source 未限制为 identifier matching，可用未验证邮箱链接既有账号

- **级别**：High
- **位置**：`authentik/sources/oauth/types/dingtalk.py:839-845`、`authentik/core/sources/matcher.py:82-138`、`authentik/sources/oauth/api/source.py:60-129`
- **问题**：钉钉 profile 的 email 被交给通用 source matcher，但适配器没有提供 `email_verified` 事实，也没有在 serializer 或运行时禁止 `EMAIL_LINK`。管理员一旦把钉钉 source 配为邮箱匹配，通用 matcher 会自动链接相同邮箱的既有账号。
- **触发与影响**：攻击者能够控制或碰撞 profile 邮箱时，可能把钉钉身份链接到已有高权限 Authentik 用户。
- **建议**：钉钉 source 在 API 校验和运行时都强制 `IDENTIFIER`；迁移并审计现有 source 配置和连接记录。

#### AK-BE-02　多企业登录与目录同步没有证明企业上下文一致

- **级别**：High
- **位置**：`authentik/sources/oauth/types/dingtalk.py:687-745`、`:208-221`、`authentik/sources/oauth/api/dingtalk_directory.py:181-194`、`authentik/sources/oauth/tasks.py:79-88`、`authentik/sources/oauth/dingtalk/client.py:42-134`、`authentik/sources/oauth/dingtalk/sync.py:111-135`
- **问题**：登录 token 的 `corpId` 与应用级 legacy API 按 `unionId` 查询出的 `userid/dept_id_list` 没有同企业校验，白名单却把两者合并后判断。手工同步 API 又接受任意 `corp_id`，而实际 legacy 目录请求没有携带该 corp 上下文，最终把返回数据强行写到请求提供的 corp 标签下。
- **触发与影响**：同一 unionId 多企业、管理员输入错误 corp，或应用 token 只代表另一企业时，可能把企业 A 的 userid/部门写入企业 B，造成白名单误放、误拒和 EasyAuth `MANAGED_USERS` 组织链污染。
- **建议**：只接受已由当前 source 明确授权并验证的 corp；外部请求必须使用企业范围明确的接口，并校验 `(corp_id, unionId, userid)` 一致。无法证明企业绑定时，部门准入和目录发布必须失败关闭。

#### AK-BE-03　目录 generation 没有运行代次栅栏，旧任务可覆盖新快照

- **级别**：High
- **位置**：`authentik/sources/oauth/dingtalk/sync.py:50-107,111-126,181-190`
- **问题**：任务开始只把共享 status 改为 `running`；发布时才锁行并 `generation += 1`，没有记录或校验本任务的 run ID/起始 generation。T2 后启动先成功后，T1 仍可最后发布旧数据并取得更高 generation；旧任务的异常也可覆盖新成功状态。
- **影响**：EasyAuth 的 generation fencing 无法识别“编号更高但内容更旧”的快照，离职或组织调整可能被旧任务复活。
- **建议**：任务启动时在行锁内分配 run ID/generation；成功和失败写入都使用 compare-and-swap，仅当前代任务可发布。最好同 source/corp 串行执行并增加乱序完成测试。

#### AK-BE-04　HTTP 错误可能把钉钉 app access token 持久化并回显

- **级别**：High
- **位置**：`authentik/sources/oauth/dingtalk/client.py:48-53,91-99,125-133`、`authentik/sources/oauth/dingtalk/sync.py:181-190`、`authentik/sources/oauth/api/dingtalk_directory.py:155-178`
- **问题**：legacy API 把 access token 放在 URL query；`raise_for_status()` 的异常字符串可能包含完整 URL。同步任务把 `str(exc)` 写入 `status.error`，状态 API 再原样返回。
- **影响**：token 可能进入数据库、备份、日志和管理员浏览器。
- **建议**：持久化前只保留错误类别、HTTP status 和钉钉稳定错误码；统一清洗 URL query/header。修复后轮换可能已暴露的 token。

#### AK-BE-05　身份标识仍存在 openId fallback 与全局 username 冲突

- **级别**：Medium
- **位置**：`authentik/sources/oauth/types/dingtalk.py:786-793,814-840`、`authentik/sources/oauth/dingtalk/managed_users.py:93-120,194-207`、`website/docs/customize/policies/types/expression/dingtalk_allowlist.md:187-190`
- **问题**：unionId 缺失时允许用 openId 建连接，但 managed-users resolver 只按 unionId 解析；username 又只使用 corp 内的 userid，不包含 corp。
- **影响**：降级登录会产生 resolver 永久 `unbound` 的身份；unionId 后续恢复时可能出现第二次 enroll/link。不同企业相同 userid 还会碰撞 Authentik 全局 username。
- **建议**：unionId 缺失时失败关闭；提供现存 fallback 连接审计/修复命令。username 使用 corp-qualified 或 union-derived 值，短 userid 只作为属性/claim。

#### AK-BE-06　常规 OAuth state 不是一次性且无时限，DingTalk 未启用 PKCE

- **级别**：Medium
- **位置**：`authentik/sources/oauth/types/dingtalk.py:617-623`、`authentik/sources/oauth/clients/oauth2.py:39-55`、`authentik/sources/oauth/types/registry.py:42`
- **问题**：常规登录只比较 session state，不原子消费、无 max age；DingTalk source 沿用 `PKCE=NONE`。相比之下 discovery state 已实现签名、600 秒和一次性消费。
- **影响**：state 泄露后扩大 login-CSRF 窗口；并发登录也只有单一 state 槽。nonce 不适用，因为该流程不消费 ID token。
- **建议**：callback 原子 pop state并校验发起时间；若钉钉支持，启用 S256 PKCE；补并发和重放测试。

#### AK-BE-07　共享 flow 中多个钉钉 source 的托管策略可能互相执行

- **级别**：Medium
- **位置**：`authentik/sources/oauth/types/dingtalk.py:307-427`
- **问题**：binding 搜索跨 source、认证/注册 flow 和 stage，只返回排序第一条；生成的 ExpressionPolicy 只判断 `provider_type=dingtalk`，没有固化并校验 source slug/pk。
- **影响**：两个钉钉 source 共享 flow 时，策略可能叠加为 AND 拒绝，或 guard 读取另一 source 的企业配置。
- **建议**：策略正文固化 source 标识，非本 source 立即跳过；guard 只寻找当前 source 的托管 policy，并增加共享 flow 双 source 测试。

#### AK-BE-08　目录权限只有 source 级，没有 corp 级边界；本人上下文接口又被前置权限拦截

- **级别**：Medium
- **位置**：`authentik/sources/oauth/api/dingtalk_directory.py:31-78,226-275`
- **问题**：一 source 多 corp 时，用户/部门 API 和 EasyAuth managed-users API 只能授 source/global model 权限，不能限定 corp。另一方面，“本人组织上下文”虽然有 own-context 分支，普通用户仍先被 `CanViewDingTalkDirectory` 拦截。
- **影响**：委派某一企业的目录运维权限会读到该 source 下全部企业；普通用户又无法使用设计上的本人查询能力。
- **建议**：增加 corp-scoped service credential/ACL，或明确禁止一个 source 承载多个委派租户；本人路径使用独立权限，路径身份匹配后才放行。

#### AK-BE-09　app token 缓存指纹不包含 secret，部分调用又绕过缓存

- **级别**：Medium
- **位置**：`authentik/sources/oauth/types/dingtalk.py:116-153,539-552`
- **问题**：缓存键只散列 consumer key，secret 原地轮换不会使旧 token cache 失效；org auth 又直接调用 `_fetch_dingtalk_app_token`，频繁 discovery 会绕过共享缓存并触发限流。
- **建议**：凭据指纹同时覆盖 key 和 secret 的不可逆摘要；统一走缓存，401/明确失效码再 force refresh。

### 2.2 前端

#### AK-FE-01　切换 source 时白名单脏模型未重置，可写入错误 source

- **级别**：High
- **位置**：`web/src/admin/sources/oauth/DingTalkAllowlistPanel.ts:300,528,895`
- **问题**：source A 有未保存修改时切到 B，组件只触发 refresh，不清理 `dirty/model/departmentInputs/loaded`；refresh 又因 dirty 拒绝用 B 的策略替换模型。保存时使用当前 B slug，却提交 A 的模型。
- **影响**：管理员可把 A 的企业/部门白名单覆盖到 B。
- **建议**：slug 变化时原子重置全部 source-scoped 状态并提示丢弃草稿；加载期间禁用写操作；保存捕获并校验开始时 slug。

#### AK-FE-02　目录面板切换 source 时旧行仍可操作，删除会落到新 source

- **级别**：High
- **位置**：`web/src/admin/sources/oauth/DingTalkDirectoryPanel.ts:264,276,383,548`
- **问题**：A→B 时 `statuses/loaded/manualCorpId/loadError` 不重置，B 请求完成前仍显示 A 的删除按钮；回调只保存 corpId，实际请求使用当前 B slug。
- **影响**：界面显示删除 A 记录，实际可能删除 B 下同 corpId 的目录缓存。
- **建议**：source 变化时立即停止轮询、清空状态并进入 loader；删除回调绑定并复核渲染时 source slug。

#### AK-FE-03　OAuth source 页面请求无代次保护，旧响应可覆盖新路由

- **级别**：Medium
- **位置**：`web/src/admin/sources/oauth/OAuthSourceViewPage.ts:83`
- **问题**：快速 A→B 会发起并发 retrieve，A 最后返回时仍无条件写入 `this.source`，错误时也继续保留旧 source。
- **影响**：URL、显示对象和编辑目标不一致，并放大 AK-FE-01/02。
- **建议**：使用 request generation 或取消机制，只接受当前 slug；新请求开始先清空旧对象，提供可重试错误态。

#### AK-FE-04　展示 label 被纳入准入版本，改名会迫使在线用户重新登录

- **级别**：Medium
- **位置**：`web/src/admin/sources/oauth/DingTalkAllowlistPolicy.ts:43-50,184-186,234`
- **问题**：`configVersion` 对包含 label 的整个 stored model 序列化；仅修改企业显示名也会使现有 session marker 版本失配。
- **建议**：配置回读保留 label，但授权版本只包含 `corp_id/allow_all/dept_ids` 等准入事实。

#### AK-FE-05　钉钉拒绝消息仍固化中文，未进入 i18n

- **级别**：Medium
- **位置**：`web/src/admin/sources/oauth/DingTalkAllowlistPolicy.ts:223,235,248,253,260,267`、`authentik/sources/oauth/views/callback.py:198,208,218,278`、`authentik/sources/oauth/types/dingtalk.py:327,344,353,366,368`
- **问题**：生成的运行时 policy 直接嵌入中文，后端又以中文作为 gettext msgid；非中文 locale 仍显示中文，XLIFF 无法覆盖 policy 自然语言。
- **建议**：运行时只返回稳定错误码，在 flow/UI 层翻译；后端使用英文 msgid + zh-Hans target。

#### AK-FE-06　目录输入和部门层级语义仍不完整

- **级别**：Low
- **位置**：`web/src/admin/sources/oauth/DingTalkDirectoryPanel.ts:515-529`、`web/src/admin/sources/oauth/DingTalkDepartmentPickerModal.ts:258-342`
- **问题**：Corp ID label 没有 `for/id` 或 `aria-label`，回车不能触发同步；部门层级只靠缩进，`role=grid` 也没有 grid 键盘模型。
- **建议**：Corp ID 使用 Authentik 表单组件或完整 label 契约；部门选择采用 PatternFly tree/tree table 语义，或移除不完整的 grid role。

### 2.3 i18n 与 Authentik 样式专项结论

- 5 个钉钉专属 TS 文件中的静态 UI `msg()` 均有显式 id；抽查的 134 个 id 均存在于 `zh-Hans.xlf`、target 非空且已生成 locale 文件。
- 当前明确 i18n 漏项是 AK-FE-05 的运行时 policy/后端中文正文，而不是静态管理界面消息字典。
- 当前钉钉管理 UI 使用 `AKElement`、`AKModal`、`ak-spinner-button`、`ak-alert`、`ak-status-label`、`ak-empty-state`、`ak-forms-confirm`、`ak-timestamp` 及 PatternFly class/token；没有发现另一套自造视觉体系。
- 历史裸 checkbox、嵌套响应式表格、裸 JSON counters、非 `ak-timestamp` 时间等问题已修复，不再列入。

## 三、EasyAuth

### 3.1 后端与授权链

#### EA-BE-01　Authentik 管理组降权不会撤销既有 EasyAuth 超管会话

- **级别**：High
- **位置**：`src/easyauth/accounts/auth.py:175-180`、`src/easyauth/admin_console/identity.py:42-47`、`src/easyauth/admin_console/authz.py:14-27`
- **问题**：登录时把 Authentik groups 复制进 session；后续每次鉴权只读取旧 session groups。上游把用户移出 `EASYAUTH_CONSOLE_SUPERUSER_GROUPS`、但用户仍 active 时，旧会话继续被视为 superuser。
- **影响**：被降权人员可继续管理应用、成员、审批代审、生命周期和 Connector，直到会话自然结束或主动登出。
- **建议**：引入上游 group/session revision 并在组变更时撤销，或使用短 TTL re-auth/introspection/back-channel logout；高危操作增加 step-up。

#### EA-BE-02　Authentik directory client 仍无响应上限和整轮 deadline

- **级别**：High
- **位置**：`src/easyauth/integrations/authentik/directory_client.py:141-209`、`src/easyauth/tasks/authentik.py:57-67`、`src/easyauth/config/settings/base.py:335-339`
- **问题**：目录分页和 org 响应使用全量 `response.read()`；只有单请求 timeout，没有总字节、总对象、整轮 deadline 或 Celery hard/soft time limit。
- **影响**：上游超大/慢滴响应可使 worker OOM 或长时间占用，离职撤权与组织同步延迟，周期任务还可能重叠。
- **建议**：复用 admin client 的有界读取；限制页数、对象数、总字节和单调总 deadline，并配置 Celery time limit。
- **历史复核**：0710 报告把 BS-05/BF-25 标为已修复，但当前 `directory_client` 不满足该结论，因此本项按当前代码保留。

#### EA-BE-03　审批详情轮询与创建审批共用创建限流桶

- **级别**：Medium
- **位置**：`src/easyauth/api/approval_views.py:83-108,147-181`、`sdk/python/src/easyauth_app_sdk/client.py:60-63`
- **问题**：GET detail 和 POST create 都通过 `_authenticated_app` 无条件递增 `approval-create-rate`。SDK 又把 detail 轮询作为 webhook 之外的兜底。
- **影响**：同一 credential 轮询多个实例达到 60 次/分钟后，新审批创建被 429 阻断。
- **建议**：认证与操作限流分离；POST 使用 create bucket，GET 使用独立 query bucket；429 返回 `Retry-After`，SDK 做退避。

#### EA-BE-04　NetBird Connector 未复用有效授权谓词，停用组后 VPN 权限仍持续

- **级别**：High
- **位置**：`src/easyauth/connectors/services.py:44-87`、`src/easyauth/grants/query.py:193-206`、`src/easyauth/connectors/netbird/connector.py:233-293`、`src/easyauth/admin_console/authorization_groups_api.py:233-257,314-329`
- **问题**：`build_desired_state()` 只看 grant/current/user active，不检查 `authorization_group.is_active`，也不检查 `AccessGrantGroup.expires_at`。权威权限查询却会同时过滤组 active 和成员期限。
- **触发与影响**：停用 VPN 授权组后，EasyAuth query 已拒绝权限，但 Connector 每轮仍把成员放进 desired 并保留/恢复 NetBird group、解除 block，形成永久口径分裂。限时授权到期则通常等待约 60 秒 cleanup；beat 故障会继续延长。
- **建议**：抽取并复用单一 effective-membership predicate；desired state 自身按当前时间、group active、grant/current/user active 全部过滤，不能把安全正确性托给异步清理。

#### EA-BE-05　NetBird 列表响应对畸形元素 fail-open

- **级别**：Medium
- **位置**：`src/easyauth/connectors/netbird/client.py:90-95,149-154,240-264`、`src/easyauth/connectors/netbird/connector.py:137-176,338-375`
- **问题**：非 object 行被静默丢弃；缺失/错型 id、role、`is_blocked`、`auto_groups` 又被降成空串、false 或空集。reconcile 随后把该不完整状态当成功快照并执行写操作。
- **影响**：NetBird API 漂移或部分畸形 200 可使撤权用户“消失”而未被移组/block，同时本轮继续扩权其他用户。
- **建议**：任何关键字段、重复 ID 或未知 role 契约错误都应在首个写调用前使整轮失败。

#### EA-BE-06　Connector `auto_create` 是死配置，却可能对账成功

- **级别**：Medium
- **位置**：`src/easyauth/connectors/services.py:80-87`、`src/easyauth/connectors/base.py:47-54`、`src/easyauth/connectors/netbird/client.py:149-161`、`src/easyauth/connectors/netbird/connector.py:124-197`
- **问题**：desired state 产出 `auto_create_group_refs`，client 也实现 `create_group`，但 reconcile 从不消费它；缺失组只计入 `groups_missing`，最终仍可返回 success。
- **影响**：审批已通过但 VPN 组未创建、权限未落地，控制台呈现假成功。
- **建议**：若 external ref 是不可变 group ID，应删除 auto-create 能力并对缺组 hard fail；若必须自动创建，应以名称创建后原子回写新 ID，并处理并发和同名冲突。

### 3.2 Python SDK

#### EA-SDK-01　Bearer 客户端默认跟随重定向并无界读取响应

- **级别**：High
- **位置**：`sdk/python/src/easyauth_app_sdk/client.py:65-95`
- **问题**：urllib 默认 redirect handler 可能把 `Authorization: Bearer` 带到跨 origin 30x；成功体全量读取，HTTPError 也是先全量读取再截 500 字符。
- **影响**：下游 app token/OAuth token 可能泄露，或下游 worker 被慢滴/超大响应耗尽。
- **建议**：带凭据请求默认禁重定向；确需跟随只允许同 scheme/host/port。强制生产 HTTPS，并实现 Content-Length、N+1 分块上限和 total deadline。

#### EA-SDK-02　FastAPI 生命周期入口在验签前无界读取匿名请求体

- **级别**：High
- **位置**：`sdk/python/src/easyauth_app_sdk/fastapi.py:75-84`、`sdk/python/src/easyauth_app_sdk/lifecycle.py:58-61`
- **问题**：`await request.body()` 先完整缓冲，之后才验签。
- **影响**：任何匿名客户端都可向默认 handover 路径发送超大/chunked body，造成每个接入 SDK 的下游进程内存耗尽。
- **建议**：SDK 提供小且安全的 `max_body_bytes` 默认值；先验 Content-Length，再流式读取并在超限时返回 413；代理层再做第二道限制。

#### EA-SDK-03　manifest 校验器弱于服务端权威契约

- **级别**：Medium
- **位置**：`sdk/python/src/easyauth_app_sdk/manifest.py:35-132`、`src/easyauth/applications/permission_template_parsing.py:27-134,190-308`
- **问题**：SDK 对 permission groups、authorization groups、approval rules 基本只检查 list，对重复 key、未知引用、重复 grant/target、非法 kind/risk/signing 和未知字段等不做服务端同等校验。
- **影响**：下游 CI/启动得到“合法”结果，自动接入时才被 EasyAuth 422 拒绝。
- **建议**：发布并共享同一 JSON Schema/生成模型；至少增加唯一性、交叉引用、extra-forbid 和双向合同 fixture。

### 3.3 前端

#### EA-FE-01　合法 app owner/developer 被全局 Console 门禁拦截

- **级别**：High
- **位置**：`frontend/src/App.tsx:41-48,69-71`、`src/easyauth/admin_console/views.py:20-51`、`src/easyauth/applications/ownership.py:18-36`
- **问题**：前端只认展示字符串 `currentUser.role === "EasyAuth Admins"`，否则立即跳 forbidden；后端却明确允许 developer 查看、owner 管理自己的 App。
- **影响**：合法委派的应用管理、目录、凭据和配置 UI 全部不可用；后端能力只能绕过前端直接调用 API。
- **建议**：shell 下发权威 `is_superuser/capabilities`；按 route/action 能力展示，不使用本地化展示 role 作为门禁事实。

#### EA-FE-02　权限申请提交中仍可编辑，旧成功响应会清空新草稿

- **级别**：Medium
- **位置**：`frontend/src/pages/portal/hooks/useAccessRequestForm.ts:252-280`、`frontend/src/pages/portal/components/AccessRequestForm.tsx:14-47`
- **问题**：mutation 捕获旧 payload，成功后不校验草稿版本便清空目标和理由；提交中只禁提交按钮，没有冻结 picker/fields。
- **复现**：提交 A，响应未到时改选 B 并填写新理由；A 成功后 B 的选择和理由被清空，而 app/期限仍残留，形成半旧半新状态。
- **建议**：提交期间冻结全部输入和导航，或给 draft 加 revision，onSuccess 只在 revision 未变化时 reset。

#### EA-FE-03　编辑授权组仍会永久清空英文名称与描述

- **级别**：High
- **位置**：`frontend/src/pages/console/workspace/matrix/grantDraft.ts:24-31,56-65`、`src/easyauth/admin_console/authorization_groups_api.py:84-95,314-329`
- **问题**：payload 不含 `name_en/description_en`，后端把缺失解析为空并无条件覆盖。
- **影响**：对已有双语授权组做任意编辑都会破坏英文数据。
- **建议**：表单、draft、API schema 完整覆盖双语字段并做 round-trip 测试，或改为真正字段级 PATCH。

#### EA-FE-04　英文模式仍混入中文并使用固定中文格式器

- **级别**：Medium
- **位置**：`AccessRequestFields.tsx:43-117`、`RequestTargetPicker.tsx:54-82`、`Dialog.tsx:36,55`、`ManifestTab.tsx:433-437`、`UserSummary.tsx:21-45`、`frontend/src/lib/status.ts:149-163`、`frontend/src/i18n/noHardcodedChinese.test.ts:12-38`
- **问题**：多处可见文字绕过消息系统，目录对象直读 `.name`；日期固定 `zh-CN`，插值器无复数规则。守护测试只扫部分文件，恰好漏过这些组件。
- **建议**：全源扫描最小白名单；目录统一 locale-aware selector；I18nProvider 暴露日期/数字/ListFormat/PluralRules；API 使用稳定 code 而非中文正文。

#### EA-FE-05　隐藏菜单和权限树动画状态仍破坏键盘/读屏体验

- **级别**：High/Medium
- **位置**：`frontend/src/components/shell/UserSummary.tsx:52-64`、`frontend/src/styles/layout-shell.css:253-274`、`frontend/src/pages/portal/components/PermissionSelector.tsx:258-285,721-788`
- **问题**：关闭菜单只改 opacity/pointer-events，仍在 DOM 与 accessibility tree 中；权限树 entering/exiting timer 在快速反向操作时会留下永久状态或提前结束新动画，退出行仍可被读屏/Tab 访问。
- **建议**：关闭时卸载或使用 hidden/inert 并恢复焦点；权限树使用 per-key generation/presence 状态机，退出开始即移出可访问树。

#### EA-FE-06　`prefers-reduced-motion`、Toast 和状态实时语义不完整

- **级别**：Medium
- **位置**：`frontend/src/styles/index.css:188-197`、`layout-shell.css:167-183,253-274,323-333,416-430`、`Button.tsx:52-57`、`components/ui/Toast.tsx:53-81,136-159`
- **问题**：reduce 只关闭少量 shimmer，菜单、导航、spinner 和权限树 JS 延时仍存在；Toast 固定 4–6 秒且 hover/focus/页面隐藏不暂停；主要状态组件缺 `status/alert/live/busy` 语义。
- **建议**：统一 motion token，reduce 时同步取消视觉动画和 JS timer；Toast 支持暂停/关键错误持久；状态组件按用途补 live semantics。

### 3.4 EasyAuth i18n 与动画专项结论

- i18n 消息字典本身未发现 key 数量不对称；主要缺陷是双语目录数据破坏、硬编码正文、固定格式器和守护测试覆盖不足。
- Dialog 输入抢焦点、Portal 分页、审批事实 fail-closed、跨 app workspace 状态污染等 0710 问题已修复，不再重复。
- 动画不应先追求“更多”。应先修 hidden/inert、焦点恢复、稳定状态机和 reduced-motion，再为 Dialog/Toast/menu 增加短 presence 过渡；普通空状态无动画不算缺陷。

## 四、EasyTrade

### 4.1 后端

#### ET-BE-01　首次权限快照写缓存存在并发唯一键竞态

- **级别**：Medium
- **位置**：`backend/app/domain/authz/easyauth_client.py:194-206,242-275`、`backend/app/domain/authz/models.py:77-101`
- **问题**：缓存缺失时先查后 insert+flush；同一新用户的两个并发请求都可能看到空缓存、都请求 EasyAuth、都插入相同唯一键，其中一笔抛 `IntegrityError`。
- **影响**：首次登录、缓存被清后并发加载页面会随机 500；不是越权，但授权链可靠性不足。
- **建议**：使用 PostgreSQL upsert/advisory lock，或捕获唯一冲突后回滚并重读赢家；补真实并发测试。

#### ET-BE-02　紧急撤权存在最多约 300 秒缓存窗口

- **级别**：残余风险
- **位置**：`backend/app/domain/authz/request_context.py:52-61`、`backend/app/domain/authz/easyauth_client.py:227-239`、EasyAuth `src/easyauth/api/permission_query_auth.py:12-16`
- **问题**：有效快照到 `expires_at` 前不访问上游，默认 TTL 为 300 秒；没有 grant mutation webhook 主动失效 EasyTrade 缓存。
- **影响**：管理员紧急撤权后，已有缓存的用户最长约 5 分钟仍可能执行写操作；缓存到期/上游失败后会 fail closed，因此不是永久越权。
- **建议**：明确并接受“撤权 SLA≤5 分钟”，或接入授权变更事件主动删缓存；高风险写操作可要求更短 freshness。

### 4.2 前端

- EasyTrade 前端没有自建 EasyAuth 权限申请流程，本轮未发现新的申请/审批契约问题。
- 既有样品 capability 门禁问题已记录在当前 `FULLSTACK_BUG_REPORT`，本报告不重复。

## 五、NetBird 与 NetBird Dashboard

### 5.1 NetBird

- NetBird 服务端当前主要风险来自 EasyAuth Connector 的 desired-state 和 client 契约，已归入 EA-BE-04～06。
- 既往未授权 JIT 默认放行、offboard/reconcile 并发、外部 account ID 多 App 覆盖等问题已有 fork/config 与 generation/lease/fencing 修复，本报告不重复。

### 5.2 NetBird Dashboard

- Dashboard 不直接消费 EasyAuth；它使用 NetBird `/users/current` 权限。
- `PermissionsProvider.tsx:17-63` 会对缺失 module 补全 deny，当前默认拒绝正确。
- 本轮没有发现需要单列的 Dashboard 权限申请或授权问题。

## 六、验证与测试缺口

已完成：

- EasyAuth 前端：40 个测试文件、279 项通过。
- EasyAuth 后端/SDK定向：46 项通过、2 项跳过。
- Authentik 钉钉前端：4 个 Vitest 文件、85 项通过；`npm run lint:types` 通过。
- 历史报告与后续提交逐项去重，未把已修复问题重复纳入。

现有测试通过不覆盖本报告关键边界。建议优先补：

1. Authentik 双 source 快速切换、脏白名单跨 source 保存、旧目录行跨 source 删除。
2. Authentik 同 corp 两个同步任务乱序完成、旧 error 覆盖新 success。
3. 任意 corp 输入与真实 app corp 不一致、token query 清洗。
4. DingTalk source 拒绝 `EMAIL_LINK`、unionId 缺失失败关闭、共享 flow 双 source。
5. EasyAuth 上游移组后旧 session 立即失去 superuser。
6. 停用/过期授权组后 Connector desired state 与 permission query 完全一致。
7. NetBird 畸形 200 在任何写入前整轮失败；`auto_create` 契约测试。
8. SDK 跨 origin redirect、超大/慢滴响应、超大 unsigned lifecycle body。
9. app owner/developer Console 路由、申请提交中编辑、双语授权组 round-trip、reduced-motion/timer 竞态。
10. EasyTrade 首次缓存并发唯一键冲突与主动撤权失效。

## 七、历史审计去重说明

已读并复核：`docs/audit/audit_report_0705.md`、`docs/audit/audit_report_0710.md`、Authentik 未跟踪的 `dingtalk-frontend-review.md`，以及相关后续提交。

确认已修复、未进入正文的代表问题包括：

- EasyAuth Portal 服务端分页、Console 深链、跨 app 状态复用、配置读取失败后破坏性写入。
- AccessRequest 幂等键、审批时期限复核、grant 失败/过期终态、审批详情 fail-closed、申请人自审。
- durable outbox、生命周期/Connector generation 与 lease、离职 active-user fencing、NetBird account 唯一绑定。
- Authentik 合法空目录快照发布与 EasyAuth 严格 generation/计数消费。合法空集清理是当前明确契约，不按“空结果即 bug”重复报告。
- Authentik 部门树环保护、轮询恢复、discovery 关闭、per-corp UI 清理、PatternFly checkbox/switch、时间与 counters 展示。
- SDK token 常量时间比较、MANAGED_USERS snapshot digest、EasyTrade 旧开发提权路径、Dashboard 缺失模块默认拒绝。

其中 EasyAuth 0710 对 `directory_client` 响应上限的修复结论与当前代码不一致，已作为 EA-BE-02 明确保留；Authentik 历史 label 版本问题仍未修复，已作为 AK-FE-04 保留。

## 八、建议修复顺序

1. **P0**：AK-BE-01～04、EA-BE-01、EA-BE-04、EA-SDK-01～02。
2. **P1**：AK-FE-01～03、AK-BE-05～07、EA-BE-02、EA-FE-01、EA-FE-03、EA-BE-05～06。
3. **P2**：其余可靠性、i18n、动画、可访问性和 EasyTrade 缓存问题。

修复时应优先统一“权威事实”：企业身份上下文、有效授权谓词、管理员 session revision、Connector external identity 和 SDK 网络契约各保留一个实现，避免用额外兼容分支掩盖口径分裂。
