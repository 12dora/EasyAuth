# EasyAuth 仓库地图与审计覆盖分析

## 1. 报告范围

本报告用于为后续安全、领域、接口、前端、测试和部署审计建立统一的仓库地图。内容来自
2026-07-27 对工作区的静态检查，不代表已经证明实现正确，也不替代动态测试、数据库迁移验证、
真实外部系统联调或生产拓扑演练。

检查基线如下：

- 仓库根目录：`/Users/konata/code/EasyAuth`
- 当前分支：`main`
- 检查时提交：`18cd9363854efd9dfb0dce82291543c43b517add`
- Python 版本基线：`.python-version` 为 `3.12`，`pyproject.toml` 支持
  `>=3.12,<3.15`
- 项目协作约束：`AGENTS.md`
- 敏感本地文件：`.env.local` 和 `db.sqlite3` 均被 `.gitignore`、`.dockerignore`
  排除；本次地图审计未读取其内容

## 2. 技术栈与运行形态

| 层次 | 技术与版本入口 | 主要文件 | 审计关注点 |
| --- | --- | --- | --- |
| 后端 | Python、Django 5.2、Django REST Framework 3.16 | `pyproject.toml`、`manage.py`、`src/easyauth/config/` | 设置分层、认证与授权门禁、事务、ORM 约束、错误语义 |
| 授权协议 | 静态 Bearer token、OAuth2 client credentials | `src/easyauth/api/authentication.py`、`src/easyauth/applications/oauth.py`、`src/easyauth/config/urls.py` | 两种凭据是否映射到同一 App 主体、禁用与轮换、token 明文存储边界 |
| 登录与强认证 | Authentik OIDC、本地超管、TOTP、WebAuthn | `src/easyauth/accounts/`、`src/easyauth/admin_console/two_factor_api.py` | 会话固定、OIDC state/nonce、CSRF、暴破限制、密钥加密、通行密钥 RP 约束 |
| 前端 | React 19、TypeScript 5.9、React Router 7、TanStack Query、Vite 7、Tailwind CSS 4 | `frontend/package.json`、`frontend/src/`、`frontend/vite.config.ts` | 路由门禁仅作展示还是形成越权、API 契约校验、敏感信息展示、构建清单 |
| 异步处理 | Celery 5.5、Redis broker/result/cache、Celery beat | `src/easyauth/config/settings/base.py`、`src/easyauth/config/celery.py`、`src/easyauth/tasks/` | 队列路由、幂等、重试、任务丢失、并发抢占、健康信号 |
| 数据库 | 生产基线 PostgreSQL；调试模式可用 SQLite | `src/easyauth/config/settings/base.py`、`docker-compose.yml`、`docker-compose.deploy.yml` | PostgreSQL/SQLite 语义差异、锁与并发、约束和迁移、部署口径漂移 |
| 外部集成 | Authentik、DingTalk、NetBird、下游 webhook | `src/easyauth/integrations/`、`src/easyauth/connectors/`、`src/easyauth/webhooks/` | 出站 SSRF、签名、重放、超时、密钥脱敏、外部状态与本地事实边界 |
| SDK | 独立零依赖 Python 包，可选 FastAPI 适配 | `sdk/python/pyproject.toml`、`sdk/python/src/easyauth_app_sdk/` | 公共 API 契约漂移、签名校验、错误映射、独立发布与版本 |
| 容器与发布 | 多阶段、多架构 Docker 镜像；GHCR、Cosign、SBOM | `Dockerfile`、`.github/workflows/docker-build.yml` | 构建可复现性、基础镜像、运行用户、静态资源、质量门禁缺口 |

根 `pyproject.toml` 使用 `hatchling` 构建 `src/easyauth`；SDK 使用独立的
`sdk/python/pyproject.toml` 和 `setuptools`。两者是两个发布单元，审计时不能假定根项目的
测试、类型检查或构建会自动覆盖 SDK。

## 3. 进程、入口与数据流

### 3.1 进程入口

| 运行组件 | 入口 | 说明 |
| --- | --- | --- |
| Django 命令行 | `manage.py` | 启动前读取仓库根的 `.env.local`，默认 settings 为 `easyauth.config.settings.base` |
| WSGI | `src/easyauth/config/wsgi.py` | 读取本地环境后创建 Django WSGI application |
| ASGI | `src/easyauth/config/asgi.py` | 当前仅创建标准 Django ASGI application，未发现独立 websocket 路由 |
| Celery | `src/easyauth/config/celery.py` | 加载 `CELERY_*` 设置，并为关键任务成功写运行心跳 |
| Django URL 根 | `src/easyauth/config/urls.py` | 汇聚 Admin、登录、公共 API、控制台、DingTalk、OAuth、门户和健康检查 |
| React 入口 | `frontend/src/main.tsx`、`frontend/src/App.tsx` | 根据 Django shell 注入的数据决定 console/portal 路由 |
| React shell | `src/easyauth/frontend_shell.py`、`src/easyauth/config/templates/easyauth/react_shell.html` | 读取 Vite manifest 并注入当前用户与品牌数据 |
| DingTalk Stream 常驻进程 | `src/easyauth/integrations/management/commands/run_dingtalk_stream.py` | Stream 事件落库、ACK 与 Celery 派发的边界 |
| 本地超管创建 | `src/easyauth/accounts/management/commands/create_local_admin.py` | 初始凭据、强制改密与口令策略入口 |
| 试点数据初始化 | `src/easyauth/applications/management/commands/seed_crm_pilot.py` | 只应作为明确的试点初始化入口审计，不能成为生产事实兜底 |
| 审计日志清理 | `src/easyauth/audit/management/commands/prune_audit_logs.py` | 保留策略、删除边界与合规性入口 |

### 3.2 HTTP 命名空间

`src/easyauth/config/urls.py` 暴露下列根路径：

- `/admin/`：Django Admin。
- `/auth/`：OIDC 登录回调、登出、本地超管登录、TOTP、WebAuthn 和密码安全页，
  具体路由在 `src/easyauth/accounts/urls.py`。
- `/api/v1/`：下游应用公共 API，具体路由在 `src/easyauth/api/urls.py`。
- `/console/api/v1/`：React 管理控制台私有 API，路由集中在
  `src/easyauth/admin_console/urls.py`。
- `/console/`：React 控制台页面及深链回落。
- `/portal/api/v1/`：当前员工的授权、申请和审批 API，具体路由在
  `src/easyauth/portal/urls.py`。
- `/portal/`：React 员工门户及深链回落。
- `/integrations/dingtalk/callback`：DingTalk 回调入口，见
  `src/easyauth/integrations/dingtalk/urls.py`。
- `/oauth/token`：OAuth2 token 入口。
- `/health/`：数据库、broker 和后台任务心跳聚合，实现在
  `src/easyauth/config/urls.py` 与 `src/easyauth/config/runtime_health.py`。

`src/easyauth/config/settings/base.py` 中 `REST_FRAMEWORK` 的全局默认认证类和权限类均为空。
因此公共 API 是否安全完全依赖每个 view 的显式门禁。审计必须逐个将
`src/easyauth/api/urls.py` 的路由与 `src/easyauth/api/authentication.py`、对应 view
的认证和权限声明交叉核对，不能只检查全局设置。

### 3.3 关键异步链路

Celery 任务集中在 `src/easyauth/tasks/`，导入列表和 beat 调度表位于
`src/easyauth/config/settings/base.py`：

- 授权过期：`src/easyauth/tasks/grants.py`
- Authentik/DingTalk 目录同步与离职撤权：`src/easyauth/tasks/authentik.py`
- 依赖与运行心跳：`src/easyauth/tasks/health.py`
- webhook 投递：`src/easyauth/tasks/webhooks.py`
- 入转离生命周期：`src/easyauth/tasks/lifecycle.py`
- DingTalk Stream 事件处理：`src/easyauth/tasks/dingtalk_stream.py`
- NetBird 等连接器对账：`src/easyauth/tasks/connectors.py`
- 事务 outbox 扫描：`src/easyauth/tasks/outbox.py`
- 通知投递、回执对账和清理：`src/easyauth/tasks/notify.py`

`easyauth.webhooks.deliver` 被路由到 `webhooks` 队列，
`easyauth.notify.deliver_message` 被路由到 `notify` 队列；其余任务进入默认队列。
`docker-compose.deploy.yml` 分别运行 `worker`、`webhook-worker`、`notify-worker`、
`beat` 和 `stream`。审计应将任务名称、队列名、worker `--queues`、beat 表和健康检查逐项
对齐，特别检查路由遗漏是否会让任务进入无人消费的队列。

## 4. 后端领域地图

以下文件数为静态检查时排除 `migrations/` 与 `__pycache__/` 后的 Python 源文件数，用于
衡量审计面积，不代表复杂度或覆盖率。

| 领域 | 规模 | 主要文件与职责 | 应交叉核对的审计域 |
| --- | ---: | --- | --- |
| 项目配置 | 17 | `src/easyauth/config/settings/base.py`、`src/easyauth/config/settings/test.py`、`src/easyauth/config/settings/deploy.py`、`src/easyauth/config/urls.py`、`src/easyauth/config/middleware.py`、`src/easyauth/config/crypto.py`、`src/easyauth/config/net.py`、`src/easyauth/config/rate_limit.py`、`src/easyauth/config/runtime_health.py` | 环境变量快速失败、DEBUG 分支、可信代理、缓存、CSRF、安全 cookie、SSRF、密钥派生、健康检查 |
| 账号与目录镜像 | 18 | `src/easyauth/accounts/models.py`、`auth.py`、`oidc_exchange.py`、`views.py`、`local_admin.py`、`local_admin_views.py`、`directory_snapshot.py`、`directory_references.py` | OIDC、会话、本地超管、TOTP/WebAuthn、Authentik UID、在职状态、目录新鲜度 |
| 应用与授权目录 | 30 | `src/easyauth/applications/models.py`、`ops_models.py`、`oauth_models.py`、`services.py`、`configuration.py`、`permission_templates.py`、`permission_template_storage.py`、`manifest_*`、`integration_settings.py` | App 生命周期、凭据、OAuth 绑定、权限目录、模板导入、配置完整性、敏感配置加密 |
| 访问申请 | 11 | `src/easyauth/access_requests/models.py`、`services.py`、`approvals.py`、`application.py`、`application_grants.py`、`submission_validation.py`、`target_validation.py` | 申请状态机、请求目标、审批规则、永久/限时授权、幂等、并发提交 |
| 授权事实 | 12 | `src/easyauth/grants/models.py`、`services.py`、`query.py`、`lifecycle.py`、`operations.py`、`managed_users.py` | 授权唯一写入口、版本、撤销/过期、权限展开、`MANAGED_USERS`、缓存失效 |
| 审批工作流 | 4 | `src/easyauth/workflows/models.py`、`services.py` | 审批实例状态、待处理回调、外部审批证据、重放与乱序 |
| 组织与团队 | 4 | `src/easyauth/teams/models.py`、`services.py` | 成员资格、团队授权范围、离职/转岗联动 |
| 生命周期 | 4 | `src/easyauth/lifecycle/models.py`、`services.py` | 入职、离职、交接、转移计划、部分失败和恢复；`services.py` 约 1386 行，是高复杂度热点 |
| 审计日志 | 8 | `src/easyauth/audit/models.py`、`src/easyauth/audit/services.py`、`src/easyauth/audit/admin.py`、`src/easyauth/audit/management/commands/prune_audit_logs.py` | 安全事件完整性、追加语义、敏感字段脱敏、查询隔离、保留和清理 |
| 通知 | 4 | `src/easyauth/notify/models.py`、`services.py` | 接收幂等、配额、收件人解析、发送 lease、状态机、对账、清理；`services.py` 约 1455 行，是最大热点 |
| 事务 outbox | 4 | `src/easyauth/outbox/models.py`、`services.py` | 业务事务内入队、event key 冲突、`select_for_update`、lease、发布后崩溃造成的至少一次语义 |
| webhook | 7 | `src/easyauth/webhooks/models.py`、`delivery.py`、`transport.py`、`signing.py`、`hooks.py` | 密钥、签名、重试、响应大小、总时限、重定向、DNS 重绑定、SSRF、投递幂等 |
| 出站连接器 | 10 | `src/easyauth/connectors/models.py`、`src/easyauth/connectors/services.py`、`src/easyauth/connectors/dispatch.py`、`src/easyauth/connectors/registry.py`、`src/easyauth/connectors/netbird/client.py`、`src/easyauth/connectors/netbird/connector.py` | 连接器注册、密钥脱敏、NetBird API、授权组映射、周期对账、离职阻断 |
| 外部集成 | 21 | `src/easyauth/integrations/authentik/`、`src/easyauth/integrations/dingtalk/`、`src/easyauth/integrations/models.py` | Authentik 目录/管理 API、DingTalk token/签名/回调/Stream、事实来源边界、超时和重试 |
| 公共 API | 16 | `src/easyauth/api/urls.py`、`views.py`、`authentication.py`、`serializers.py`、`approval_views.py`、`directory_views.py`、`notify_views.py`、`manifest_sync_views.py` | 凭据与 App 绑定、对象级权限、分页、限流、统一错误、请求体限制、契约版本 |
| 管理控制台 API | 63 | `src/easyauth/admin_console/urls.py` 及同目录 `*_api.py`、`authz.py`、`identity.py`、`request_guards.py` | session/CSRF、系统管理员与 App owner 边界、所有写接口门禁、批量操作、重试与审计 |
| 员工门户 | 13 | `src/easyauth/portal/urls.py`、`api.py`、`approvals_api.py`、`request_catalog.py`、`views.py` | 当前用户边界、代申请/代审批风险、申请目录快照、撤回、续期与分页 |
| 任务编排 | 10 | `src/easyauth/tasks/` | task 名称稳定性、队列、幂等、重试策略、异常传播、心跳真实性 |

### 4.1 数据模型与迁移面积

领域模型主要分布在：

- `src/easyauth/accounts/models.py`
- `src/easyauth/applications/models.py`
- `src/easyauth/applications/ops_models.py`
- `src/easyauth/applications/oauth_models.py`
- `src/easyauth/applications/health_models.py`
- `src/easyauth/access_requests/models.py`
- `src/easyauth/grants/models.py`
- `src/easyauth/workflows/models.py`
- `src/easyauth/lifecycle/models.py`
- `src/easyauth/connectors/models.py`
- `src/easyauth/notify/models.py`
- `src/easyauth/outbox/models.py`
- `src/easyauth/webhooks/models.py`
- `src/easyauth/audit/models.py`
- `src/easyauth/teams/models.py`
- `src/easyauth/integrations/models.py`

仓库共有 74 个编号迁移文件，分布在 12 个业务应用；其中 `applications` 27 个、
`accounts` 13 个、`access_requests` 11 个，迁移历史最密集。只有
`tests/integration/migrations/test_notification_channel_migrations.py` 形成了明确的迁移集成
测试文件。后续数据库审计应至少执行 PostgreSQL 空库全量迁移、现有快照升级、
`manage.py migrate --check`、约束反例和回滚可行性检查，不能用 SQLite 单独证明迁移正确。

## 5. 前端地图

### 5.1 页面与路由

React 路由集中在 `frontend/src/App.tsx`：

- 门户：`/portal`、`/portal/request`、`/portal/requests`、`/portal/expiring`、
  `/portal/approvals`、`/portal/settings`
- 控制台：`/console`、`/console/apps/new`、`/console/apps/:appKey`、
  `/console/teams`、`/console/teams/:teamId`、`/console/people`、
  `/console/lifecycle/handover-tasks`、`/console/lifecycle/handover-tasks/:taskId`、
  `/console/lifecycle/onboarding`、`/console/approval-templates`、
  `/console/operations/approval-instances`、`/console/operations/:section`、
  `/console/settings`

主要页面目录：

- 管理控制台：`frontend/src/pages/console/`
- 应用工作台页签：`frontend/src/pages/console/workspace/tabs/`
- 入转离生命周期：`frontend/src/pages/console/lifecycle/`
- 新应用向导：`frontend/src/pages/console/onboarding/`
- 员工门户：`frontend/src/pages/portal/`
- 共享壳与组件：`frontend/src/components/`
- API、领域类型、凭据与 WebAuthn：`frontend/src/lib/`
- 中英文消息：`frontend/src/i18n/messages.ts`

前端的管理员条件渲染不能作为安全边界。每个
`frontend/src/pages/console/**/*.tsx` 发出的写请求，都应反查
`src/easyauth/admin_console/urls.py` 和具体 `*_api.py` 是否独立完成后端身份、App owner
或 superuser 校验。

### 5.2 构建产物

`frontend/vite.config.ts` 将生产构建写入
`src/easyauth/static/easyauth/frontend/`，包括 `.vite/manifest.json`、散列 JS/CSS、字体和
品牌资源。产物目录被 `.gitignore` 排除，只保留 `.gitkeep`；因此：

- Docker 镜像通过 `Dockerfile` 的前端阶段重新生成产物。
- 本地 Django 服务依赖最近一次 `pnpm --filter @easyauth/frontend build` 的结果。
- `src/easyauth/frontend_shell.py` 与
  `src/easyauth/config/templates/easyauth/react_shell.html` 必须共同审计 manifest 缺失、
  入口名变化和缓存行为。
- 工作区中存在的散列产物可能是旧构建，不能作为当前源码已加载的证据。

## 6. SDK 与契约地图

独立 Python SDK 源码位于 `sdk/python/src/easyauth_app_sdk/`：

- `client.py`：公共 API 客户端
- `descriptor.py`、`manifest.py`：应用描述与 manifest
- `webhook.py`：webhook 校验
- `lifecycle.py`：生命周期集成
- `integration.py`：接入编排
- `fastapi.py`：可选 FastAPI 适配
- `__init__.py`：公开导出面

对应测试为 `sdk/python/tests/` 下 7 个 `test_*.py`。公共契约还散布在：

- `docs/api/easyauth-public-api.md`
- `docs/api/easyauth-console-api.md`
- `docs/api/easyauth-portal-react-api.md`
- `tests/contract_samples/directory/*.json`
- `tests/contract_samples/notify/*.json`
- `src/easyauth/api/serializers.py`
- `src/easyauth/api/directory_payloads.py`
- `src/easyauth/api/approval_views.py`
- `src/easyauth/api/notify_views.py`
- `src/easyauth/api/manifest_sync_views.py`

契约审计应以“后端路由与序列化器—样例—SDK—文档—下游接入指南”五方一致为目标。根
`pyproject.toml` 的 pytest `testpaths` 仅包含 `tests`，`basedpyright` 也只包含 `src` 和
`tests`，因此日常根命令不会自动覆盖 SDK。

## 7. 测试与质量门槛地图

### 7.1 现有测试规模

| 测试层 | 文件数 | 位置 | 说明 |
| --- | ---: | --- | --- |
| 后端单元测试 | 96 | `tests/unit/` | 领域服务、模型、配置、传输与 payload |
| 后端集成测试 | 74 | `tests/integration/` | API、登录、Authentik、DingTalk、OAuth、门户、Admin 与迁移 |
| 项目脚手架测试 | 1 | `tests/test_project_scaffold.py` | 项目基线与结构 |
| 前端单元/组件测试 | 41 | `frontend/src/**/*.test.ts(x)` | 组件、页面、API 工具、i18n 与状态映射 |
| Playwright 测试文件 | 3 | `frontend/e2e/` | `smoke.spec.ts`、`connector.spec.ts`、`visual-alignment.spec.ts` |
| SDK 测试 | 7 | `sdk/python/tests/` | 客户端、描述符、FastAPI、生命周期、审批和 webhook |

后端测试设置 `src/easyauth/config/settings/test.py` 使用 eager Celery、
`LocMemCache` 和 SQLite 测试数据库语义。它适合快速隔离，但不会自然覆盖真实 Redis、
broker 断连、多 worker 竞争、PostgreSQL `skip_locked`、SQLite 文件锁或独立进程心跳。

前端 Playwright 配置 `frontend/playwright.config.ts` 只启动 Vite，并复用已有
`127.0.0.1:5173` 服务；大量 E2E 数据通过 `page.route()` 模拟。它能覆盖交互和布局，但不能
证明 Django session/CSRF、真实响应契约、数据库写入和前后端完整链路正确。

### 7.2 文档列出的本地质量命令

`README.md` 给出的主要门槛为：

```bash
.venv/bin/python manage.py check
.venv/bin/python manage.py migrate --check
.venv/bin/pytest
.venv/bin/ruff check .
.venv/bin/basedpyright
pnpm --filter @easyauth/frontend test
pnpm --filter @easyauth/frontend build
pnpm --filter @easyauth/frontend e2e
PYTHONPATH=sdk/python/src .venv/bin/pytest sdk/python/tests
```

还应单独验证发布构建：

```bash
uv build
cd sdk/python && python -m build
docker build .
```

仓库没有发现 `.coveragerc`、pytest-cov 配置或 Vitest 覆盖率阈值，也没有发现统一的
`Makefile`、`justfile` 或 `Taskfile`。唯一 GitHub Actions 工作流是
`.github/workflows/docker-build.yml`，它执行多架构镜像构建、SBOM、签名和发布，但没有
显式运行 pytest、ruff、basedpyright、Vitest、Playwright 或 SDK 测试。因此“本地文档列出
命令”不能等价为“合并前持续执行”。

## 8. 部署与运维地图

### 8.1 本地依赖

`docker-compose.yml` 仅提供 PostgreSQL 16 和 Redis 7，并把端口限制在回环地址。Django
通常由宿主的 `manage.py runserver` 启动。

### 8.2 镜像

`Dockerfile`：

- 使用 Node 22 和 pnpm 11.2.2 构建 React。
- 使用 Python 3.12 slim 和 `uv.lock` 安装后端运行依赖。
- 复制 `src/`、`manage.py`、`deploy/webhook-worker-entrypoint.sh` 及前端产物。
- 以 UID 10001 的非 root 用户运行默认 web 进程。
- 默认命令为 Gunicorn，监听 `8001`。
- 健康检查访问 `/health/`。

### 8.3 当前反代部署编排

`docker-compose.deploy.yml` 明确采用开发级 SQLite、`DJANGO_DEBUG=1` 和 Django
`runserver`，同时启动 web、默认 worker、webhook worker、notify worker、beat、DingTalk
Stream 与 Redis。`webhook-worker`、`notify-worker` 以 root 和 `NET_ADMIN` 能力启动，
由 `deploy/webhook-worker-entrypoint.sh` 配置出站 iptables。

这一编排与 `Dockerfile` 的 Gunicorn/PostgreSQL 生产基线、`docker-compose.yml` 的
PostgreSQL 服务，以及 `docs/architecture/easyauth-architecture-design.md` 的 PostgreSQL
架构描述并不一致。审计应把它视为需要明确决策的部署分叉，重点验证：

- 多 Celery 进程与 web 并发写同一 SQLite 的锁、事务与故障恢复。
- `DEBUG=1` 对错误页、静态资源、安全 cookie、HSTS 与代理头的影响。
- `settings/deploy.py` 对 `base.py` 安全分支的实际覆盖结果。
- root + `NET_ADMIN` worker 的最小权限和 iptables 失败模式。
- Docker Desktop 专用 `198.18.0.0/15` 放行是否可能误用于 Linux 生产。
- `/health/` 是否能准确区分 web、worker、beat、stream、通知和外部依赖的部分失效。

## 9. 高风险审计区域与建议交叉检查

### 9.1 第一优先级：授权事实与跨域状态机

主路径跨越：

`src/easyauth/portal/` → `src/easyauth/access_requests/` →
`src/easyauth/workflows/` → `src/easyauth/grants/` →
`src/easyauth/outbox/`、`src/easyauth/webhooks/`、`src/easyauth/connectors/`。

建议交叉检查：

1. 从每个授权写入口反向证明最终只通过 `src/easyauth/grants/services.py` 或受控领域服务写入。
2. 对批准、拒绝、撤回、重试、乱序回调、重复回调、过期和离职并发建立状态转换矩阵。
3. 对 `AccessRequest`、`ApprovalInstance`、`AccessGrant`、`OutboxEvent`、
   `WebhookDelivery` 的幂等键和事务边界做成对检查。
4. 验证失败恢复不会把拒绝或已撤销的授权重新激活。
5. 将 `docs/decisions/ADR-001-业务授权运营边界.md` 和
   `docs/decisions/ADR-002-MANAGED_USERS管理范围契约.md` 的不变量逐条映射到测试。

### 9.2 第一优先级：管理端对象级授权

`src/easyauth/admin_console/` 有 63 个 Python 源文件，
`src/easyauth/admin_console/urls.py` 约 601 行，管理面明显大于公共 API。现有测试虽有
41 个 `tests/integration/admin_console/test_*.py`，但单纯按文件数量仍不足以证明所有方法和
对象分支都覆盖。

建议为 `src/easyauth/admin_console/urls.py` 生成路由清单，并对每个
GET/POST/PUT/PATCH/DELETE 分别确认：

- 未登录返回 401 或登录跳转，而不是空成功。
- 普通员工不能读取管理数据。
- App owner 只能操作自己有 membership 的 App。
- 只有系统管理员能执行全局设置、紧急撤权、成员归属和敏感重试。
- CSRF 对所有 session 写操作生效。
- 列表、详情和重试接口使用相同对象范围。
- 所有安全敏感成功与失败尝试都有正确审计记录且不泄露 secret。

### 9.3 第一优先级：认证、MFA 与凭据

重点文件：

- `src/easyauth/accounts/auth.py`
- `src/easyauth/accounts/oidc_exchange.py`
- `src/easyauth/accounts/views.py`
- `src/easyauth/accounts/local_admin.py`
- `src/easyauth/accounts/local_admin_views.py`
- `src/easyauth/admin_console/two_factor_api.py`
- `src/easyauth/api/authentication.py`
- `src/easyauth/applications/services.py`
- `src/easyauth/applications/oauth.py`
- `src/easyauth/config/crypto.py`
- `src/easyauth/config/rate_limit.py`

建议交叉验证 OIDC state/nonce/issuer/audience/JWKS、会话轮换、登出 state、本地超管强制改密、
TOTP 重放、WebAuthn challenge 与 origin、共享 Redis 限流、静态 token 哈希、OAuth token
失效时间、应用禁用传播和一次性 secret 展示。

### 9.4 第一优先级：出站网络与外部回调

重点文件：

- `src/easyauth/config/net.py`
- `src/easyauth/webhooks/transport.py`
- `src/easyauth/webhooks/delivery.py`
- `src/easyauth/webhooks/signing.py`
- `src/easyauth/integrations/dingtalk/signature.py`
- `src/easyauth/integrations/dingtalk/callbacks.py`
- `src/easyauth/integrations/dingtalk/stream.py`
- `src/easyauth/integrations/authentik/admin_client.py`
- `src/easyauth/connectors/netbird/client.py`
- `deploy/webhook-worker-entrypoint.sh`

建议交叉验证 DNS 重绑定、IPv4/IPv6、重定向、SNI/Host、一域多地址、响应体上限、总时限、
代理环境变量、内网域名、签名时间窗、事件重放、ACK 时机、secret 日志脱敏，以及应用层
URL 校验和容器 iptables 是否采用同一出站策略。

### 9.5 第二优先级：真实并发与后台可靠性

风险主要来自测试设置与生产拓扑差异：

- `src/easyauth/config/settings/test.py` 使用 eager Celery 和 `LocMemCache`。
- `src/easyauth/outbox/services.py` 根据数据库能力选择 `skip_locked`。
- `src/easyauth/notify/services.py`、`src/easyauth/lifecycle/services.py` 是超千行热点。
- `docker-compose.deploy.yml` 使用多个进程共享 SQLite。

建议在 PostgreSQL + Redis + 多 worker 环境补充通知配额竞争、lease 抢占、outbox 发布失败、
任务重复交付、目录同步与撤权并发、审批回调乱序、worker 中途退出和 beat 单实例测试；另对
当前 SQLite 部署做明确的压力与锁冲突实验，不能将单进程 pytest 结果外推为部署可靠性。

### 9.6 第二优先级：前后端真实契约

前端有 41 个单元/组件测试和 3 个 Playwright 文件，但 E2E 大量模拟 API。建议选择下列
真实链路做不模拟验证：

- OIDC 或本地超管登录后进入 `/console`。
- App owner 与普通员工对同一控制台 URL/API 的差异。
- 创建 App、创建凭据、一次性 secret 展示与刷新后消失。
- 门户申请、审批、授权落库、公共权限查询、撤回/撤销。
- TOTP/WebAuthn 配置和强制验证。
- 生命周期交接与失败恢复。
- webhook/连接器配置中的 secret 回显和错误脱敏。
- 中英文切换下的服务端错误、空状态和移动端布局。

### 9.7 第二优先级：文档与实现漂移

`docs/architecture/easyauth-architecture-design.md` 仍出现“Django SSR + HTMX”和
PostgreSQL 单一运行口径，而当前主要 UI 是 React，当前反代编排为 SQLite + runserver。
文档还保留了一些早期模型命名，与当前 `AuthorizationGroup`、
`AuthorizationGroupGrant`、`PermissionGroup` 和生命周期实现可能不完全一致。

建议将下列材料与当前代码逐条核对：

- `docs/architecture/easyauth-architecture-design.md`
- `docs/api/easyauth-public-api.md`
- `docs/api/easyauth-console-api.md`
- `docs/api/easyauth-portal-react-api.md`
- `docs/design/platform-directory-notify/`
- `docs/guides/zero-to-full-deployment.md`
- `README.md`
- `docker-compose.deploy.yml`

### 9.8 第三优先级：持续集成覆盖

`.github/workflows/docker-build.yml` 能证明 Dockerfile 在两个架构上可构建，但不能证明
测试、lint、类型、迁移、SDK 和 E2E 通过。建议新增或在外部流水线中确认以下独立门槛：

- 后端 pytest、ruff、basedpyright。
- PostgreSQL `manage.py check`、全量 migrate、`migrate --check`。
- 前端 Vitest、TypeScript/Vite build、最小真实后端 Playwright。
- SDK 测试、类型/构建和安装烟测。
- 依赖漏洞、许可证、secret 扫描。
- 镜像启动后真实 `/health/` 与静态页面探测。
- 覆盖率报告及关键安全模块的分支阈值。

## 10. 建议的审计分工矩阵

| 审计分工 | 主检查路径 | 必须联查路径 |
| --- | --- | --- |
| 认证与会话 | `src/easyauth/accounts/`、`src/easyauth/config/middleware.py` | `src/easyauth/admin_console/identity.py`、`frontend/src/lib/webauthn.ts`、`tests/integration/auth/` |
| App 凭据与公共 API | `src/easyauth/api/`、`src/easyauth/applications/oauth.py`、`src/easyauth/applications/services.py` | `sdk/python/`、`docs/api/easyauth-public-api.md`、`tests/integration/oauth/` |
| 授权与申请状态机 | `src/easyauth/access_requests/`、`src/easyauth/grants/`、`src/easyauth/workflows/` | `src/easyauth/portal/`、`src/easyauth/outbox/`、`src/easyauth/webhooks/` |
| 控制台越权 | `src/easyauth/admin_console/urls.py`、同目录全部 `*_api.py` | `src/easyauth/applications/ownership.py`、`frontend/src/pages/console/`、`tests/integration/admin_console/` |
| 目录与生命周期 | `src/easyauth/integrations/authentik/`、`src/easyauth/accounts/models.py`、`src/easyauth/lifecycle/` | `src/easyauth/tasks/authentik.py`、`src/easyauth/tasks/lifecycle.py`、`src/easyauth/grants/lifecycle.py` |
| DingTalk 审批与通知 | `src/easyauth/integrations/dingtalk/`、`src/easyauth/notify/` | `src/easyauth/workflows/`、`src/easyauth/tasks/dingtalk_stream.py`、`src/easyauth/tasks/notify.py` |
| webhook、连接器与网络 | `src/easyauth/webhooks/`、`src/easyauth/connectors/`、`src/easyauth/config/net.py` | `deploy/webhook-worker-entrypoint.sh`、`docker-compose.deploy.yml` |
| 数据模型与迁移 | 所有 `models.py`、`*_models.py`、`*/migrations/` | 服务层事务、PostgreSQL 实测、`tests/integration/migrations/` |
| 前端与可访问性 | `frontend/src/` | Django React shell、控制台/门户 API、`frontend/e2e/` |
| 部署与供应链 | `Dockerfile`、两个 compose 文件、`.github/workflows/docker-build.yml` | settings 分层、健康检查、静态构建、README 与部署指南 |
| 文档与 SDK 契约 | `docs/api/`、`sdk/python/`、`tests/contract_samples/` | 后端路由、payload、序列化器、前端 API 类型 |

## 11. 审计完成判定建议

仓库级审计不应只以“所有测试通过”结束。建议至少满足：

1. 所有 HTTP 路由、管理命令、Celery task 和常驻进程都有明确责任人和审计结论。
2. 所有授权写路径都能追踪到单一领域入口、事务、幂等键和审计日志。
3. 所有外部输入和出站请求都覆盖认证、签名、超时、大小限制、重放与 SSRF。
4. 管理端每个写接口都有未登录、普通员工、错误 App owner、正确 App owner、系统管理员的
   对象级授权结论。
5. PostgreSQL、Redis、多 worker 的行为经过真实环境验证，而非只依赖 test settings。
6. 前端至少有一组不模拟 API 的关键业务闭环。
7. SDK、文档、样例与后端公共 API 契约一致。
8. 部署形态已明确选择并消除 SQLite/runserver 与 PostgreSQL/Gunicorn 的口径分叉，或正式
   记录其适用边界、风险和退出条件。
9. CI 明确执行项目声称的质量门槛，并对关键安全模块设置可审查的覆盖率要求。
