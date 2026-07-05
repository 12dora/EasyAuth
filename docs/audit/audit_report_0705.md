# EasyAuth 全量代码审计报告

- 审计日期：2026-07-05
- 审计范围：后端 Django 服务（`src/easyauth/`，约 25.9k 行）、Python SDK（`sdk/python/`）、前端 React + TypeScript SPA（`frontend/src/`，约 15.2k 行）
- 审计方法：按子系统拆分为 7 个并行深审通道（后端 5 + 前端 2），每个通道同时排查**功能性**与**安全性**缺陷，逐条对照真实代码路径验证；报告作者对最高影响项做了二次人工复核（`file:line` 均已核对）。
- 报告口径：所有结论均以源码为准。标注 `【存疑】` 的项表示需要额外运行时事实或外部契约才能最终确认。

> 重要前置事实（影响多处严重级别评估）：
> 1. 本项目**尚未上线**（见 `AGENTS.md`：“项目尚未上线，默认不保留历史错误形态”）。因此涉及“存量数据迁移”的问题在真实生产环境暂无历史数据，但仍是代码缺陷。
> 2. **审批 → 授权的出站链路尚未接入**：仓库中没有任何位置写入 `AccessRequest.dingtalk_process_instance_id`，而回调靠该字段匹配请求（`inbound_callbacks.py:189-195`）。因此“自助审批”等审批链缺陷**当前处于潜伏状态**，一旦出站创建审批流的代码补齐即变为可直接利用。这一事实已在相关条目中标注。

---

## 一、结论摘要

整体评价：这是一套**工程纪律相当高**的代码库。核心认证/鉴权设计大体正确——静态 token 用 PBKDF2 存储与常量时间比较、OAuth 走唯一索引、查询 API 有跨应用 IDOR 防护、控制台每个写端点都有 owner/superuser 门禁且对象级作用域正确、CSRF 全局启用、密钥仅在创建时一次性返回、审计日志只追加、OIDC 做了签名/issuer/aud/nonce/state 校验、WebAuthn 挑战一次性且校验 origin/RP-ID、登录有节流。**未发现可当前直接利用的严重认证绕过**。

主要问题集中在两类：
- **授权模型层**：审批人由申请人自选且不排除本人、审批人为空时回调 fail-open（潜伏，但一旦出站链路接入即为 Critical）。
- **控制台前端数据可见性**：服务端分页被完全忽略，导致应用/运营/审计列表只显示前 20 行——管理员**无法看到或管理**第 20 行之后的任何数据（High，实际运营阻断）。

### 缺陷统计

| 象限 | Critical | High | Medium | Low | 小计 |
|---|---|---|---|---|---|
| 后端 · 安全性 | 1（潜伏） | 2 | 8 | 13 | 24 |
| 后端 · 功能性 | 0 | 0 | 4 | 9 | 13 |
| 前端 · 安全性 | 0 | 0 | 0 | 2 | 2 |
| 前端 · 功能性 | 0 | 1 | 6 | 9 | 16 |
| **合计** | **1** | **3** | **18** | **33** | **55** |

### 严重级别定义

- **Critical**：可导致权限提升、认证绕过或大规模数据/授权破坏，需最优先修复。
- **High**：可造成明显安全弱化或核心功能阻断。
- **Medium**：真实缺陷，有明确影响但触发条件受限或影响面可控。
- **Low**：加固项、健壮性、契约一致性或体验缺陷。

---

## 二、后端 · 安全性（24 项）

### BS-1　审批人可由申请人自选、且不排除申请人本人（自助审批）
- **级别**：Critical（当前潜伏，出站审批链路接入后即可直接利用）
- **位置**：`src/easyauth/access_requests/submission_validation.py:62-77`、`inbound_callbacks.py:165-170`
- **问题**：提交时 `approver_user_ids` 完全由申请人的门户 payload 提供，服务端**仅校验“是活跃用户”**，既不排除申请人本人，也不与目标的 `ApprovalRule.approver_userids` / 直属主管做绑定校验。回调侧 `_callback_approver_is_authorized` 又只按“是否在这份申请人自选列表里”判断。
- **影响 / 利用**：用户可将自己（或串通同事）设为唯一审批人，自审自批任意可申请的权限组 / 直接权限，包括 MANAGED_USERS 范围提权。`request_catalog` 虽计算了“正确的默认审批人”，但提交路径从不强制它。
- **证据**：
  ```python
  def validated_approver_user_ids(approver_user_ids):
      user_ids = _unique_non_empty_strings(approver_user_ids)
      # 只校验活跃用户，从不排除申请人，也不比对审批规则
  ```
- **修复**：① 提交时若 `input_data.user.authentik_user_id in user_ids` 直接拒绝；② 服务端将提交的审批人与目标的**权威审批集合**（MANAGED_USERS 取直属主管，其余取 `ApprovalRule.approver_userids`/应用 owner）求交，非子集即拒；③ 回调再断言 `approver_user_id != access_request.user.authentik_user_id`。
- 备注：可由申请人自选是设计，但是必须为不是自己；默认填入 authentik 获取的钉钉组织关系的领导

### BS-2　审批人列表为空时回调鉴权 fail-open
- **级别**：Medium（列表为空的请求可达时升为 High）
- **位置**：`src/easyauth/access_requests/inbound_callbacks.py:169-170`
- **问题**：`return not allowed or approver_user_id in allowed`——当 `approver_user_ids` 为空（模型默认空 `list`）时 `not allowed` 为真，**任何**能产出合法签名回调的审批人都被接受。门户提交强制非空，但模型默认值及任何非门户创建路径（admin/seed/迁移/未来代码）都可能产生空审批人请求。
- **影响 / 利用**：审批人身份这道最后防线在空列表时被完全绕过。
- **证据**：`allowed = [u for u in access_request.approver_user_ids if u]; return not allowed or approver_user_id in allowed`
- **修复**：fail-closed —— `return bool(allowed) and approver_user_id in allowed`，并把“无审批人的请求”视为需排查的硬错误。

### BS-3　目录出现未映射状态时，全公司离职回收被静默跳过
- **级别**：High
- **位置**：`src/easyauth/integrations/authentik/directory_sync.py:294-297, 328-334`；任务重试 `tasks/authentik.py:57-65`
- **问题**：`_reconcile_user_mirror_status` 在进入回收循环前，为**每个**用户构建 `status_by_key`，其中 `_directory_user_status` 对任何不在 5 项映射表内的状态串（如 `"suspended"`/`"frozen"`/`"resigned"`）抛 `ValueError`。该异常发生在回收循环之前，导致本轮**没有任何**离职用户被回收；且 `ValueError` 不在任务的 `autoretry_for`，任务直接失败不重试。前几个阶段（镜像 upsert/prune）已提交，看起来“干过活”，但安全关键的离职回收被整体跳过。
- **影响**：已离职/停用员工的授权无限期保留，直到有人发现任务失败并补映射——直接破坏目录同步的首要目的（及时回收访问）。
- **修复**：对未知状态做防御性处理（映射为安全默认如 `DISABLED`，或跳过该单个用户继续回收其余），并记录审计/健康告警；把 `ValueError` 纳入重试/告警路径。

### BS-4　目录响应截断/分页形态变化可导致大规模误撤授权
- **级别**：High
- **位置**：`directory_sync.py:289-325`、`directory_client.py:127-135, 180-186`
- **问题**：`_synced_corp_ids` 只防“完全空响应”。任何在响应中出现了 corp、但 `(corp_id, user_id)` 不在 `snapshot.users` 里的 `UserMirror` 都被当作 `DEPARTED` 并回收授权。`_iter_paginated` 只要某页缺少形如 `{"pagination":{"next":<int>}}` 的正整数 `next` 就停止翻页。一旦上游端点分页形态变化（`next` 变成 URL 字符串、过滤/部分结果等）而 corp 仍有代表用户，同步会静默截断，**截断点之后的每个在职用户都被离职并回收**。没有任何“数量骤降”下限保护。
- **影响**：上游一次良性 API 形态变更或部分响应，即可为大量在职用户回收访问。
- **修复**：批量离职前加完整性护栏——当某 corp 观测用户数相对上次已知值下降超过阈值时拒绝 prune/depart（改为可重试失败而非误撤），并校验分页确实抵达上游报告的总数。

### BS-5　Authentik 管理 API token 明文存储
- **级别**：Medium
- **位置**：`src/easyauth/applications/integration_settings.py:30-33`（消费于 `:74-78`、`directory_client.py:137-149`）
- **问题**：`IntegrationSettings.authentik_api_token` 是普通 `CharField`，明文落库，且被用作 `Authorization: Bearer` 调 Authentik **管理** API。任何库读取（备份、只读副本、他处 SQL 注入、admin 导出）都会泄露一个高权限凭据。
- **修复**：静态加密该字段（KMS 信封加密/加密字段）或改用密钥管理器仅存引用；至少在 admin 中改为只写并从序列化/日志中排除。

### BS-6　TOTP 共享密钥明文存储
- **级别**：Medium
- **位置**：`src/easyauth/accounts/models.py:173`
- **问题**：`totp_secret` 为普通 `CharField`，base32 种子明文落库（且注册时会回显）。库泄露/备份泄露/他处注入即可拿到所有管理员的 TOTP 种子，永久绕过第二因子。
- **修复**：静态加密（Fernet/KMS，仅在内存中解密用于校验）或存入密钥库。

### BS-7　TOTP 验证码可重放（无一次性消费）
- **级别**：Medium
- **位置**：`src/easyauth/accounts/local_admin.py:208-212`；模型缺“最近使用 timestep”字段（`models.py:173-174`）
- **问题**：`verify_totp_code` 接受窗口内任意码，从不记录已消费的 timestep。`valid_window=1` 下单个码约 90 秒有效，可在多会话/多标签页内反复提交，违反 RFC 6238 §5.2。
- **影响**：攻击者一旦获取一个有效码（钓鱼反代、肩窥、截图、并发标签泄露），可在窗口内重放满足第二因子（需已握有口令，故与口令泄露链式）。
- **修复**：按账户持久化“最近接受的 timestep”，拒绝 `<=` 已存值的码，仅成功时前移。

### BS-8　暴力破解节流依赖单进程 LocMemCache
- **级别**：Medium
- **位置**：`config/settings/base.py`（全仓未定义 `CACHES`）；消费于 `local_admin.py:153-169`
- **问题**：本地管理员登录、强制改密、TOTP 校验的唯一暴破防护是 `django.core.cache` 计数器；未配置 `CACHES` 时 Django 回落到**每进程独立**的 `LocMemCache`（尽管已有 Redis 供 Celery 使用）。多 worker/多实例部署下，有效上限变为 `N × 5`，重启即清零，严重削弱（worker 足够多时形同失效）5 次锁定。
- **修复**：为 `CACHES["default"]` 配置共享后端（Redis），或改用 DB/原子存储做节流。

### BS-9　`managed-users-preview` 越权枚举任意用户的汇报链
- **级别**：Medium
- **位置**：`src/easyauth/admin_console/managed_users_preview_api.py:47-63, 124-138, 155-162`
- **问题**：端点仅用 `can_view_app`（应用的任意 developer/owner 即可）门禁，但请求体里的目标 `user_id` **任意、与应用/调用者无任何关系**，却会解析并返回该用户钉钉主管链的下属集合。
- **影响 / 利用**：任意应用（owner 可自行开启 `dingtalk_manager_chain` 默认策略）的 developer/owner 可用任意 `user_id` 探测“谁向该人汇报”，形成组织架构 oracle。
- **修复**：改为要求 `can_manage_app`（owner），并将目标约束到应用授权实际可达的用户；每次预览记审计（actor + target）。

### BS-10　OIDC `sub` 命名空间可与 local-admin 主题前缀冲突【存疑】
- **级别**：Medium（取决于 IdP `sub` 是否可被攻击者控制）
- **位置**：`accounts/auth.py:142-166`（`bind_oidc_session` 原样存 `claims.subject`）、`local_admin.py:85-90`（凡以 `local-admin:` 开头的会话主题即视为该本地管理员）
- **问题**：OIDC `sub` 命名空间与合成的 `local-admin:<username>` 命名空间之间无隔离，`current_local_admin` 仅按字符串前缀匹配。若某次 OIDC 登录产出形如 `local-admin:<已存在用户名>` 的已验证 `sub`，该普通 OIDC 会话会被当作对应本地管理员（可给其注册 WebAuthn passkey 等）。Authentik `sub` 通常为不可控 UUID，故标存疑。
- **修复**：为本地管理员会话打专用不可伪造标志（`request.session["easyauth_local_admin"]=True`）并在 `current_local_admin` 强制校验；同时在 `bind_oidc_session` 拒绝以 `local-admin:` 开头的 OIDC 主题。

### BS-11　健康快照持久化未脱敏摘要（可能含 broker 凭据）
- **级别**：Medium（疑似真实泄露）
- **位置**：写入 `applications/dependency_health_checks.py:66-73, 177-183`；脱敏 `dependency_health.py:106-110, 26-47`
- **问题**：`summary`/`error_summary` 原始写入 `DependencyHealthSnapshot`，脱敏 `_safe_summary` 仅在展示时应用，且是朴素子串黑名单。Celery 检查构造 `error_summary=f"{type(error).__name__}: {error}"`，broker 连接错误可能内嵌 `redis://:password@host` 等凭据——既不含 `password` 字面子串（漏脱敏），又已明文入库。
- **修复**：在写入边界脱敏；用结构化脱敏（从任意 URL 剥离凭据），不要把原始异常/连接串直接插入摘要。

### BS-12　SDK 描述符共享 token 使用 `==` 比较（时序侧信道）
- **级别**：Medium
- **位置**：`sdk/python/src/easyauth_app_sdk/integration.py:44-45`
- **问题**：下游用固定 `required_token` 保护 `/.well-known/easyauth-app.json` 时，用 Python `==` 比对，短路泄露长度/前缀时序。该长期可复用共享密钥泄露后可读取该应用完整权限清单。
- **证据**：`authorized = authorization == f"{BEARER_PREFIX}{required_token}"`
- **修复**：`hmac.compare_digest(...)`。

### BS-13　停用 local admin 不失效其已建控制台会话【存疑】
- **级别**：Low
- **位置**：`admin_console/identity.py:15-39` vs `local_admin.py:85-90`
- **问题**：控制台鉴权 `actor_from_request` 从 `UserMirror`（`local-admin:<user>`，`status` 仍 `active`）+ 会话组解析，**从不查 `LocalAdminAccount.is_active`**。设 `is_active=False` 只挡新登录，已有浏览器会话在自然过期前仍持超管权限。
- **修复**：对 `local-admin:` 主题在 `actor_from_request` 校验后端 `LocalAdminAccount.is_active`（失效则清会话），或停用时 flush 会话。

### BS-14　2FA 变更缺少 step-up 重认证，且 disable 未限流
- **级别**：Low
- **位置**：`admin_console/two_factor_api.py:96-112, 124-170`；`local_admin_views.py:254-264, 299-308`
- **问题**：任意已登录本地管理员会话可注册/删除 passkey、禁用 TOTP，无需重输口令/第二因子；`totp_disable` 的验证码校验不受登录节流覆盖（可在会话内无限猜 disable 码）。CSRF 已启用可缓解会话外攻击。
- **修复**：注册/移除因子要求新鲜口令或现有 2FA 确认；对 disable/confirm 码校验套用节流。

### BS-15　本地管理员用户名可经响应时序枚举
- **级别**：Low
- **位置**：`accounts/local_admin_views.py:98-102`
- **问题**：`account is None or not is_active or not check_password(...)` 短路——账户不存在/停用时不跑昂贵的 PBKDF2，有效与无效用户名响应延迟可测（Django 原生 `authenticate()` 用 dummy hash 规避）。
- **修复**：账户缺失/停用时也跑一次常量时间 dummy hash。

### BS-16　本地管理员口令策略过弱
- **级别**：Low
- **位置**：`local_admin_views.py:63, 368-380`；`management/commands/create_local_admin.py`（完全无策略）
- **问题**：仅要求长度 ≥ 8 且与旧密码不同；无复杂度、无常见/泄露口令拒绝；`AUTH_PASSWORD_VALIDATORS` 未配置也未应用于本地管理员。
- **修复**：在改密视图与建号命令中调用 `validate_password`（CommonPassword、MinimumLength ≥ 12 等）。

### BS-17　WebAuthn 校验不要求 user verification
- **级别**：Low
- **位置**：`accounts/local_admin.py:259-262, 282-289, 306-313, 330-335`
- **问题**：`generate_*_options`/`verify_*_response` 未传 `require_user_verification=True`。作为口令后的第二因子可接受（证明持有），但 UV 可把仪式绑定到 PIN/生物特征。
- **修复**：如期望 UV 能力认证器，传 `require_user_verification=True` 并在 options 设 UV `required`。

### BS-18　DingTalk 回调 5 分钟窗口内无 nonce 防重放
- **级别**：Low（已很大程度缓解）
- **位置**：`integrations/dingtalk/signature.py:8, 25-32`
- **问题**：只要签名正确且时间戳在 ±5 分钟内即接受，无一次性 nonce 存储，窗口内可重放。因 approve/reject 按状态幂等，影响有限；仅在回调信道非 TLS 时有实质风险。
- **修复**：引入并持久化 per-callback nonce（或按 `(process_instance_id, signature)` 去重），并强制 TLS-only。

### BS-19　Authentik base_url 未强制 HTTPS，token 可能明文传输
- **级别**：Low
- **位置**：`integration_settings.py:74-78`、`directory_client.py:137-149`、`liveness.py:38-42`
- **问题**：`authentik_runtime_config` 只 `.rstrip("/")`，不校验协议。若配成 `http://`，管理 API token 以明文 `Authorization: Bearer` 头发送。
- **修复**：在 model `clean()` + 配置层校验必须为合法 `https://`，非 dev 拒绝明文 HTTP。

### BS-20　未认证即可放大审计写入（回调 / 失败登录 DoS）
- **级别**：Low
- **位置**：`integrations/dingtalk/callbacks.py:41-51, 55-59, 137-152`；`accounts/local_admin_views.py:100-102`
- **问题**：签名/载荷无效的回调在认证成功前就插入 `AuditLog`；每次失败登录（含不存在用户名）也写审计，节流按用户名，轮换用户名即可绕过。均无限流，未认证攻击者可膨胀审计表并淹没真实安全事件。
- **修复**：对回调端点限流（按 IP/全局）；对预认证拒绝与失败登录审计写入做限流/聚合/采样。

### BS-21　auto-onboarding 存在 SSRF（superuser 受控 URL，无内网防护）
- **级别**：Low
- **位置**：`admin_console/auto_onboarding_api.py:58-64, 195-244`
- **问题**：`_auto_onboard` 对 caller 提供的 `base_url` 仅校验以 `http://`/`https://` 开头，无 host/IP 白名单，允许明文 http 打内网，服务端 `urlopen(f"{base_url}{DESCRIPTOR_WELL_KNOWN_PATH}")`。受 superuser 门禁与固定后缀约束，故 Low。
- **修复**：强制 HTTPS-only，解析 host 并拒绝私网/环回/链路本地段，或域名白名单。

### BS-22　OAuth access token 明文存储（继承自 django-oauth-toolkit）
- **级别**：Low
- **位置**：`applications/oauth.py:115-127`；底层 `oauth2_provider` 的 `AccessToken.token = TextField()`
- **问题**：静态 token 路径存 PBKDF2 哈希，但 OAuth 路径依赖库默认的明文 token 列（`token_checksum` 只是 SHA-256 查找索引，非哈希替代）。只读库泄露即可拿到所有存活 OAuth token 直接当 bearer 用。
- **修复**：非本仓可独立修复——跟进上游；以短 access-token 生命周期、库静态加密、把 token 表当机密处理来缓解。

### BS-23　认证与查询端点无限流
- **级别**：Low
- **位置**：`api/authentication.py`、`api/views.py`（全仓无 throttle 配置）
- **问题**：bearer 认证与 `query_user_permissions` 无节流。token 256 位熵 + 廉价索引查询使暴破/CPU-DoS 风险不高，但缺乏纵深防御。
- **修复**：加认证失败与 per-token 节流（DRF throttling / django-ratelimit）。

### BS-24　logged-out 标记 cookie 缺 Secure 标志
- **级别**：Low
- **位置**：`accounts/logout_state.py:23-34`
- **问题**：cookie 设了 `httponly`/`SameSite=Lax` 但无 `secure=`，与生产的 `SESSION_COOKIE_SECURE`/`CSRF_COOKIE_SECURE` 不一致（值为非敏感 `"1"`，仅标志不一致）。
- **修复**：`set_cookie`/`delete_cookie` 设 `secure=not settings.DEBUG`。

---

## 三、后端 · 功能性（13 项）

### BF-1　迁移 0011 新增 `token_lookup` 无回填 → 存量静态 token 全部 401
- **级别**：Medium（未上线，暂无生产历史数据，但本地 dev 凭据会断）
- **位置**：`applications/services.py:154-158`；`migrations/0011_app_credential_token_lookup.py:13-17`
- **问题**：认证现在**强依赖**精确匹配 `token_lookup = sha256(token)`。迁移只 `AddField(default="")`，无 `RunPython` 回填（也无法回填——需明文 token 而仅存哈希）。`_static_token_lookup(...)` 恒返回 64 位 hex，绝不为 `""`，故迁移前创建的凭据（`token_lookup=""`）永远被过滤掉 → 401，且无任何解释性错误。
- **修复**：要么保留一条同时匹配 `token_lookup=""` 行并跑 PBKDF2 verify、成功时惰性回填 `token_lookup` 的路径；要么明确“部署即轮换”runbook 并在遇到 `token_lookup=""` 的活跃凭据时发独立审计/日志，使静默失败可观测。

### BF-2　MANAGED_USERS 动态解析不进入 `snapshot_version` → 下游快照陈旧【存疑】
- **级别**：Medium（取决于下游缓存契约）
- **位置**：`grants/query.py:292-293`（`_snapshot_version`），解析于 `:213-219 / :256-261`
- **问题**：`snapshot_version = f"{grant_version}.{catalog_version}"`。MANAGED_USERS 的有效人员集是查询时从钉钉主管链**动态**解析的，下属增减不改变 `grant_version`/`catalog_version`。按 `snapshot_version` 做缓存/etag 的下游会持续服务陈旧集合，直到无关的 grant/catalog 变更才失效。代码自身注释（`managed_users.py:79-87`）承认该危害但只守了“瞬时失败”未守“合法成员变更”。
- **修复**：把 managed-users 解析身份并入版本/etag——将 `resolved.resolved_at` 和/或 `resolved.user_ids` 稳定哈希并入 `snapshot_version`，或另暴露下游必须纳入缓存键的 `resolved_at`/digest。

### BF-3　MANAGED_USERS `resolved_at` 缺失/naive → 整个权限查询 500
- **级别**：Medium
- **位置**：`api/serializers.py:277-287, 301-307`；生产者 `api/permission_query_payloads.py:17-22`；错误路径 `api/views.py:76-88`
- **问题**：`expanded_grant_payload` 原样透传 `grant.resolved.resolved_at`，其来源 `directory_payloads.py:153` 对缺失字段产出 `""` 且不做时区/格式校验；而响应序列化器严格要求它能解析为**带时区**的 ISO datetime。单个 grant 校验失败使 `_read_grants` 返回 `None`，整个序列化失败，view 转 500——**连同该用户所有无关的非 managed grant 一起挂掉**，下游无法与真实故障区分。
- **修复**：在数据入口规范化/校验 `resolved_at`（解析为 aware datetime，缺失时默认解析时刻 UTC），或放宽序列化器：丢弃/标记单个异常 grant 而非整体返回 `None`。

### BF-4　单用户 org 上下文拉取失败中止整个目录同步
- **级别**：Medium
- **位置**：`directory_sync.py:115-130`；`directory_client.py:106-112, 158-177`
- **问题**：`_fetch_directory_snapshot` 为**每个**用户调 `get_user_org`，任一持续失败（某用户 `/org/` 404/403）都抛 `AuthentikDirectoryError` 中止快照组装，整个同步永远落不了地、无限重试。只有完全一致的目录才能同步。
- **修复**：per-user 隔离 org 拉取——逐用户捕获异常、跳过（或标记 stale）该用户，继续处理其余，把失败聚合进结果/健康快照。

### BF-5　权限查询端点不校验 HTTP 方法
- **级别**：Low
- **位置**：`api/views.py:37`、`api/urls.py:8-12`
- **问题**：纯函数视图直连 url，无 `@require_GET`；POST/PUT/DELETE 都执行同样读逻辑返回权限数据，永不返回 405。
- **修复**：`@require_http_methods(["GET"])`。

### BF-6　`/me/access-requests` 内存分页，且 `page` 无上界
- **级别**：Low
- **位置**：`portal/api.py:89`、`access_request_data.py:20-36`、`pagination.py:42-50, 77-83`
- **问题**：grants 走 DB 分页，但 access-requests 用 `paginate_items(...)` 把该用户所有请求 + 每条 group/direct-grant 关联全量载入内存再切片，`page_size` 不约束工作量；`_positive_integer(..., maximum=None)` 又允许任意大 `page`（DB 分页端点会产生巨大 OFFSET）。限于调用者自身数据，故 Low。
- **修复**：把 access-request 分页下推到 queryset（先切片再 hydrate），并对 `page`/offset 设上界。

### BF-7　`total_pages()` 在 `page_size == 0` 时除零
- **级别**：Low（当前不可达）
- **位置**：`api/pagination.py:27-30`
- **问题**：`((total_items-1)//page_size)+1` 无 `page_size==0` 防护。现有调用方都经 `_positive_integer` 夹紧 ≥1，故暂不可达，但这是 in-scope 公共工具。
- **修复**：`page_size <= 0` 时返回 0 或抛校验错误。

### BF-8　目录健康检查只反映最近同步的单个 corp
- **级别**：Low
- **位置**：`applications/dependency_health_checks.py:135-166`
- **问题**：`_check_dingtalk` 取 `order_by("-last_synced_at").first()` 单行。多 corp 部署下，一个健康的较新 corp 会掩盖另一个 corp 的失败/陈旧。
- **修复**：评估所有 sync-state 行（任一 corp 出错/陈旧即 unhealthy），worst-of 汇总。

### BF-9　目录分页无“前进/循环”保护
- **级别**：Low
- **位置**：`directory_client.py:127-135, 180-186`
- **问题**：`_iter_paginated` 信任 `pagination.next` 为下一页号，不校验其递增。上游返回恒定/非递增的正 `next` 会无限循环；因快照会被物化成 tuple，任务挂死直到 worker 被杀。
- **修复**：要求 `next_page > page`（否则停止），并加硬性最大页数/迭代上限。

### BF-10　角色↔权限矩阵每次变更写重复审计事件【存疑：疑似遗留兼容】
- **级别**：Low
- **位置**：`admin_console/configuration.py:87-98`
- **问题**：每次单元格切换发**两条**元数据相同、动作名不同的审计（`role_permission_matrix_updated` 与 `role_permission_matrix_changed`），外加 `bump_catalog_version` 的第三条。按这些动作计数的分析会重复计。
- **修复**：只发一个规范动作；若迁移期需保留旧名，用显式开关门禁并写明移除条件（与 `AGENTS.md` 的“不新增兼容分支”一致）。

### BF-11　单实体 catalog PATCH 无乐观并发控制（丢更新）
- **级别**：Low
- **位置**：`scopes_api._update_scope`、`roles_api._update_role`、`permissions_api._update_permission`、`permission_group_write_helpers._save_group_update`、`authorization_groups_api._save_authorization_group_update`
- **问题**：与矩阵保存（`select_for_update` + `base_version`）和 retry-grant 不同，单实体编辑是无锁无版本的读-改-写。两个并发 PATCH 同一角色/范围/权限/组静默 last-write-wins。
- **修复**：为单实体更新加同样的 `base_version`/`catalog_version` 乐观校验或 `select_for_update`。

### BF-12　`configuration-status` 用 `items` 而非规范 `data` 键；且不校验方法
- **级别**：Low
- **位置**：`apps_api.py:167-186`（`items` 于 `:182`）、`console_app_api.py:22-37`
- **问题**：这两个读端点从不限制 HTTP 方法（POST/PUT/DELETE 也返回读载荷）；`configuration-status` 列表用 `"items"`，而全库已统一列表响应为 `"data"`（`api_payloads.list_payload`）。仅契约不一致，非数据暴露。
- **修复**：非 GET 返回 `method_not_allowed_response()`；`items` → `data`（或用 `list_payload` 包装）。

### BF-13　门户死代码：`grant_rows.py` 与 `views.py` 行构建器未被引用
- **级别**：Low
- **位置**：`portal/grant_rows.py`（`PortalGrantRow`/`current_grant_rows_for_user`/`expiring_grant_rows`）、`portal/views.py:75-116`（`request_rows_for_user`/`AccessRequestRow`）
- **问题**：真实 API 路径经 `portal/api_data.py` + `permission_aggregation.py` 渲染；grep 确认上述构建器无非测试调用方。这套平行实现（含自己硬编码的 `EXPIRING_SOON_DAYS = 14`）会与真实路径静默漂移。
- **修复**：删除死模块/函数，或收敛到到期窗口/状态文案的单一事实源（符合 `AGENTS.md` 的“正本清源”）。

---

## 四、前端 · 安全性（2 项）

> 正向结论：审计范围内**无 `dangerouslySetInnerHTML`/`innerHTML`/原始 HTML 注入**，所有服务端字符串均作为 JSX 文本子节点由 React 转义——**无 XSS**。CSRF 处理正确（`api.ts` 读 Django `csrftoken` cookie 并在非安全方法附 `X-CSRFToken`，`credentials:"include"`）。**无开放重定向**（唯一由服务端数据构造的登出 URL 经 `localLogoutUrl` 硬化，拒绝 `//`/`\`/非 `/` 值）。一次性密钥仅存于 React state，不入 `localStorage`/`sessionStorage`、不 `console.log`、不按键缓存。以下仅 2 项 Low。

### FS-1　`buildApiError` 将非 JSON 响应体原样作为用户可见错误
- **级别**：Low
- **位置**：`frontend/src/lib/api.ts:133-156`
- **问题**：对任何非 `application/json` 的错误响应，`parseResponse` 返回 `response.text()`，`buildApiError` 用整串作为 `ApiError.message`，各控制台页在 `StatusBanner` 原样渲染。代理/网关错误页或 Django `DEBUG` traceback 页会被灌进 UI。
- **修复**：非 JSON 错误体改用基于状态码的通用文案，不回显任意 HTML/文本。

### FS-2　未校验的 `avatarUrl` 直接写入 `<img src>`
- **级别**：Low（纵深防御）
- **位置**：`frontend/src/components/shell/UserSummary.tsx:43-44`（源自 `main.tsx:56` 的服务端 `data-current-user-avatar-url`）
- **问题**：`currentUser.avatarUrl` 无 scheme 白名单直接进 `src`。`<img src>` 非脚本执行汇聚点（`javascript:` 不会执行），故非 XSS；残余风险是 `data:`/跨源 URL 用于追踪。值得注意的是同级 `logoutUrl` **有**校验（`localLogoutUrl`）而 `avatarUrl` 没有，属不一致。
- **修复**：渲染前将 `avatarUrl` 白名单到 `https:`/同源（或已知 CDN），与 `logoutUrl` 一致处理。

---

## 五、前端 · 功能性（16 项）

### FF-1　服务端分页被完全忽略 → 应用/运营/审计列表只显示前 20 行
- **级别**：High
- **位置**：`ConsoleAppList.tsx:41-45, 159-164`；`OperationsPage.tsx:39-53, 55-60`；`lib/api.ts:96-104`
- **问题**：这些端点服务端按 `DEFAULT_PAGE_SIZE = 20` 分页并返回 `{data, pagination}`，但客户端调用**不带任何 `page`/`page_size`**，`itemsFromPayload` 只读 `payload.data`（前 20 行）并**丢弃 `pagination`**，表格再对这 20 行做客户端分页。若某安装的应用/请求/授权/审计超过 20 条，第 20 行之后从控制台**无法查看或管理**；`itemsFromPayload` 形状不符时静默返回 `[]` 又使失败无信号。
- **修复**：组件 state 跟踪 `page`/`page_size` 作为查询参数传入，读 `payload.pagination.total_pages`，改为服务端分页驱动（或 react-table `manualPagination`）；`ConsoleAppList` 与 `OperationsPage` 各段一并修复。

### FF-2　OperationsPage 审计段套用了 access-request 列 schema → 审计数据全空
- **级别**：Medium
- **位置**：`OperationsPage.tsx:27-32, 146-173`；`lib/domain.ts:339-353`
- **问题**：`operationColumns()` 只特判 `dependency-health` 与 `access-grants`，`audit` 落入 access-request 列（读 `user_id`/`app_key`/`status`/`request_type`/`submitted_at`），而审计记录字段是 `actor_id`/`event_type`/`target_id`/`created_at`（`audit_api.py:42-50`），列全都读不到，`OperationRow` 甚至没声明这些字段。审计视图显示一个 ID 列 + 五个 `"-"`。
- **修复**：新增 `audit` 分支，用 `event_type`/`actor_id`/`target_id`/`created_at` 列，并在 `OperationRow` 补字段。

### FF-3　TOTP 注册开始（`openEnroll`）无错误处理，失败静默
- **级别**：Medium
- **位置**：`TwoFactorSection.tsx:79-90, 105`
- **问题**：其余 2FA 动作都 `try/catch + setError`，唯 `openEnroll` 只 `try/finally` 无 `catch`，且以 `onClick={() => void openEnroll()}` 调用。`POST …/totp/begin` 失败时 promise 静默拒绝、spinner 停、对话框不开、用户零反馈（未处理的 promise rejection）。
- **修复**：加 `catch` 把错误呈现到行级错误态/StatusBanner，与 `TotpEnrollDialog.confirm` 一致。

### FF-4　`CreateCredentialForm` 可重复提交 → 一次性密钥永久丢失
- **级别**：Medium
- **位置**：`CreateCredentialForm.tsx:13-35`；`useCredentialsActions.ts:50-60`
- **问题**：两个创建按钮仅在 `!name` 时禁用，从不在 `createSecretMutation.isPending` 时禁用；父组件在第一个 `await` resolve 后才关对话框，留下二次点击触发第二个 `POST` 的窗口。两个 `onSuccess` 都 `setSecret(payload)`，后者覆盖前者——第一个凭据的**一次性**明文永不展示，但该凭据已在服务端激活。
- **修复**：把 `isPending` 传入表单、在途禁用两按钮（并/或防止 secret setter 被覆盖）。

### FF-5　定时授权可选择过去时间（无 `min`、无未来校验）
- **级别**：Medium
- **位置**：`AccessRequestFields.tsx:46-53`；`useAccessRequestForm.ts:182, 386`
- **问题**：`timed` 时客户端只校验 `expiresAt` 非空，`datetime-local` 无 `min`。用户可选过去时刻提交，走完审批后端按 `expires_at <= now` 视为立即过期（`application_grants.py:251`），浪费审批且困惑申请人。
- **修复**：输入加 `min={now}`，`canSubmit` 内要求 `new Date(expiresAt) > new Date()` 并给内联错误。

### FF-6　`Dialog` 非真模态（无焦点陷阱/初始焦点/焦点恢复）
- **级别**：Medium
- **位置**：`components/Dialog.tsx:24-88`
- **问题**：设了 `role="dialog"`+`aria-modal="true"`，但 `useDialogEffects` 只挂 Escape + 滚动锁；打开时焦点从不移入、Tab 不被困、关闭不回焦触发元素。键盘/读屏用户被困，背景控件仍可达。影响所有 `Dialog` 消费者（如 `SecretDialog`）。
- **修复**：打开时存 `activeElement`、移焦到面板首个可聚焦元素、在卡片内困住 Tab/Shift-Tab、卸载时恢复焦点。

### FF-7　申请人可选自己为审批人（前端无自排除）【存疑】
- **级别**：Medium
- **位置**：`AccessRequestFields.tsx:62-129`；`useAccessRequestForm.ts:176-184`
- **问题**：审批人多选列出全部 `approverOption`，`canSubmit` 只校验非空；`currentUserId` 在 shell 层可得却从未传入表单，无客户端自排除。已确认后端 `validated_approver_user_ids` 也不排除申请人（见 BS-1）。若申请人出现在 `approver_options`（如自己是本应用 owner/默认审批人）即可自审自批。存疑点在于其是否出现在选项取决于后端目录。
- **修复**：把 `currentUserId` 传入表单，从 `approverOptions` 过滤本人并在校验拒绝（服务端同样加 BS-1）。

### FF-8　高风险权限时长/永久前端未强制
- **级别**：Low
- **位置**：`useAccessRequestForm.ts:176-184`；`AccessRequestFields.tsx:40-45`
- **问题**：后端强制高风险授权组不可 `permanent` 且有最大时长（`high_risk_duration.py`），前端从不读 `risk_level`，可自由把高风险目标设为 `permanent`，走完整表单再被服务端生硬拒绝。纯 UX/校验缺口，后端仍安全。
- **修复**：目录视图带 per-target 风险/时长策略，前端强制 `timed` + 最大时长并给说明。
- 备注：应当允许所有权限都设为永久，请你修改前后端


### FF-9　门户与控制台大量硬编码中文，忽略语言切换
- **级别**：Low
- **位置**：门户 `PortalPage.tsx:76, 92-108, 144-159, 259-307`；控制台 `OperationsPage.tsx`/`MatrixTab.tsx`/`CatalogTab.tsx`/`RulesTab.tsx`/`CredentialsTab.tsx`/`OverviewTab.tsx`/`QueryTestTab.tsx`/`SecretDialog.tsx`/`CreateCredentialForm.tsx` 等
- **问题**：这些组件不走 `t()`，切到 English locale 时整块区域仍为中文，EN locale 在控制台基本不可用。
- **修复**：用户可见字符串统一走 `messages.ts` + `t()`。

### FF-10　`Field` 对非 input 子元素错误关联 label
- **级别**：Low
- **位置**：`components/Field.tsx:18-28`；消费者 `RequestTargetPicker.tsx:77-97`、`AccessRequestFields.tsx:77`
- **问题**：`Field` 克隆任意子元素注入 `id` 并 `<label htmlFor>` 指向它；当子元素是 `<div>`（审批人picker）或不透传 props 的自定义组件（`PermissionSelector`）时，id 落到不可 label 的元素或被丢弃，可见 label 未与任何控件程序化关联，点击 label 不聚焦。
- **修复**：复合字段改用 `role="group"`/`aria-labelledby`，或让这些子元素接受并应用注入的 `id`。

### FF-11　`<html lang>` 初始不随存储 locale
- **级别**：Low
- **位置**：`i18n/I18nProvider.tsx:27-54`
- **问题**：`documentElement.lang` 只在 `setLocale` 内更新；首屏若 `readStoredLocale()` 返回 `"en"`，`lang` 仍是服务端渲染值直到用户点切换。读屏首屏语言错误。
- **修复**：在 mount / `locale` 变化的 effect 内设 `documentElement.lang = locale`。

### FF-12　未分组权限的 app 过滤比分组更严格（丢 app-less 权限）【存疑】
- **级别**：Low
- **位置**：`useAccessRequestForm.ts:360-362` vs `permissionTree.ts:39, 52`
- **问题**：分组权限保留 `!app_key || app_key === appKey`（保留 app-less），未分组权限用 `app_key === appKey`，选定 app 后**排除** `app_key` 为空的未分组权限，导致同一 app-less 权限在组内可见、作为未分组行被隐藏。存疑于未分组条目实践中是否总带 `app_key`。
- **修复**：与分组规则一致：`(p) => !appKey || !p.app_key || p.app_key === appKey`。

### FF-13　递归权限树无环保护（循环目录 → 栈溢出）【存疑】
- **级别**：Low
- **位置**：`permissionTree.ts:11-22`；`useAccessRequestForm.ts:495-529`；`PermissionSelector.tsx:617-682, 885-896`
- **问题**：`collectGroupPermissions`/`collectScopedGroupPermissions`/`findPermissionGroup`/`collectDescendantGroupKeys`/`buildGroupRows` 均无 visited-set 递归 `children`。若服务端返回带环的组图（A⊂B⊂A）则无限递归栈溢出、请求页崩溃。存疑于目录通常是 DAG。（注：后端 `permission_group_clean()` 有环检测，故触发需绕过该约束。）
- **修复**：递归 walker 记录已访问 group key 并在重访短路。

### FF-14　`canSubmit` 接受纯空白理由
- **级别**：Low
- **位置**：`useAccessRequestForm.ts:181`；`AccessRequestFields.tsx:55-57`
- **问题**：校验为 `fields.reason &&`（真值性），纯空格/换行为真值可过，payload 原样发送。后端 `Field(min_length=1)` 同样接受空白。
- **修复**：校验 `fields.reason.trim().length > 0` 并发送 trim 后的值。

### FF-15　MatrixTab `updateGrant` 使用捕获的 `grants` 快照（stale closure）
- **级别**：Low
- **位置**：`MatrixTab.tsx:390-418`
- **问题**：`updateGrant`/`updateGrantManagedScopePolicy` 在函数式 `setForm((current)=>...)` 内 map 的是**参数 `grants`**（渲染时捕获的 `form.grants` 快照）而非 `current.grants`（`removeGrant` 却正确用 `current.grants`）。批处理下两次更新落在一次 re-render 前会互相覆盖。
- **修复**：updater 内改 map `current.grants`，删除 `grants` 参数。

### FF-16　`{ items?: T[] }` 响应类型与后端 `data` 契约不符（靠巧合工作）
- **级别**：Low
- **位置**：`UserSelect.tsx:32`、`MatrixTab.tsx:49-57`、`CatalogTab.tsx:89-97`、`OverviewTab.tsx:41`、`OperationsPage.tsx:41-46` 等
- **问题**：多处查询类型标为 `{items?: T[]}`，而后端列表信封是 `{data:[...]}`，实际读取靠 `itemsFromPayload` 读 `.data`。`items` 类型是死的；且 `itemsFromPayload` 形状不符返回 `[]` 而非报错，未来后端漂移会静默渲染空表无失败信号。
- **修复**：类型改为 `{data?: T[]; pagination?: Pagination}`，并考虑让 `itemsFromPayload` 在 dev 下对非数组 `data` 告警。
---

## 六、已验证为“无缺陷”的关键面（供放心与避免重复排查）

- **认证核心**：静态 token = SHA-256 索引查找 + PBKDF2 常量时间校验；OAuth = 唯一 `token_checksum` 索引；服务端密钥比较**无时序攻击**、无明文比较。查询 API 有跨应用 IDOR 防护（`principal.app_key != app_key` 门 + app 由凭据派生 + `app_key` 唯一）。**无服务端权限缓存**，故无缓存投毒面。
- **OIDC**：ID token 对 JWKS 验签，校验 issuer/aud/nonce/state，算法白名单（`RS256`）——配置下无 `alg:none`/HS256 混淆。state/nonce 256 位、一次性。`session.cycle_key()` 防会话固定。
- **WebAuthn**：挑战一次性 + TTL + `compare_digest` 状态令牌校验，校验 origin 与 RP-ID。
- **重定向**：`next`/redirect 参数在三处校验器均限制为本地绝对路径；登出 `@require_POST` + CSRF。
- **强制改密中间件**：在 SessionMiddleware 之后运行，对 `must_change_password` 管理员拦截所有非白名单路径（含 `/console/**` 及其 API），未发现绕过到受保护页面。
- **控制台鉴权**：读=任意已认证控制台用户，写=owner/superuser，create/delete/memberships/operations/集成设置=superuser——逐端点核对**一致且正确**，无缺失门禁、无写操作 IDOR、CSRF 全局启用、密钥仅创建时一次性返回、审计只追加。
- **门户 IDOR**：所有门户读写均按会话用户作用域（`user=user`），提交 payload 无 `user` 字段，无“按 id 取他人请求”端点。
- **授权事实一致性**：MANAGED_USERS **正确排除申请人本人**（`managed_users.py:97-101`）；目录瞬时失败 fail-fast 而非静默缩集；到期边界（查询/门户/`can_expire`）三处口径一致且全程 timezone-aware；grant 版本状态机 + 唯一约束 + `select_for_update` 正确序列化并发。
- **回调幂等/防重放**：HMAC + 5 分钟窗口 + `compare_digest`，approve/reject 对终态幂等、真冲突显式报错、apply 可重入——重放不产生重复授权。空/缺失 `EASYAUTH_DINGTALK_CALLBACK_SECRET` 时验证 **fail-closed**（拒绝一切）。Authentik/DingTalk HTTP 调用使用默认 TLS 上下文，**未禁用证书校验**；路径参数经 `quote(safe="")` 转义。
- **前端**：无 XSS 汇聚点、CSRF 正确、密钥不落存储/不打日志、无内存泄漏（防抖/timeout/ResizeObserver 均正确清理）。

---

## 七、修复优先级建议

**P0（授权模型 + 运营阻断，优先）**
- FF-1 服务端分页缺失（控制台数据不可见）——**当前真实阻断，最先修**。
- BS-1 / BS-2 审批人自选与空列表 fail-open——在接入出站审批链路**之前**必须修好授权模型（否则上线即 Critical）。
- BS-3 / BS-4 目录同步的“未知状态中止回收”“截断误撤”——直接影响访问回收正确性。

**P1（数据/凭据安全 + 核心功能正确性）**
- BS-5 / BS-6 明文密钥（Authentik token、TOTP 种子）静态加密。
- BS-7 TOTP 重放、BS-8 节流共享缓存、BS-9 越权枚举汇报链。
- BF-1 静态 token 迁移无回填、BF-3 `resolved_at` 致查询 500、BF-4 单用户失败中止同步、BF-2 快照版本陈旧。
- FF-2 审计列错配、FF-4 一次性密钥丢失、FF-3 TOTP 注册静默失败。

**P2（加固 + 契约 + 体验）**
- 其余 Low 项：BS-10~BS-24、BF-5~BF-13、FS-1~FS-2、FF-5~FF-16。可结合 `AGENTS.md` 的“正本清源”原则批量收敛（死代码、契约 `data` 键统一、i18n 补齐、方法保护、并发控制、可访问性）。

---

## 附：审计通道与文件覆盖

| 通道 | 覆盖 |
|---|---|
| 后端 API + 认证 + SDK | `api/*`、`applications/oauth*`、`services.py`(凭据认证)、`sdk/python/*` |
| 后端 admin_console + authz | `admin_console/*`（全部 `*_api.py`、`authz.py`、`request_guards.py`、`ownership.py`…） |
| 后端 accounts / 2FA | `accounts/*`、`two_factor_api.py`、WebAuthn/TOTP、`config/middleware.py` |
| 后端 grants / access_requests / portal | 三个包全量，审批 → 授权 → 到期 → MANAGED_USERS 全链路 |
| 后端 integrations / applications / tasks / audit | `integrations/authentik/*`、`integrations/dingtalk/*`、`tasks/*`、健康检查、凭据存储 |
| 前端 lib + console | `lib/*`、`pages/console/**`、`App.tsx`、`main.tsx` |
| 前端 portal + shell + i18n | `pages/portal/**`、`components/shell/*`、`components/ui/*`、`i18n/*` |
