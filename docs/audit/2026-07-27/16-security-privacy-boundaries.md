# 安全、隐私与信任边界审计

## 1. 结论摘要

本次审计聚焦身份认证、管理员授权、机密配置、出站网络、浏览器敏感状态、个人信息保留、审计与运行状态暴露。共确认 12 项问题：

| 编号 | 严重度 | 置信度 | 问题 |
| --- | --- | --- | --- |
| SPB-01 | 严重 | 高 | 公网部署强制开启 `DEBUG`，并在当前部署状态使用公开固定密钥 |
| SPB-02 | 高 | 高 | 本地管理员会话版本在控制台鉴权入口被绕过 |
| SPB-03 | 高 | 高 | OIDC 管理员权限是登录时的组快照，撤组后不会及时失效 |
| SPB-04 | 高 | 高 | 公网部署挂载的 SQLite 数据库为 `0644`，数据与密钥边界未隔离 |
| SPB-05 | 中 | 高 | 自动接入描述符抓取仍可被 DNS 重绑定或重定向绕过 SSRF 校验 |
| SPB-06 | 中 | 高 | Pydantic 原始校验异常会把提交的 token 或 secret 回显给客户端 |
| SPB-07 | 中 | 高 | TOTP 种子与一次性凭据响应缺少禁止存储策略 |
| SPB-08 | 中 | 高 | 离职员工的联系方式与画像被无限期保留 |
| SPB-09 | 中 | 高 | Stream、Webhook 与审计原始数据没有自动保留期 |
| SPB-10 | 低 | 高 | 审批操作用 `403` 与 `404` 暴露申请编号是否存在 |
| SPB-11 | 低 | 高 | 匿名健康端点暴露内部组件与任务节奏 |
| SPB-12 | 低 | 高 | 权限查询 token 在前端 mutation 状态中继续存活 |

优先级应是：先停止公网 `DEBUG` 并轮换密钥；随后统一控制台身份校验，确保本地管理员会话版本和 OIDC 管理组撤销都能即时生效；再处理数据库权限、出站请求固定目标以及敏感响应。

## 2. 审计范围与方法

审计覆盖以下边界：

- 浏览器会话到 Django 控制台身份的认证与授权边界；
- EasyAuth 到 Authentik、下游应用、钉钉和 Webhook 目标的网络边界；
- 环境变量、数据库、容器日志和浏览器内存之间的机密边界；
- 员工目录、原始事件、Webhook 与审计数据的隐私保留边界；
- 匿名调用方到运行状态和审批资源存在性的可见性边界。

采用源码数据流追踪、配置检查、只读文件权限检查、虚构 token 的本地校验探针和现有测试执行。未发送真实网络请求，未读取或回显任何密钥值、员工字段或业务事件正文。

严重度含义：

- **严重**：当前公网部署直接破坏多个核心信任根，需立即停止暴露并轮换；
- **高**：可保留或获得管理员能力，或使敏感数据在既有部署边界内可直接读取；
- **中**：需要特定权限或前置条件，但可导致 SSRF、机密扩散或持续隐私暴露；
- **低**：暴露有限的资源存在性、拓扑或延长浏览器内机密生命周期。

## 3. 已确认问题

### SPB-01：公网部署强制开启 `DEBUG`，并在当前部署状态使用公开固定密钥

- **严重度**：严重
- **置信度**：高
- **位置**：
  - `docker-compose.deploy.yml:1-23`
  - `docker-compose.deploy.yml:29-36`
  - `docker-compose.deploy.yml:69-75`
  - `src/easyauth/config/settings/base.py:15-40`
  - `src/easyauth/config/settings/base.py:189-196`
  - `src/easyauth/config/settings/deploy.py:1-12`
  - `src/easyauth/config/crypto.py:31-38`

**证据与安全复现**

- 部署文件明确标注为 `iam.jiefakj.com` 公网反代部署，却强制设置 `DJANGO_DEBUG: "1"`，并使用 `runserver`。
- `required_env()` 在 `DEBUG` 下允许使用仓库中公开的固定 `SECRET_KEY` 和字段加密密钥。
- Secure session cookie、Secure CSRF cookie 和 HSTS 只在 `not DEBUG` 分支开启；`deploy.py` 没有重新启用这些设置。
- 当前未跟踪的 `.env.local` 不含 `DJANGO_SECRET_KEY` 和 `EASYAUTH_FIELD_ENCRYPTION_KEY`。只读 settings 探针得到：

```text
DEBUG=True
SESSION_COOKIE_SECURE=False
CSRF_COOKIE_SECURE=False
SECURE_HSTS_SECONDS=0
known_dev_secret_key=True
known_dev_field_key=True
```

探针只比较布尔值，没有输出环境文件中的任何值。

**受影响边界**

公网请求与 Django 异常处理、浏览器会话 cookie、数据库密文及 Django 签名信任根之间的边界。

**影响**

- 未捕获异常可能暴露 traceback、源码路径、局部变量和请求上下文。
- session 与 CSRF cookie 允许在非 TLS 请求中发送，应用也不发布 HSTS。
- 拿到数据库副本的人可以使用公开字段密钥派生 Fernet key，解密 TOTP 和集成凭据等加密字段。
- 固定 Django `SECRET_KEY` 破坏所有依赖该密钥的签名和会话信任。

**修复建议**

1. 删除公网 compose 中的 `DJANGO_DEBUG: "1"` 和 `runserver`，使用正式 WSGI 服务与静态资源服务。
2. 为公网 settings 增加启动断言：只要 `DEBUG=True`、密钥等于已知开发值或数据库仍是 SQLite，就立即拒绝启动。
3. 显式配置两把独立高熵密钥；轮换 Django 密钥并使全部现有会话失效。
4. 用旧字段密钥受控解密、再用新字段密钥重加密全部 `Encrypted*Field`，完成后销毁旧密钥。
5. 在最终反代响应上核验 Secure cookie、HSTS 和错误页，而不只检查本地 settings。

### SPB-02：本地管理员会话版本在控制台鉴权入口被绕过

- **严重度**：高
- **置信度**：高
- **位置**：
  - `src/easyauth/accounts/models.py:211-216`
  - `src/easyauth/accounts/local_admin.py:98-113`
  - `src/easyauth/accounts/local_admin.py:359-367`
  - `src/easyauth/admin_console/identity.py:16-47`
  - `src/easyauth/admin_console/authz.py:14-28`
  - `tests/integration/auth/test_local_admin_login.py:645-676`

**证据与推理**

- `session_version` 的模型注释明确要求改密、停用账号或变更第二因子后使其他已签发会话失效。
- 规范校验器 `current_local_admin()` 同时检查本地管理员专用会话标志、`local-admin:` subject、账号启用状态和会话版本。
- 控制台统一入口 `actor_from_request()` 没有调用该校验器。它遇到 `local-admin:` subject 时只检查账号当前是否启用，随后继续用会话中的组计算 `is_superuser`。
- 因此，改密或第二因子变更递增版本后，旧会话虽然不能再进入 `/auth/local/security/`，仍可通过 `require_superuser()` 访问控制台接口。
- 现有两条撤销测试均通过，但只请求 `/auth/local/security/`，没有请求 `/console/` 或任一控制台 API，因而没有覆盖实际绕过入口。

**受影响边界**

本地管理员凭据生命周期到控制台超级管理员权限的边界。

**影响**

被盗的旧管理员会话无法通过改密、重置第二因子或停用后再启用来可靠撤销，攻击者可以继续读取审计、修改集成设置、管理应用和签发凭据。

**修复建议**

- `actor_from_request()` 对本地管理员 subject 必须委托 `current_local_admin()`，不得复制一个弱化版本的身份判断。
- 版本或专用标志不匹配时清除完整认证会话并拒绝请求。
- 增加改密、启停 TOTP、增删 passkey、停用再启用后的旧会话访问 `/console/` 和高权限 API 的回归测试。

### SPB-03：OIDC 管理员权限是登录时的组快照，撤组后不会及时失效

- **严重度**：高
- **置信度**：高
- **位置**：
  - `src/easyauth/accounts/auth.py:149-185`
  - `src/easyauth/admin_console/identity.py:28-47`

**证据与推理**

- OIDC 登录时把 `claims.groups` 写入 Django session。
- 控制台每次请求会重新检查 `UserMirror.status`，但超级管理员判断只使用 session 中的旧组列表。
- 项目中未发现登录后的管理组重新查询、token refresh、管理会话版本、`set_expiry()` 或 OIDC back-channel logout 处理。
- 安全复现无需操作真实 Authentik：建立含 `EasyAuth Admins` 的 session 后，从上游移除同名组；只要本地用户仍为 active，`_is_console_superuser()` 的输入就没有变化。

**受影响边界**

Authentik 权威组成员关系到 EasyAuth 控制台超级管理员授权的边界。

**影响**

从管理组移除用户不能及时撤销 EasyAuth 管理权限。离职、临时运维授权结束或误加组纠正后，旧 session 仍保留高权限直到自然过期或主动登出。

**修复建议**

- 为控制台高权限建立可即时撤销的权威判定：每次高权限请求查询可信组状态，或使用短时管理令牌加服务端 session epoch。
- 接入 Authentik back-channel logout 或组变更事件，以失效相关本地会话。
- 权威组状态无法确认时，高权限接口必须失败关闭。
- 测试上游撤组、禁用和删除用户后的既有 session。

### SPB-04：公网部署挂载的 SQLite 数据库为 `0644`，数据与密钥边界未隔离

- **严重度**：高
- **置信度**：高
- **位置**：
  - `docker-compose.deploy.yml:15-18`
  - `docker-compose.deploy.yml:52-55`
  - `src/easyauth/accounts/models.py:31-59`
  - `src/easyauth/accounts/models.py:110-139`

**证据与安全复现**

部署把仓库根目录的 `db.sqlite3` 直接挂载为生产状态库。只读权限检查得到：

```text
-rw-r--r-- 644 /Users/konata/code/EasyAuth/db.sqlite3
```

数据库中包含员工姓名、邮箱、手机号、工号、组织关系，以及集成和认证相关密文。审计只统计表和非空记录，没有输出任何个人信息或密文。

**受影响边界**

运行服务账号、同机账号、备份或同步程序、源码工作区与生产身份数据之间的边界。

**影响**

同机可遍历该路径的账号和宽权限工具可复制完整数据库。与 SPB-01 的公开固定字段密钥组合后，数据库泄露不再只是密文泄露，还会直接暴露认证和集成凭据。

**修复建议**

- 立即将数据库设为 `0600`，并最小化父目录、备份目录和容器卷访问权限。
- 公网部署迁移到 PostgreSQL，以独立数据库角色、网络访问控制、加密备份和磁盘加密隔离数据。
- 密钥不得与数据库或源码工作区同边界保存。
- 扫描既有备份、压缩包和同步目标，确认数据库是否已被复制到更宽的权限域。

### SPB-05：自动接入描述符抓取仍可被 DNS 重绑定或重定向绕过 SSRF 校验

- **严重度**：中
- **置信度**：高
- **位置**：
  - `src/easyauth/admin_console/auto_onboarding_api.py:203-225`
  - `src/easyauth/config/net.py:65-81`
  - `src/easyauth/webhooks/transport.py:57-82`

**证据与安全复现**

- `_fetch_descriptor()` 先用 `socket.getaddrinfo()` 检查主机，再把原域名交给 `urlopen()`。
- `urlopen()` 建连时会再次解析 DNS，并默认跟随 HTTP 重定向；代码没有固定第一次校验得到的 IP，也没有逐跳重新校验 scheme、host 和 IP。
- 安全推理场景一：受控域名第一次解析为公网 IP，通过校验；建连时第二次解析为回环、内网或云元数据地址。
- 安全推理场景二：公网描述符端点返回 `302 Location: http://169.254.169.254/...`，默认重定向处理器在未重新调用 `assert_public_host()` 的情况下继续请求。
- 项目已有 Webhook 传输实现把校验所得 IP 固定到 socket，同时保留原域名做 TLS SNI 和证书校验，证明自动接入路径没有采用项目内已有的安全边界。

该端点要求控制台超级管理员操作，但描述符服务本身属于不可信外部边界，因此管理员输入一个合作方地址仍不应授予该服务访问内网的能力。

**受影响边界**

外部应用描述符服务到 EasyAuth 所在内网、宿主服务和云元数据地址的边界。

**影响**

恶意或被劫持的描述符服务可借 EasyAuth 发起内网请求、探测内部服务或读取无额外认证的元数据。若请求携带 `descriptor_token`，其在重定向中的具体转发行为还需单独验证，本报告不把该部分作为已证实影响。

**修复建议**

- 复用 Webhook 的固定 IP HTTPS 传输，不要继续直接调用 `urlopen()`。
- 禁止自动重定向；如业务必须支持，则逐跳限制为 HTTPS、重新解析和校验全部地址、固定实际连接 IP，并限制跳数。
- 保持原域名用于 `Host`、SNI 与证书校验，同时限制响应体、连接时间和总时限。
- 添加 DNS 两次返回不同地址及公网地址重定向到私网地址的无网络单元测试。

### SPB-06：Pydantic 原始校验异常会把提交的 token 或 secret 回显给客户端

- **严重度**：中
- **置信度**：高
- **位置**：
  - `src/easyauth/admin_console/settings_api.py:34-42`
  - `src/easyauth/admin_console/settings_api.py:84-93`
  - `src/easyauth/admin_console/auto_onboarding_api.py:58-64`
  - `src/easyauth/admin_console/auto_onboarding_api.py:106-114`
  - `src/easyauth/admin_console/notification_channel_api.py:259-278`

**证据与安全复现**

两个接口都用 `{"errors": str(exc)}` 返回 Pydantic `ValidationError`。使用只含虚构标记的超长 token 调用模型校验，Pydantic 2.13 的错误字符串包含 `input_value`，本地探针结果为：

```text
integration_token dummy_marker_reflected=True
descriptor_token dummy_marker_reflected=True
```

通知通道 API 已有安全实现：调用 `errors(include_input=False, include_context=False, include_url=False)`，说明可以复用现有模式。

**受影响边界**

管理员提交的 Authentik token、钉钉 secret、描述符 token 到浏览器响应、反向代理和错误遥测的边界。

**影响**

格式错误或过长的秘密会再次出现在响应体，扩大到浏览器开发工具、抓包、代理日志或前端错误采集。SPB-01 的 `DEBUG` 会进一步放大异常上下文风险。

**修复建议**

- 统一返回字段名与稳定错误码，调用 `errors(include_input=False, include_context=False, include_url=False)`。
- 对 secret 字段使用 `SecretStr`，并配置 `hide_input_in_errors=True`。
- 增加断言：错误响应不得包含提交 secret 的任意足够长子串。

### SPB-07：TOTP 种子与一次性凭据响应缺少禁止存储策略

- **严重度**：中
- **置信度**：高
- **位置**：
  - `src/easyauth/accounts/local_admin_views.py:216-239`
  - `src/easyauth/accounts/templates/accounts/local_admin/security.html:429-437`
  - `src/easyauth/admin_console/two_factor_api.py:66-88`
  - `src/easyauth/admin_console/credentials_api.py:92-102`
  - `src/easyauth/admin_console/credentials_api.py:119-131`
  - `src/easyauth/admin_console/credentials_api.py:150-162`
  - `src/easyauth/admin_console/credentials_api_payloads.py:52-62`
  - `src/easyauth/api/responses.py:20-29`

**证据与推理**

- 本地管理员安全页是 GET 响应，直接呈现 TOTP seed、二维码和 enrollment nonce。
- 控制台 API 返回 TOTP seed、`otpauth_uri`、二维码，以及只显示一次的静态 token 或 OAuth client secret。
- 这些路径使用普通 `render()` 或通用 `JsonResponse`，没有设置 `Cache-Control: no-store, private`；安全页也没有 `never_cache`。

**受影响边界**

服务端一次性秘密到浏览器历史、前进后退缓存、共享代理缓存和调试工具的边界。

**影响**

用户离开页面后，TOTP seed 或一次性凭据仍可能留在浏览器缓存与历史恢复状态中。POST 响应通常较少被共享缓存保存，但不应依赖缓存实现的默认行为保护认证机密。

**修复建议**

- 为含认证秘密的 HTML 和 JSON 建立统一响应辅助器，明确设置 `Cache-Control: no-store, private`，必要时补充 `Pragma: no-cache`。
- 安全设置页使用 Django `never_cache`。
- 浏览器测试验证成功和错误分支都包含禁止存储头，且后退导航不会恢复秘密。

### SPB-08：离职员工的联系方式与画像被无限期保留

- **严重度**：中
- **置信度**：高
- **位置**：
  - `src/easyauth/accounts/models.py:31-59`
  - `src/easyauth/accounts/models.py:76-82`
  - `src/easyauth/accounts/models.py:110-139`
  - `src/easyauth/integrations/authentik/directory_sync.py:534-555`

**证据与推理**

- `UserMirror` 保存姓名、邮箱、头像、部门、钉钉标识、工号和经理，并在实例删除入口明确禁止物理删除。
- `DingTalkUserMirror` 保存姓名、头像、职务、邮箱、手机号和工号；注释明确要求 tombstone 继续“保留身份与联系方式”。
- 离职同步只清空 `department_ids` 和 `manager_userid`，不会清空姓名、邮箱、手机号、头像、职务和工号。
- 未发现离职后按期限匿名化或转入受限归档的流程。

**受影响边界**

在职目录运营需要与离职后审计、法务留存及删除请求之间的隐私边界。

**影响**

离职人员的可识别画像在主业务表和备份中无限期存在，持续扩大数据库泄露和内部滥用的影响面。保留稳定身份以维持审计引用，不等于必须永久保留全部联系方式和画像。

**修复建议**

- 按数据用途明确最短保留期及法律保留例外。
- 业务闭环后把 tombstone 最小化为不可逆稳定标识、状态和离职时间，清空联系方式与画像。
- 如确需更长期留存，迁移到访问受限、独立审计的归档域，不在主业务镜像表永久保存。
- 同时设计备份过期与删除传播流程。

### SPB-09：Stream、Webhook 与审计原始数据没有自动保留期

- **严重度**：中
- **置信度**：高
- **位置**：
  - `src/easyauth/integrations/models.py:26-60`
  - `src/easyauth/webhooks/models.py:105-139`
  - `src/easyauth/audit/models.py:21-47`
  - `src/easyauth/audit/management/commands/prune_audit_logs.py:20-36`
  - `src/easyauth/config/settings/base.py:333-377`

**证据与推理**

- `DingTalkStreamEvent` 长期保存原始 `data`、处理 `result` 和 `error`。
- `WebhookDelivery` 长期保存完整 `payload`、目标 URL 和错误。
- `AuditLog` 保存 actor、target 和任意 JSON metadata；虽然提供了专用 purge 方法和手工命令，但命令强制要求人工传入 `--keep-days`。
- Celery beat 有连接器和通知清理任务，却没有 audit、Stream 或 Webhook 清理计划。全仓搜索也未发现后三类数据的自动清理入口。

**受影响边界**

重试和短期排障需要与长期业务内容、人员标识及错误上下文存储之间的边界。

**影响**

原始事件和投递载荷会持续形成新的 PII 与业务内容仓库；错误字段还可能包含外部响应。数据量和保留时间越长，数据库、备份和内部访问泄露的影响越大。

**修复建议**

- 分别定义 Stream、Webhook 和审计 metadata 的最短保留期，并加入定时、分批、可观测的 purge 任务。
- Stream 成功处理后只保留 event ID、类型、状态与内容哈希；删除原始 data 和 result。
- Webhook 仅在重试窗口内保留 payload，完成并超过窗口后清除正文。
- 审计 metadata 采用字段白名单和假名化；不能用任意外部错误正文作为长期审计内容。

### SPB-10：审批操作用 `403` 与 `404` 暴露申请编号是否存在

- **严重度**：低
- **置信度**：高
- **位置**：
  - `src/easyauth/portal/approvals_api.py:135-150`
  - `src/easyauth/access_requests/approvals.py:239-254`
  - `src/easyauth/access_requests/approvals.py:328-340`

**证据与安全复现**

服务层对不存在的 ID 返回 `not_found`，对存在但当前用户不是审批人的 ID 返回 `not_approver`；门户 API 分别映射为 `404` 和 `403`。任意已登录用户可对连续整数 ID 提交合法的非空审批决定，根据状态码判断申请是否存在。源码注释已承认统一返回 `404` 会泄露更少。

**受影响边界**

普通登录用户与不属于其待办范围的访问申请元数据之间的边界。

**影响**

攻击者可枚举申请活动和编号密度，为时间关联、内部人员活动推断和后续社会工程提供信号；无法仅凭该差异读取申请正文。

**修复建议**

门户边界将“不存在”和“不是审批人”统一为相同 `404` 错误码与文案；真实拒绝原因只写入服务端安全审计。

### SPB-11：匿名健康端点暴露内部组件与任务节奏

- **严重度**：低
- **置信度**：高
- **位置**：
  - `src/easyauth/config/urls.py:26-67`
  - `src/easyauth/config/urls.py:91-96`
  - `src/easyauth/config/urls.py:103-113`

**证据与安全复现**

`/health/` 无认证公开，响应包含 database、broker、beat worker、Stream 处理与 ACK、授权清理、目录同步等组件名，并返回每项的 `age_seconds` 和 `max_age_seconds`。匿名 GET 即可获得这些信息。

**受影响边界**

公网调用方与内部依赖拓扑、后台任务存活及调度时序之间的边界。

**影响**

外部调用方可判断 Redis、数据库、Stream、目录同步和清理任务的故障窗口及运行节奏，辅助选择攻击时机。该问题本身不提供管理能力。

**修复建议**

- 公网 liveness 只返回固定的整体状态，不返回组件名和时序。
- 详细 readiness 放在内网、独立管理端口或强认证之后。
- 反向代理仅允许监控来源访问详细端点。

### SPB-12：权限查询 token 在前端 mutation 状态中继续存活

- **严重度**：低
- **置信度**：高
- **位置**：
  - `frontend/src/pages/console/onboarding/AppOnboardingWizard.tsx:961-980`
  - `frontend/src/pages/console/onboarding/AppOnboardingWizard.tsx:987-992`
  - `frontend/src/pages/console/onboarding/AppOnboardingWizard.tsx:1027-1029`

**证据与推理**

- `testMutation.mutate()` 的 variables 对象包含明文 token。
- 成功回调只执行 `setToken("")`，没有 reset mutation；错误渲染随后还读取 `testMutation.variables`。
- 因而清空输入框只清除了 React 本地输入状态，TanStack mutation 状态仍保留原 token，直到 reset、卸载或下一次 mutation。

**受影响边界**

一次性验证输入与浏览器 JavaScript 堆、React 查询开发工具、错误采集及同源脚本之间的边界。

**影响**

token 的浏览器内存存活期被无必要延长。该问题不能单独绕过同源边界，但会扩大 XSS、浏览器扩展或调试信息泄露后的可见秘密范围。

**修复建议**

- 不把 secret 放入会长期保留 variables 的通用 mutation 状态；由短生命周期闭包发送请求。
- 成功和失败后都只复制非敏感结果，再立即 reset mutation 并清空输入。
- 测试提交完成后 mutation cache、组件状态和错误对象均不包含 token。

## 4. 未提升为已确认缺陷的边界

以下内容经过检查，但当前证据不足以列为独立已确认问题：

- Git 跟踪文件和相关历史的静态模式扫描未发现可确认的真实明文私钥或访问令牌；`.env.local` 已被 Git 与 Docker 构建上下文排除，当前权限为 `0600`。该结论不是凭据有效性或完整熵扫描。
- 没有发现可直接利用的前端 XSS sink；因此没有仅因缺少 CSP 就创建清单式问题。CSP 仍可作为纵深防御，但不能替代输出编码和依赖治理。
- 钉钉非认证错误响应体会被截断后写入 API 响应和审计，但未证实上游会回显提交的 secret，故未把“凭据已泄露”列为事实。
- 公网反代部署没有设置 `EASYAUTH_TRUSTED_PROXY_HOPS`。这会让限流按代理地址聚合，但实际可用性影响取决于未纳入仓库的 frpc 与前置代理拓扑，需要结合线上请求头再验证。
- 自动接入重定向时是否会把 `Authorization` 头转发给不同主机没有做真实网络验证；SPB-05 只依赖已确认的目标地址未重新校验与未固定 IP。

## 5. 验证记录

执行了以下只读验证：

- Django deploy settings 布尔探针：确认 `DEBUG`、cookie、HSTS 与是否命中已知开发密钥；
- 环境键存在性检查：只检查键名，不输出值；
- `stat` 权限检查：确认 `db.sqlite3` 为 `0644`；
- 两个虚构 token 的 Pydantic 校验探针：确认错误字符串包含输入标记；
- 现有本地管理员会话撤销测试：

```text
tests/integration/auth/test_local_admin_login.py::test_password_change_revokes_other_local_admin_sessions
tests/integration/auth/test_local_admin_login.py::test_reactivating_account_does_not_revive_sessions_from_before_deactivation
2 passed
```

这两条测试通过只能证明安全设置页使用了规范版本校验，不能证明控制台入口安全；SPB-02 正是两个鉴权入口不一致造成的缺陷。
