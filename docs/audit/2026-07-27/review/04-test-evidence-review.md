# 测试证据交叉复核

复核日期：2026-07-27

复核对象：

- `11-backend-test-decay.md`
- `12-frontend-e2e-test-decay.md`
- `17-independent-full-sweep.md` 中与测试有关的结论

本次只读取源码、配置和原报告，并执行安全的收集、定向测试与静态计数。没有修改测试、业务
代码或原报告，也没有提交 commit。

## 总体结论

三份报告的主结论大体可靠：仓库没有自动化测试门禁，后端默认套件缺少 PostgreSQL 并发
验证，SDK FastAPI 面在当前环境整模块跳过，控制台与通知测试存在会伪造业务事实的全局
fixture，前端默认并发运行不稳定，Playwright 主要是 mock UI 冒烟而非真实全栈 E2E，
`itemsFromPayload` 测试确实固化了错误的空列表兜底。

但以下口径必须收紧：

1. SDK 未设置 `PYTHONPATH` 时的 `5 errors` 是错误测试入口/未安装本地包造成的收集失败，
   不是 5 个 SDK 产品缺陷。应修的是可复现安装入口和 CI。
2. Playwright 的 `27 项全部失败` 全部发生在业务断言执行前，直接原因是缺少与
   Playwright 1.60.0 匹配的 Chromium Headless Shell。这是环境限制，不是 27 个产品回归。
3. 前端随机红灯现象已确认，但“并发资源竞争”仍是高概率解释而非已隔离的唯一根因。
   失败用例不能直接定性为产品缺陷。
4. `12` 的 `F-10` 尚不足以证明时间测试会随机失败。相对当前时间加减 1 小时或 7 天本身
   是在规避固定日期过期；冻结时钟有利于确定性，但当前证据只支持低优先级加固。
5. `11` 的 `BTD-07` 确认存在语义重复和生产强度 PBKDF2 耗时，但
   `StaticTokenService` 目前有多个生产调用方，不能仅凭“facade”推定为可删除兼容层。
6. 前端父子层重复提交测试和 CSS 契约测试有重叠或实现耦合，但删除前必须先有等价的行为、
   架构或视觉替代，不能只按“低价值”批量删减。

## 复核命令与结果

| 命令 | 复核结果 | 性质 |
| --- | --- | --- |
| `.venv/bin/pytest --collect-only -q` | 收集 `1292` 项 | 确认 `11:35` 的收集数；未重复执行耗时约 176 秒的全量套件 |
| `.venv/bin/pytest -ra --collect-only sdk/python/tests` | `5 errors, 2 skipped`，5 个错误均为 `ModuleNotFoundError: easyauth_app_sdk` | 调用入口/安装环境问题 |
| `PYTHONPATH=sdk/python/src .venv/bin/pytest -ra sdk/python/tests` | `69 passed, 2 skipped in 0.74s` | 确认 `11:37`；两个 skip 均为缺少可选 FastAPI 依赖 |
| 正常运行控制台抽样用例 | `1 passed` | fixture 生效 |
| 同一用例加 `--noconftest` | `401 != 200` | 确认该用例依赖 conftest 建立的非生产登录桥 |
| `pnpm exec playwright test --list` | `3` 个文件、`27` 项 | 确认 `12:9` |
| 单项 Playwright 冒烟 | 启动浏览器前失败，缺少 `chromium_headless_shell-1223` | 纯环境限制 |
| `pnpm test -- --run --reporter=dot` | `41` 个文件；`292 passed, 3 failed` | 独立复现默认并发随机红灯 |
| 将本轮 3 个失败文件以单 worker 重跑 | `21 passed` | 支持测试稳定性问题，不支持产品回归 |
| 将 `17:249` 所列 4 个文件以单 worker 重跑 | `68 passed` | 精确复核 `17` 的 68 项说法 |

当前实际工具版本为 Node 26.0.0、Vitest 4.1.8、Playwright 1.60.0；锁文件确实解析到
Playwright 1.60.0。测试运行中稳定出现 `localStorage` 实验警告和 React `act(...)`
警告。

有两项执行结果未作为产品证据：

- 首次并发启动三个 Django 定向测试时，多个进程同时初始化 SQLite 测试库并等待；这是本次
  复核的调用方式问题。终止后已经改为串行并使用 `--reuse-db`，得到上表中的有效结果。
- 一次高负载下的 Vitest JSON 运行以 `0 tests` 退出，没有可用失败明细，已丢弃。有效证据
  只采用随后正常收集 `295` 项的运行。

## `11-backend-test-decay.md` 逐项复核

### 已确认

#### BTD-01：CI 门禁缺失

确认。根配置只收集 `tests`（`pyproject.toml:43-47`）；唯一工作流只有 Docker job，
没有 pytest、SDK、ruff、basedpyright、Vitest 或 Playwright 步骤
（`.github/workflows/docker-build.yml:20-71`）。`11:54-83` 的修复方向正确。

需要修正表述：从仓库根目录直接指定 SDK 测试却未安装 SDK，也未设置其 src 路径，本来就会
收集失败。因此 `11:36` 的 `5 errors` 只证明“当前根测试入口不包含 SDK”，不能证明 SDK
实现有 5 个错误。正确动作是让 CI 从 `sdk/python` 安装包及 `.[fastapi]` 后运行测试。

#### BTD-02：PostgreSQL 并发覆盖缺失

确认静态事实：

- `src/easyauth` 中有 23 个文件、61 次 `select_for_update`。
- 测试树只有 4 处 `django_db(transaction=True)`。
- `tests/integration/notify/test_quota_concurrency.py:19-28` 会在非 PostgreSQL 环境整模块
  跳过。
- 默认数据库由 `DATABASE_URL` 决定，缺失时在 debug 下使用 SQLite
  （`src/easyauth/config/settings/base.py:104-128`）。

因此 `11:85-123` 所要求的 PostgreSQL 必跑 lane 和多连接回归成立。这里确认的是重大测试
缺口，不是已经证实 notify、outbox、审批、交接或 TOTP 存在并发产品 bug。

#### BTD-03：控制台 legacy 登录桥

确认。`tests/integration/admin_console/conftest.py:15-40` 的 autouse fixture 会把
`Client.login` 改成同时创建 `UserMirror`、写入 `AUTHENTIK_SESSION_KEY`，并为 Django
superuser 写入控制台管理员组。生产身份解析只看对应会话和镜像
（`src/easyauth/admin_console/identity.py:16-39`）。

静态计数也准确：26 个文件、33 次 `client.login(...)`。抽样用例正常运行通过，使用
`--noconftest` 后在
`tests/integration/admin_console/test_onboarding_templates_api.py:25-44` 得到 401。
虽然 `--noconftest` 同时移除了同目录另一个默认组设置 fixture，但 401 出现在身份缺失阶段，
足以证明该用例没有自行建立生产会话契约。`11:152-161` 的“删除桥、使用显式真实会话
fixture、补 401/403/允许矩阵”应执行。

#### BTD-04：单元测试真实探测外部依赖

确认，而且“约 6.4 秒稳定耗时”的说法不应被当成稳定上界。

`tests/unit/applications/test_dependency_health_notify.py:101-105` 直接调用完整健康检查；
`src/easyauth/applications/dependency_health_checks.py:67-77` 会执行 Authentik、目录、钉钉、
Celery 和连接器探测；Celery 在 `:315-342` 连接 broker。复核时 Redis 未运行，该用例进入
`localhost:6379` 连接拒绝和 Kombu 重试，超过 70 秒仍未完成，随后人工终止。

这证明的是测试隔离缺陷与环境敏感性，不是 Redis 或产品健康检查坏了。`11:184-190` 提议将
编排测试注入固定检查器，并把真实探测移到显式 external smoke，方向正确。

#### BTD-05：SDK FastAPI 整模块跳过

确认当前环境没有 `fastapi` 和 `starlette`。两个文件在 import 阶段使用
`pytest.importorskip`（`sdk/python/tests/test_fastapi.py:3-11`、
`sdk/python/tests/test_lifecycle_fastapi.py:8-16`），所以 pytest 摘要只显示两个模块 skip，
实际未执行 3 个描述符路由测试和 5 个生命周期路由测试。

这是测试环境/门禁缺口，不是 FastAPI 适配层已知产品缺陷。`11:213-219` 的双 lane 方案
合理：全功能 lane 安装 extra 且不允许 skip，最小依赖 lane 只验证核心包可导入。

#### BTD-08、BTD-09、BTD-10、BTD-11、BTD-12、BTD-13、BTD-14

- `BTD-08` 确认：`tests/unit/notify/conftest.py:19-55` 用 autouse signal 自动创建通知
  通道，还按 `app_key` 子串猜 corp。这是在伪造数据库业务事实，不只是隔离外部依赖。
- `BTD-09` 的名称误导和弱断言证据存在。但 `require_secure_url` 的正向测试以“不抛异常”
  作为契约并非天然无效；应优先改名和参数化，而非强行添加无关断言。
- `BTD-10` 确认所列 Celery 薄 wrapper 缺少直接回归；补任务名、参数透传、retry、time
  limit 和安全审计测试是正确动作。
- `BTD-11` 确认测试树没有 `prune_audit_logs` 引用；破坏性审计清理边界应补测试。
- `BTD-12` 的精确计数成立：`tests/unit` 有 96 个 `test_*.py`，其中 68 个显式使用
  `django_db` marker 或数据库 fixture。
- `BTD-13` 的静态因果成立：test settings 没有固定数据库，而 base settings 在 import
  期读取 `DATABASE_URL`（`src/easyauth/config/settings/test.py:5-18`、
  `src/easyauth/config/settings/base.py:104-128`）。本次没有故意传入外部数据库 URL，
  避免误连现有数据库。
- `BTD-14` 所列类变量、本地 socket 和 outbox 清表代码均存在；原报告已正确标成“当前未
  复现顺序失败”，不得升级为已确认 flaky defect。

### 需要降级或增加前置条件

#### BTD-06：legacy 删除

正向 legacy 测试与兼容实现确实存在，且与项目当前“默认不保留错误历史形态”的规则冲突。
但 `11:255-265` 中“先确认外部契约/部署事实”的前置条件不可省略。迁移测试只有在确认旧
schema 从未部署后才能删除；负向“旧入口继续关闭”测试应保留。

#### BTD-07：静态 token 重复与删除建议

以下证据确认：

- 生产代码直接实例化 `PBKDF2PasswordHasher`
  （`src/easyauth/applications/services.py:202-215`），绕过测试设置的 MD5 hasher。
- `tests/unit/applications/test_services.py:36-47` 的名称称“Django password hasher”，
  实际固定断言 PBKDF2。
- `test_services.py` 与 `test_static_tokens.py` 对创建、认证、禁用和旋转有明显语义重叠。

但 `StaticTokenService` 不是已证明的死兼容 facade。它仍被
`src/easyauth/admin_console/credentials.py:15-99`、
`src/easyauth/api/authentication.py:19-44` 和 seed 命令使用，并且对返回类型和异常语义
做了适配。`AppStaticToken = AppCredential` 才是明确的模型别名
（`src/easyauth/applications/models.py:296`）。

因此正确处置是先决定 canonical 公共 API、迁移生产调用方，再合并重复测试；不能先删
`StaticTokenService` 测试。测试 PBKDF2 降低迭代数是合理提速，但必须另保留生产算法/参数
契约，不能 mock 掉哈希与验证事实。

## `12-frontend-e2e-test-decay.md` 逐项复核

### 计数、skip 与 CI

确认 41 个 Vitest 文件、295 个展开测试、3 个 Playwright 文件和 27 个 Playwright 测试。
精确检索未发现 `test/it/describe.skip`、`.only`、`.todo` 或快照断言。所谓“无 expect”
测试实际通过 `expectInterfaceFields` assertion helper 断言
（`frontend/src/lib/api.test.ts:146-175`），因此 `12:435-440` 的无问题项基本成立。

前端测试没有进入 GitHub Actions，确认 `F-04` 的 CI 缺口。

### F-01 与 `17` 的 C-08：前端并发稳定性

确认现象，且本次得到第三组不同失败数：

- `12:31`：11 项失败；
- `17:13`：10 项失败；
- 本次默认并发：3 项失败、292 项通过。

本次失败为：

- `frontend/src/pages/console/ApprovalTemplatesPage.test.tsx:60`，5 秒超时；
- `frontend/src/pages/console/OperationsPage.test.tsx:74`，等待数据行超时；
- `frontend/src/pages/console/workspace/tabs/IntegrationTab.test.tsx:76-79`，异步读取完成前
  switch 仍 disabled。

随后把这 3 个文件以单 worker 运行，21 项全部通过；把 `17:246-249` 所列的 4 个文件以
单 worker 运行，68 项全部通过。由此可以确认“默认完整套件不可重复”，但当前证据只能把
资源竞争、长交互链和等待条件列为候选根因，不能断言每次失败都由 Vitest 文件并发唯一导致。
`12:97-103` 与 `17:261-266` 的拆分长场景、固定 worker、修复等待条件和多次门禁复跑合理。

### F-02 与 `17` 的 C-01：错误列表契约被测试固化

确认，且这是产品与测试同时存在的缺陷：

- `frontend/src/lib/api.ts:105-116` 把缺失/错型 `payload.data` 返回为共享空数组；
- `frontend/src/lib/api.test.ts:123-142` 把该行为写成正向测试；
- 生产环境没有开发期 `console.warn`，所以“不是静默兜底”的测试名不符合真实行为；
- E2E 中多处继续返回 `{ items: [...] }`，例如
  `frontend/e2e/visual-alignment.spec.ts:84-120` 和
  `frontend/e2e/smoke.spec.ts:277-370`；
- 视觉冒烟只断言页面外壳，没有断言 `Demo App` 等种子行可见
  （`frontend/e2e/visual-alignment.spec.ts:17-31`）。

应替换为空间明确的运行时 envelope 解析和错误态测试，并同步修正所有自身 API mock。

### F-03：Playwright mock 范围

确认。`frontend/playwright.config.ts:13-17` 只启动 Vite；E2E 共检出 55 处 route/fulfill
相关调用。`smoke.spec.ts:172-428`、`connector.spec.ts:82-216` 和
`visual-alignment.spec.ts:46-174` 均注入管理员身份或伪造 EasyAuth API。

因此这些测试应命名为浏览器 UI smoke，不能作为 Django shell、CSRF、真实鉴权、代理或
序列化契约的 E2E 证据。保留少量 mock smoke 并新增禁止伪造自身 API 的全栈 lane，是
正确替换方案。

### F-04：浏览器缺失

确认浏览器缓存中没有 `chromium_headless_shell-1223`，单项测试在启动浏览器前失败。
这只能证明当前机器未安装锁文件所需浏览器，不能证明 E2E 断言失败。仓库又没有安装浏览器
并运行 Playwright 的 CI，所以“缺少可复现门禁”成立。

不建议把浏览器下载塞进每次本地 `e2e` script；更稳定的做法是在 CI/setup 明确执行
`playwright install --with-deps chromium`，并按锁定的 Playwright 版本缓存。

### F-05 至 F-09、F-11

- `F-05` 确认：`visual-alignment.spec.ts:176-221` 只检查前 12 个可见控件、中心点遮挡和
  DOM overflow，没有截图断言。应改名为布局冒烟，或以少量截图基线替换。
- `F-06` 确认：`frontend/src/i18n/noHardcodedChinese.test.ts:12-56` 使用手写名单；
  `GuideTab.tsx:20-73` 和 `ManifestTab.tsx:411-425` 的硬编码未进入扫描。`17` 的 C-07
  也由 `ManifestTab.tsx:108-243` 的更多硬编码支持。
- `F-07` 确认测试与源码形状/CSS 文本耦合
  （`tableArchitecture.test.ts:9-96`、`AppShell.test.tsx:318-339`、
  `baseComponents.test.tsx:32-195`）。但先建立 lint、design token 或截图替代，再删除
  纯实现断言；不能先造成覆盖空窗。
- `F-08` 所列父子测试关注同一重复提交门槛，但层次不同：子组件验证 disabled/callback，
  父层验证真实 mutation 的 POST 次数。两者都很便宜，仅凭语义重叠不足以判定必须删除。
  可在保持一条组件职责和一条集成职责的前提下精简。
- `F-09` 的状态机重叠成立，但 mock 浏览器 happy path 仍能覆盖组件组合与浏览器交互。
  在真实全栈 E2E 建立前，不应直接删除唯一浏览器路径；可以缩短，但替换优先于删除。
- `F-11` 确认：`frontend/src/test/setup.ts:32-51` 会直接读取 `window.localStorage`，在当前
  Node 26/jsdom 环境每个 worker 都产生实验警告；本次还复现多条 React `act(...)` 警告。
  这是测试环境噪声与同步缺陷，不是产品页面失败。

### F-10：时间测试需降级

`frontend/src/pages/portal/hooks/useAccessRequestForm.test.ts:111-132` 使用当前时间前后 1
小时，`PortalPage.test.tsx:294-331` 使用当前时间后 7 天并转换为本地
`datetime-local`。这些间隔足够大，且转换显式使用当前时区；报告没有展示跨时区或临界点
失败。

冻结系统时间仍可提高可读性和完全确定性，但本项应从“已确认时间敏感问题”降为低优先级
加固，不应和已复现 flaky 测试并列。

## `17-independent-full-sweep.md` 的测试相关结论

- `17:11` 的 `1291 passed, 1 skipped` 与 `11` 完全一致；本次重新确认收集 1292 项，但
  未在共享高负载环境重复跑完整后端套件。因此“通过摘要”属于两份独立报告相互印证，
  “收集数与 skip 原因”属于本次直接确认。
- `17:13`、`17:239-266` 的 C-08 已直接复现。失败数不是稳定的 10，而是随运行变化；
  这反而加强“门禁不确定”的结论。
- `17:42-73` 的 C-01 已由实现、Vitest 正向测试和 E2E 错误 mock 直接确认。
- `17:168-184` 关于测试固化英文错误的证据成立：
  `tests/integration/portal/test_access_request_s14.py:142-170` 直接断言
  `Authorization group must be requestable`。
- `17:217-237` 的 i18n 护栏假阴性成立。
- `17:445` “后端全量通过不等于完成渗透测试”的边界表述正确；同样也不能把默认 SQLite
  通过解释为 PostgreSQL 并发正确。

## 最终处置建议

### 立即修复

1. 建立后端、PostgreSQL、SDK/FastAPI、前端构建/Vitest、Playwright 的必跑 CI，并让镜像
   发布依赖这些 job。
2. 删除控制台 login bridge 和通知 autouse 造数，改为显式生产会话 fixture 与业务 factory。
3. 将依赖健康单元测试改为注入检查器；真实网络只进 external smoke。
4. 将 `itemsFromPayload` 改为严格解析，修正 E2E mock 并断言种子业务值实际渲染。
5. 固定前端 worker 预算，拆分长旅程，修复明确等待条件与所有 `act(...)`/Storage 警告。
6. 增加 PostgreSQL 多连接并发回归；当前 skip 不能作为生产正确性证明。

### 先替换再删除

1. `noHardcodedChinese.test.ts` 替换为自动发现的 lint/架构检查。
2. `tableArchitecture.test.ts` 和纯 CSS/class 断言先由架构规则、design token 或截图基线
   接管，再删除。
3. mock Playwright 保留最短 UI smoke，新增真实全栈 E2E 后再缩减重叠路径。
4. 静态 token 先确定 canonical 服务、迁移生产调用方、建立测试 hasher 与生产算法契约，
   再合并重复测试。

### 只有前置事实确认后才能删除

1. 未列入正式外部契约/白名单的正向 legacy 测试与对应实现。
2. 仅服务从未部署旧 schema 的 backfill 迁移测试。
3. `AppStaticToken` 等明确别名及其重复测试，但必须先迁移所有生产调用方。

### 不应误报为产品缺陷

- 未设置 `PYTHONPATH` 导致的 SDK 5 个收集错误。
- 未安装 Chromium 导致的 27 个 Playwright 启动失败。
- 当前环境缺少 FastAPI 导致的两个模块 skip；缺陷在全功能 CI 未安装 extra。
- 默认并发下失败后单 worker 通过的具体前端断言；现阶段确认的是测试门禁不稳定。
- 本次复核首次并发初始化 SQLite 和高负载 JSON 运行产生的无效结果。
