# 后端功能缺陷审计

审计日期：2026-07-27

## 1. 审计范围与结论

本次审计聚焦 Django 后端的认证、授权、权限边界、会话与令牌、公开 API、控制台 API、通知受理、分页过滤和外部依赖错误处理。审计方法包括静态调用链追踪、契约与测试对照、全量测试以及不写库的最小隔离复现。

结论：

- 已验证缺陷 8 项：严重 1 项、高 1 项、中 6 项。
- 风险项 4 项：其中 2 项涉及特权入口或第二因子边界。
- 全量测试通过，但现有测试未覆盖本报告中的关键撤权、会话版本、通行密钥节流、通知幂等字段全集和严格输入校验场景。
- 本次审计未修改源码或测试。

严重度口径：

- 严重：可保留或取得系统级超级管理员权限，直接突破既定撤权机制。
- 高：权限撤销不能及时生效，已签发会话继续保留全局管理权限。
- 中：业务契约、失败语义或安全控制明确失效，但利用条件或影响面低于系统级权限突破。

## 2. 已验证缺陷

### BF-01 本地超管会话版本在控制台鉴权入口被绕过

- 严重度：严重
- 置信度：高
- 证据：
  - `src/easyauth/accounts/models.py:214-217` 明确规定改密、停用账号或变更第二因子时递增 `session_version`，使其他会话失效。
  - `src/easyauth/accounts/local_admin.py:98-113` 的 `current_local_admin()` 正确校验专用会话标志、账号状态和会话版本。
  - `src/easyauth/accounts/local_admin.py:359-367` 的 `rotate_local_admin_session()` 会递增数据库版本并仅更新当前会话。
  - `src/easyauth/admin_console/identity.py:16-39` 的 `actor_from_request()` 对 `local-admin:` 身份只检查账号仍为 active 和 `UserMirror` 为 active，完全未调用 `current_local_admin()`，也未检查 `LOCAL_ADMIN_SESSION_FLAG` 或 `LOCAL_ADMIN_SESSION_VERSION_KEY`。
  - `src/easyauth/admin_console/request_guards.py:16-24` 表明控制台 API 统一依赖上述 `actor_from_request()`。
  - `tests/integration/auth/test_local_admin_login.py:902-916` 仅覆盖账号停用，未覆盖 `session_version` 不一致。
- 复现或失败场景：
  1. 本地超管在浏览器 A、B 登录，会话版本均为 1。
  2. 在浏览器 A 修改密码、停用 TOTP 或变更通行密钥，数据库版本变为 2。
  3. 浏览器 B 保留版本 1，继续请求任意控制台 API。
  4. 最小隔离复现中，在会话版本为 1、数据库版本设定为 2 的前提下，`actor_from_request()` 仍返回 `is_superuser=True`。
- 受影响行为：
  - 改密和第二因子变更承诺的“其他会话立即失效”对控制台 API 不成立。
  - 泄露或被盗的旧会话可继续以全局超级管理员身份操作。
  - 账号先停用后重新启用时，旧会话也可能重新恢复有效，因为它仍未经过版本校验。
- 根因：项目存在两套本地超管身份解析路径；安全页使用完整校验，控制台守卫重新实现了一个只校验 active 状态的弱化版本。
- 正本清源修复：
  - 将本地超管身份解析统一收敛到 `current_local_admin()` 或等价的唯一权威解析器。
  - `actor_from_request()` 遇到 `local-admin:` 时必须同时校验专用标志和版本；失败后清理全部认证相关会话键并返回 401。
  - 增加改密、TOTP 启停、通行密钥增删、停用后重新启用后的旧会话失效集成测试。
  - 不保留弱校验分支或旧会话兼容逻辑。

### BF-02 OIDC 管理员组撤销不会撤销既有控制台超级管理员会话

- 严重度：高
- 置信度：高
- 证据：
  - `src/easyauth/accounts/auth.py:149-185` 只在登录绑定时将 OIDC `groups` 写入 Django session。
  - `src/easyauth/admin_console/identity.py:42-47` 每次鉴权都仅以 session 中的组与 `EASYAUTH_CONSOLE_SUPERUSER_GROUPS` 求交集，决定 `is_superuser`。
  - `src/easyauth/admin_console/identity.py:16-39` 的请求期校验只重新确认本地 `UserMirror` 为 active，不重新确认上游组成员关系，也没有权限版本或撤权时间戳。
- 复现或失败场景：
  1. 用户以 `EasyAuth Admins` 组成员身份登录，组信息写入 session。
  2. 在 Authentik 中移除该用户的管理员组。
  3. 用户不重新登录，使用原 session 请求控制台。
  4. 本地 `UserMirror` 仍为 active，旧 session 组仍命中配置组，因此继续得到 `is_superuser=True`。
- 受影响行为：上游管理员撤权无法及时生效；既有会话可持续执行全局管理操作，直至会话主动退出、自然过期或被其他机制清理。
- 根因：把登录时声明快照当作长期授权事实，缺少服务端可撤销的授权版本、有限缓存期或上游登出事件。
- 正本清源修复：
  - 为控制台超级管理员资格建立服务端权威状态和单调权限版本，并将版本绑定到会话。
  - 通过 Authentik 回调、同步任务或短周期权威校验更新资格；组撤销时批量失效相应会话。
  - 若使用短缓存，缓存失效时必须重新取得权威结果，不得回退到旧 session 组。
  - 增加“登录后移出管理员组”的撤权集成测试。

### BF-03 通行密钥二次验证记录失败却不执行登录节流

- 严重度：中
- 置信度：高
- 证据：
  - `src/easyauth/accounts/local_admin.py:61-62` 定义 5 次、300 秒的失败限制；`src/easyauth/accounts/local_admin.py:178-190` 实现计数和限流判定。
  - `src/easyauth/accounts/local_admin_views.py:126-140` 的 TOTP 验证会在验证前调用 `login_is_throttled()`。
  - `src/easyauth/accounts/local_admin_views.py:143-172` 的通行密钥 begin 和 complete 均不检查节流；complete 失败时却在 164-166 行继续累加同一失败计数。
  - `docs/guides/local-admin-login.md:63-65` 明确承诺登录失败按用户名节流，且包含二次验证失败。
  - `tests/integration/auth/test_local_admin_login.py:354-367` 只覆盖密码失败后的节流。
- 复现或失败场景：
  1. 输入正确密码进入通行密钥验证阶段。
  2. 重复请求 `/auth/local/passkey/begin/` 并向 complete 提交无效凭据。
  3. 失败计数达到甚至超过 5 次后，begin 仍继续签发挑战，complete 仍继续进入验证。
- 受影响行为：文档和实现声明的统一登录节流对通行密钥路径无效，可造成无上限验证请求、审计噪声和资源消耗；安全控制在不同第二因子之间不一致。
- 根因：节流检查只嵌入 TOTP 视图，没有收敛为第二因子入口的共同前置条件。
- 正本清源修复：
  - 在密码、TOTP、通行密钥 begin 和 complete 前使用同一权威节流守卫。
  - 达到限制后停止签发挑战，并返回统一的 429 或明确限流响应。
  - 增加通行密钥达到阈值、窗口恢复及成功后重置的集成测试。

### BF-04 通知幂等哈希遗漏 `biz_tag`

- 严重度：中
- 置信度：高
- 证据：
  - `src/easyauth/notify/models.py:125-133` 分别持久化 `dedup_key`、`payload_hash` 和 `biz_tag`。
  - `src/easyauth/notify/services.py:213-236` 的 `compute_payload_hash()` 只包含模板、标题、内容、跳转信息和收件人，不接收也不包含 `biz_tag`。
  - `src/easyauth/notify/services.py:278-324` 已规范化 `biz_tag`，但计算哈希时未传入该字段。
  - `src/easyauth/notify/services.py:326-342` 在同一 `dedup_key` 命中且哈希相同时直接返回首次消息。
  - `docs/api/easyauth-public-api.md:559-560` 将 `dedup_key` 和 `biz_tag` 均定义为请求字段；`docs/api/easyauth-public-api.md:582-587` 规定同键但载荷不同必须返回 409。
  - `tests/unit/notify/test_accept_idempotency.py:77-120` 覆盖内容相同和不同；`tests/unit/notify/test_quota_and_idempotency_rejected.py:141-173` 覆盖 `deeplink_title`，未覆盖 `biz_tag`。
- 复现或失败场景：
  1. 第一次用 `dedup_key=event:1`、`biz_tag=A` 受理消息。
  2. 第二次保持其他字段完全相同，仅改为 `biz_tag=B`。
  3. 两次哈希相同，第二次被当作重复成功返回首次消息，而不是 409；后续按 `biz_tag=B` 查询也找不到调用方以为已受理的消息。
- 受影响行为：业务分类标签与调用方请求不一致，幂等冲突被错误吞掉，API 返回错误成功语义。
- 根因：规范化载荷和幂等身份字段没有统一的权威字段全集。
- 正本清源修复：
  - 将 `biz_tag` 纳入规范化载荷哈希。
  - 用一个不可遗漏的规范化请求值对象同时驱动校验、哈希和持久化。
  - 为每个请求字段增加“仅该字段变化必须冲突”的参数化测试。

### BF-05 通知 API 将错误 JSON 类型静默强制转换为字符串

- 严重度：中
- 置信度：高
- 证据：
  - `src/easyauth/api/notify_views.py:74-90` 将公开请求字段逐个交给 `_as_str()` 后传入业务服务。
  - `src/easyauth/api/notify_views.py:319-334` 只校验顶层 JSON 是对象。
  - `src/easyauth/api/notify_views.py:337-344` 将整数、浮点数和布尔值转换为字符串，将对象或数组转换为空串。
  - `docs/api/easyauth-public-api.md:551-560` 对请求字段给出了明确的字符串、枚举和长度契约；`docs/api/easyauth-public-api.md:587` 规定参数问题返回 422。
- 复现或失败场景：
  - 请求体中的 `"content": true` 被转换为字符串 `"True"`，可作为有效正文受理。
  - 数值型 `dedup_key` 或 `biz_tag` 被改写后参与业务处理。
  - 对象型可选字段被静默改为空串，使明显错误输入变成另一条合法请求。
- 受影响行为：调用方的 schema 错误不再快速失败；服务端可能持久化调用方没有实际发送的业务值，并返回 202/200。
- 根因：视图使用宽松的手写强制转换代替严格请求模型。
- 正本清源修复：
  - 使用严格请求模型校验所有字段类型、枚举、长度和未知字段，显式输入错误统一返回 422。
  - 删除 `_as_str()` 的数值、布尔值和复杂对象转换逻辑。
  - 增加布尔、数值、对象、数组及未知字段的契约测试。

### BF-06 多个列表 API 对无效过滤和分页参数静默默认或改写

- 严重度：中
- 置信度：高
- 证据：
  - `src/easyauth/api/directory_views.py:487-511` 将非整数、非正数静默改为默认值，并将超上限值截断。
  - `src/easyauth/api/directory_views.py:379-383` 将除 `true` 外的任意 `include_inactive` 值都当作 false。
  - `src/easyauth/api/approval_views.py:238-257` 不校验审批状态枚举，任意字符串直接进入数据库过滤。
  - `src/easyauth/api/approval_views.py:260-280` 同样静默默认或截断分页参数。
  - `src/easyauth/portal/pagination.py:44-52,79-94` 对门户分页使用相同的默认和截断策略。
  - `src/easyauth/admin_console/apps_api.py:482-491` 对未知 `status` 直接返回未过滤查询集，即 `status=typo` 会返回全部 App。
  - 作为反例，`src/easyauth/admin_console/operation_filters.py:219-254` 已能对无效整数、非正数和超限值抛出明确验证错误。
- 复现或失败场景：
  - `GET /api/v1/apps/{app_key}/directory/users?page=abc&page_size=-1` 返回第 1 页、每页 20 条的 200。
  - `GET /api/v1/apps/{app_key}/approval-instances?status=typo` 返回空列表 200。
  - `GET /console/api/v1/apps?status=typo` 返回全部 App 200。
  - `include_inactive=yes` 被当作 false，而不是报告参数错误。
- 受影响行为：拼写错误和非法输入被掩盖，调用方会把错误查询结果当成业务事实；同类接口之间错误语义不一致。
- 根因：将“参数未提供”和“参数已提供但非法”合并为同一默认路径。
- 正本清源修复：
  - 建立共享的严格查询 DTO；只有字段缺省时使用默认值，显式非法值一律返回 422，并在 details 中给出字段和值。
  - 状态和布尔过滤必须使用闭合集合。
  - 超上限分页值必须报错，不得静默截断。

### BF-07 连通性测试以 HTTP 200 表示失败，并可能回显上游错误正文

- 严重度：中
- 置信度：高
- 证据：
  - `src/easyauth/admin_console/settings_api.py:147-166` 捕获 `DingTalkApiError` 后返回 `{"ok": false}`，未设置错误 HTTP 状态，并直接把 `str(error)` 返回给前端。
  - `src/easyauth/admin_console/connectors_api.py:160-189` 捕获 `ConnectorError` 或收到失败探测后同样始终返回 200。
  - `src/easyauth/integrations/dingtalk/api_client.py:321-350` 对非 401/403 的 HTTP 错误会把最多 500 字符的上游响应体拼入异常消息。
  - `src/easyauth/admin_console/notification_channel_api.py:102-142` 的同类连通性测试在失败时正确返回 503 和稳定错误码，说明项目内部已有正确语义。
  - `docs/api/easyauth-console-api.md:186-195` 明确规定连通性失败不返回钉钉底层错误原文。
- 复现或失败场景：
  - 钉钉返回 HTTP 500 且正文为内部网关、追踪或诊断内容；全局钉钉测试返回 HTTP 200，并把正文嵌入 `message`。
  - 连接器探测抛出异常时，负载均衡、前端通用错误处理和监控均只看到 200。
- 受影响行为：失败被包装为传输层成功，自动化监控和调用方容易误判；上游内部错误正文可能泄露到控制台响应。
- 根因：不同连通性端点各自定义成功语义，缺少统一的依赖失败响应和错误净化边界。
- 正本清源修复：
  - 所有探测失败统一返回 503 `DEPENDENCY_UNAVAILABLE`，只有实际探测成功才返回 2xx。
  - 对外只返回稳定、已净化的中文错误信息；原始详情仅进入受控日志或审计元数据。
  - 统一三个连通性测试端点的响应契约和测试。

### BF-08 已停用用户的 OIDC 回调先返回登录成功，随后才被门户清退

- 严重度：中
- 置信度：高
- 证据：
  - `src/easyauth/accounts/auth.py:158-180` 对已存在 `UserMirror` 只更新资料，不检查其状态，并直接写入认证 session。
  - `src/easyauth/accounts/views.py:77-103` 把该绑定视为成功，OIDC callback 返回到目标页面的 302。
  - `src/easyauth/portal/views.py:16-27` 到达门户后才要求 `UserMirror.status=active`，否则删除 session 键并再次跳转登录。
- 复现或失败场景：
  1. EasyAuth 中用户镜像已为 disabled 或 departed，但 Authentik 仍允许该 subject 完成 OIDC。
  2. callback 成功绑定 session 并 302 到门户。
  3. 门户立即清理该 session 并跳回登录；再次登录会重复该流程。
- 受影响行为：认证回调错误报告成功并形成登录循环；客户端无法区分“本地账号已停用”和普通未登录状态。
- 根因：OIDC 身份验证和本地账户准入检查被拆到不同请求阶段，绑定函数没有维护“只有 active 用户才能建立会话”的不变量。
- 正本清源修复：
  - 在 `bind_oidc_session()` 内锁定用户后立即校验本地状态；非 active 时不写 session，并抛出专用授权错误。
  - callback 返回明确的 403 或产品定义的停用页面。
  - 若目录同步确认用户重新 active，应由目录权威流程显式恢复状态，不能由登录路径隐式改写。

## 3. 风险项

以下项目有明确攻击面或失效可能，但现有实现、文档或测试显示其可能是当前产品选择，或尚未完成可利用性复现，因此不列为已验证缺陷。

### BR-01 未绑定第二因子的本地超管可长期仅用密码进入控制台

- 风险级别：高
- 置信度：高
- 证据：
  - `src/easyauth/accounts/models.py:218-227` 的 TOTP 默认关闭，通行密钥也可能为空。
  - `src/easyauth/accounts/local_admin_views.py:96-115` 在账号没有第二因子时直接绑定超级管理员会话。
  - `docs/guides/local-admin-login.md:45-52` 明确记录“没有任何二次验证方式时直接进入 console”，因此当前行为是已知设计。
- 风险场景：初始化后若管理员一直不绑定第二因子，账号将长期退化为单因素全局超级管理员。
- 建议：密码验证后只建立受限的“待绑定”会话，只允许进入第二因子注册页；完成至少一种第二因子后才能建立控制台 actor。恢复流程应单独设计，不以永久单因素入口代替。

### BR-02 `/admin/` 形成独立于 EasyAuth 身份与二次验证的第二套特权平面

- 风险级别：高
- 置信度：高
- 证据：
  - `src/easyauth/config/settings/base.py:44-52` 启用 Django admin 和 auth。
  - `src/easyauth/config/urls.py:103-110` 对外注册 `/admin/`。
  - `src/easyauth/applications/admin.py:132-155,225-245` 注册应用、审批规则和凭据等关键模型管理入口。
- 风险场景：Django staff/superuser 使用独立密码会话进入 `/admin/`，绕开 EasyAuth 本地超管或 OIDC 的组权限、第二因子和会话版本撤权机制。
- 建议：生产环境移除 `/admin/`，或将其放到与控制台相同的权威身份、二次验证、会话撤权和审计边界中；不要长期维护平行特权凭据。

### BR-03 OIDC 外部响应缺少大小上限，部分畸形密钥错误可能逃逸为 500

- 风险级别：中
- 置信度：中
- 证据：
  - `src/easyauth/accounts/oidc_exchange.py:105-120` 使用无大小上限的 `response.read()`，且网络层只归一化 `HTTPError` 和 `URLError`。
  - `src/easyauth/accounts/oidc_exchange.py:151-194,262-268` 对 JWT/JWK 的 base64url 解码和 RSA 公钥构造未在本层统一包装所有解码或数值异常。
- 风险场景：异常或被劫持的 IdP/JWKS 返回超大正文导致内存压力，或返回畸形 RSA 参数导致 callback 产生未归一化 500。
- 建议：使用明确字节上限读取 token/JWKS 响应；对解码、JSON、密码学构造和超时错误做窄范围捕获，统一转换为 `OidcSessionError`；配置启动时验证超时为有限正数。

### BR-04 任意控制台登录用户可读取全部 App 的基础信息与 owner 标识

- 风险级别：中
- 置信度：高
- 证据：
  - `src/easyauth/admin_console/apps_api.py:412-423` 列表项包含名称、描述、状态、owner 用户标识和配置状态。
  - `src/easyauth/admin_console/apps_api.py:465-467` 明确忽略 actor，返回全部 App。
  - `tests/integration/admin_console/test_apps_api_ops1.py:62-93` 明确断言非成员和普通成员均可列出所有 App，因此属于当前已知行为。
- 风险场景：普通控制台用户可枚举不属于自己的应用、owner 身份和应用配置状态，为组织信息搜集和定向攻击提供素材。
- 建议：确认该目录是否确属公开产品需求；若不是，列表应按成员关系过滤，超级管理员才可看全局。不要以“详情接口另有权限”替代列表最小披露原则。

## 4. 测试与覆盖结论

执行命令：

```text
.venv/bin/pytest -q
```

结果：

```text
1291 passed, 1 skipped
```

另执行不写库的最小隔离验证：

- 构造本地超管旧会话版本为 1、权威账号版本为 2 的场景，`actor_from_request()` 仍返回 `is_superuser=True`。
- 使用仅 `biz_tag` 不同的两份通知请求事实计算幂等身份，哈希保持相同；`compute_payload_hash()` 的函数签名本身也不接受 `biz_tag`。
- `_as_str(True)` 的实际结果为字符串 `"True"`。

测试全绿说明既有断言与当前实现一致，不代表上述安全和契约不变量已经覆盖。建议优先为 BF-01、BF-02、BF-03 和 BF-04 添加回归测试，再修复实现；其余项目应以严格失败语义统一清理，避免继续扩散静默默认和错误成功响应。
