# 后端可靠性与性能审计

## 审计说明

- 审计日期：2026-07-27
- 审计范围：`src/easyauth` 后端代码、相关任务与部署配置。
- 审计方法：静态调用链检查，重点覆盖异常边界、任务恢复、资源生命周期、并发一致性、数据库查询、外部调用、缓存和无界操作。
- 限定：本报告没有进行生产数据规模压测；涉及规模放大的结论均给出了明确触发条件。未发现证据充分的问题不会作为结论列出。

## 结论摘要

本轮确认 26 项问题，其中严重 2 项、高 13 项、中 10 项、低 1 项。最优先处理的是 Webhook 投递永久悬空和离职禁号假成功；两者都会把必须完成的安全或交付动作留在不可自动恢复的状态。其次应处理 WebAuthn 并发计数、目录同步完整性、外部请求无界读取、数据库锁内网络调用，以及几个会随数据量线性或超线性恶化的查询路径。

## 发现明细

### REL-PERF-01 Webhook 非预期异常或 worker 丢失后会永久停留在 `pending`

- 严重性：严重
- 置信度：高
- 证据：`src/easyauth/tasks/webhooks.py:19-35` 只处理 `WebhookNotConfiguredError` 和 `WebhookDeliveryAttemptError`；`src/easyauth/webhooks/delivery.py:125-165` 在成功认领后仍有配置解析、JSON 编码、传输和数据库完成写入等未统一保护的步骤；`src/easyauth/webhooks/delivery.py:228-250` 只写入 45 秒租约；`src/easyauth/webhooks/delivery.py:253-296` 只有已归一化的投递失败才会清理认领并创建下一次 outbox 事件。
- 影响：非预期异常、硬超时或进程丢失会使任务被确认，但投递行继续为 `pending`；原 outbox 已发布，代码也没有过期租约扫描器，人工重投又只接受 `failed`，因此投递无法自动恢复。
- 触发或复现：在任务认领成功后让配置解密、请求构造、HTTP 实现或完成写入抛出非 `WebhookDeliveryAttemptError`；也可在 20 秒硬时限处终止 worker。
- 根因：租约只用于排除并发认领，没有与权威的恢复调度器配套；异常状态机只覆盖已知网络失败。
- 直接修复：增加扫描 `pending` 且租约过期行的权威 watchdog，并以 `delivery_id + generation` 创建幂等重调度事件；为 worker 丢失配置拒绝重投语义并验证 broker 可见性超时；任务边界统一处理 soft limit、数据库瞬时错误及未预期异常，持久化失败事实后再重试。

### REL-PERF-02 离职禁号失败被任务转换为成功，分页上限还会误判用户不存在

- 严重性：严重
- 置信度：高
- 证据：`src/easyauth/tasks/lifecycle.py:16-44` 虽为 `AuthentikAdminError` 配置自动重试，却捕获未配置和用户不存在错误、记录失败审计后直接返回成功结果；`src/easyauth/integrations/authentik/admin_client.py:119-152` 最多扫描 40 页、每页 500 人，未到真实末页时仍抛 `AuthentikAdminUserNotFoundError`；调度入口为 `src/easyauth/lifecycle/services.py:957-964`。
- 影响：外部账号和会话可能继续有效，但 Celery 将关键安全动作视为成功且不再重试；超过 20,000 个用户时，位于第 41 页之后的真实用户会稳定触发这一假成功。
- 触发或复现：未配置 Authentik 管理接口；或目录用户超过 20,000，离职用户不在前 40 页。
- 根因：任务返回值与安全动作是否完成脱钩；分页资源上限被错误映射为“用户不存在”。
- 直接修复：禁号未完成时持久化明确失败状态并重新抛出可重试或部署错误，禁止返回成功字符串；优先使用服务端 UID 精确查询，暂时保留分页时必须在未到真实末页处抛出分页上限错误，而不是用户不存在。

### REL-PERF-03 WebAuthn `sign_count` 的并发更新可丢失或回退

- 严重性：高
- 置信度：高
- 证据：`src/easyauth/accounts/local_admin.py:403-420` 先无锁读取 passkey 和旧 `sign_count`，完成验证后再无条件 `save()`。
- 影响：两个并发认证可基于同一旧计数同时通过；写入顺序反转时数据库计数还可能从较大值回退，削弱克隆和重放检测。
- 触发或复现：对同一 passkey 并发提交两个有效认证响应，两次请求都在任一次保存前读到相同旧值。
- 根因：读取、密码学验证和计数推进之间没有行锁或比较并交换条件。
- 直接修复：在短事务内锁定 passkey 行后使用最新计数验证并写入，或按“主键、旧计数、单调前移”执行原子条件更新；更新 0 行必须作为并发重放拒绝，同时保留 WebAuthn 对计数 0 的协议语义。

### REL-PERF-04 部分用户组织信息拉取失败仍会推进整代目录状态

- 严重性：高
- 置信度：高
- 证据：`src/easyauth/integrations/authentik/directory_sync.py:175-192` 捕获单个用户的全部 `AuthentikDirectoryError` 后继续，只有所有用户都失败才中止；`src/easyauth/integrations/authentik/directory_sync.py:371-393` 随后仍把 generation 写为成功；相同 generation 会在 `src/easyauth/integrations/authentik/directory_sync.py:326-341` 被跳过。
- 影响：失败用户的主管链、部门摘要和审批路由可长期保留旧值，但同步任务与健康事实显示成功；除非上游产生新 generation，否则同一代不会自动补齐。
- 触发或复现：让一轮 1,000 个用户中 999 个 `get_user_org` 失败、1 个成功。
- 根因：同步代次是全局完成事实，但实现将部分失败当作可提交的成功。
- 直接修复：任何必需组织上下文失败都应使对应 corp 的本代失败，且不得推进 generation；改用批量权威组织快照。若确需部分处理，必须建立可持久化的不完整状态和同 generation 定向重试，而不能写成功。

### REL-PERF-05 目录客户端无界读取响应，读取超时还会绕过自动重试

- 严重性：高
- 置信度：高
- 证据：`src/easyauth/integrations/authentik/directory_client.py:190-209` 直接执行无大小上限的 `response.read()`，只捕获 `HTTPError` 和 `URLError`；`src/easyauth/tasks/authentik.py:57-67` 只对 `AuthentikDirectoryError` 自动重试。
- 影响：超大响应可耗尽 Celery worker 内存；连接建立后的 `TimeoutError` 或 `OSError` 不会归一化为目录异常，从而跳过既有自动重试。
- 触发或复现：让目录接口返回超大或持续分块响应；或在响应头返回后暂停 body 读取直至 socket 超时。
- 根因：该客户端没有复用项目其他 HTTP 客户端已有的有界分块读取和完整传输异常边界。
- 直接修复：校验 `Content-Length`，按块读取并同时限制实际字节数和单调时钟总 deadline；将读取阶段的 `TimeoutError`、`OSError` 和 `URLError` 统一转换为 `AuthentikDirectoryUnavailableError`。

### REL-PERF-06 目录同步每轮全量执行逐用户远端 N+1，且可与下一轮重叠

- 严重性：高
- 置信度：高
- 证据：`src/easyauth/integrations/authentik/directory_sync.py:164-189` 全量物化用户后为每个用户串行调用一次 `get_user_org`；generation 比较直到全部网络请求结束后才在 `src/easyauth/integrations/authentik/directory_sync.py:108-120` 执行；任务未配置总时限，见 `src/easyauth/tasks/authentik.py:57-67`；默认每 300 秒调度，见 `src/easyauth/config/settings/base.py:343-346`。
- 影响：N 个用户至少产生 N 次额外 HTTP；即使 generation 未变化也会重复。单轮超过五分钟时下一轮可并发开始，造成 worker 堆积、上游压力放大及离职撤权延迟。
- 触发或复现：扩大目录用户数或让单次组织查询接近客户端超时，使总运行时间超过调度间隔。
- 根因：变化检测放在完整快照之后，组织上下文又没有批量接口或嵌入用户页；任务入口没有单实例租约。
- 直接修复：先获取轻量状态并比较 generation，只拉取变化 corp；让用户分页携带组织上下文或提供批量接口；任务入口增加有 TTL 的单实例租约和总 deadline，超大同步拆成有游标、有限批次、可恢复的工作单元。

### REL-PERF-07 Webhook URL 接受 Unicode 请求路径，但传输层不能编码且未归一化异常

- 严重性：高
- 置信度：高
- 证据：`src/easyauth/config/net.py:182-223` 原样保留 path 和 query；`src/easyauth/webhooks/transport.py:145-175` 将其传给 `http.client`，但只归一化 `TimeoutError`、`HTTPException` 和 `OSError`。
- 影响：合法保存的 IRI 路径会在 `putrequest()` 抛 `UnicodeEncodeError`。异步投递会进入 REL-PERF-01 的永久 `pending`，同步交接钩子也会绕过 `HookCallError` 状态记录。
- 触发或复现：配置 `https://example.com/回调` 或 `https://example.com/callback?q=中文` 后发起投递。
- 根因：URL 解析层没有将 IRI path/query 规范化为 RFC 3986 百分号编码，也没有拒绝非 ASCII request-target。
- 直接修复：在唯一 URL 解析层规范化 path/query，或明确拒绝非 ASCII；把请求构造阶段的编码错误统一包装为 `WebhookTransportError`，并补端到端测试。

### REL-PERF-08 交接预览在行锁事务内执行最长 30 秒外部 HTTP

- 严重性：高
- 置信度：高
- 证据：`src/easyauth/lifecycle/services.py:213-245` 在 `transaction.atomic()` 内先调用 `_locked_action()`，再同步调用钩子；`src/easyauth/lifecycle/services.py:967-978` 使用 `select_for_update()`；钩子总时限为 30 秒，见 `src/easyauth/webhooks/hooks.py:30-39`。
- 影响：慢端点会长期占用数据库连接和 action 行锁；并发预览、换接收人、跳过或执行请求在 Web worker 中排队，容易形成锁队列。
- 触发或复现：让 preview endpoint 黑洞 30 秒，同时并发操作同一个 action。
- 根因：为防旧响应覆盖，代码将数据库锁跨越了不受本系统控制的网络往返。
- 直接修复：短事务写入 preview claim/version/token 后释放锁；网络完成后用 token 与版本条件更新，旧响应以比较并交换失败结束，禁止跨网络持有数据库锁。

### REL-PERF-09 `direct_grants` 没有数量上限并叠加逐项查询和写入

- 严重性：高
- 置信度：高
- 证据：相邻集合都限制 20 项，而 `src/easyauth/portal/access_request_payloads.py:32-39` 的 `direct_grants` 无 `max_length`；`src/easyauth/access_requests/target_validation.py:49-59,110-126` 逐项校验并逐项执行 `AppScope.exists()`；`src/easyauth/access_requests/services.py:244-255` 逐项 `full_clean()` 和 `save()`。
- 影响：认证用户可用大量不同 permission/scope 组合制造巨大集合查询、数千次 ORM 查询、长事务和超大错误响应。
- 触发或复现：提交包含数千个不同 direct grant 的访问申请，尤其混合大量无效 scope。
- 根因：集合基数不变量只存在于部分 API 字段，领域服务也未设置上限；批量事实被按单行重复校验和落库。
- 直接修复：API 与领域服务统一设置明确上限；批量预取 permission、scope 和规则后做集合校验，校验成功后使用 `bulk_create`。

### REL-PERF-10 审批列表的每一行都会开启独立事务并获取写锁

- 严重性：高
- 置信度：高
- 证据：`src/easyauth/api/approval_views.py:192-227` 对分页后的每个实例调用 `recover_stale_submission()`；`src/easyauth/workflows/services.py:376-404` 每次都进入 `transaction.atomic()` 并 `select_for_update().get()`；该接口单页最多 100 条，见 `src/easyauth/api/approval_views.py:42-45`。
- 影响：普通 GET 一页可产生 100 个额外写锁事务，并与审批回调和状态更新竞争；高并发列表读取会放大数据库延迟。
- 触发或复现：请求包含 100 个审批实例的列表页，即使没有任何实例处于过期 submitting 状态。
- 根因：过期恢复逻辑被放在逐行序列化路径，且没有先筛选真正需要恢复的行。
- 直接修复：列表前用严格条件一次筛选并集合式恢复过期记录，或移至周期任务；GET 序列化应只读最终快照，不逐行锁定。

### REL-PERF-11 控制台 App 列表调用详情级 readiness，形成嵌套 N+1

- 严重性：高
- 置信度：高
- 证据：`src/easyauth/admin_console/apps_api.py:148-152,412-420` 对每个 App 分别查 owner 并调用 `configuration_readiness_for_app()`；后者在 `src/easyauth/applications/configuration.py:46-107,157-166,202-209,232-240` 分别查询 permission、group、credential、scope、policy 等事实，并在组和 grant 内继续查询。
- 影响：`page_size=100` 时可产生数百至上千条 SQL，列表延迟和数据库负载随 App 数以及每 App 配置量放大。
- 触发或复现：创建较多 App、requestable group 和 managed grant 后读取最大页。
- 根因：列表直接复用逐 App、逐关联读取的详情实现，没有批量预取或数据库聚合。
- 直接修复：用 `Prefetch`、`Exists`、`Count` 和条件聚合一次装载一页所需事实；让 readiness 接受预载映射，或按 `catalog_version`/配置版本缓存摘要。

### REL-PERF-12 授权组全集接口无分页，多层 N+1 还绕过已有预取

- 严重性：高
- 置信度：高
- 证据：`src/easyauth/admin_console/permission_catalog_data.py:97-101` 已预取 `grants__permission`，但 `src/easyauth/admin_console/permission_catalog_data.py:149-166` 序列化时重新查询每组 grants；`src/easyauth/admin_console/permission_catalog_data.py:180-220` 又为每个 grant 查询管理范围策略；入口 `src/easyauth/admin_console/authorization_groups_api.py:98-100` 没有分页。
- 影响：SQL 数量按 group 和 grant 多层增长，响应体也随整个授权组目录无界增长。
- 触发或复现：读取包含大量授权组和 grant 的任一 App 授权目录。
- 根因：序列化器没有消费 prefetched related manager 或 `to_attr`，policy 也按 grant 查询；接口契约要求一次返回全集。
- 直接修复：使用带稳定排序的 `Prefetch(..., to_attr=...)`；一次查询全部相关 policy 后构建映射；列表分页或设置硬上限，必要时按 `catalog_version` 缓存目录。

### REL-PERF-13 连接器健康快照被写入后又从统一结果中丢弃

- 严重性：高
- 置信度：高
- 证据：`src/easyauth/applications/dependency_health_checks.py:67-89` 每轮执行并保存 `_check_connectors()`；`src/easyauth/applications/dependency_health.py:7-26` 的 `CORE_DEPENDENCIES` 没有 `DEPENDENCY_CONNECTORS`；`src/easyauth/applications/dependency_health.py:65-81` 只按该不完整元组返回结果。
- 影响：统一健康 API 和运维页永远看不到连接器故障；任务实际写 6 条快照却返回 5 项结果，形成监控盲区。
- 触发或复现：让任一连接器检查为 warning/unhealthy 后读取依赖健康接口。
- 根因：检查生产者和读取端维护了两套不一致的依赖枚举。
- 直接修复：建立唯一依赖注册表，由检查、持久化、读取和模型约束共同引用；补连接器故障在 GET、立即检测和 Celery 返回数量中的不变量测试。

### REL-PERF-14 Authentik 状态响应缺字段时会被误报为健康

- 严重性：高
- 置信度：高
- 证据：`src/easyauth/integrations/authentik/directory_payloads.py:84-88` 在 `source_slug` 缺失或类型错误时回退到配置值，并把缺失或错误的 `sync` 解析为空元组；`src/easyauth/applications/dependency_health_checks.py:126-146` 解析成功后直接标为健康。
- 影响：上游返回空对象、schema 漂移或缺失同步事实时会出现假健康，掩盖目录与离职撤权链路失效。
- 触发或复现：让状态端点返回 HTTP 200 的 `{}` 或 `{"sync": null}`。
- 根因：健康检查使用了宽松业务解析器，必需字段缺失被静默默认。
- 直接修复：为健康契约使用严格解析器，要求正确 `source_slug`、`sync` 类型及必要 corp 状态；任何缺失或类型错误都转换为明确依赖不可用。

### REL-PERF-15 DNS 超时通过遗弃不可取消线程实现，可无界耗尽线程

- 严重性：高
- 置信度：高
- 证据：`src/easyauth/config/net.py:125-156` 每次带时限解析都新建 daemon 线程，调用方超时后只停止等待，无法终止线程内 `socket.getaddrinfo()`；Webhook 调用入口见 `src/easyauth/webhooks/transport.py:128-136`。
- 影响：DNS 或 NSS 持续卡住时，每次校验、投递和重试都会遗留线程及其栈内存，最终耗尽进程线程资源。
- 触发或复现：让 `getaddrinfo` 长时间不返回并持续发起 Webhook 投递或配置校验。
- 根因：用“每请求一个线程加 Queue 超时”模拟不可取消的 DNS deadline，且没有全局并发上限或背压。
- 直接修复：使用支持 deadline/cancel 的异步 DNS 或隔离解析进程；至少使用有界共享 resolver 池、有限队列和拒绝策略，禁止每请求创建不可回收线程。

### REL-PERF-16 DingTalk Stream 心跳线程遇一次缓存异常便永久退出

- 严重性：中
- 置信度：高
- 证据：`src/easyauth/integrations/management/commands/run_dingtalk_stream.py:30-48` 启动 daemon 心跳线程，循环没有异常处理；`src/easyauth/config/runtime_health.py:37-42` 的每轮操作是可能抛错的 `cache.set()`；`docker-compose.deploy.yml:165-174` 禁用了容器 healthcheck。
- 影响：Redis 短暂故障一次即可杀死心跳线程，但主 Stream 消费进程继续存活；缓存恢复后严格健康检查仍持续失败，容器也不会因主进程退出而自愈。
- 触发或复现：在运行期间短暂重启 Redis，使一次 `cache.set()` 抛异常。
- 根因：常驻辅助线程没有有限重试、监督或向主线程传播失败的策略。
- 直接修复：每轮捕获异常、记录并有限退避后继续；或把持续心跳失败提升到主线程使进程退出重启，同时显式监控心跳线程存活。

### REL-PERF-17 OIDC 登录响应无界读取且每次重新下载 JWKS

- 严重性：中
- 置信度：高
- 证据：`src/easyauth/accounts/oidc_exchange.py:105-120` 对 token 和 JWKS 响应直接 `response.read()`，且只捕获 `HTTPError`、`URLError`；`src/easyauth/accounts/oidc_exchange.py:123-167` 每次验证 ID token 都重新请求 JWKS；回调只捕获 `OidcSessionError`，见 `src/easyauth/accounts/views.py:77-99`。
- 影响：超大响应可耗尽 Django worker 内存；读取阶段 `TimeoutError` 或 `OSError` 会变为 500；正常登录也永久增加一次同步网络往返和 IdP 压力，并把每次登录绑定到 JWKS 端点瞬时可用性。
- 触发或复现：正常执行任意 OIDC 登录即可观察重复 JWKS 请求；让 token/JWKS 返回超大 body 或在 body 阶段超时可触发资源和 500 路径。
- 根因：同步 HTTP 读取没有大小上限和总 deadline，公钥也没有 issuer/JWKS URL 级缓存。
- 直接修复：为 token/JWKS 设置独立小型字节上限、分块读取和单调时钟 deadline，完整归一化传输异常；按 issuer/JWKS URL 缓存已验证密钥，`kid` 未命中时只强制刷新一次，并用 single-flight 防止缓存击穿。

### REL-PERF-18 健康状态查询扫描全部历史，历史表又没有保留策略

- 严重性：中
- 置信度：高
- 证据：`src/easyauth/applications/dependency_health.py:65-74` 为取得每类最新一行而实例化并遍历全部快照；`src/easyauth/applications/dependency_health_checks.py:78-89` 每轮追加 6 行后立即再次读取；默认每 300 秒运行，见 `src/easyauth/config/settings/base.py:347-351`；仓库没有该表的清理路径。
- 影响：每天约增加 1,728 行，查询耗时、对象分配和文本字段传输随运行时间线性增长，最终会反过来拖慢监控任务和运维页面。
- 触发或复现：持续运行服务并累积健康快照，比较 `latest_items()` 在不同表规模下的查询行数和内存。
- 根因：已有按 dependency 与时间排序的索引未用于数据库侧每组 top-1，且未定义历史保留期。
- 直接修复：用 `Subquery`、窗口函数或 PostgreSQL `DISTINCT ON` 只取每个依赖最新一行；增加明确保留期和有限批量清理，或拆为当前状态表与受限历史表。

### REL-PERF-19 过期授权清理一次物化并处理全部积压，没有批次或总时限

- 严重性：中
- 置信度：高
- 证据：`src/easyauth/tasks/grants.py:29-60` 查询全部到期 grant 并逐个处理，没有 limit、游标或任务时限；`src/easyauth/grants/services.py:132-138` 每个 grant 都进入事务；`src/easyauth/grants/expiration.py:77-122` 又执行多次删除、存在性查询、保存、审计和 outbox 操作。
- 影响：大量积压会形成长任务、大量对象物化和查询突发；默认每分钟调度时，前一轮未完成可与下一轮重叠并争用相同行。
- 触发或复现：一次制造大量同时到期的授权，等待周期任务运行。
- 根因：周期任务把全量 backlog 当作单个工作单元，缺少有界批处理和单实例协调。
- 直接修复：按稳定主键或到期时间游标处理固定批次，结合 `skip_locked` 或单实例租约避免重叠；每批完成后按剩余量重调度，并设置 soft/hard time limit。

### REL-PERF-20 多个同步列表接口一次物化全部数据或明确执行 N+1

- 严重性：中
- 置信度：高
- 证据：目录部门接口在 `src/easyauth/api/directory_views.py:268-302` 直接 `list(queryset)`；团队接口在 `src/easyauth/admin_console/teams_api.py:96-116` 加载全部 Team 与全部成员并嵌入单个响应；岗位模板接口在 `src/easyauth/admin_console/lifecycle_api.py:514-523` 加载全部模板，并由 `src/easyauth/admin_console/lifecycle_api.py:913-947` 为每个模板单独查询 items。
- 影响：数据库读取、进程内存、JSON 序列化和响应带宽随全集规模无界增长；模板接口还额外产生 N+1 查询。
- 触发或复现：不带 `parent_id` 读取大组织部门，或在团队、岗位模板数量和成员/模板项增长后读取列表。
- 根因：列表与详情数据形态没有分离，也没有统一分页契约。
- 直接修复：所有列表使用稳定游标或严格分页及最大页大小；列表项只给成员数/模板项数等摘要，详情再分页读取；模板项使用 `Prefetch(..., to_attr=...)`。

### REL-PERF-21 连接器外部组 GET 在请求 worker 内执行最长 30 秒全量远端读取

- 严重性：中
- 置信度：高
- 证据：`src/easyauth/admin_console/connectors_api.py:214-240` 在普通 GET 中同步调用 `connector.list_external_groups()` 并全量序列化；当前 NetBird 客户端总时限为 30 秒，见 `src/easyauth/connectors/netbird/client.py:19-23,172-190`。
- 影响：慢连接器可让单个页面请求占用 worker 30 秒；并发打开页面会耗尽 Web worker。大量外部组又会产生无界响应，每次访问还重复抓取。
- 触发或复现：让 NetBird API 变慢或返回大量组，并发请求外部组选择列表。
- 根因：远端目录获取被直接放入同步页面读取路径，没有本地快照、缓存或 single-flight。
- 直接修复：后台刷新带 `refreshed_at` 和状态的本地外部组快照，GET 只读本地分页数据，并提供显式异步刷新；最低限度也应加共享短缓存、single-flight 和数量上限。

### REL-PERF-22 通知对账把依赖故障标记为已对账

- 严重性：中
- 置信度：高
- 证据：`src/easyauth/notify/services.py:486-528` 对配置缺失和对账调用统一继续，并无条件执行 `_mark_task_reconciled()`；`src/easyauth/notify/services.py:572-582` 捕获请求错误或不可用错误后返回空结果。
- 影响：DingTalk 故障没有错误状态或重试事实，却更新 `last_reconciled_at`；任务会被排序推后，超出对账窗口后，已发送但状态未知的通知可永久不再核实。
- 触发或复现：让一次 provider 状态查询抛 `DingTalkRequestError` 或不可用异常。
- 根因：对账函数用空结果同时表示“成功且无更新”和“调用失败”，调用者无法区分却总标记成功。
- 直接修复：返回明确的成功、失败、无变化三态；只有成功查询后才标记已对账，失败必须持久化类型化错误并让任务重试或进入健康告警。

### REL-PERF-23 目录聚合审计使用非原子的缓存读改写，且尾桶可能永不落库

- 严重性：中
- 置信度：高
- 证据：`src/easyauth/api/directory_views.py:554-580` 先 `cache.get()`，在 Python 中递增后再 `cache.set()`，只在后续请求观察到小时切换时冲刷上一桶。
- 影响：并发请求会发生丢失更新；小时边界的多个请求可能重复冲刷；服务在某小时后不再收到请求时，最后一个桶永远不会形成审计记录。
- 触发或复现：同一 App、endpoint 和小时并发发起多个目录请求，或在某小时最后一次请求后停止访问。
- 根因：缓存被当作计数器使用，却采用非原子读改写并把落库完全依赖下一次业务请求。
- 直接修复：使用 Redis 原子 `INCR`、hash 或 Lua，以不可变时间桶为键并设置 TTL；由周期任务按幂等唯一键冲刷闭合桶，禁止把审计落库触发绑定到下一次请求。

### REL-PERF-24 非法分页参数被静默替换或截断

- 严重性：低
- 置信度：高
- 证据：`src/easyauth/api/approval_views.py:260-280` 和 `src/easyauth/api/directory_views.py:487-511` 都在解析失败或非正数时返回默认值，并把超限值静默截断。
- 影响：调用方收到 200 却不知道参数无效，可能重复消费第一页、遗漏数据或形成重试循环；也违反项目对静默默认值的硬约束。
- 触发或复现：请求 `page=abc`、`page=0`、负数或远超上限的 `page_size`。
- 根因：缺失参数与非法参数共用同一 fallback。
- 直接修复：仅参数缺失时采用默认值；格式错误、非正数和超上限都返回明确 422 及字段级详情，复用项目已有严格整数过滤器。

### REL-PERF-25 停用 App 仍可签发从生成起就不可用的静态 token

- 严重性：中
- 置信度：高
- 证据：认证路径在 `src/easyauth/applications/services.py:170-193` 明确拒绝停用 App；签发路径 `src/easyauth/applications/services.py:218-230` 没有检查 App 状态便生成明文并创建 credential。
- 影响：接口返回仅展示一次的 secret 并记录创建成功，但该 token 永远不能认证，形成误导性成功和无效凭据。
- 触发或复现：对 `is_active=False` 的 App 创建或轮换静态 token。
- 根因：签发和认证两条服务边界使用了不一致的 App 状态不变量。
- 直接修复：在签发事务内锁定并重新读取 App，停用时抛出明确领域错误，且不生成 secret、不创建凭据、不记录成功审计；创建和轮换共用同一校验。

### REL-PERF-26 管理范围预览把目录依赖故障吞并为客户端 400

- 严重性：中
- 置信度：高
- 证据：`src/easyauth/admin_console/managed_users_preview_api.py:169-184` 捕获 `AuthentikDirectoryError` 或发现 stale 后都调用 `_bad_request()`；`src/easyauth/admin_console/managed_users_preview_api.py:241-247` 固定返回 `VALIDATION_ERROR` 和 HTTP 400，且没有记录原始依赖异常。
- 影响：监控、网关和调用方把依赖不可用误判为请求错误，通常不会执行合理重试；诊断链也被丢失。
- 触发或复现：在管理范围预览期间让 Authentik directory 超时或返回 stale 快照。
- 根因：依赖失败与输入校验复用了同一响应辅助函数，异常边界没有保留故障类别。
- 直接修复：不可用返回明确 `DEPENDENCY_UNAVAILABLE` 和 503，stale 使用独立依赖或冲突语义；记录脱敏异常与依赖标识，并保留异常链。

## 修复优先级建议

1. 先修复 REL-PERF-01、02、03、04、05，恢复安全动作、任务恢复和认证并发不变量。
2. 随后处理 REL-PERF-06、07、08、13、14、15，消除会造成级联故障、假健康或资源耗尽的路径。
3. 再集中治理数据库与接口放大问题：REL-PERF-09、10、11、12、18、19、20、21。
4. 最后修复错误分类、缓存一致性和契约 fail-fast：REL-PERF-16、17、22、23、24、25、26。

每项修复都应补充针对触发条件的回归测试；涉及异步任务的测试必须同时验证数据库终态、重试或恢复事件以及外部动作是否真正完成，不能只断言任务返回值。
