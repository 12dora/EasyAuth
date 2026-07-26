# 前端审计证据复核

## 一、结论

本次复核以当前工作区源码为准，重点交叉检查 `05-frontend-architecture-smells.md`、`06-frontend-functional-bugs.md`、`07-ui-layout-accessibility.md` 和 `17-independent-full-sweep.md`，并用 `08`、`09`、`10`、`12`、`13`、`14` 号专项报告识别重复项。

总体判断：

- 06 号报告的功能缺陷证据最扎实，但 `06/C-05` 把“点击下一步立即被 PATCH 拒绝”写成了“允许走完整流程并最终提交”，关键运行时叙述与源码不符。
- 07 号报告的无障碍静态证据大多成立；`EA-UI-01`、`EA-UI-02` 的截图结论没有保存截图、浏览器轨迹或可直接重放的成功用例，必须把“源码可推导”与“本次可复核的运行时观察”分开。
- 05 号报告准确识别了结构事实，但多项“高严重度”只是维护风险推断，并非已观察到的功能错误。尤其 `EA-FE-03` 所称防环语义分叉只作用于被后端领域规则禁止的循环树。
- 17 号报告的大部分事实成立，但与专项报告重复较多，不应再次计入独立问题总数；其 `C-03`、`C-10`、`C-12`、`C-13` 更接近产品规范或设计质量建议，不能仅凭源码宣称已观察到用户损害。
- 本轮独立复现了生产主包 `826.08 kB`、定向 `npm test` 参数转发失败，以及默认并发 Vitest 不稳定。默认并发本次为 4 个文件、5 个用例失败；同 4 个文件以单 worker 重跑为 63 个用例全部通过。因此“存在并发/资源敏感性”已确认，但每次失败文件数和用例数不是稳定事实。

分类口径：

- `confirmed`：源码、契约或独立命令足以直接支持核心结论。
- `downgrade/qualify`：基础事实成立，但严重度、用户影响、触发范围或因果表述超过证据。
- `duplicate`：与另一报告的发现实质相同；事实可成立，但不能重复计数。
- `contradicted`：当前源码直接否定核心运行时叙述。
- `unverified`：缺少支持基线、运行时产物、业务数据条件或可复现实验。

## 二、05 号报告逐项复核

| 发现 | 分类 | 复核结论 |
| --- | --- | --- |
| `05/EA-FE-01` | `downgrade/qualify` | 裸整数步骤、分散转换和两套执行路径均存在，见 `frontend/src/pages/console/lifecycle/HandoverWizard.tsx:69`、`:197-219`、`:221-246`、`:256-311`、`:507-537`。但报告没有展示不可达状态、错误跳转或闭包竞态的复现；“高严重度”应降为中等架构债，运行时影响标为推断。 |
| `05/EA-FE-02` | `downgrade/qualify` | 千行 Hook 和宽返回接口是可核对的结构事实，见 `frontend/src/pages/portal/hooks/useAccessRequestForm.ts:133-213`、`:216-305`、`:888-1028`。但“非法中间组合会造成错误提交”没有样例或失败测试，严重度宜为中等维护风险。 |
| `05/EA-FE-03` | `downgrade/qualify` | 三个文件确有重复遍历：`frontend/src/pages/portal/permissionTree.ts:15-35`、`frontend/src/pages/portal/hooks/useAccessRequestForm.ts:652-668`、`frontend/src/pages/portal/components/PermissionSelector.tsx:943-970`。不过后端明确禁止权限分组环，见 `src/easyauth/applications/permission_group_rules.py:15-40`；选择器缺少 `visited` 不会使合法目录产生不同结果。应保留“重复实现、未来漂移”问题，删除“当前同树会得到不同结果”的高严重度暗示。 |
| `05/EA-FE-04` | `confirmed` | 空输入在 HTML 层是合法的非必填值，提交时由 `Number(intervalDraft) \|\| 300` 静默改为 300，见 `frontend/src/pages/console/workspace/tabs/ConnectorTab.tsx:195-201`、`:464-477`。修复为显式必填、整数和范围校验是对根因的处理。 |
| `05/EA-FE-05` | `duplicate` | 两个无消费者的历史类型存在于 `frontend/src/lib/domain.ts:81-89`、`:385-394`；与 `13/D-07`、`17/C-11` 重复。不得作为三个独立问题计数。 |
| `05/EA-FE-06` | `downgrade/qualify` | 20 个页面文件包含重复表头循环，`frontend/src/components/tableArchitecture.test.ts:74-96` 也确实用名称正则固化实现。但测试并没有禁止所有共享抽象，只禁止特定名称及 `PermissionSelector` 使用现有 primitives；“阻止建立合适抽象”和“一次性迁移全部调用方”是设计判断。建议降为中等或较低维护债，并先用一个表格族验证抽象边界。 |
| `05/EA-FE-07` | `confirmed` | 页面内存在多套手写解码器和收尾断言，例如 `frontend/src/pages/portal/portalListPayload.ts:47-166`、`frontend/src/pages/portal/hooks/useAccessRequestForm.ts:888-1028`、`frontend/src/pages/console/workspace/tabs/ConnectorTab.tsx:873-923`。建议以端点契约生成类型和解码器，且不放宽非法字段，符合项目快速失败要求。 |
| `05/EA-FE-08` | `downgrade/qualify` | JS 与 CSS 共享 `160` 的维护风险成立，见 `frontend/src/pages/portal/components/PermissionSelector.tsx:79`、`:734-831` 和 `frontend/src/styles/features/permission-selector.css:226-250`。但没有观察到实际错时；`10/MOT-06` 还把当前生命周期作为正向实现。严重度宜降为较低。修复若只改用 `animationend` 会遗漏 `prefers-reduced-motion: reduce` 下 `animation:none` 的不触发路径，必须有立即完成分支，见 `permission-selector.css:423-437`。 |
| `05/EA-FE-09` | `confirmed` | `frontend/package.json:6-11` 无 lint 脚本，`:23-37` 无 ESLint 依赖；`HandoverWizard.tsx:122`、`:218` 的压制注释当前没有门禁。独立执行 `npm test -- --run src/components/tableArchitecture.test.ts` 复现 `Missing script`，直接执行 Vitest 则 5 个测试通过。测试脚本部分也与 `14/BCO-11` 重叠。 |
| `05/EA-FE-10` | `confirmed` | 外部点击和 Escape 逻辑确实散落于 `frontend/src/components/UserSelect.tsx:42-55`、`frontend/src/components/shell/Topbar.tsx:37-61`、`frontend/src/pages/portal/components/PermissionSelector.tsx:356-379`，且焦点归还策略不同。按报告的低严重度保留合理。 |
| `05/H-01` | `unverified` | `frontend/src/pages/portal/components/AccessRequestFields.tsx:37` 和 `frontend/src/pages/portal/hooks/useAccessRequestForm.ts:196-210` 支持“时间自然跨界后状态可能陈旧”的假设，但没有假时钟复现。报告保留为假设是正确边界。 |
| `05/H-02` | `unverified` | `frontend/src/pages/console/workspace/tabs/ConnectorTab.tsx:677-693` 会在成功 refetch 后重建草稿，但是否应覆盖取决于产品对“重新加载”的定义；报告未把它提升为缺陷是正确的。 |

## 三、06 号报告逐项复核

### 3.1 确认或重复

| 发现 | 分类 | 复核结论 |
| --- | --- | --- |
| `06/C-01` | `confirmed` | 导航无能力过滤，见 `frontend/src/components/shell/Sidebar.tsx:22-49`；除新建应用外的路由没有超管守卫，见 `frontend/src/App.tsx:81-96`。这是可由非超管 Console 用户稳定触发的入口/API 能力不一致。 |
| `06/C-02` | `duplicate` | 行内启停、删除和接入入口无超管判断，见 `frontend/src/pages/console/ConsoleAppList.tsx:117-160`、`:181-191`；启停和删除 mutation 无失败处理，见 `:63-80`。它与 `17/C-02`、`09/TF-03`、`09/TF-04` 重复。 |
| `06/C-03` | `confirmed` | 工作区仅给凭据和集成传 `can_manage`，见 `frontend/src/pages/console/ConsoleAppWorkspace.tsx:163-173`。开发者可看到目录写按钮但后端仅允许 owner，见 `src/easyauth/applications/ownership.py:29-32`、`src/easyauth/admin_console/catalog_write_common.py:53-68`；owner 可看到成员按钮但成员 API 要求超管，见 `frontend/src/pages/console/workspace/tabs/OverviewTab.tsx:49-75`、`src/easyauth/admin_console/memberships_api.py:171-191`。连接器 UI 的 `canOperate` 只检查数据加载与类型，见 `frontend/src/pages/console/workspace/tabs/ConnectorTab.tsx:314-320`，而写 API 要求超管，见 `src/easyauth/admin_console/connectors_api.py:139-171`、`:692-699`。 |
| `06/C-04` | `confirmed` | Portal 申请列只有展示字段，见 `frontend/src/pages/portal/PortalPage.tsx:123-171`；撤回端点存在于 `src/easyauth/portal/urls.py:29-31` 和 `src/easyauth/portal/api.py:125-145`。 |
| `06/C-06` | `confirmed` | 所有任务都显示删除，见 `frontend/src/pages/console/lifecycle/HandoverTaskList.tsx:237-253`；服务只允许 `cancelled`，见 `src/easyauth/lifecycle/services.py:570-582`。 |
| `06/C-07` | `confirmed` | 编辑器可停用授权组，见 `frontend/src/pages/console/workspace/tabs/MatrixTab.tsx:321-328`；刷新列表只返回活动组，见 `src/easyauth/admin_console/permission_catalog_data.py:97-102`。管理闭环缺失成立。 |
| `06/C-08` | `confirmed` | 应用选择器固定请求第一页 100 条且无后续分页，见 `frontend/src/pages/console/lifecycle/OnboardingPage.tsx:424-428`。 |
| `06/C-09` | `confirmed` | mutation 从可变闭包取 `userId/token`，任意完成响应都会覆盖结果，按钮也未在 pending 时禁用，见 `frontend/src/pages/console/workspace/tabs/QueryTestTab.tsx:34-49`、`:83-96`。竞态可由两个不同延迟的 Promise 稳定构造。 |
| `06/C-10` | `confirmed` | Portal 优先显示后端 `status_label`，见 `frontend/src/pages/portal/PortalPage.tsx:137-160`、`frontend/src/pages/portal/components/PortalApprovalsSection.tsx:377-390`；因此当前语言无法控制状态文案。 |
| `06/C-11` | `duplicate` | `frontend/src/pages/console/TwoFactorSection.tsx:45-53` 把加载、错误和不支持折叠为 `null`。与 `09/TF-07` 重复。 |
| `06/C-12` | `confirmed` | 删除成功只失效查询，未收敛 `pageIndex`，见 `frontend/src/pages/console/ConsoleAppList.tsx:42-47`、`:71-80`、`:165-173`；分页栏会形成大于总页数的显示，见 `frontend/src/components/ui/PaginationBar.tsx:66-68`。 |
| `06/C-13` | `duplicate` | `frontend/src/components/CodeBlock.tsx:19-23` 在未等待 Clipboard Promise 时立即显示成功；与 `09/TF-10` 重复。 |
| `06/C-14` | `confirmed` | `frontend/src/components/ApprovalDecisionDialog.tsx:44-51`、`:80-94` 没有 2000 字符约束，而后端在 `src/easyauth/portal/approvals_api.py:52-59` 拒绝超长输入。按低严重度保留合理。 |
| `06/C-15` | `confirmed` | 任意 `:section` 都进入页面，`ENDPOINTS[section]` 失败后静默取默认配置，见 `frontend/src/App.tsx:92-94`、`frontend/src/pages/console/OperationsPage.tsx:40-45`、`:65-73`。 |
| `06/R-01` | `duplicate` | `frontend/src/lib/api.ts:105-116` 把非法 envelope 返回为空数组；与 `17/C-01`、`12/F-02` 重复。 |
| `06/R-02` | `confirmed` | `localStorage.getItem/setItem` 没有捕获 `SecurityError`，见 `frontend/src/i18n/I18nProvider.tsx:28-34`、`:57-60`。报告明确以受限存储为条件，没有越过证据边界。 |
| `06/R-05` | `duplicate` | 顶层没有 Error Boundary，见 `frontend/src/main.tsx:24-35`；与 `09/TF-14` 重复。 |
| `06/R-06` | `confirmed` | 前端把空 `supported_scopes` 当作全部活动 scope，见 `frontend/src/pages/console/workspace/tabs/MatrixTab.tsx:69-75`；后端只接受显式集合成员，见 `src/easyauth/admin_console/authorization_groups_api.py:260-275`。报告按条件性风险处理合理。 |
| `06/R-07` | `duplicate` | 组合框缺少 `aria-controls`、`aria-activedescendant` 和稳定 option ID，见 `frontend/src/components/UserSelect.tsx:72-103`、`:155-180`；它是 `07/EA-UI-04` 的子集。 |

### 3.2 被源码否定或仍未验证

| 发现 | 分类 | 复核结论 |
| --- | --- | --- |
| `06/C-05` | `contradicted` | 前端确实允许在接收策略为空时点击下一步，并发出 `to_user_id:null`、`release_to_pool:false`，见 `frontend/src/pages/console/lifecycle/HandoverWizard.tsx:125-149`、`:256-278`、`:305-311`。但下一步必须等这次 PATCH 的 `onSuccess` 才进入步骤 2；后端在同一次 PATCH 内调用 `update_action_receiver` 并执行 XOR 校验，失败后立即返回校验错误，见 `src/easyauth/admin_console/lifecycle_api.py:647-695`、`src/easyauth/lifecycle/services.py:178-188`、`:998-1006`。因此“允许走完整流程，最终提交时才拒绝”不成立。应改写为“前端缺少本地 XOR 校验，点击下一步会产生一次必失败且可见的 PATCH”。 |
| `06/R-03` | `unverified` | `frontend/src/components/shell/Sidebar.tsx:116-140` 无条件使用 `ResizeObserver` 是事实，但项目没有声明需支持不具备该 API 的浏览器/WebView。没有支持基线时不能判为中严重度产品风险。 |
| `06/R-04` | `unverified` | `frontend/src/pages/portal/hooks/useAccessRequestForm.ts:275-289` 直接使用 `crypto.randomUUID` 是事实，但是否缺失取决于浏览器和 HTTPS 部署基线。应先声明支持矩阵并做启动能力测试。 |

## 四、07 号报告逐项复核

| 发现 | 分类 | 复核结论 |
| --- | --- | --- |
| `07/EA-UI-01` | `downgrade/qualify` | 单行页头、不可收缩动作区和移动端全局裁剪可由源码确认，见 `frontend/src/components/PageHeader.tsx:12-18`、`frontend/src/pages/console/ConsoleAppList.tsx:177-192`、`frontend/src/styles/responsive.css:58-61`。但报告没有保存所称 390px 截图、DOM 测量或一条当前可成功运行的复现用例；“浏览器隔离渲染已确认”目前不可独立审计。缺陷本身可信，运行证据标签应改为“源码确认，报告称已观察”。 |
| `07/EA-UI-02` | `downgrade/qualify` | 表格只有 `min-w-full` 且单元格可逐字换行，见 `frontend/src/components/ui/tableStyles.ts:5-14`；这支持压缩风险。但 HTML table 的实际最小宽度仍受内容影响，报告同样未保存截图或测量结果。应保留共享响应式缺陷，降低运行时证据表述。 |
| `07/EA-UI-03` | `confirmed` | 颜色 token、10.5–13px 字号及消费位置可核对，见 `frontend/src/styles/index.css:15-29`、`:53-56`、`frontend/src/components/Badge.tsx:8-21`、`frontend/src/components/Field.tsx:20-21`、`:61-67`。报告给出的对比度方向和 AA 结论成立。 |
| `07/EA-UI-04` | `confirmed` | option 是可聚焦 button，却只有 `onPointerDown`，见 `frontend/src/components/UserSelect.tsx:72-103`；输入框模式又把活动项留在输入焦点但没有 ARIA 引用，见 `:135-180`、`:235-299`。键盘模型冲突成立。 |
| `07/EA-UI-05` | `confirmed` | 全局 `accent/50` 焦点环见 `frontend/src/styles/index.css:137-139`；登录模板更弱的半透明环见 `src/easyauth/accounts/templates/accounts/local_admin/login.html:145-148`。 |
| `07/EA-UI-06` | `confirmed` | 两处 tablist 都让所有 tab 保持默认 `tabIndex=0` 且没有方向键处理，见 `frontend/src/pages/console/ConsoleAppWorkspace.tsx:133-160`、`frontend/src/pages/portal/components/PortalApprovalsSection.tsx:232-249`。 |
| `07/EA-UI-07` | `confirmed` | `StatusBanner` 只渲染普通 div，见 `frontend/src/components/StatusBanner.tsx:20-30`；异步错误调用点没有统一 live region。修复应像报告所述按用途显式区分，而不是给所有静态 Banner 强加 `alert`。 |
| `07/EA-UI-08` | `confirmed` | 用户弹层声明 menu 但没有焦点进入、方向键和显式焦点归还，见 `frontend/src/components/shell/UserSummary.tsx:34-68`、`frontend/src/components/shell/Topbar.tsx:37-61`；语言和通知弹层也缺少内容关联，见 `frontend/src/components/shell/LanguageSwitcher.tsx:23-59`、`frontend/src/components/shell/NotificationsButton.tsx:16-33`。 |
| `07/EA-UI-09` | `confirmed` | `InfoTip`、chip 删除和 Toast 关闭按钮没有 padding 或最小尺寸，实际元素只由 13px、12px、15px 图标撑开，见 `frontend/src/components/InfoTip.tsx:11-18`、`frontend/src/components/UserSelect.tsx:313-323`、`frontend/src/components/ui/Toast.tsx:261-268`。 |
| `07/EA-UI-10` | `confirmed` | 工作账号入口是带 `role="button"` 的链接，见 `src/easyauth/accounts/templates/accounts/local_admin/login.html:250`；删除该角色是直接且充分的修复。 |
| `07/EA-UI-11` | `unverified` | 固定 `w-64`、居中定位和父级裁剪风险存在，见 `frontend/src/components/InfoTip.tsx:19-24`、`frontend/src/styles/responsive.css:58-61`，但没有保存 320px/390px 实测。报告已使用中置信度和代码推断，应继续留在待运行验证区，而非“已确认问题”。 |
| `07/EA-UI-12` | `confirmed` | topbar 内容高 56px 且外加 1px 边框，主区仍使用 `100vh - 56px`，见 `src/easyauth/accounts/templates/accounts/local_admin/login.html:41-56`、`:93-100`；1px 滚动的原因链完整。视觉 token 分叉也可由同模板 `:9-23` 与 `frontend/src/styles/index.css:11-29` 直接确认。 |

07 号报告“真实页面验证”只覆盖 `/auth/local/`；受保护 React 页是隔离 mock 渲染，不能写成真实后端数据验证。报告正文已说明这一点，但各发现的“验证方式：浏览器隔离渲染”仍应附可追溯截图或测量 JSON，否则复核者只能确认静态条件，不能确认所述像素结果。

## 五、17 号报告逐项复核

| 发现 | 分类 | 复核结论 |
| --- | --- | --- |
| `17/C-01` | `duplicate` | `frontend/src/lib/api.ts:97-116` 的契约兜底和 `frontend/e2e/visual-alignment.spec.ts:84-120` 的 `{items: [...]}` mock 均成立，但与 `06/R-01`、`12/F-02` 重复。修复为严格 envelope 解码并断言种子业务行是优质建议。 |
| `17/C-02` | `duplicate` | 与 `06/C-02`、`09/TF-03`、`09/TF-04` 相同，证据为 `frontend/src/pages/console/ConsoleAppList.tsx:63-80`。 |
| `17/C-03` | `downgrade/qualify` | 多个成功路径只关闭对话框或刷新缓存是事实，见 `frontend/src/pages/console/ConsoleAppWorkspace.tsx:65-75`、`:215-227` 和 `frontend/src/pages/console/ConsoleTeamDetail.tsx:75-113`。但“所有核心写操作都需要 Toast”不是由源码推出的缺陷；对话框关闭、数据立即更新或持久“已保存”均可构成反馈。应先建立交互规范，再按高风险、后台异步和页内保存分类，避免全站成功 Toast 噪声。该项还与 `09/TF-24`、`09/TF-25` 部分重复。 |
| `17/C-04` | `confirmed` | 通知组件明确标注占位并永远显示空状态，见 `frontend/src/components/shell/NotificationsButton.tsx:10-33`；Topbar 在公共壳也渲染它，见 `frontend/src/components/shell/Topbar.tsx:73-86`。Portal 安全设置进入占位页，见 `frontend/src/App.tsx:61-68`、`:131-145`。 |
| `17/C-05` | `duplicate` | 英文领域异常经 API `str(exc)` 和前端 `error.message` 直接展示，见 `src/easyauth/access_requests/target_validation.py:88-126`、`src/easyauth/access_requests/submission_validation.py:135-175`、`src/easyauth/portal/api.py:209-214`、`frontend/src/pages/portal/components/AccessRequestForm.tsx:70`。事实成立，但与 `08/I18N-04`、`08/I18N-05` 重复。 |
| `17/C-06` | `confirmed` | `frontend/src/lib/status.ts:149-163` 默认固定 `zh-CN`，而 Portal 直接调用它，见 `frontend/src/pages/portal/PortalPage.tsx:89`、`:149-160`。根因和修复方向正确。 |
| `17/C-07` | `duplicate` | Manifest 硬编码和 i18n 白名单遗漏均成立，见 `frontend/src/pages/console/workspace/tabs/ManifestTab.tsx:108-243`、`frontend/src/i18n/noHardcodedChinese.test.ts:12-43`；与 `08/I18N-01`、`08/I18N-16` 重复。 |
| `17/C-08` | `duplicate` | 与 `12/F-01` 重复。独立顺序运行 `pnpm --dir frontend test -- --run` 得到 4 个文件、5 个用例失败；随后把这 4 个文件用 `--maxWorkers=1 --no-file-parallelism` 重跑，63 个用例全部通过。因此不稳定性已确认，但报告中的“6 个文件、10 个用例”和“4 个文件、68 个用例”只是某次快照，不能作为稳定计数。失败中也包含等待不到 DOM 的断言，不应统一写成“主要都是 5 秒超时”。 |
| `17/C-09` | `duplicate` | `frontend/src/App.tsx:11-24` 同步导入全部路由；独立生产构建再次得到 `main-CNN3Qfdd.js` 826.08 kB、gzip 217.92 kB，并触发 500 kB 告警。事实成立，但与 `14/BCO-11` 的包体部分重复。 |
| `17/C-10` | `downgrade/qualify` | 10 个链接、小屏横向滚动和隐藏分组标题均可由 `frontend/src/components/shell/Sidebar.tsx:22-49`、`frontend/src/styles/responsive.css:16-35` 确认。可是“后部入口不可发现”尚无任务完成率、滚动位置或真实设备测试；报告的中高信心应降为中，并继续以运行验证为准。 |
| `17/C-11` | `duplicate` | `RoleItem`、`PortalCatalogRole` 与 `blocked` 兼容分支分别见 `frontend/src/lib/domain.ts:81-89`、`:385-394`、`frontend/src/lib/status.ts:48-65`；与 `05/EA-FE-05`、`13/D-07`、`13/D-08` 重复。 |
| `17/C-12` | `duplicate` | 内部字段名文案确实存在于 `frontend/src/i18n/messages.ts:201-218`、`:298-309`、`:337-350`，但“暴露技术标识符是否错误”取决于控制台目标用户和排障需求。它与 `08/I18N-07`、`08/I18N-13`、`08/I18N-14` 重复；应保留“业务主文案 + 可选技术详情”的建议，不把所有字段名视为缺陷。 |
| `17/C-13` | `duplicate` | Dialog 和 Toast 确实直接挂载/卸载，见 `frontend/src/components/Dialog.tsx:45-88`、`frontend/src/components/ui/Toast.tsx:77-84`、`:209-269`；与 `10/MOT-02`、`10/MOT-05` 重复。缺少动画是较低优先级设计缺口，不是功能错误。 |
| `17/H-01` | `unverified` | 通配路由重定向存在于 `frontend/src/App.tsx:68`、`:96`，但是否违反产品路由策略未定义。保留为假设正确。 |
| `17/H-02` | `unverified` | Toast 固定右上角和多条堆叠见 `frontend/src/components/ui/Toast.tsx:209-225`，但尚无 320px/390px 连续错误实测。保留为假设正确。 |

## 六、具体遗漏

仅记录能由当前源码直接证明、且会改变修复范围的遗漏：

1. `06/C-03` 漏掉连接器映射编辑同样没有超管能力门禁。映射保存 mutation 和按钮位于 `frontend/src/pages/console/workspace/tabs/ConnectorTab.tsx:696-748`、`:834-851`，后端 PUT 明确要求超管，见 `src/easyauth/admin_console/connectors_api.py:253-268`。修复能力模型时必须同时覆盖主配置、协调、删除、测试和映射写入。
2. `17/C-06` 只列了 `PortalPage`，实际固定 `zh-CN` helper 还被审批详情和大量 Console 页面调用。例如 `frontend/src/pages/portal/components/PortalApprovalsSection.tsx:422-452`、`:532`，`frontend/src/pages/console/ConsoleAppList.tsx:114`，`frontend/src/pages/console/ConsoleTeamDetail.tsx:232-233`、`:440`。修复不能只改 Portal 列表。
3. `17/C-07` 的证据范围止于 `ManifestTab.tsx:243`，但同文件后半仍有用户可见硬编码：空态在 `:268`，差异分类和表头在 `:414-437`，无差异文案在 `:469`。现有修复建议写了“全部文案”，执行清单仍应纳入这些位置。
4. `07/EA-UI-01`、`07/EA-UI-02` 缺少可审计的运行产物。报告称完成 390px 隔离截图，但仓库中没有对应截图、DOM 宽度记录或成功完成该场景的测试输出；现有 `frontend/e2e/visual-alignment.spec.ts:35-42`、`:84-120` 还包含过期定位器和契约错误 mock。应在修复前补一份可重复的像素/可见性基线。

## 七、修复建议质量

优先采纳：

1. `17/C-01` 的严格 envelope 解码、真实 mock 契约和种子业务值断言。
2. `06/C-01` 至 `C-03` 的服务端能力模型统一，但必须覆盖连接器映射遗漏。
3. `06/C-07` 的管理端“可见停用资源并可恢复”闭环。
4. `07/EA-UI-04`、`EA-UI-06`、`EA-UI-08` 的标准组合控件键盘模型。
5. `17/C-05` 的稳定错误码、结构化参数和前端本地化。

需要修改后再采纳：

1. `05/EA-FE-06` 不应先承诺“一次性迁移所有表格”；先以一种客户端表格和一种服务端表格验证窄抽象，再决定全量替换。
2. `05/EA-FE-08` 不能只用 `animationend` 代替定时器；必须处理减少动效、动画取消和节点提前卸载。
3. `06/C-05` 应修复本地 XOR 校验和错误定位，但不得沿用“完整流程最终失败”的错误复现描述。
4. `17/C-03` 不应把所有成功写操作机械统一为 Toast；应按风险和持续时间定义反馈契约。
5. `17/C-13` 的 140–200ms 数值没有项目内测量依据，宜先建立动效 token 和减少动效行为，再确定时长。

## 八、复核记录

- `npm test -- --run src/components/tableArchitecture.test.ts`：复现 `Missing script`。
- `npx vitest run src/components/tableArchitecture.test.ts`：5 个测试全部通过。
- `pnpm --dir frontend test -- --run`：独立顺序运行得到 41 个文件中 4 个失败、295 个用例中 5 个失败。
- 对上述 4 个失败文件执行 `npx vitest run ... --maxWorkers=1 --no-file-parallelism`：4 个文件、63 个用例全部通过。
- `pnpm --dir frontend build`：成功；主 JavaScript 为 826.08 kB，gzip 217.92 kB。
- 因生产构建刷新了 React 产物，已重启 `easyauth-web-1`；`GET /health/` 返回 200，`GET /console/` 返回预期 302 登录跳转，真实 HTTP 获取的 `main-CNN3Qfdd.js` 与本地构建文件 SHA-256 一致。

本复核没有修改业务源码、测试、配置或原始审计报告，也没有提交 commit。
