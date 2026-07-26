# 后端测试腐化审计

审计日期：2026-07-27

审计范围：

- Django 后端：`tests/`、`src/easyauth/`、根目录 `pyproject.toml`、测试设置与 GitHub Actions。
- Python SDK：`sdk/python/tests/`、`sdk/python/src/easyauth_app_sdk/`、`sdk/python/pyproject.toml`。
- 本次只审计并新增本报告，没有修改、删除测试或业务代码，也没有提交 commit。

## 结论摘要

当前测试并非“红灯失修”：本机主套件是 `1291 passed, 1 skipped`，SDK 正确设置
`PYTHONPATH` 后是 `69 passed, 2 skipped`。真正的问题是测试入口和测试替身制造了大面积
假绿灯：

1. 仓库唯一 GitHub Actions 工作流只构建镜像，不运行主后端、SDK、迁移检查或静态检查；
   根目录默认 `pytest` 也不会收集 SDK。
2. 默认测试数据库是 SQLite，生产 PostgreSQL 的并发与行锁语义只写了一个测试，而且该测试
   在默认套件中永远跳过；代码中有 23 个文件、61 处 `select_for_update`。
3. 控制台测试用一个名为“legacy bridge”的全局 fixture，把 Django 测试登录偷偷改造成
   Authentik 会话。移除该 fixture 后，抽样用例从通过变成 401。
4. 一个放在 `tests/unit/` 的用例会真实探测 Authentik 和 Celery；其单次 call 稳定耗时约
   6.4 秒，并受本机网络、DNS、Redis/broker 状态影响。
5. SDK 最关键的 FastAPI 适配层在默认环境中整文件跳过；正向 legacy 兼容测试又在持续保护
   项目硬约束明确禁止的兼容输入和兼容字段。

建议先修复测试门禁和假绿灯，再做测试删减。否则删除低价值测试只会让一个没有生产数据库
并发验证、没有 SDK/FastAPI 门禁的套件更快地返回绿色。

## 执行结果与方法

| 命令 | 结果 | 观察 |
|---|---:|---|
| `.venv/bin/pytest -ra --durations=30` | 成功 | 收集 1292 项；`1291 passed, 1 skipped in 176.00s`。唯一跳过是 PostgreSQL 通知配额并发测试。 |
| `.venv/bin/pytest -ra --durations=20 sdk/python/tests` | 失败 | `5 errors, 2 skipped`；5 个模块均因 `ModuleNotFoundError: easyauth_app_sdk` 收集失败。 |
| `PYTHONPATH=sdk/python/src .venv/bin/pytest -ra --durations=20 sdk/python/tests` | 成功 | `69 passed, 2 skipped in 0.59s`；两个 FastAPI 测试模块整文件跳过。 |
| `.venv/bin/pytest -q --noconftest tests/integration/admin_console/test_onboarding_templates_api.py::test_superuser_toggles_onboarding_template_status` | 失败 | 原本通过的用例得到 401，断言期望 200；证明其依赖全局认证桥接 fixture，而非测试自身建立真实控制台会话。 |
| `.venv/bin/pytest -q --durations=3 tests/unit/applications/test_dependency_health_notify.py::test_notify_check_included_in_full_run` | 成功但过慢 | call 6.39 秒，setup 3.55 秒，总计 10.01 秒；该“单元测试”执行真实依赖探测。 |

静态审计共扫描 `tests/` 与 `sdk/python/tests/` 下 217 个 Python 文件、1185 个
`test*` 函数（参数化后主套件为 1292 项），并检查了跳过/xfail、直接断言、完全相同 AST
测试体、全局可变状态、时间/网络调用、数据库事务、兼容口径和生产任务入口：

- 没有发现 `xfail`。
- 没有发现完全相同的测试函数体。
- 主套件有 1 个跳过项，SDK 有 2 个整模块跳过项。
- 除调用断言 helper 的测试外，发现 3 个实际收集且没有任何直接断言/异常断言的正向用例。
- 没有在本次顺序下复现普通数据库测试的跨用例污染；但已发现全局 fixture、类变量和本地
  socket 等共享状态/环境敏感点，详见下文。

## 详细发现

### BTD-01：没有任何自动化后端测试门禁

严重度：严重；置信度：高；处置：修复并补充门禁，不能删除现有测试

证据：

- 根配置只把 `tests` 设为 `testpaths`：`pyproject.toml:43-47`。
- SDK 是独立 src-layout 包：`sdk/python/pyproject.toml:5-17`，正确命令必须额外设置
  `PYTHONPATH=sdk/python/src`，文档也明确如此：`README.md:481-493`、
  `sdk/python/README.md:232-236`。
- 唯一工作流 `.github/workflows/docker-build.yml:20-71` 只执行 Docker Buildx 构建；
  `Dockerfile:43-54` 只安装运行时依赖并复制源码，没有复制或运行测试。
- 实测从根目录直接指定 SDK 测试得到 5 个收集错误；只运行默认 `.venv/bin/pytest`
  则完全不收集 SDK。

危害：

- PR 可以在主后端、SDK 或 FastAPI 适配全部失败时仍通过唯一 GitHub 检查。
- README 中的“质量门槛”只是人工命令清单，不是可执行门禁。
- 默认 `pytest` 的绿色容易被误读成“整个 Python 仓库通过”。

精确回归要求：

1. 新增 Linux CI 快速作业，固定执行：
   `manage.py check`、`manage.py migrate --check`、主 pytest、ruff、basedpyright。
2. 新增 SDK 作业，从 `sdk/python` 安装 `.[fastapi]` 后执行全部 SDK 测试；不得依赖调用者
   手写 `PYTHONPATH`。
3. CI 必须显示主套件和 SDK 的收集数量，并以“出现任何 skip”为失败或维护显式 skip
   白名单，防止整模块静默退出。
4. Docker 发布作业必须依赖上述作业成功。

### BTD-02：生产 PostgreSQL 的并发正确性没有进入默认回归

严重度：严重；置信度：高；处置：保留 SQLite 快速层，新增 PostgreSQL 必跑层；把现有 skip 改为
PostgreSQL 作业中的必跑测试

证据：

- 测试设置使用从基础设置继承的数据库；未提供 `DATABASE_URL` 时走 SQLite：
  `src/easyauth/config/settings/base.py:104-128`、`src/easyauth/config/settings/test.py:5-18`。
- 唯一显式 PostgreSQL 测试
  `tests/integration/notify/test_quota_concurrency.py:19-28` 在非 PostgreSQL 下整模块跳过。
- 实测跳过信息：
  `SKIPPED tests/integration/notify/test_quota_concurrency.py:28:
  并发配额锁需要 PostgreSQL 行锁语义。`
- 生产代码共有 23 个文件、61 处 `select_for_update`。例如：
  - 通知配额：`src/easyauth/notify/services.py:353-365`；
  - outbox 的 `skip_locked` 分支：`src/easyauth/outbox/services.py:102-136`；
  - 交接任务：`src/easyauth/lifecycle/services.py:552-588`；
  - 审批实例：`src/easyauth/workflows/services.py:130-156`；
  - 本地管理员 TOTP 原子消费依赖条件更新：`src/easyauth/accounts/local_admin.py:277-293`。
- 整个测试树只有 4 处 `django_db(transaction=True)`，远少于生产锁边界。

危害：

- SQLite 上 `select_for_update` 不提供生产行锁语义；绿色无法证明重复投递、双审批、
  outbox 多 worker 抢占、交接并发和配额计数是原子的。
- 当前唯一真正覆盖 PostgreSQL 语义的测试恰好在开发者最常执行的套件中跳过。

精确回归要求：

1. PostgreSQL 作业并发执行两个 `accept_notify_message`，断言恰好一个 accepted、一个
   throttled，并断言数据库只计入一个受理收件人。
2. 两个独立连接同时调用 outbox `_claim_events`，断言 `skip_locked` 下同一事件只被一个
   worker 发布，且两批 claim 集合不相交。
3. 两个事务同时审批/回调同一 `ApprovalInstance`，断言状态只推进一次、回调/审计副作用
   只产生一次。
4. 两个事务同时执行 lifecycle 交接确认或 grant apply，断言无重复当前授权、无丢失更新。
5. 两个独立会话并发消费同一 TOTP timestep，断言恰好一个成功。
6. PostgreSQL lane 不得使用 `skipif`；连接不到数据库应令作业失败。

### BTD-03：控制台测试的 legacy 登录桥制造大面积假绿灯

严重度：严重；置信度：高；处置：删除该 autouse 桥接 fixture，替换 26 个受影响文件的登录 helper

证据：

- `tests/integration/admin_console/conftest.py:15-40` 的 autouse fixture 名为
  `bridge_legacy_client_login_to_authentik_session`。它 monkeypatch 全局
  `Client.login`，在普通 Django 登录成功后自动创建 `UserMirror`，写入
  `AUTHENTIK_SESSION_KEY`，并给 Django superuser 注入 Authentik 管理员组。
- 生产授权只读取 Authentik/本地管理员会话，不读取 Django `request.user`：
  `src/easyauth/admin_console/identity.py:16-39`。
- 共有 26 个控制台测试文件、33 次 `client.login(...)` 依赖或可能依赖该桥。例：
  `tests/integration/admin_console/test_onboarding_templates_api.py:74-78`。
- 抽样用例在正常套件中通过；用 `--noconftest` 去掉桥后，
  `test_superuser_toggles_onboarding_template_status` 在
  `tests/integration/admin_console/test_onboarding_templates_api.py:39-44` 得到 401 而不是 200。

危害：

- 测试声称验证 Authentik 控制台权限，实际先走一个生产中不存在的 Django 用户名/密码登录，
  再由 fixture 悄悄伪造会话。
- fixture 同时伪造身份事实和授权组，能够掩盖会话键、用户镜像状态、组映射或认证中间件的
  回归。
- helper 自带 `assert client.login(...) is True`，让测试输出看似验证了登录，但断言的是
  不相关的 Django auth。

精确回归要求：

1. 删除 bridge 后，提供两个显式 fixture：
   “已验证 Authentik 会话”和“已验证本地管理员会话”；它们必须直接建立各自真实生产会话
   契约，不得调用 `Client.login`。
2. 每个控制台端点至少覆盖 anonymous=401、active 普通用户=403/按成员权限处理、
   配置组内管理员=允许。
3. 增加反向测试：只有 Django `_auth_user_id`、没有 `AUTHENTIK_SESSION_KEY` 的客户端必须
   返回 401。
4. 增加 inactive/missing `UserMirror` 后旧会话立即失效的集成测试。

### BTD-04：“单元测试”会真实访问 Authentik 和 Celery

严重度：高；置信度：高；处置：修复；保留纯编排断言，另建显式外部依赖冒烟层

证据：

- `tests/unit/applications/test_dependency_health_notify.py:101-105` 为了断言通知检查被包含，
  直接调用 `run_dependency_health_checks()`，没有替换其他探测器。
- 被调函数明确执行真实探测：
  `src/easyauth/applications/dependency_health_checks.py:67-77`。
- Authentik liveness 在 `src/easyauth/applications/dependency_health_checks.py:92-109`
  发请求；Celery 在 `src/easyauth/applications/dependency_health_checks.py:315-342`
  对 broker 执行 `control.ping(timeout=1.0)`。
- 完整套件 slowest 记录该用例 call 6.40 秒；单独复跑 call 6.39 秒。

危害：

- 无 Authentik/Redis 的离线开发机、受限 CI、DNS 异常环境会让“单元测试”变慢或行为变化。
- 测试只断言结果中存在 `dingtalk_notify`，即使其他五个真实探测全部失败也仍然通过；它既
  付出了外部集成成本，又没有验证外部结果。

精确回归要求：

1. 将 `run_dependency_health_checks` 的检查器列表变为可注入的单一事实源，测试注入 6 个
   固定返回的真实类型 fake，断言每个检查器恰好调用一次、六种快照全部持久化且脱敏。
2. `check_dingtalk_notify` 的业务测试继续直接调用该纯检查器。
3. 如需真实探测，另建带 `external` marker 的部署后冒烟测试，明确要求 Authentik、Redis
   和 worker；不得混入默认单元/集成回归。

### BTD-05：SDK FastAPI 产品面整模块静默跳过

严重度：高；置信度：高；处置：修复测试环境与 CI，不删除

证据：

- `sdk/python/tests/test_fastapi.py:3-11` 和
  `sdk/python/tests/test_lifecycle_fastapi.py:8-16` 在 import 时使用
  `pytest.importorskip`。
- 实测 SDK 仅收集 69 项，两个模块各报告一次 skip；被跳过的实际用例有 3 个描述符路由
  测试和 5 个生命周期路由测试。
- FastAPI 是 README 和接入指南直接推荐的集成入口：
  `sdk/python/README.md:20`、`docs/guides/easyauth-app-sdk-integration.md:21`。
- 适配层包含运行时注解、流式 body 上限和验签前读取等易回归逻辑：
  `sdk/python/src/easyauth_app_sdk/fastapi.py:31-100`。

危害：

- 核心框架升级造成路由注册、Request 注解、流式读取或响应类型破坏时，默认 SDK 套件仍绿。
- “可选运行时依赖”不等于“可选测试依赖”；发布 SDK 必须验证所有声明 extra。

精确回归要求：

1. SDK CI 安装 `easyauth-app-sdk[fastapi]`，8 个 FastAPI 用例必须全部收集且不允许 skip。
2. 保留一个最小依赖作业，验证不安装 FastAPI 时导入 SDK 核心模块仍成功；该作业不运行
   FastAPI 测试文件。
3. 新增分块/无 `Content-Length` 超限、负/非法 `Content-Length`、callback 抛错 500、
   自定义 path 的路由回归。

### BTD-06：正向 legacy 兼容测试持续保护被项目硬约束禁止的形态

严重度：高；置信度：高；处置：删除正向兼容行为并用 canonical 契约测试替换；
负向“旧入口保持关闭”测试应保留

证据：

- 项目规则仅允许写入白名单、外部契约或短期迁移窗口且写明移除条件的兼容；全仓检索没有
  找到任何 legacy 白名单或移除条件。
- SDK 明确保留兼容前缀和行为：
  - `sdk/python/src/easyauth_app_sdk/client.py:35-36` 定义
    “Legacy-only/deprecated” `dt:` 前缀；
  - `sdk/python/src/easyauth_app_sdk/client.py:201-206` 允许裸 user id/旧 `dt:<id>`；
  - `sdk/python/src/easyauth_app_sdk/client.py:426` 对非统一错误保留旧文本回退。
- 服务端也接受非 scoped 引用：
  `src/easyauth/accounts/directory_references.py:56-74`、
  `src/easyauth/accounts/directory_references.py:88-110`。
- 数据库专门保留 legacy 唯一约束：
  `src/easyauth/notify/models.py:263-286`；对应正向测试
  `tests/unit/notify/test_recipient_scope.py:164-199` 明确要求 legacy 行继续受支持。
- `tests/unit/accounts/test_directory_references.py:42-46` 要求 legacy department id 保持有效。
- `tests/integration/admin_console/test_apps_contract_compat.py:39-65` 的注释明确要求
  “同时保留旧字段并包含兼容字段”。
- 迁移测试 `tests/integration/migrations/test_notification_channel_migrations.py:124-153`
  及 `:254-493` 大量维护 legacy message/environment fallback；该文件 4 个测试约占完整套件
  slowest 榜的 19 秒以上。

危害：

- 这些测试会阻止删除兼容分支，使错误/歧义数据模型长期固化。
- 裸 `dt:<id>` 在多企业目录下天然歧义；测试现在保护的是“遇到歧义再失败”，而不是从输入
  契约上消除歧义。
- 尚未上线的项目为未部署历史数据支付迁移和测试维护成本。

精确处置：

1. 先确认是否存在未入库的外部系统契约；若没有，删除裸 user/dept 引用解析、legacy
   recipient 约束、SDK 旧错误回退及对应正向测试，只保留 opaque scoped ref。
2. 若确有外部契约，必须建立正式白名单文档，写明调用方、截止版本、移除日期；测试名需包含
   白名单编号，不能泛称 `compat`。
3. 尚未部署的迁移应正本清源为 canonical schema，并删除 legacy backfill 测试；用
   “从空库迁移到最新”“最新模型约束成立”“必要时相邻 reverse”替换。
4. 以下负向测试不是兼容层，应保留：
   `tests/integration/portal/test_portal_api_ops2.py:192-218`（旧表单 POST 保持关闭）和
   `tests/integration/config/test_error_pages.py:47-57`（已移除 dev-login 保持 404）。

### BTD-07：静态 token 测试重复、命名误导，并成为套件主要耗时源

严重度：中；置信度：高；处置：合并/替换重复测试，保留一个生产算法契约测试

证据：

- 测试设置声明使用 MD5 以提速：`src/easyauth/config/settings/test.py:10-12`。
- 静态 token 实现绕过 Django `PASSWORD_HASHERS`，直接实例化生产强度
  `PBKDF2PasswordHasher`：`src/easyauth/applications/services.py:202-215`。
- `tests/unit/applications/test_services.py:36-47` 名为
  “uses django password hasher”，实际显式断言 PBKDF2，测试名与行为不符。
- 同一实现被两个 facade 测两遍：
  - `tests/unit/applications/test_services.py:18-159` 测 `StaticTokenService`；
  - `tests/unit/applications/test_static_tokens.py:17-102` 测 `AppCredentialService`；
  - `src/easyauth/applications/services.py:72-163` 显示前者主要转调后者；
  - `src/easyauth/applications/models.py:296` 还保留 `AppStaticToken = AppCredential` 别名。
- slowest 中同一旋转语义两次出现：
  `tests/unit/applications/test_static_tokens.py:86` 为 3.17 秒，
  `tests/unit/applications/test_services.py:123` 为 2.84 秒；大量 API 测试创建/认证 token 后也进入 2～7 秒区间。

危害：

- 测试设置给出“已用快 hasher”的错觉，但 token 路径仍反复执行生产 PBKDF2。
- facade 与核心服务逐项重复断言，增加运行时间，却没有增加并发、查找键碰撞、事务回滚等
  更关键覆盖。
- `AppStaticToken`、`StaticTokenService` 等兼容别名与项目“无兼容层”约束冲突。

精确回归要求：

1. 确定唯一公开服务和模型名，删除未被外部契约白名单保护的 facade/别名及重复测试。
2. 绝大多数行为测试使用低迭代但真实的测试 PBKDF2 hasher；不得 mock 掉哈希、查找键或校验
   事实。
3. 单独保留一个生产算法契约测试，验证生产配置使用目标算法；不要在每个 API 测试重复支付
   生产迭代成本。
4. 新增 `token_lookup` 精确命中单行、相同 token 不可产生多候选、发放/审计事务整体回滚、
   rotate 保留 capabilities 的回归。

### BTD-08：通知测试的 autouse fixture 伪造业务事实

严重度：中；置信度：高；处置：修复；改为显式 factory fixture

证据：

- `tests/unit/notify/conftest.py:19-45` 给所有 notify 单元测试挂载 `App.post_save`，
  每创建一个 App 就自动创建完整通知通道。
- 通道的企业目录作用域不是由测试显式给定，而是根据 `app_key` 是否包含 `claim`、`quota`、
  `accept` 等字符串猜测：`tests/unit/notify/conftest.py:48-55`。
- 例如 `tests/unit/notify/test_recipient_scope.py:68-72` 创建 App 后直接
  `AppNotificationChannel.objects.get`，业务前置事实完全来自隐藏 fixture。

危害：

- 新测试即使忘记配置通知 capability、channel、企业目录作用域，也可能因隐藏信号自动补齐而
  通过。
- app_key 文本变化会隐式改变 corp，失败原因难以从用例本身理解。
- fixture 违反“mock 只能隔离外部依赖，不得替代业务事实”的项目规则；这里创建的是数据库
  业务事实，不是外部依赖替身。

精确回归要求：

1. 删除 autouse signal，提供 `notify_app_factory(channel_scope=...)`，每个用例显式选择是否
   建通道。
2. 增加“无通道必须快速失败且不落消息”“通道 scope 与收件人 scope 不同必须失败”的回归。
3. factory 返回 app、channel 和目录用户，禁止通过 app_key 子串推断事实。

### BTD-09：有误导名称和无直接断言的低变异敏感测试

严重度：低；置信度：高；处置：修复或拆分，不必整文件删除

证据：

- `tests/integration/auth/test_local_admin_login.py:742-759` 名为
  `test_create_local_admin_command_is_idempotent`，但第二次无 `--update` 明确抛
  `CommandError`；生产命令也在 `src/easyauth/accounts/management/commands/create_local_admin.py:52-54`
  定义为失败，不是幂等成功。该测试还把创建、重复拒绝、更新三种行为揉在一起。
- 以下实际收集用例没有直接断言或 `pytest.raises`：
  - `tests/unit/config/test_net.py:18-19`；
  - `tests/unit/applications/test_permission_scope_grant_invariants.py:50-60`；
  - `tests/unit/applications/test_app_credential_model.py:32-43`。
- `tests/integration/admin_console/test_apps_contract_compat.py:65` 使用
  `assert datetime.fromisoformat(...)`，只验证“能解析且对象 truthy”，没有验证时区或精确格式。

危害：

- 名称会误导失败归因和后续重构；删除被测调用后，无直接断言的测试可能继续通过。
- 一个测试覆盖三种命令语义，失败时无法快速定位创建、冲突还是更新。

精确处置：

1. 把命令测试拆成“首次创建成功”“重复创建失败且原密码不变”“显式 update 成功并递增
   session_version”。
2. 正向 URL 测试应让 `require_secure_url` 返回规范化结果，或至少参数化正向/负向契约到同一
   测试表；若函数设计坚持返回 `None`，保留“不得抛异常”语义但用清晰名称说明。
3. `full_clean` 正向测试增加与不变量直接相关的字段/数据库保存后断言，不能只有“没抛异常”。
4. datetime 契约断言 `tzinfo is not None` 并验证 UTC/项目规定偏移。

### BTD-10：Celery 任务注册、调度和安全关键 wrapper 覆盖严重不足

严重度：高；置信度：高；处置：补回归测试

证据：

- `src/easyauth/config/settings/base.py:318-377` 定义 2 条路由、9 个 task import 和 9 个
  beat schedule。
- `tests/test_project_scaffold.py:28-43` 只断言 grant cleanup schedule/import 和 webhook
  queue；没有参数化验证其余任务名与注册。
- 下列任务 wrapper 没有直接测试：
  - 健康心跳与依赖探测：`src/easyauth/tasks/health.py:11-20`；
  - 通知 deliver/reconcile/prune：`src/easyauth/tasks/notify.py:21-38`；
  - 离职禁号与审计：`src/easyauth/tasks/lifecycle.py:16-62`；
  - 定时目录同步 wrapper：`src/easyauth/tasks/authentik.py:57-78`。
- `tests/unit/webhooks/test_tasks.py:32-54` 已经为 webhook wrapper 提供了正确范例：断言参数
  透传、返回值和 time limit。

危害：

- settings 中的字符串任务名可与 decorator 的真实 task name 漂移，beat 会静默发布无人注册
  的任务。
- 离职禁号属于权限回收边界；当前没有验证 missing/not-configured/not-found/success 的审计
  和返回语义，也没有验证 `AuthentikAdminError` 的 Celery retry 配置。

精确回归要求：

1. 用参数表一次性断言 9 个 `CELERY_IMPORTS`、9 个 schedule 的 task name/interval，以及
   notify/webhook 的独立 queue。
2. 对每个薄 wrapper 断言参数和返回值透传；对 `deliver_message_task`、lifecycle/webhook
   断言 `acks_late`、soft/hard limit、autoretry/max_retries。
3. 离职任务覆盖 user missing、admin 未配置、Authentik user missing、成功禁用、
   普通 `AuthentikAdminError` 进入 retry；每条断言对应审计事件且无敏感信息。
4. 心跳任务断言写入正确 heartbeat key，健康检查 task 断言返回持久化的检查数量。

### BTD-11：审计日志唯一合法删除入口没有测试

严重度：高；置信度：高；处置：补测试，不能删除该命令

证据：

- `src/easyauth/audit/management/commands/prune_audit_logs.py:15-37` 声明这是审计表“唯一合法的
  删除口径”，按时间执行破坏性清理。
- 测试树中没有任何 `prune_audit_logs` 或 `prune_audit` 引用。
- 现有 `tests/unit/audit/test_services.py:12-116` 验证追加写入和 append-only 约束，没有
  覆盖管理命令的参数和时间边界。

危害：

- `keep-days` 的边界、时区、恰好 cutoff 的保留/删除口径、非法参数和输出数量均可回归而无
  红灯。
- 这是不可恢复数据删除路径，风险高于普通查询 helper。

精确回归要求：

1. 冻结 `timezone.now`，创建 cutoff 前、恰好 cutoff、cutoff 后三条日志，明确断言边界。
2. `0`、负数、非整数、缺少参数必须 `CommandError` 且零删除。
3. 断言只允许命令调用受控 purge API，普通 QuerySet delete 仍受模型保护。
4. 断言 stdout 删除数量与真实删除行一致。

### BTD-12：`unit` 分类失真，拖慢开发反馈

严重度：中；置信度：高；处置：重新分层；不要为了数字简单删测试

证据：

- `tests/unit/` 下 96 个 `test_*.py` 文件中有 68 个显式使用 `django_db` 或数据库 fixture。
- 例如 `tests/unit/lifecycle/test_services.py:58`、
  `tests/unit/grants/test_query.py:37`、`tests/unit/api/test_directory_views.py:35`
  都是数据库集成测试。
- 主套件 1292 项耗时 176 秒；最慢项包括 HTTP API、迁移、真实依赖探测和生产 PBKDF2。

危害：

- 开发者无法只运行真正快速、无数据库、无网络的 unit 层。
- `tests/unit` 名称会让 CI 设计和失败归因低估其初始化、事务与共享状态成本。

精确处置：

1. 定义 marker：`unit`（无 DB/网络）、`db`、`postgres`、`external`、`migration`、`sdk`。
2. 快速 PR lane 运行纯 unit + SQLite DB；PostgreSQL/SDK/FastAPI 为并行必跑 lane；真实外部
   探测只用于部署后 smoke。
3. 迁移测试按 schema 变更触发或独立并行运行，但仍是合并门禁。
4. 建立耗时预算并输出 `--durations`；先消除真实网络与重复 PBKDF2，再评估拆分测试。

### BTD-13：测试数据库选择和设置受调用者环境变量影响

严重度：中；置信度：高；处置：修复测试入口

证据：

- `src/easyauth/config/settings/test.py:5-8` 只对 `DJANGO_DEBUG` 使用 `setdefault`，随后导入
  基础设置。
- `src/easyauth/config/settings/base.py:104-128` 在 import 期读取 `DATABASE_URL`；
  因此调用者若遗留该变量，测试会切换到 PostgreSQL，若遗留 `DJANGO_DEBUG=0` 且没有测试
  密钥，基础设置还可能提前失败。
- 当前唯一 PostgreSQL skip 直接读取 `connection.vendor`：
  `tests/integration/notify/test_quota_concurrency.py:21-25`，所以同一命令的收集/执行结果取决于
  shell 环境。

危害：

- 本机、IDE、CI 与生产 shell 中同一命令可能连接不同数据库、得到不同 skip 数，甚至尝试
  连接开发者原有数据库服务。
- “偶然跑到 PostgreSQL”不是可靠的生产数据库 lane。

精确回归要求：

1. SQLite 测试设置显式固定数据库，不读取任意继承的 `DATABASE_URL`。
2. PostgreSQL 使用独立设置模块和 CI 专用临时数据库 URL；启动时断言 vendor 必须为
   `postgresql`。
3. 两个 lane 都显式提供测试密钥和 DEBUG 值，不依赖 `setdefault`。

### BTD-14：其余共享状态、本地网络与顺序敏感点

严重度：低；置信度：中；处置：加隔离与分类；当前没有复现顺序失败

证据：

- `tests/integration/api/test_approval_instances_api.py:30-35` 使用未重置的类变量
  `_FakeDingTalkClient._seq`。当前断言不依赖固定序号，因此本次顺序下没有失败，但结果仍由
  之前运行过多少测试决定。
- `sdk/python/tests/test_client.py:280-321` 启动真实 `ThreadingHTTPServer` 并绑定
  `127.0.0.1` 随机端口；实测该测试耗时 0.50 秒。它不访问外网且有 `finally` 清理，安全
  价值较高，但会在禁止 bind socket 的沙箱中失败。
- `tests/unit/outbox/test_services.py:29-32` 的 autouse fixture 会先删除整张
  `OutboxEvent` 表，注释称为了防止 `transaction=True` 测试遗留事件。pytest-django 本应
  隔离用例；整表删除可能掩盖真正的事务清理缺陷。
- `tests/unit/webhooks/test_transport.py:69-83` 和
  `tests/unit/connectors/fakes.py:42-50` 对共享类状态有显式 reset，是可保留的正确做法。

精确处置：

1. 每用例重置 `_seq`，或由实例持有计数；测试结果不得依赖全套件运行历史。
2. 给本地 socket 用例加 `local_socket`/`integration` marker，在允许 bind 的 SDK CI 中
   必跑；继续禁止外网。
3. 删除 outbox 整表清理前，先写“事务测试结束后数据库为空”的隔离回归；若仍有泄漏，应
   修复泄漏源而非清表掩盖。
4. 后续引入随机顺序插件，在至少 3 个 seed 下运行纯 unit/SQLite 层；当前项目没有随机顺序
   插件，因此本次不能把“当前顺序通过”解释为顺序无关证明。

## 删除、修复、替换清单

### 应删除

- 没有白名单/外部契约/移除条件的正向 legacy 兼容测试及对应兼容代码：
  unscoped directory ref、legacy notify recipient 行、旧错误文本回退、同时保留旧字段的
  contract compat 断言。
- 确认没有独立公共契约后，删除 `StaticTokenService`/`AppStaticToken` 兼容 facade 的重复
  行为测试，只保留 canonical 服务。
- 项目确实从未部署旧 schema 时，删除只服务旧数据 backfill 的迁移测试，改正 canonical
  schema 后 squash/重写迁移。

### 应修复

- 控制台 legacy 登录 bridge、通知 autouse 造数、真实依赖探测单元测试。
- 无断言/误导名称测试、测试设置环境漂移、静态 token 测试哈希耗时。
- outbox 整表清理与未重置类变量。

### 应保留但重新分类

- 旧 dev-login、旧门户 POST 必须继续返回 404/405 的负向安全测试。
- SDK 本地 redirect server 测试：它验证真实 urllib redirect handler 不泄露
  Authorization，价值高；归入本地 socket 集成层。
- 当前迁移测试中若已有部署版本必须继续支持的部分；前提是补正式 legacy 白名单和移除条件。

### 必须新增的关键回归

优先级从高到低：

1. PostgreSQL 多连接并发矩阵：notify、outbox、approval、lifecycle/grant、TOTP。
2. CI 主后端 + PostgreSQL + SDK/FastAPI 必跑门禁。
3. 不借助 Django login bridge 的真实控制台认证/授权矩阵。
4. Celery task name/import/schedule/queue 参数化契约与离职禁号 task 行为。
5. 审计日志 prune 的冻结时间边界与非法参数零删除。
6. 依赖健康检查的纯编排测试和部署后真实 smoke 分层。
7. canonical scoped directory/notify 契约，明确拒绝所有未白名单 legacy 输入。

## 建议验收标准

完成整改后，后端测试体系至少满足：

- PR 上不存在“只构建镜像、不跑测试”的绿色路径。
- 根 Python 测试、PostgreSQL 并发测试、SDK 全量（含 FastAPI）均有独立必跑作业。
- 默认回归不访问外网、不连接开发者 broker、不依赖遗留环境变量。
- `pytest` 摘要无未白名单 skip/xfail；FastAPI 不再整模块跳过。
- 控制台测试中不再出现生产不存在的 `Client.login` 桥。
- 生产 PostgreSQL 锁边界至少有上述 5 组真实多连接回归。
- 纯 unit lane 不使用数据库或 socket，并能在合理时间内完成；迁移、DB、SDK、本地 socket
  和部署后 external smoke 有明确 marker。
- 所有保留的 legacy 测试都能指向正式白名单、外部契约和可验证的移除条件。
