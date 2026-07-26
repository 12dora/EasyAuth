# 前端与端到端测试腐化审计

审计日期：2026-07-27

审计范围：`frontend/src/**/*.test.{ts,tsx}`、`frontend/e2e/*.spec.ts`、Vitest/Vite/Playwright 配置、前端测试脚本、相关关键业务实现及 GitHub Actions。

## 结论摘要

当前前端共有 41 个 Vitest 文件、295 个测试；端到端目录共有 3 个 Playwright 文件，展开参数化视口后共 27 个测试。静态检查未发现 `.skip`、`.only`、`todo`、快照断言或完全无 `expect` 的测试。

测试数量不算少，但存在四项会显著削弱质量门槛的系统性问题：

1. 同一代码状态下，连续两次完整 Vitest 运行分别得到“11 项失败”和“295 项全过”，说明门槛不可重复。
2. `itemsFromPayload` 的测试把畸形成功响应降级为空列表固化成正确行为，与项目“契约异常必须快速失败”的硬约束相反。
3. Playwright 只启动 Vite，并大规模伪造身份与 API；它是浏览器级 UI 冒烟，不是验证 Django、鉴权、代理和真实 API 契约的端到端测试。
4. 唯一 GitHub Actions 工作流只构建镜像，不运行 Vitest、Playwright 或前端构建测试；现有测试并不是合并门槛。

综合评级：高风险。建议先恢复测试门槛的可运行性和确定性，再补真正的全栈回归。

## 执行命令与结果

### Vitest 首次完整运行

命令：

```bash
cd frontend
pnpm test -- --run --reporter=verbose
```

结果：失败，41 个测试文件中 6 个文件失败；295 项测试中 11 项失败、284 项通过；总耗时 70.44 秒。

代表性失败：

- `frontend/src/pages/console/ApprovalTemplatesPage.test.tsx:60`：5 秒超时。
- `frontend/src/pages/console/ConsoleAppWorkspace.test.tsx:75`：找不到“权限分组”标题。
- `frontend/src/pages/console/ConsoleAppWorkspace.test.tsx:112`：找不到“审批规则”页签。
- `frontend/src/pages/console/ConsoleAppWorkspace.test.tsx:141`：找不到“用户 ID”输入框。
- `frontend/src/pages/console/ConsoleAppWorkspace.test.tsx:707`：5 秒超时。
- `frontend/src/pages/portal/PortalPage.test.tsx:451`：5 秒超时。
- `frontend/src/pages/console/workspace/tabs/IntegrationTab.test.tsx:76-79`：本应启用的开关仍处于禁用状态。
- `frontend/src/pages/console/workspace/tabs/MatrixTab.test.tsx:247`：找不到“编辑授权组”对话框。

运行期间还反复出现 `localStorage is not available because --localstorage-file was not provided`，并出现 `PermissionSelector` 状态更新未包裹在 `act(...)` 中的 React 警告。

### Vitest 紧接着第二次完整运行

命令：

```bash
cd frontend
pnpm exec vitest run --reporter=json --outputFile=/tmp/easyauth-frontend-vitest.json
```

结果：通过，95 个展开后的测试套件全部通过；295 项测试全部通过，0 项失败、0 项待定。代码与测试在两次运行之间没有修改。该结果确认首次失败不能作为稳定的确定性回归信号。

### Playwright

命令：

```bash
cd frontend
pnpm exec playwright test --reporter=line
```

结果：27 项全部失败。Vite 测试服务器可以启动，但 Playwright 1.60.0 所需的 Chromium Headless Shell 不存在：

```text
Executable doesn't exist at .../chromium_headless_shell-1223/...
Please run: pnpm exec playwright install
```

这不是业务断言失败，但证明仓库当前没有提供可复现的浏览器安装门槛，现有环境无法直接执行 E2E。

## 发现清单

### F-01：Vitest 全量套件在相同代码状态下结果相反

- 严重级别：高
- 置信度：高（现象）；中（具体根因）
- 类型：失败、时间敏感、资源/并发敏感、误导性门槛
- 建议：修复

证据：

- `frontend/vite.config.ts:24-29` 只配置 `jsdom`、全局变量、初始化文件和排除目录，没有显式的 `testTimeout`、worker 数、文件并行策略或慢测试分组。
- `frontend/src/pages/console/ApprovalTemplatesPage.test.tsx:60-95` 在单项测试内连续执行大量输入清空、粘贴和提交，首次全量运行触发默认 5 秒超时。
- `frontend/src/pages/console/ConsoleAppWorkspace.test.tsx:32-87`、`:89-116`、`:118-155`、`:707-765` 是重渲染与多请求交织的长场景；首次运行出现未完成加载或找不到页面元素，第二次完整运行全部通过。
- `frontend/src/pages/portal/PortalPage.test.tsx:451-558` 是长链路交互测试，首次运行恰好在默认 5 秒超时，第二次通过。
- `frontend/src/pages/console/workspace/tabs/IntegrationTab.test.tsx:73-79` 已使用 `waitFor`，但首次运行仍在异步读取完成前观察到禁用状态。

影响：

- 同一提交可能随机红或随机绿，开发者无法区分产品回归与测试资源竞争。
- 失败集中于高价值业务测试，若通过重跑解决，会逐渐形成“红了先重跑”的坏习惯。

具体建议：

1. 在 CI 中先固定 Node、pnpm 和 worker 数，分别记录 `--maxWorkers=1` 与受控并发结果。
2. 对超长页面场景拆分为更小的业务断言，减少单项测试中重复输入和多轮列表刷新。
3. 用明确的加载完成条件代替只依赖默认轮询时限；不得仅把全局超时调大来掩盖未同步的状态。
4. 把 React `act(...)` 警告提升为测试失败，并修复触发警告的 `PermissionSelector` 交互。
5. 连续运行完整套件至少 10 次，确认零随机失败后再恢复强制门槛。

### F-02：测试把畸形成功响应降级为空列表固化为正确行为

- 严重级别：高
- 置信度：高
- 类型：过时/错误口径、误导、低价值
- 建议：替换

证据：

- `frontend/src/lib/api.test.ts:123-126` 断言缺少列表数据时返回稳定空数组。
- `frontend/src/lib/api.test.ts:134-142` 断言 `payload.data` 为字符串时返回空数组，只要求开发环境 `console.warn`。
- `frontend/src/lib/api.ts:105-116` 实现确实在契约不匹配时返回 `EMPTY_ITEMS`。

测试名声称“不是静默兜底”，但生产环境不会输出开发警告，最终仍把畸形 `200` 响应表现成“空列表成功”。这与项目硬约束“违反数据契约必须快速失败，不得以空结果兜底掩盖真实问题”直接冲突。

具体建议：

- 删除现有“返回空数组”断言。
- 用运行时 schema/显式解析器替换 `itemsFromPayload`，畸形 `200` 必须抛出可定位错误。
- 新回归应验证页面进入明确错误态、禁止写操作，且不会显示“暂无数据”。

### F-03：Playwright 并不验证真实后端、鉴权或前后端契约

- 严重级别：高
- 置信度：高
- 类型：网络敏感、共享环境敏感、误导、低价值 E2E
- 建议：替换

证据：

- `frontend/playwright.config.ts:13-17` 的 `webServer` 只启动 `pnpm dev`，没有启动 Django。
- `frontend/vite.config.ts:7-14` 声明 API 代理到 `127.0.0.1:8000`，但大部分 E2E API 都被路由拦截，代理本身没有被验证。
- `frontend/e2e/smoke.spec.ts:172-208` 通过改写 HTML 和 `dataset` 注入管理员身份，绕过真实登录、会话、权限和服务端重定向。
- `frontend/e2e/smoke.spec.ts:210-428` 大量 `page.route(...).fulfill(...)` 自造应用、凭据、Manifest、查询、矩阵、目录和提交响应。
- `frontend/e2e/connector.spec.ts:82-107` 同样注入管理员身份；`:126-216` 自造连接器 API 状态机。
- `frontend/e2e/visual-alignment.spec.ts:17-30` 在每个页面先执行身份和数据 mock。

影响：

- Django shell 的 root 属性、CSRF、登录态、权限拒绝、真实重定向、序列化格式、Vite 代理和生产静态资源漂移都可以在 Playwright 全绿时损坏。
- 测试名称和 README 中的“Playwright 冒烟”容易被误认为已有端到端保障。

具体建议：

1. 保留少量 mock UI smoke，但目录和命令明确命名为 `ui-smoke`。
2. 新增真正全栈 E2E：启动 Django 与所需依赖，使用真实测试数据库和正式 shell/静态资源。
3. 至少覆盖匿名、普通用户、系统管理员三种身份，以及一条控制台写流程和一条门户申请流程。
4. 全栈 E2E 中禁止 `page.route` 伪造 EasyAuth 自身 API；只允许隔离明确的外部系统。

### F-04：E2E 浏览器依赖没有可复现安装步骤，且任何前端测试都未进入 CI

- 严重级别：高
- 置信度：高
- 类型：失败、环境敏感、过时门槛
- 建议：修复

证据：

- `frontend/package.json:11` 的 `e2e` 仅执行 `playwright test`，没有浏览器安装或存在性检查。
- `frontend/package.json:24` 允许 `@playwright/test` 通过 `^1.57.0` 升级；`pnpm-lock.yaml:36-38` 当前实际解析为 1.60.0，浏览器缓存版本随之变化。
- 本次运行 27 项全部因缺少 `chromium_headless_shell-1223` 失败。
- `.github/workflows/docker-build.yml:20-71` 的唯一 job 只构建镜像，没有 `pnpm install`、前端 build、Vitest、浏览器安装或 Playwright 步骤。
- `README.md:481-492` 只把测试列为人工命令。

具体建议：

- 增加独立质量工作流，至少执行：

```bash
pnpm install --frozen-lockfile
pnpm --filter @easyauth/frontend build
pnpm --filter @easyauth/frontend test -- --run
pnpm --filter @easyauth/frontend exec playwright install --with-deps chromium
pnpm --filter @easyauth/frontend e2e
```

- 缓存 Playwright 浏览器时把实际 Playwright 版本纳入 cache key。
- PR 必须等待这些 job 成功，不得只依赖镜像能构建。

### F-05：所谓“视觉回归”没有截图基线，且只检查前 12 个控件

- 严重级别：中
- 置信度：高
- 类型：误导、低价值
- 建议：修复或替换

证据：

- `frontend/e2e/visual-alignment.spec.ts:17-31` 只检查标记文案、路由属性、可点击性和文本横向溢出。
- `frontend/e2e/visual-alignment.spec.ts:176-181` 把每个范围的可见控件检查硬截断为前 12 个。
- `frontend/e2e/visual-alignment.spec.ts:184-221` 只做中心点遮挡和 DOM 几何启发式检查，没有 `toHaveScreenshot` 或像素基线。
- `docs/architecture/easyauth-frontend-visual-contract.md:150-158` 将其称为“视觉回归”和“已完成的验证”。

影响：

- 页面下半段、弹窗后续控件、移动端折叠区、颜色、间距、字体、错位和大部分视觉变化不会失败。

具体建议：

- 若不引入截图基线，将文件和文档改称“布局冒烟”，明确能力边界。
- 对登录壳、门户申请、控制台关键弹窗建立少量稳定截图基线；对动态区域做明确遮罩。
- 不要以“前 12 个”代表整个页面；按关键区域选择具名控件。

### F-06：静态 i18n 护栏手工列白名单，已出现真实漏检

- 严重级别：中
- 置信度：高
- 类型：过时、误导、低价值
- 建议：替换

证据：

- `frontend/src/i18n/noHardcodedChinese.test.ts:12-43` 手工维护 `GUARDED_FILES`。
- `frontend/src/i18n/noHardcodedChinese.test.ts:47-56` 只对名单中的文件做简易正则扫描。
- `frontend/src/pages/console/workspace/tabs/GuideTab.tsx:20-21`、`:36-39`、`:64`、`:73` 存在多处用户可见硬编码中文，但 `GuideTab.tsx` 不在白名单中，测试仍然通过。
- `frontend/src/pages/console/workspace/tabs/ManifestTab.tsx:411-425` 的“新增/变更/移除”也没有进入该白名单扫描。

这已经不是理论上的未来漏检，而是当前确定存在的假阴性。

具体建议：

- 删除手写文件清单，按 `frontend/src/pages` 与用户可见组件目录自动发现源文件。
- 静态规则迁移为 lint/独立架构检查；Vitest 只保留语言切换和运行时用户可见行为。
- 新回归应证明新增任意页面文件都会自动被检查。

### F-07：大量样式与源码字符串测试对实现细节高度耦合

- 严重级别：中
- 置信度：高
- 类型：低价值、脆弱、误导
- 建议：删除或替换

证据：

- `frontend/src/components/tableArchitecture.test.ts:9-32` 扫描整个源码目录并匹配禁止字符串。
- `frontend/src/components/tableArchitecture.test.ts:35-59` 直接读取 `PermissionSelector.tsx`，要求特定 import、变量名、`useState`/`useMemo` 源码形状和正则片段。
- `frontend/src/components/tableArchitecture.test.ts:63-96` 把递归文件扫描和禁词规则塞进常规 Vitest。
- `frontend/src/components/AppShell.test.tsx:318-339` 直接固定 `56px`、`240px`、`1440px`、圆角、阴影和 padding 的 CSS 文本。
- `frontend/src/components/baseComponents.test.tsx:32-42`、`:45-52`、`:72-80`、`:83-100`、`:121-160`、`:163-195` 大量断言 Tailwind class 和旧 class 不存在。

影响：

- 等价重构、设计 token 抽取或合法改名会产生假阳性；真实的可访问性、点击、布局或视觉错误反而可能通过。
- 仓库级静态架构规则混入组件测试，放大全量套件开销。

具体建议：

- `tableArchitecture.test.ts` 替换为独立 lint/架构检查命令。
- 删除纯 class/token 断言；保留加载中禁止点击、复制、Dialog 焦点/关闭、分页等行为断言。
- 视觉细节由浏览器截图或设计 token 单一事实源验证。

### F-08：凭据重复提交在父子两层重复覆盖

- 严重级别：低
- 置信度：高
- 类型：重复
- 建议：合并

证据：

- `frontend/src/pages/console/workspace/credentials/CreateCredentialForm.test.tsx:8-30` 验证创建中按钮禁用以及再次点击不触发回调。
- `frontend/src/pages/console/workspace/tabs/CredentialsTab.test.tsx:14-44` 再次验证同一按钮在创建请求在途时只发送一次 POST。

父层集成测试能覆盖真实 mutation 与网络次数，价值更高。建议保留父层测试；子层只保留“两个凭据类型按钮都正确传参”这类纯组件职责，避免重复验证同一个 `isCreating` 门槛。

### F-09：连接器 E2E 与组件测试重叠，但没有覆盖真实高风险链路

- 严重级别：中
- 置信度：中高
- 类型：重复、低价值、网络伪造
- 建议：替换

证据：

- `frontend/e2e/connector.spec.ts:41-80` 通过 mock 完成“测试连接后保存启用、再保存映射”。
- `frontend/src/pages/console/workspace/tabs/ConnectorTab.test.tsx:67-163` 已更深入覆盖候选配置必须重新测试、旧测试结果失效、测试结果不能跨 connector key 复用。
- `frontend/src/pages/console/workspace/tabs/ConnectorTab.test.tsx:165-260` 还覆盖映射读取失败、缓存后失败和畸形 `200`。

具体建议：

- mock 浏览器测试缩减为一条最短 happy path，或直接由组件测试承担。
- 浏览器预算改投真实后端的创建/编辑、删除、手动 reconcile、失败响应和权限拒绝。

### F-10：相对当前时间的回归未冻结系统时钟

- 严重级别：低到中
- 置信度：中
- 类型：时间敏感
- 建议：修复

证据：

- `frontend/src/pages/portal/hooks/useAccessRequestForm.test.ts:111-132` 使用 `Date.now() ± 1 小时` 验证过去/未来。
- `frontend/src/pages/portal/PortalPage.test.tsx:294-331` 使用 `Date.now() + 7 天`，再按本地时区转换 `datetime-local`。

当前时间间隔较大，普通运行通常稳定，但测试仍依赖机器时区和真实时钟。建议使用 `vi.useFakeTimers()` 与 `vi.setSystemTime(...)` 固定基准时间，并在结束后恢复真实计时器。

### F-11：测试初始化本身持续触发 `localStorage` 环境告警

- 严重级别：低
- 置信度：高
- 类型：环境敏感、噪声
- 建议：修复

证据：

- `frontend/src/test/setup.ts:32-45` 用 `!window.localStorage` 判断是否需要 stub；读取该属性本身就在当前 Node/jsdom 环境触发实验警告。
- `frontend/src/test/setup.ts:48-51` 每项测试又直接访问并清空该对象。
- 两次完整 Vitest 运行都由大量 worker 重复输出相同警告。

噪声会掩盖新的真实警告。建议为 jsdom 配置稳定 URL，或在不触发 getter 的前提下显式定义测试用 Storage；同时把意外 `console.warn/error` 纳入失败策略。

## 关键缺失回归

以下按风险排序，均应新增具体业务回归，不建议用纯渲染或 class 断言替代。

### 1. 真实鉴权与 Django shell

业务证据：

- `frontend/playwright.config.ts:13-17` 当前不启动 Django。
- `frontend/e2e/smoke.spec.ts:172-208` 当前直接伪造管理员身份。

应补场景：

1. 匿名访问 `/console`、`/portal`、`/auth` 的真实重定向。
2. 普通用户访问系统管理员页面得到明确拒绝。
3. Django 模板把真实 root 属性、CSRF 和用户上下文交给 React 后能成功挂载。
4. 生产构建资源由 Django shell 正确加载。

### 2. 真实 Portal 申请闭环

应补场景：

1. 选择授权组/直接权限后，真实请求 payload 与服务端契约一致。
2. 服务端校验失败、409、500、超时分别显示准确错误，不能显示成功。
3. 提交中重复点击只产生一个真实请求，并正确复用幂等键。
4. 成功后历史列表和授权状态从真实后端刷新。

### 3. 生命周期入职页

业务证据：

- `frontend/src/App.tsx:90` 暴露 `/console/lifecycle/onboarding`。
- `frontend/src/pages/console/lifecycle/OnboardingPage.tsx:78-147` 包含模板查询、创建、编辑、启停、删除。
- `frontend/src/pages/console/lifecycle/OnboardingPage.tsx:424-463` 组装应用、组、权限与 `timed` 的 `duration_days`。
- 没有 `OnboardingPage.test.tsx`。

应补场景：

1. `group` 与 `permission` 项的 payload 正确。
2. 只有 `grant_type=timed` 才发送有效 `duration_days`。
3. 启停和删除成功/失败均有明确反馈并刷新列表。
4. 批量入职的冲突、部分失败、成功后刷新。

### 4. Catalog 高风险写入

业务证据：

- `frontend/src/pages/console/workspace/tabs/CatalogTab.tsx:86-101` 同时读取 tree、group、permission、scope。
- `frontend/src/pages/console/workspace/tabs/CatalogTab.tsx:106-155` 分别执行 permission、scope、group 写入和缓存失效。
- `frontend/src/pages/console/ConsoleAppWorkspace.test.tsx:32-87` 目前只验证已有内容能渲染，没有验证这些写入。

应补场景：

1. permission 的 `supported_scopes` 去空格、去空项并形成正确 payload。
2. group/scope/permission 编辑回填与 PATCH 路径。
3. scope 启停后 scope 列表与 permission tree 同步刷新。
4. 四个读取中任一个失败时展示明确错误，写入保持关闭。

### 5. WebAuthn 注册与序列化

业务证据：

- `frontend/src/lib/webauthn.ts:14-79` 负责 base64url、创建参数解析和注册凭据序列化。
- `frontend/src/pages/console/TwoFactorSection.tsx:459-489` 串联 begin、`navigator.credentials.create`、complete 与 step-up 密码。
- `frontend/src/pages/console/TwoFactorSection.test.tsx:16-106` 只覆盖 TOTP begin 失败、停用 TOTP 和删除 passkey，没有注册流程；不存在 `webauthn.test.ts`。

应补场景：

1. `challenge`、`user.id`、`excludeCredentials[].id` 的 base64url 解码。
2. `rawId`、`clientDataJSON`、`attestationObject`、`transports` 的序列化。
3. 浏览器返回 `null` 和抛 `DOMException` 时显示取消，不发送 complete。
4. complete 必须携带 `state_token`、`name.trim()` 和 `current_password`。

### 6. Guide 页签

业务证据：

- `frontend/src/pages/console/workspace/tabs/GuideTab.tsx:15-31` 读取接入说明并动态生成 endpoint、curl 和 TypeScript 示例。
- 当前没有 `GuideTab.test.tsx`。

应补场景：

1. 后端自定义 `permission_query_endpoint` 必须同步进入两种代码示例。
2. `credential_modes=[]` 展示真实空状态，不保留 skeleton 或旧数据。
3. 读取失败显示明确 Banner。
4. 同时修复并回归该页的 i18n 硬编码。

### 7. 真正的视觉基线

应补场景：

1. 登录壳、控制台应用页、Portal 申请页的桌面与 390px 移动端截图。
2. Dialog、长表格、错误 Banner、空状态和加载状态。
3. 字体加载失败、长中英文文案和横向滚动边界。

## 删除、修复、替换优先级

### 立即修复

1. 建立 CI 前端质量 job，并安装与锁文件版本一致的 Chromium。
2. 消除 Vitest 两次运行结果相反的问题。
3. 将畸形 `payload.data` 从空列表降级改为快速失败。
4. 清除 `act(...)` 与 `localStorage` 环境警告。

### 立即替换

1. 将 mock Playwright 与真实全栈 E2E 分层。
2. 将 `noHardcodedChinese.test.ts` 改成自动发现的 lint/架构规则。
3. 将 `tableArchitecture.test.ts` 从常规组件测试迁出。
4. 将“视觉回归”改为真实截图基线，或准确降级命名为布局冒烟。

### 可删除或合并

1. 删除 `AppShell.test.tsx:318-339` 的纯 CSS 文本锁定。
2. 删除 `baseComponents.test.tsx` 中只断言 Tailwind class/旧 class 的部分，保留行为测试。
3. 合并凭据父子两层重复提交测试。
4. 缩减 mock connector E2E，把重复状态机覆盖留在 Vitest。

## 无问题项

- 未发现被跳过、仅运行或待办测试。
- 未发现快照测试或仅快照测试。
- 未发现完全没有 `expect` 的测试用例。
- 未发现测试直接访问真实外部网络；Vitest 基本通过 `fetch` stub 隔离，Playwright 也主要通过本地 Vite 与 route mock 运行。

这些“无问题项”不改变总体结论：当前主要风险不是测试数量不足，而是测试门槛没有进入 CI、全量结果不可重复、部分测试固化错误业务契约，以及 E2E 能力被命名得比实际覆盖更强。
