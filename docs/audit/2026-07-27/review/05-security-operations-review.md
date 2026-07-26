# 14、16 号报告安全与运维交叉复核

复核日期：2026-07-27

复核基线：`18cd9363854efd9dfb0dce82291543c43b517add`

## 1. 结论

本次只复核 `[14]`《构建、配置与运维审计报告》和 `[16]`《安全、隐私与信任边界审计》。
两份报告共列出 24 项发现；按本次证据重新判定后：

| 判定 | 数量 | 说明 |
| --- | ---: | --- |
| 已确认 | 16 | 当前源码或配置足以确认主要事实 |
| 需限定或降级 | 6 | 根因存在，但报告把配置风险写成了运行事实、混入了不成立的推论，或缺少保留政策等外部口径 |
| 重复 | 2 | 与另一份报告的发现是同一根因，不能重复计数 |
| 整项矛盾 | 0 | 没有整项被当前源码推翻 |
| 整项未验证 | 0 | 没有只能依靠外部系统才能成立的整项发现 |

需要立即保留的核心结论有两组：

1. 仓库确实存在一条自称“公网反代部署”的开发级编排：它强制 `DEBUG=1`，使用
   `runserver`、SQLite、本地构建镜像和源码挂载，并把同一 `.env.local` 下发给全部应用
   服务。若这条编排被实际启用并经反向代理暴露，它会同时破坏部署完整性、密钥隔离、Cookie
   安全和数据边界。
2. 两条管理员撤权链路确实失效：本地管理员控制台入口没有校验 `session_version`，OIDC
   超级管理员能力只读取登录时写入 session 的组快照。

但“配置文件名为公网部署”不等于“服务当前从互联网可达”。两份原报告都没有 DNS、反向代理、
防火墙或外部 HTTP 证据；最终总报告必须把相关表述写成“若该编排实际启用并暴露”，不能写成
“当前公网正在暴露”。

## 2. 复核方法与安全边界

本次采用源码追踪、配置比对、文件权限检查和只使用虚构标记的本地校验探针：

- 只检查 `.env.local` 的键名存在性和文件权限，没有输出任何值；
- 只对 `db.sqlite3` 执行 `stat`，没有查询表、记录、用户名、联系方式、密文或凭据；
- 没有尝试用已知开发密钥解密任何真实字段；
- 没有使用真实账号、token、Cookie、OIDC client secret 或 Authentik API token；
- 没有发送外部网络请求、DNS 重绑定请求、重定向请求或健康探测；
- Pydantic 回显验证只使用 `DUMMY_REVIEW_MARKER_` 虚构字符串；
- 复核了 Ruff 的 15 项失败和前端 `--run` 参数失败；没有重新完成耗时较长的
  basedpyright 全量检查，因此不独立背书“1718”这一精确数量；
- 没有修改应用代码、原报告或运行数据。

判定含义如下：

- **已确认**：不依赖外部状态，当前源码、配置或安全的本地探针可以确定主要事实。
- **需限定或降级**：主要结构存在，但影响、严重度或部分因果需要条件；或报告把一个版本/工具
  事实解释成了无法由证据推出的运行事实。
- **重复**：另一项已经覆盖同一根因和修复目标；可以保留补充影响，但不能作为独立问题计数。
- **矛盾**：当前证据直接否定报告的主要事实。
- **未验证**：当前本地证据不足，必须依赖外部系统、真实运行态或被禁止的敏感操作。

## 3. 14 号报告逐项判定

### 3.1 部署、数据与发布链路

| 发现 | 判定 | 复核结果与证据 |
| --- | --- | --- |
| `[14]/BCO-01`（报告位置 `docs/audit/2026-07-27/14-build-config-operations.md:28`） | **需限定，不降低阻断优先级** | 编排自称公网反代部署并强制 `DJANGO_DEBUG: "1"`、`runserver`（`docker-compose.deploy.yml:1`、`:29-35`、`:69-75`）；DEBUG 下缺失密钥会落到公开固定值（`src/easyauth/config/settings/base.py:22-40`），缺失 `DATABASE_URL` 会落到 SQLite（`src/easyauth/config/settings/base.py:116-127`），字段密钥经 SHA-256 派生成 Fernet key（`src/easyauth/config/crypto.py:31-38`）。安全键名检查也确认当前 `.env.local` 不含两把关键密钥和 `DATABASE_URL`。配置缺陷已确认；“当前互联网可达”和报告中的真实钉钉 secret 解密探针本次未验证。 |
| `[14]/BCO-02`（报告位置 `docs/audit/2026-07-27/14-build-config-operations.md:65`） | **需限定** | 同一 SQLite 文件挂到公共模板（`docker-compose.deploy.yml:52-55`），web、worker、webhook-worker、notify-worker、beat、stream 六个服务均继承它（`docker-compose.deploy.yml:69-174`）；当前权限仍为 `0644`。但“六个进程”不准确：这里至少是六个服务/容器，Celery worker 自身还会派生并发子进程。并发写风险成立，不等于已观测到锁故障。报告记录的精确文件大小也不是稳定事实，复核时已与 `30,261,248` 字节不一致。 |
| `[14]/BCO-03`（报告位置 `docs/audit/2026-07-27/14-build-config-operations.md:95`） | **已确认** | 唯一 CI 作业是镜像构建、签名和发布路径（`.github/workflows/docker-build.yml:20-93`），没有 pytest、Ruff、basedpyright、Django 迁移检查、Vitest 或 Playwright；仓库却把这些命令列为质量门槛（`README.md:481-492`），并已有对应配置（`pyproject.toml:43-89`）。隔离归档中的 Ruff 复核仍为 15 项错误。basedpyright 的精确 1718 项本次未独立复跑，但不影响“CI 未执行质量门槛”这一主要结论。 |
| `[14]/BCO-04`（报告位置 `docs/audit/2026-07-27/14-build-config-operations.md:141`） | **已确认** | CI 生成 provenance、SBOM 并签名 digest（`.github/workflows/docker-build.yml:58-87`）；部署编排却引用并本地构建 `easyauth-web:local`（`docker-compose.deploy.yml:26-27`、`:69-73`），还把宿主 `deploy.py` 覆盖到镜像源码路径（`docker-compose.deploy.yml:52-55`）。因此这条声明的部署路径不能由 CI 签名产物证明。是否有某个真实环境另行使用签名 digest，不在仓库证据内。 |
| `[14]/BCO-05`（报告位置 `docs/audit/2026-07-27/14-build-config-operations.md:166`） | **已确认** | 公共 anchor 统一加载完整 `.env.local`（`docker-compose.deploy.yml:26-31`），六个应用服务全部继承该 anchor（`docker-compose.deploy.yml:69-174`）；两个出站 worker 还以 root 和 `NET_ADMIN` 运行（`docker-compose.deploy.yml:95-104`、`:125-133`）。只检查键名已确认当前文件包含 OIDC client secret 和 Authentik API token 配置键。发现应表述为“按此 Compose 启动时全部容器会获得这些变量”，而不是声称已读取了运行中容器环境。 |

### 3.2 构建、健康检查与工具链

| 发现 | 判定 | 复核结果与证据 |
| --- | --- | --- |
| `[14]/BCO-06`（报告位置 `docs/audit/2026-07-27/14-build-config-operations.md:196`） | **已确认** | README 推荐 `.venv/bin/uvicorn`（`README.md:367-374`），运行依赖只有 Gunicorn、没有 Uvicorn（`pyproject.toml:7-23`），`uv.lock` 也没有 `uvicorn` 包，本地 `.venv/bin/uvicorn` 不存在。 |
| `[14]/BCO-07`（报告位置 `docs/audit/2026-07-27/14-build-config-operations.md:214`） | **已确认** | PostgreSQL 和 Redis 都没有 `healthcheck`（`docker-compose.yml:1-20`），README 却要求确认二者 `healthy` 后继续（`README.md:408-410`）；部署 Redis 同样只有启动顺序依赖（`docker-compose.deploy.yml:59-67`）。这与 `[16]/SPB-11` 的“健康端点信息过多”不是同一问题。 |
| `[14]/BCO-08`（报告位置 `docs/audit/2026-07-27/14-build-config-operations.md:236`） | **已确认** | 单一作业统一声明 `contents: write`、`id-token: write`、`packages: write`（`.github/workflows/docker-build.yml:20-26`），全部第三方 Action 使用可变大版本标签（`.github/workflows/docker-build.yml:28-60`、`:73-93`）。外部 fork PR 的实际 token 权限可能被 GitHub 自动降级，但同仓 PR、push 和后续新增步骤仍受当前宽权限结构影响；可变 Action 标签问题不依赖该差异。 |
| `[14]/BCO-09`（报告位置 `docs/audit/2026-07-27/14-build-config-operations.md:249`） | **需限定并拆分** | Node 口径确实漂移：README 只写 Node ≥ 20（`README.md:239-242`），锁定的 Vite 要求 `^20.19.0 \|\| >=22.12.0`（`pnpm-lock.yaml:1244-1246`）；项目声明 Python 3.12—3.14（`pyproject.toml:6`），容器和 CI 只直接验证 3.12（`Dockerfile:25`、`.github/workflows/docker-build.yml:58-71`）。但 `uv.lock:1491-1494` 中的 uv 0.11.19 是项目 dev 依赖的锁定版本，不能证明该版本生成了锁文件；把它与 Dockerfile 的 uv 0.8.22 比较后直接推断“锁文件生成环境漂移”证据不足。应保留 Node 条件和 Python 支持矩阵缺口，uv 部分降为“解释器版本不统一，兼容性需单独验证”。 |
| `[14]/BCO-10`（报告位置 `docs/audit/2026-07-27/14-build-config-operations.md:267`） | **已确认** | `manage.py:20-44` 与 `src/easyauth/config/local_env.py:11-41` 各有一套相同解析器；WSGI/ASGI 使用后者（`src/easyauth/config/wsgi.py:7-11`、`src/easyauth/config/asgi.py:7-11`），现有直接测试只覆盖 manage.py 版本（`tests/unit/config/test_manage_local_env.py:13-47`）。 |
| `[14]/BCO-11`（报告位置 `docs/audit/2026-07-27/14-build-config-operations.md:279`） | **已确认** | Vite 只有单入口且没有体积预算（`frontend/vite.config.ts:16-22`）；当前主包仍为约 826 kB。测试脚本使用 `node -e`、`spawnSync(..., shell: true)`（`frontend/package.json:6-11`），本次再次执行 `pnpm --filter @easyauth/frontend test --run` 得到 `node: --run requires an argument` 和退出码 9。性能影响仍需真实测量，不能把体积警告写成已发生的用户延迟。 |
| `[14]/BCO-12`（报告位置 `docs/audit/2026-07-27/14-build-config-operations.md:306`） | **已确认，保持提示级** | Git ignore 与 Docker ignore 明确排除环境文件、SQLite、缓存和构建产物（`.gitignore:1-23`、`.dockerignore:20-43`）；当前受跟踪缓存/备份候选为 0，有限的常见密钥模式扫描为 0，`.env.local` 为 `0600`。这只表示本次模式和当前跟踪集没有命中，不等于完成凭据有效性、熵或全历史审计。 |

## 4. 16 号报告逐项判定

### 4.1 密钥与管理员会话

| 发现 | 判定 | 复核结果与证据 |
| --- | --- | --- |
| `[16]/SPB-01`（报告位置 `docs/audit/2026-07-27/16-security-privacy-boundaries.md:45`） | **重复于 `[14]/BCO-01`，保留安全补充** | `DEBUG=1`、公开固定密钥和 `runserver` 是同一根因，不应再计一项。16 号补充的 Cookie/HSTS 影响成立：Secure session cookie、Secure CSRF cookie 和 HSTS 只在 `not DEBUG` 分支开启（`src/easyauth/config/settings/base.py:189-196`），而 `deploy.py` 只补 `SECURE_PROXY_SSL_HEADER`（`src/easyauth/config/settings/deploy.py:1-12`）。应避免泛化为“已可伪造所有 Django 数据库会话”；当前确定的是所有依赖 `SECRET_KEY` 的签名对象失去可信密钥边界。 |
| `[16]/SPB-02`（报告位置 `docs/audit/2026-07-27/16-security-privacy-boundaries.md:95`） | **已确认** | 模型明确以 `session_version` 撤销旧会话（`src/easyauth/accounts/models.py:211-216`）；规范入口同时校验本地标志、subject、启用状态和版本（`src/easyauth/accounts/local_admin.py:98-113`）。控制台 `actor_from_request()` 对 `local-admin:` 只检查 `is_active`（`src/easyauth/admin_console/identity.py:16-39`），`require_superuser()` 完全依赖该 actor（`src/easyauth/admin_console/authz.py:14-28`）。强制改密中间件遇到版本失配只会得到 `None` 后继续放行（`src/easyauth/config/middleware.py:54-64`），不会补上版本校验。现有撤销测试只请求安全页（`tests/integration/auth/test_local_admin_login.py:645-676`），确实没有覆盖控制台。 |
| `[16]/SPB-03`（报告位置 `docs/audit/2026-07-27/16-security-privacy-boundaries.md:129`） | **已确认** | 登录时把 claims groups 写入 session（`src/easyauth/accounts/auth.py:149-180`）；控制台每次请求只重新确认 `UserMirror.status`，超级管理员判断仍只读取 session groups（`src/easyauth/admin_console/identity.py:28-47`）。仓库中没有登录后权威组刷新或管理 session epoch。用户离职导致本地状态变化时会失效，但仅从管理组撤除、用户仍 active 时不会即时撤权。 |
| `[16]/SPB-04`（报告位置 `docs/audit/2026-07-27/16-security-privacy-boundaries.md:159`） | **重复于 `[14]/BCO-02`** | SQLite bind mount 和 `0644` 权限完全重复。16 号补充了数据敏感度证据：用户镜像存储姓名、邮箱、组织和钉钉标识（`src/easyauth/accounts/models.py:31-59`、`:110-139`），集成 token 和钉钉 secret 使用加密字段（`src/easyauth/applications/integration_settings.py:24-47`）。整改时作为 BCO-02 的数据边界子项，不重复计数。 |

### 4.2 出站网络与敏感响应

| 发现 | 判定 | 复核结果与证据 |
| --- | --- | --- |
| `[16]/SPB-05`（报告位置 `docs/audit/2026-07-27/16-security-privacy-boundaries.md:194`） | **已确认** | `_fetch_descriptor()` 先调用 `assert_public_host()`，随后把原域名交给 `urlopen()`（`src/easyauth/admin_console/auto_onboarding_api.py:203-225`）；校验函数只返回成功/异常，不返回和固定已校验 IP（`src/easyauth/config/net.py:65-81`）。因此连接时重新解析 DNS，默认重定向也没有逐跳重新经过该校验。项目已有固定校验 IP、保留原域名用于 TLS 的实现（`src/easyauth/webhooks/transport.py:56-82`）。实际 DNS 缓存和代理会影响可利用性，但 TOCTOU 与重定向校验缺口是静态确定事实。 |
| `[16]/SPB-06`（报告位置 `docs/audit/2026-07-27/16-security-privacy-boundaries.md:228`） | **已确认** | 集成设置和自动接入接口都返回 `{"errors": str(exc)}`（`src/easyauth/admin_console/settings_api.py:84-93`、`src/easyauth/admin_console/auto_onboarding_api.py:106-114`），相关模型包含 token/secret 字段（`src/easyauth/admin_console/settings_api.py:34-42`、`src/easyauth/admin_console/auto_onboarding_api.py:58-64`）。虚构超长标记探针在两条路径均被 `str(exc)` 回显。通知通道已经使用 `include_input=False` 的安全模式（`src/easyauth/admin_console/notification_channel_api.py:259-277`）。 |
| `[16]/SPB-07`（报告位置 `docs/audit/2026-07-27/16-security-privacy-boundaries.md:264`） | **已确认，缓存影响为条件性** | 本地管理员 GET 安全页向模板传递 TOTP secret、URI、二维码和 nonce（`src/easyauth/accounts/local_admin_views.py:216-239`）；控制台 TOTP API 返回同类秘密（`src/easyauth/admin_console/two_factor_api.py:66-88`），凭据 API 返回一次性 static token 或 OAuth secret（`src/easyauth/admin_console/credentials_api.py:92-102`、`:119-131`、`:150-162`）。通用 JSON 响应没有设置禁止存储头（`src/easyauth/api/responses.py:20-29`），这些路径也没有 `never_cache`。头缺失已确认；具体浏览器、代理是否实际缓存本次未动态验证。 |
| `[16]/SPB-12`（报告位置 `docs/audit/2026-07-27/16-security-privacy-boundaries.md:415`） | **已确认** | mutation variables 明文携带 token（`frontend/src/pages/console/onboarding/AppOnboardingWizard.tsx:967-972`），成功后只清空输入 state（`:973-979`），错误分支继续读取 `testMutation.variables`（`:1027-1029`），组件中没有 `testMutation.reset()`。因此 token 的内存生命周期确实超过输入框清空时点；这扩大已有同源脚本/XSS/调试暴露面，但自身不构成跨源读取或权限绕过。 |

### 4.3 数据保留与低敏感边界

| 发现 | 判定 | 复核结果与证据 |
| --- | --- | --- |
| `[16]/SPB-08`（报告位置 `docs/audit/2026-07-27/16-security-privacy-boundaries.md:298`） | **需限定并降为保留治理缺口** | `UserMirror` 禁止实例物理删除（`src/easyauth/accounts/models.py:72-82`）；钉钉 tombstone 明确保留身份和联系方式（`src/easyauth/accounts/models.py:110-139`）；离职处理只清部门和主管字段（`src/easyauth/integrations/authentik/directory_sync.py:534-555`）。仓库内确实没有自动匿名化流程。但“无限期保留即为缺陷”的严重度还需要用途、法定留存、审计引用和删除请求政策；源码只能确认“没有已编码的最小化/到期流程”。 |
| `[16]/SPB-09`（报告位置 `docs/audit/2026-07-27/16-security-privacy-boundaries.md:330`） | **需限定并降为保留治理缺口** | Stream 保存 `data/result/error`（`src/easyauth/integrations/models.py:26-60`），Webhook 保存 payload、URL 和错误（`src/easyauth/webhooks/models.py:105-139`），AuditLog 保存任意 metadata（`src/easyauth/audit/models.py:38-47`）。审计日志已有手工 purge 接口和必须传 `--keep-days` 的命令（`src/easyauth/audit/models.py:30-34`、`src/easyauth/audit/management/commands/prune_audit_logs.py:20-36`），beat 仅调度连接器和通知清理，没有这三类自动任务（`src/easyauth/config/settings/base.py:333-377`）。因此“缺少自动保留期”成立，但实际合规缺口和严重度取决于尚未给出的保留矩阵；审计日志并非完全没有清理能力。 |
| `[16]/SPB-10`（报告位置 `docs/audit/2026-07-27/16-security-privacy-boundaries.md:363`） | **已确认** | 存在 ID 先产生 `not_approver`（`src/easyauth/access_requests/approvals.py:239-254`），不存在 ID 产生 `not_found`（`:328-340`），门户分别映射为 403 和 404（`src/easyauth/portal/approvals_api.py:135-150`）。攻击者必须是已登录用户并提交合法决定；差异只暴露编号存在性，不暴露申请正文，低级别合理。 |
| `[16]/SPB-11`（报告位置 `docs/audit/2026-07-27/16-security-privacy-boundaries.md:388`） | **需限定，建议降为提示或低** | `/health/` 确实无应用级认证（`src/easyauth/config/urls.py:103-113`），响应包含 database、broker 和多类后台 heartbeat，并返回 age/max-age（`src/easyauth/config/urls.py:26-67`、`:91-96`）。但 Compose 只把 web 端口发布到 `127.0.0.1`（`docker-compose.deploy.yml:69-75`），仓库中没有实际 frpc/nginx 路由规则证明 `/health/` 被转发到公网。应表述为“应用路由匿名；若通用反代暴露全部路径则泄漏内部节奏”。 |

## 5. 重复、局部矛盾与未验证子结论

### 5.1 两份报告的具体重叠

| 根因簇 | 发现 | 裁决 |
| --- | --- | --- |
| 开发级公网编排 | `[14]/BCO-01`、`[16]/SPB-01` | 完全共享 `DEBUG=1`、开发密钥、SQLite 和 `runserver` 根因；合并为一个阻断项，SPB-01 的 Secure Cookie/HSTS 作为子影响 |
| SQLite 数据边界 | `[14]/BCO-02`、`[16]/SPB-04` | `0644` 和 bind mount 完全重复；BCO-02 保留并发可靠性子项，SPB-04 保留敏感字段范围 |
| 同一部署文件的完整性与秘密面 | `[14]/BCO-04`、`[14]/BCO-05` | 都来自公共 Compose，但一个是镜像/源码完整性，一个是机密配置最小权限，不合并为同一发现 |
| 健康检查 | `[14]/BCO-07`、`[16]/SPB-11` | 前者是依赖服务无 readiness，后者是应用 readiness 暴露过细；修复时需同时设计内外两层健康接口，不能互相替代 |
| 工作区秘密扫描边界 | `[14]/BCO-12` 与 `[16]` 第 4 节 | 都只能说明有限模式未命中；不能据此宣称没有凭据、历史泄漏或弱密钥 |

去重后，两份报告是 22 个独立问题或治理缺口，不是 24 个。

### 5.2 局部矛盾

没有整项发现被当前源码推翻，但 `[14]/BCO-02` 的
`db.sqlite3 size=30261248 bytes` 已与复核时的只读 `stat` 不一致。数据库文件仍为 `0644`，
所以安全结论不变；精确大小和行数属于易变运行态，不应进入最终稳定摘要。

### 5.3 仍未验证的子结论

以下内容不能从本次安全范围内升级为事实：

- 域名是否可解析、frpc/nginx 是否正在运行、服务是否当前从互联网可达；
- 当前运行容器是否就是该 Compose 创建、是否另有环境变量或编排层覆盖；
- 已知开发字段密钥是否能解密当前数据库中的任一真实值；
- 当前数据库中的具体管理员、凭据、员工或业务记录数量；
- basedpyright 是否仍恰好为 1718 项错误；
- 浏览器、代理或遥测系统是否已经持久化某次 TOTP/一次性凭据响应；
- 外部系统是否另有数据保留、备份过期、匿名化或健康端点访问策略；
- 自动接入重定向是否会把 `Authorization` 转发到不同主机。16 号报告已经正确地把这一点留在
  未确认边界，最终报告也应保持该限制。

## 6. 整改顺序

### 6.1 第一批：先封闭信任根和现有数据暴露面

1. 暂停把 `docker-compose.deploy.yml` 当作可公开暴露的生产编排；建立唯一生产路径，强制
   `DEBUG=0`、PostgreSQL、正式 WSGI、不可变已签名镜像，并删除源码 bind mount。
2. 立即把现有 SQLite 及其备份权限收紧到服务账号最小范围；迁移 PostgreSQL 时验证行数和业务
   不变量，不能用空库或静默默认值掩盖迁移失败。
3. 轮换 Django `SECRET_KEY` 并使全部既有本地 session 失效。字段加密 key 不能直接替换：
   必须在明确的短期迁移窗口内受控解密、重加密并验证，完成后删除旧 key。
4. 按服务拆分机密配置。OIDC client secret、Authentik 管理 token、钉钉凭据不得继续通过同一
   `env_file` 注入全部 web/worker/beat/stream 容器。

这一批共同覆盖 `[14]/BCO-01`、`BCO-02`、`BCO-04`、`BCO-05`、
`[16]/SPB-01`、`SPB-04`，应按一个部署根因簇实施和验收。

### 6.2 第二批：修复管理员撤权

1. `actor_from_request()` 的本地管理员分支必须委托唯一的 `current_local_admin()` 权威校验，
   版本、专用标志或状态不匹配时清除完整认证 session 并失败关闭。
2. OIDC 超级管理员不能长期依赖登录组快照。可选择短时管理 session 加服务端 epoch、每次高权限
   请求读取权威组状态，或消费可靠的组变更/登出事件；权威状态不可确认时拒绝高权限请求。
3. 补齐改密、TOTP、passkey、停用再启用、OIDC 撤组/禁用/删除后的既有 session 访问
   `/console/` 和高权限 API 测试。

这一批覆盖 `[16]/SPB-02`、`SPB-03`，优先级高于一般 CI、文档和前端体积问题。

### 6.3 第三批：收紧出站和秘密响应边界

1. 自动接入复用已存在的固定 IP HTTPS 传输；禁止自动重定向，或逐跳重新校验 scheme、host、IP
   并固定连接地址。
2. 所有含 secret 的 Pydantic 错误统一使用 `include_input=False` 等安全序列化，不返回
   `str(exc)`。
3. 含 TOTP、一次性 token、OAuth secret 的 HTML/JSON 成功和失败响应统一加
   `Cache-Control: no-store, private`；前端 mutation 在完成后立即清除变量和错误对象。

这一批覆盖 `[16]/SPB-05`、`SPB-06`、`SPB-07`、`SPB-12`。

### 6.4 第四批：建立可发布、可观察且最小权限的运维链

1. 修清 Ruff 和基于明确范围的 basedpyright 基线，增加后端、前端、SDK、迁移和静态检查独立
   作业；镜像发布必须依赖全部质量作业成功。
2. PR 构建与 tag 发布拆分最小权限；第三方 Action 固定完整 commit SHA。
3. 为 PostgreSQL、Redis 和应用 readiness 建立明确健康门禁；公网 liveness 只返回固定整体状态，
   详细检查放到内网或强认证边界。
4. 修复 Uvicorn 文档、Node/Python 支持口径、重复 `.env.local` 解析器和 Vitest 参数包装。

这一批覆盖 `[14]/BCO-03`、`BCO-06`—`BCO-11`、`[16]/SPB-11`。

### 6.5 第五批：先定政策，再实现保留清理

先形成按数据集区分的保留矩阵，明确用途、最短/最长保留期、法定保留例外、备份过期和删除传播；
再分别实现离职画像最小化、Stream/Webhook 正文清除和审计日志定时分批 purge。没有政策前不应
随意删除审计证据，也不能把“存在手工命令”当成自动保留治理已经完成。

这一批覆盖 `[16]/SPB-08`、`SPB-09`。`SPB-10` 的 403/404 统一可作为同批低风险接口收口项。
