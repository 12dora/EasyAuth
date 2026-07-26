# 构建、配置与运维审计报告

## 1. 审计范围与结论

本报告审计仓库基线 `18cd936` 的构建、打包、依赖、环境变量、容器、部署、本地开发、CI 与运行维护配置。审计采用只读源码检查，并在 `git archive HEAD` 生成的临时目录中执行构建、测试和打包，未改动业务源码、配置或真实数据，也未提交 commit。

结论：项目的依赖锁文件、前后端构建、后端与前端测试、Python 主包和 SDK 打包均可完成；但是当前名为“公网反代部署”的实际部署路径仍是开发级配置，公开使用已知开发密钥、`DEBUG=1`、`runserver` 和多进程共享 SQLite。这一部署路径还绕过已签名镜像，并把全部敏感环境变量下发给所有容器。CI 只构建镜像，没有执行仓库自己声明的质量门槛；其中 `ruff` 和 `basedpyright` 在当前基线上实际失败。

发现汇总：

| 编号 | 严重度 | 置信度 | 摘要 |
| --- | --- | --- | --- |
| BCO-01 | 严重 | 高 | 公网部署启用 `DEBUG`，实际使用已知开发签名密钥和字段加密密钥 |
| BCO-02 | 高 | 高 | 六个进程共享 SQLite，数据库文件还以 `0644` 保存敏感 IAM 数据 |
| BCO-03 | 高 | 高 | CI 未执行质量门槛，且当前 `ruff`、`basedpyright` 门槛真实失败 |
| BCO-04 | 高 | 高 | 实际部署不用已签名镜像，并以 bind mount 覆盖镜像内可执行 settings |
| BCO-05 | 高 | 高 | OIDC client secret 和 Authentik API token 被注入全部六个应用容器 |
| BCO-06 | 中 | 高 | README 提供的 ASGI 启动命令依赖未声明，命令无法执行 |
| BCO-07 | 中 | 高 | 文档要求确认 PostgreSQL/Redis healthy，但 Compose 没有 healthcheck |
| BCO-08 | 中 | 高 | GitHub Actions 使用可变标签且单个作业始终申请发布级权限 |
| BCO-09 | 中 | 高 | 工具版本口径漂移，Node 前置条件低于锁定依赖的真实要求 |
| BCO-10 | 低 | 高 | `.env.local` 解析器存在两份实现，入口行为容易漂移 |
| BCO-11 | 低 | 高 | 前端构建和测试持续产生被忽略的警告，测试脚本的参数转发也有缺陷 |
| BCO-12 | 提示 | 高 | 未发现受 Git 跟踪的缓存、备份或常见明文密钥，但工作区残留较多忽略产物 |

## 2. 详细发现

### BCO-01：公网部署启用 `DEBUG`，实际使用已知开发密钥

- 严重度：严重
- 置信度：高
- 证据：
  - `docker-compose.deploy.yml:1` 明确把该文件定义为公网反代部署。
  - `docker-compose.deploy.yml:29-35` 从 `.env.local` 注入环境，并强制设置 `DJANGO_DEBUG: "1"`。
  - `docker-compose.deploy.yml:69-75` 使用 Django `runserver` 对外提供 web 服务。
  - `src/easyauth/config/settings/deploy.py:1-6` 明确说明该 settings 沿用 `DEBUG=1`、SQLite 和 `runserver` 的开发便利。
  - `src/easyauth/config/settings/base.py:15-41` 在 `DEBUG=1` 且未配置变量时，使用固定的 `django-insecure-easyauth-local-dev-only` 和 `easyauth-insecure-field-encryption-local-dev-only`。
  - `src/easyauth/config/settings/base.py:116-127` 在相同条件下回退仓库根目录 SQLite。
  - `src/easyauth/config/crypto.py:31-47` 直接从 `EASYAUTH_FIELD_ENCRYPTION_KEY` 的 SHA-256 摘要派生 Fernet 密钥。
  - 当前 `.env.local:14` 设置 `DJANGO_DEBUG=1`；对变量名进行脱敏检查后，文件不含 `DJANGO_SECRET_KEY`、`EASYAUTH_FIELD_ENCRYPTION_KEY` 或 `DATABASE_URL`。
  - `README.md:354-388` 的生产口径要求恰好相反：必须设置密钥和 PostgreSQL，并保持 `DJANGO_DEBUG=0`。
- 复现/检查输出：

```text
DJANGO_DEBUG=1
DEBUG= True
SECRET_KEY_is_known_dev_default= True
FIELD_KEY_is_known_dev_default= True
DB_ENGINE= django.db.backends.sqlite3
known-dev-key-decrypts-stored-dingtalk-secret= True
plaintext-output=已禁止
```

- 影响：
  - Django 签名安全建立在公开、固定的开发密钥上；一切依赖 `SECRET_KEY` 的签名对象都不再具备生产可信度。
  - 数据库中的 `EncryptedCharField` 使用公开、固定的字段密钥加密；只要取得 SQLite 文件即可离线解密其中的钉钉等敏感凭据。审计已经在只读连接中验证当前已存钉钉 secret 能被该公开开发密钥解密，但没有输出、保存或传递任何明文。
  - `DEBUG=1` 和开发服务器扩大错误信息泄漏、静态文件处理和拒绝服务风险。
  - 文档中的生产护栏实际被“完整部署”指南绕过，部署者容易把开发级形态误认为正式形态。
- 直接整改：
  1. 删除公网部署中的 `DJANGO_DEBUG=1`、`runserver` 和 SQLite 分支，不能再保留同名“开发级公网部署”兼容路径。
  2. 让唯一生产 Compose 强制要求 `DJANGO_SECRET_KEY`、`EASYAUTH_FIELD_ENCRYPTION_KEY`、`DATABASE_URL`、Redis URL 和生产域名配置，缺失即由 Compose 插值或 settings 启动检查失败。
  3. web 使用镜像默认的 Gunicorn；由反向代理或专用静态文件服务提供 `/static/`。
  4. 在切换前生成新的随机密钥，并在受控迁移中用旧字段密钥解密、用新字段密钥重加密现有敏感字段；不能直接换键导致现有密文不可读。

### BCO-02：六个进程共享 SQLite，数据库文件权限过宽

- 严重度：高
- 置信度：高
- 证据：
  - `docker-compose.deploy.yml:15-18` 承认该部署使用 SQLite，并仅按“web 与 worker、低频任务”评估锁竞争。
  - `docker-compose.deploy.yml:52-53` 把同一个 `db.sqlite3` 挂载到公共服务模板。
  - `docker-compose.deploy.yml:69-174` 实际启动 web、默认 worker、webhook worker、notify worker、beat 和 stream，共六个会读取或写入共享状态的进程；原注释已低估当前拓扑。
  - `docs/guides/zero-to-full-deployment.md:46-53` 把这一 SQLite 拓扑作为完整部署操作步骤。
  - `src/easyauth/applications/integration_settings.py:35-46` 在数据库中保存加密的 Authentik token 和钉钉 AppSecret。
  - `db.sqlite3` 是文件系统对象，无行号；当前大小为 30,261,248 字节、权限为 `0644`，且只读计数确认其中有 1 条非空钉钉 secret、5 条应用凭据和 1 个本地管理员记录。检查未读取或输出任何密文、token、用户名或口令。
- 复现/检查输出：

```text
db.sqlite3 mode=-rw-r--r--(644) size=30261248 bytes
IntegrationSettings rows|1
nonempty dingtalk secret rows|1
app credential rows|5
local admin rows|1
```

- 影响：
  - 多 Celery worker、stream 与 web 的并发写入会产生 `database is locked`、延迟尖峰和事务失败；任务量增长后风险会放大。
  - `0644` 允许同机其他账号读取 IAM 数据库。结合 BCO-01 的已知字段密钥，数据库内加密凭据可被离线解密。
  - SQLite 单文件没有仓库内备份、恢复演练或一致性快照流程，故障域与部署目录绑定。
- 直接整改：
  1. 立即把现有 `db.sqlite3` 权限收紧为 `0600`，并确认部署目录及备份同样只允许服务账号读取。
  2. 一次性迁移到 PostgreSQL，所有 web/worker/beat/stream 服务只使用同一强制 `DATABASE_URL`；迁移后移除 SQLite bind mount 和 `touch db.sqlite3` 步骤。
  3. 为 PostgreSQL 建立加密备份、保留周期、恢复演练和明确的 RPO/RTO；验证迁移行数与关键业务不变量后再切流。

### BCO-03：CI 未执行质量门槛，当前静态检查已经失败

- 严重度：高
- 置信度：高
- 证据：
  - `.github/workflows/docker-build.yml:20-71` 唯一作业只执行多架构 Docker 构建。
  - 工作流中不存在 `pytest`、`ruff check`、`basedpyright`、`manage.py check`、`migrate --check`、Vitest 或 Playwright 命令。
  - `README.md:481-492` 却把上述命令定义为“测试与质量门槛”。
  - `pyproject.toml:43-47`、`pyproject.toml:49-80`、`pyproject.toml:83-89` 已配置 pytest、Ruff 和严格 basedpyright，但 CI 没有消费这些配置。
- 复现/检查输出：

```text
pytest=无
ruff check=无
basedpyright=无
manage.py check=无
migrate --check=无
vitest=无
playwright=无

ruff check .:
Found 15 errors.

basedpyright:
1718 errors, 0 warnings, 0 notes

后端测试:
1291 passed, 1 skipped in 59.61s

前端测试:
Test Files 41 passed (41)
Tests 295 passed (295)

SDK 测试:
69 passed, 2 skipped
```

- 影响：
  - PR 可以在 lint、类型、迁移完整性或单元测试失败时通过唯一 CI。
  - README 所称“门槛”目前只是人工命令清单，并不是可执行的合并保护。
  - 大量既有类型错误形成不可用基线；后续真实回归会被错误噪声淹没。
- 直接整改：
  1. 先正本清源修完 Ruff 错误；为 basedpyright 明确实际边界，迁移文件若不做类型检查应像 Ruff 一样显式排除，然后把其余错误清零，不要以全局关闭规则或扩大 `Any` 掩盖问题。
  2. 新增独立 CI 作业并强制成功：`uv lock --check`、Django check、`makemigrations --check --dry-run`、测试、Ruff、basedpyright、前端类型检查/测试/构建、SDK 测试。
  3. Docker 发布作业依赖所有质量作业成功；tag 发布还应验证版本号与项目元数据一致。

### BCO-04：运行形态绕过已签名镜像，且覆盖镜像内代码

- 严重度：高
- 置信度：高
- 证据：
  - `.github/workflows/docker-build.yml:58-87` 构建、生成 provenance/SBOM，并用 Cosign 签名 GHCR 镜像。
  - `docker-compose.deploy.yml:26-27` 实际使用 `easyauth-web:local`，没有引用 GHCR digest 或签名验证结果。
  - `docs/guides/zero-to-full-deployment.md:46-53` 指示本地构建该镜像后直接启动。
  - `docker-compose.deploy.yml:54-55` 又把宿主机 `deploy.py` 覆盖挂载到镜像内 Python 源码路径，注释称用于“省一次重建”。
- 复现/检查输出：

```text
实际部署镜像：easyauth-web:local
运行时源码覆盖：./src/easyauth/config/settings/deploy.py -> /app/src/easyauth/config/settings/deploy.py
CI 产物：ghcr.io/...@<digest>，带 provenance、SBOM 和 Cosign 签名
```

- 影响：
  - 签名、SBOM 和 provenance 描述的不是实际运行代码；宿主机对 `deploy.py` 的任意修改无需构建、审查或签名即可生效。
  - 无法按镜像 digest 准确回滚，也无法证明线上进程与 CI 产物一致。
- 直接整改：
  1. 生产 Compose 只引用不可变 GHCR digest，并在部署门禁中执行 Cosign 验证。
  2. 删除 settings 源码 bind mount；配置差异只能通过已定义环境变量表达，代码变化必须重新构建、测试和签名。
  3. 开发 Compose 与生产 Compose 分离命名和文档，生产指南不得再构建或运行 `:local` 镜像。

### BCO-05：全部应用容器获得全部敏感环境变量

- 严重度：高
- 置信度：高
- 证据：
  - `docker-compose.deploy.yml:26-31` 在公共 anchor 上加载完整 `.env.local`。
  - `docker-compose.deploy.yml:69-174` 的 web、worker、webhook-worker、notify-worker、beat、stream 全部继承该 anchor。
  - `docker-compose.deploy.yml:95-104` 和 `docker-compose.deploy.yml:125-133` 让两个处理出站任务的 worker 以 root 启动并授予 `NET_ADMIN`，同时仍继承完整环境。
  - 当前 `.env.local:4-10` 包含 Authentik API token、OIDC client id/secret 和相关端点；本报告未读取或输出变量值。
- 复现/检查输出：

```text
含敏感 OIDC/API 凭据的服务：
beat
notify-worker
stream
web
webhook-worker
worker
含敏感 OIDC/API 凭据的服务数=6
```

- 影响：
  - 任一队列消费者、Webhook 处理链或容器逃逸面的漏洞都能读取与其职责无关的 OIDC client secret 和 Authentik 管理 token。
  - webhook/notify worker 允许访问公网 HTTPS，取得的多余密钥可直接外传，出站防火墙不能形成有效秘密隔离。
- 直接整改：
  1. 为每个服务定义最小环境变量集合，不再使用携带全部密钥的公共 `env_file`。
  2. OIDC client secret 只给 web；目录管理 token 只给确实执行 Authentik 管理操作的默认 worker/stream；webhook 与 notify 专用 worker只获得 broker、缓存和其业务必需凭据。
  3. 使用 Docker secret、编排器 secret 或外部密钥管理系统以文件方式注入，并在轮换后验证旧凭据立即失效。

### BCO-06：README 的 ASGI 启动命令缺少依赖

- 严重度：中
- 置信度：高
- 证据：
  - `README.md:367-374` 推荐 `.venv/bin/uvicorn easyauth.config.asgi:application ...`。
  - `pyproject.toml:7-23` 的运行依赖只有 Gunicorn，没有 Uvicorn。
  - `uv.lock` 不含名为 `uvicorn` 的包。
- 复现/检查输出：

```text
.venv/bin/uvicorn: 不存在
uv.lock 中 name = "uvicorn" 的匹配数：0
```

- 影响：按生产文档选择 ASGI 的部署会在启动阶段直接失败；新环境无法从锁文件复现文档命令。
- 直接整改：如果项目没有 ASGI 运行需求，删除 Uvicorn 分支并只保留已锁定、已验证的 Gunicorn 命令；如果确需 ASGI，则把 Uvicorn 加入运行依赖和锁文件，并在 CI 中真实启动和探测 ASGI 服务。

### BCO-07：数据服务没有健康检查，文档步骤不可执行

- 严重度：中
- 置信度：高
- 证据：
  - `docker-compose.yml:1-20` 定义 PostgreSQL 和 Redis，但两者都没有 `healthcheck`。
  - `README.md:408-410` 要求“确认两者 healthy 再继续”。
  - `docker-compose.deploy.yml:59-67` 也只按容器启动顺序依赖 Redis，没有 Redis healthcheck。
  - `docker-compose.yml:3` 和 `docker-compose.yml:15` 使用可变的 `postgres:16`、`redis:7` 标签，而部署文件的 Redis 又使用 digest，口径不一致。
- 复现/检查输出：

```text
postgres: healthcheck=缺失, image=postgres:16
redis: healthcheck=缺失, image=redis:7
```

- 影响：
  - `docker compose ps` 只能显示 started/running，不能满足文档中的 healthy 判定。
  - 迁移或应用进程可能在数据服务尚未就绪时启动并失败。
  - 可变镜像标签使不同日期的同一命令得到不同二进制，回滚和供应链审计不稳定。
- 直接整改：为 PostgreSQL 配置 `pg_isready`、为 Redis 配置 `redis-cli ping`，应用服务使用 `condition: service_healthy` 或等价的显式就绪门禁；所有基础镜像统一固定到经验证的 patch 版本和 digest，并通过受控依赖更新 PR 升级。

### BCO-08：GitHub Actions 供应链与权限边界过宽

- 严重度：中
- 置信度：高
- 证据：
  - `.github/workflows/docker-build.yml:23-26` 的唯一作业始终申请 `contents: write`、`id-token: write` 和 `packages: write`。
  - `.github/workflows/docker-build.yml:28-60`、`.github/workflows/docker-build.yml:73-93` 的第三方 Action 都使用 `@v2`、`@v3`、`@v4`、`@v5` 或 `@v6` 可变标签，而不是不可变 commit SHA。
  - 该作业也在 `pull_request` 触发，尽管登录、签名和发布步骤稍后才用条件跳过。
- 影响：
  - 上游 Action 标签被移动或供应链被入侵时，工作流会执行未经本仓审核的新代码。
  - 构建与发布权限集中在同一个作业，违反最小权限；后续新增步骤时容易意外让 PR 路径接触发布能力。
- 直接整改：把 PR 构建、main 推送、tag 发布拆为最小权限作业；默认 `contents: read`，只在发布作业授予 `packages: write`、`id-token: write` 和必要的 release 权限；所有第三方 Action 固定完整 commit SHA，并由 Dependabot/Renovate 提交可审查升级。

### BCO-09：工具版本和运行时要求存在漂移

- 严重度：中
- 置信度：高
- 证据：
  - `Dockerfile:12` 固定 pnpm `11.2.2`，但 `frontend/package.json:1-38` 没有 `packageManager` 字段，仓库也没有根 `package.json`、`.node-version` 或 `.nvmrc`。
  - `Dockerfile:35-45` 使用 uv `0.8.22` 解释锁文件；`uv.lock:1491-1494` 锁定的开发环境 uv 已是 `0.11.19`。
  - `README.md:239-242` 只要求 Node ≥ 20；`pnpm-lock.yaml:1244-1246` 中实际 Vite 要求 Node `^20.19.0 || >=22.12.0`。
  - `pyproject.toml:6` 声明支持 Python 3.12、3.13、3.14，但 `Dockerfile:25` 和 `.github/workflows/docker-build.yml:58-71` 只验证 Python 3.12 镜像，`pyproject.toml:83-89` 的类型检查也固定 3.12。
- 影响：
  - 新开发机可能选择 Node 20.0–20.18，安装或构建时才发现不兼容。
  - Docker 与本地使用不同代际的 uv 解释同一个锁文件，锁格式或解析语义升级后会出现只在镜像构建时暴露的问题。
  - 声明支持的 Python 3.13/3.14 没有自动验证，兼容承诺缺乏证据。
- 直接整改：
  1. 在前端包声明 `"packageManager": "pnpm@11.2.2"`，增加受版本管理的 Node 版本文件，并把 README 条件改为与锁文件一致。
  2. 选定一个 uv 版本作为单一事实源，同时更新 Dockerfile、开发引导和锁文件生成环境；不要把 uv 本身作为项目 dev 依赖来间接决定工具版本。
  3. 要么增加 Python 3.12/3.13/3.14 测试矩阵，要么把 `requires-python` 收窄到实际受支持的 3.12。

### BCO-10：`.env.local` 解析器重复实现

- 严重度：低
- 置信度：高
- 证据：
  - `manage.py:11-44` 实现一套 `load_local_env` 和 `_unquote_env_value`。
  - `src/easyauth/config/local_env.py:7-41` 存在几乎相同的第二套实现。
  - `manage.py:14-17` 使用第一套；`src/easyauth/config/wsgi.py:7-11` 和 `src/easyauth/config/asgi.py:7-11` 使用第二套。
  - 当前只有 `tests/unit/config/test_manage_local_env.py:31` 直接覆盖 manage.py 版本。
- 影响：管理命令、WSGI 和 ASGI 入口以后可能对引号、空值、错误行或环境变量优先级产生不同解释；只修改或测试其中一份不会暴露另一入口的回归。
- 直接整改：删除 manage.py 内的复制实现，三个入口统一调用 `easyauth.config.local_env.load_local_env()`；对同一函数覆盖存在文件、缺失文件、引号、空值、不覆盖既有进程环境等用例。

### BCO-11：前端警告未形成预算，测试脚本参数转发有缺陷

- 严重度：低
- 置信度：高
- 证据：
  - `frontend/vite.config.ts:16-22` 只有单入口，没有分包策略或产物体积预算。
  - `frontend/package.json:10` 用 `node -e`、`spawnSync(..., shell: true)` 包装 Vitest。
  - `.github/workflows/docker-build.yml:58-71` 只把 Vite 构建警告当普通输出，不执行前端测试。
- 复现/检查输出：

```text
main-CNN3Qfdd.js  826.08 kB │ gzip: 217.92 kB
(!) Some chunks are larger than 500 kB after minification.

CI=1 pnpm --filter @easyauth/frontend test:
41 个测试文件、295 个测试通过，但 Node 26 重复输出 localStorage ExperimentalWarning。

pnpm --filter @easyauth/frontend test --run:
node: --run requires an argument
Exit status 9
```

- 影响：
  - 首屏下载、解析和执行成本持续增长时，构建仍为成功，性能回归没有自动边界。
  - 高频警告降低日志信噪比；测试包装器不能可靠透传以 `--` 开头的 Vitest 参数。
- 直接整改：把测试脚本改成直接执行 `vitest run`，需要按路径筛选时让 pnpm 原样透传参数，不再经过 shell 字符串；固定受支持 Node 版本并消除 `localStorage` 警告；按路由或功能做动态导入，给主入口设置经测量确定的 gzip/原始体积预算并在 CI 超限失败。

### BCO-12：工作区卫生检查结果

- 严重度：提示
- 置信度：高
- 证据：
  - `.gitignore:1-23` 和 `.dockerignore:5-43` 已排除环境文件、SQLite、Node/Python 缓存、构建产物和测试报告。
  - 文件系统中仍存在 `.DS_Store`、`docs/.DS_Store`、`docs/design/.DS_Store`、大量 `__pycache__`、`dist/`、`node_modules/` 和测试缓存；它们均未受 Git 跟踪。
  - `.env.local` 权限为 `0600`，且不受 Git 跟踪。
- 复现/检查输出：

```text
受 Git 跟踪的缓存/备份文件数=0
常见私钥、GitHub token、AWS access key、OpenAI key 模式匹配数=0
.env.local mode=-rw-------(600)
```

- 影响：当前没有发现会进入版本库或镜像的缓存/备份泄漏；但本地残留会增加人工排查噪声，`db.sqlite3` 的安全问题已单列为 BCO-02。
- 直接整改：保留现有 ignore 规则；定期以明确路径清理 `.DS_Store` 和失效缓存，不要对仓库根执行宽泛递归删除；在 CI 增加受跟踪 secret 扫描和镜像 secret 扫描。

## 3. 成功验证与其他观察

以下检查在临时归档目录中成功：

```text
uv lock --check：通过，Resolved 73 packages
pnpm install --frozen-lockfile：通过，pnpm 11.2.2
前端 build：通过，1824 modules transformed
前端测试：41 files / 295 tests 通过
Django check：System check identified no issues
migrate 后 migrate --check：通过
makemigrations --check --dry-run：No changes detected
后端测试：1291 passed, 1 skipped
SDK 测试：69 passed, 2 skipped
主包 sdist/wheel：构建成功
SDK sdist/wheel：构建成功
docker-compose.yml（提供占位密码）config --quiet：通过
docker-compose.deploy.yml config --quiet：通过
```

依赖使用扫描未发现明确可安全删除的主依赖或前端直接依赖。`redis` 虽也由 Celery extra 间接引入，但应用在 `src/easyauth/config/urls.py:5` 直接导入它，仍应保留为直接运行依赖。当前更需要处理的是工具版本和运行时声明漂移，而不是在缺少运行路径证据时猜测删除依赖。

## 4. 建议整改顺序

1. 立即停止把 `docker-compose.deploy.yml` 作为公网生产配置使用，轮换签名密钥和字段加密密钥，并收紧现有 SQLite 文件权限。
2. 一次性迁移 PostgreSQL，删除 SQLite、`DEBUG=1`、`runserver` 和 settings 源码挂载的部署路径。
3. 改用已签名的不可变 GHCR digest，并按服务拆分 secrets。
4. 清零 Ruff/basedpyright 基线，建立阻断式 CI，再允许镜像发布。
5. 修正文档命令、健康检查、Action pin、工具版本和前端预算等中低风险问题。
