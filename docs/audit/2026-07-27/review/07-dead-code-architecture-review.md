# 死代码与架构异味交叉复核

## 一、复核范围与口径

本次只读复核以下报告中的架构异味、死代码、兼容残留及相关假设：

- `01-backend-architecture-smells.md`
- `05-frontend-architecture-smells.md`
- `13-dead-code-and-dev-junk.md`
- `17-independent-full-sweep.md`

复核重点是调用方、导出面、Django/Celery/pytest 等动态注册、公开 SDK 外部消费者、前端动态导入、已生成但未跟踪的运行产物，以及复杂度是否确实来自职责混杂。没有删除或修改业务代码、测试、配置和构建产物。

分类口径：

- **确认**：源码和调用链足以支持原结论。
- **降级**：核心风险存在，但原报告扩大了问题边界、严重度或修复结论。
- **重复**：事实成立，但已被另一报告完整覆盖，不应重复计数。
- **矛盾**：当前代码直接否定原报告的某个子结论。
- **未验证**：仓库静态证据无法排除运行态、外部消费者或产品决策。

删除风险表示“直接删除原报告所指代码或材料”的风险，而不是按完整迁移方案重构后的风险。

## 二、结论摘要

1. 报告 13 的明确零引用项大多成立；Django 管理命令、公开 SDK 导出、pytest `autouse` fixture 和 `applications.models` 对拆分模型的导入不能按普通静态零引用处理。
2. `src/easyauth/static/easyauth/frontend/` 虽被 Git 忽略，却是当前 Django 页面运行所需的 Vite manifest 和散列资源目录，不属于可在运行中随手删除的缓存。
3. `BAS-04` 的依赖方向问题成立，但“连接器失败会回滚授权”表述过宽。授权事务内没有连接器网络或 broker 调用，只有连接器表更新和事务发件箱写入。
4. `BAS-01` 的总状态语义不够清晰，但系统并非无法持久化“授权已转授、钩子失败”：`HandoverGrantItem.status` 与 `HandoverAppAction.status` 已共同保存该事实。
5. 通知服务、生命周期服务、交接向导和访问申请 Hook 的复杂度均来自多个独立变化原因和重复规则，不是仅凭行数得出的“大文件”结论。
6. `EA-FE-05`、`D-07`、`C-11` 是同一组历史类型；`D-08` 与 `C-11` 是同一 `blocked` 兼容分支；`R-05` 是 `C-01` 的日志侧面，均应合并计数。

## 三、报告 01：后端架构异味复核

| 报告编号 | 分类 | 复核结论与精确证据 | 删除风险 |
| --- | --- | --- | --- |
| BAS-01 | 降级 | `_execute_action()` 确实先转授授权再调用钩子（`src/easyauth/lifecycle/services.py:290-300`），失败只更新动作状态（`:1011-1018`），而授权项已更新为 `done`（`:1100-1109`）。但原报告“状态无法表达部分完成”过强：动作有独立 `status`（`src/easyauth/lifecycle/models.py:192-196`），授权项也有独立 `status`（`:315-320`），两者已经表达“动作失败、授权项完成”。成立的是总览状态含义不自足、钩子步骤没有独立持久状态。 | 高。不能删除现有状态字段；需先迁移 schema、API、前端、任务和测试。 |
| BAS-02 | 确认 | `preview_action()` 在 `transaction.atomic()` 内取得 `select_for_update()` 行锁后同步调用钩子（`src/easyauth/lifecycle/services.py:213-238`、`:967-978`）；钩子总超时为 30 秒（`src/easyauth/webhooks/hooks.py:30-39`、`:79-86`）。这是明确的事务与网络职责耦合，不是函数尺寸问题。 | 高。不可直接删除锁或事务，否则会恢复旧响应覆盖风险。 |
| BAS-03 | 确认 | 提交校验与批准落地分别维护 `_current_group_ids()` 等同名规则；提交侧查询位于 `src/easyauth/access_requests/submission_validation.py:235-345`，批准侧位于 `src/easyauth/access_requests/application_grants.py:237-399`。批准侧对成员到期时间使用当前时刻过滤，而提交侧对应集合没有等价过滤，重复规则已发生实际语义分叉。 | 高。只能在建立单一事实源并迁移两侧调用后删除重复实现。 |
| BAS-04 | 降级；含矛盾子结论 | `GrantService` 顶层依赖连接器分发（`src/easyauth/grants/services.py:9`），并在授权事务内调用（`:57-138`）；分发会查询 `ConnectorInstance`、推进 generation 并写事务发件箱（`src/easyauth/connectors/dispatch.py:21-52`），依赖方向问题成立。原报告把“连接器失败”扩大为外部连接器故障则与代码矛盾：该路径没有网络或 broker 调用，真正的 broker 发送在 `src/easyauth/outbox/services.py:77-99`，异常被持久化后重试。会回滚授权的是连接器状态/发件箱数据库写失败，不是异步连接器执行失败。 | 高。直接删除通知会丢失授权变更后的对账触发；应先建立通用领域事件。 |
| BAS-05 | 确认 | CRM 命令自行调用 `_upsert_manifest_*` 写完整目录（`src/easyauth/applications/management/commands/seed_crm_pilot.py:62-83`、`:135-257`），而正式入口调用解析、版本记录和导入服务（`src/easyauth/applications/manifest_import.py:46-83`、`src/easyauth/applications/permission_templates.py:55-77`）。这是两条真实写路径，不取决于命令是否经仓库代码直接调用。 | 中到高。Django 会按命令名动态发现 `Command`（`seed_crm_pilot.py:47-59`）；产品用途确认前不能整文件删除。 |
| BAS-06 | 确认 | `notify/services.py` 不是单纯“大”：受理入口从规范化、解析、幂等、配额到落库（`src/easyauth/notify/services.py:278-389`），投递状态机位于 `:392-485`、对账位于 `:486-588`、清理位于 `:591-617`、外部回执解析位于 `:1318-1425`。这些职责具有不同变化原因和失败边界，职责问题成立。 | 高。只能按用例迁移调用方后拆分，不能按行段机械删除。 |
| BAS-07 | 确认 | 同一模块同时包含离职交接（`src/easyauth/lifecycle/services.py:111-619`）、转岗差异（`:619-755`）、入职（`:756-823`）和同步 Webhook 编排（`:213-465`）。`_execute_action()` 还同时控制事务状态、授权转授、HTTP 和审计（`:256-367`）。复杂度来自多个聚合和协议，不是仅由 1386 行推断。 | 高。原文件是大量 API、任务和测试的活跃入口。 |
| BAS-08 | 降级；修复建议部分矛盾 | `applications.models` 的确重导出拆分模块模型（`src/easyauth/applications/models.py:19-50`），大量调用方从桶模块导入，所有权不清。可是 `ops_models.py` 中的对象确实是 Django model，例如 `AppMembership`、`PermissionGroup`、`PermissionTemplateVersion` 和 `AuthorizationGroupAccessPolicy`（`src/easyauth/applications/ops_models.py:92-132`、`:193-234`）；Django 默认自动导入 `applications.models`，当前 `models.py:21-26` 的导入同时承担模型注册。若只“删除重导出”，这些模型可能不再进入 app registry。应先设计显式注册或重新布局，再收窄调用方导入。 | 高。禁止直接删除 `models.py` 中的模型导入。 |
| BAS-09 | 确认 | 请求模型没有列表内唯一性校验（`src/easyauth/admin_console/connectors_api.py:100-116`），`_replace_mappings()` 对重复 `authorization_group_key` 直接 `continue`（`:477-488`），随后按被改写的 `resolved` 成功落库并审计（`:489-551`）。 | 低到中。可删除静默分支，但必须同时增加请求级拒绝和契约测试。 |
| BAS-10 | 确认 | `ConnectorInstance.config` 对空密文及非对象 JSON 都返回 `{}`（`src/easyauth/connectors/models.py:137-144`），类型化校验要到具体连接器的 `validate_config()` 才发生（`src/easyauth/connectors/base.py:67-90`）。损坏持久化形态和未配置状态被合并。 | 中。删除兜底前需清理非法数据并明确合法空配置。 |
| BAS-11 | 确认 | DingTalk 客户端只保证最外层 `progress`/`send_result` 是字典（`src/easyauth/integrations/dingtalk/api_client.py:221-243`）；领域服务对内部非列表、坏元素和未知形态返回空集合或跳过（`src/easyauth/notify/services.py:1318-1425`）。对账入口还把 API 异常直接转换为空变更（`:564-588`）。 | 中到高。必须先引入严格 DTO 和可观察错误状态。 |
| BAS-12 | 确认 | 模型常量定义在 `src/easyauth/grants/models.py:24-36`，又在 `grants/status.py:9`、`grants/services.py:26` 重复 `Literal`；生命周期服务直接比较 `"active"`（`src/easyauth/lifecycle/services.py:923-925`、`:1122-1140`），授权项种类又在约束和 `clean()` 重复（`src/easyauth/lifecycle/models.py:325-347`）。 | 中。裸字符串不能先删，需先迁移到唯一枚举。 |
| HYP-01 | 未验证 | 通用写辅助只提供上下文、保存和审计（`src/easyauth/admin_console/catalog_write_common.py:53-68`、`:129-152`），权限 API 自行路由写操作（`src/easyauth/admin_console/permissions_api.py:47-64`）。这只证明写编排分散，尚未枚举出实际漏审计、漏版本或漏事件的入口。 | 高。不得据假设批量删除或改写所有写入口。 |
| HYP-02 | 未验证 | 跨 App 不变量确有部分位于 `clean()`（例如 `src/easyauth/applications/models.py:535-557`），`bulk_create()` 不会自动调用它；但报告也没有确认正式授权写路径绕过校验。仓库内存在多处批量写并不等于它们写入该模型。 | 高。需先证明具体旁路和数据库可表达性。 |

## 四、报告 05：前端架构异味复核

| 报告编号 | 分类 | 复核结论与精确证据 | 删除风险 |
| --- | --- | --- | --- |
| EA-FE-01 | 确认 | `HandoverWizard` 用裸整数步骤和多组互相依赖状态（`frontend/src/pages/console/lifecycle/HandoverWizard.tsx:61-95`），转换、保存和禁用规则分散在 `:256-315`，批量执行与行内重试重复传输协议（`:221-246`、`:507-537`）。这是状态机、传输和五步视图的职责混合，不是仅因函数 530 行。 | 高。需保留现有流程行为并一次性迁移控制器和视图。 |
| EA-FE-02 | 确认 | Hook 自定义目录类型（`frontend/src/pages/portal/hooks/useAccessRequestForm.ts:18-80`），返回近 40 项的扁平接口（`:133-173`），还包含提交、树算法、联动副作用和契约解码（`:252-305`、`:394-474`、`:498-767`、`:888-1028`）。展示组件反向依赖 Hook 内类型/函数（`frontend/src/pages/portal/components/PermissionSelector.tsx:27-30`）。 | 高。不可只删除导出；需先搬迁类型和纯函数。 |
| EA-FE-03 | 确认 | 权威树模块有带 `visited` 的遍历（`frontend/src/pages/portal/permissionTree.ts:15-35`），Hook 又实现 scope 版本（`useAccessRequestForm.ts:652-668`、`:861-877`），选择器再实现一套没有同等防环语义的遍历（`PermissionSelector.tsx:835-970`）。提交与展示消费不同实现，属于规则重复。 | 高。先建立统一节点模型和行为测试，再删重复实现。 |
| EA-FE-04 | 确认 | 默认值 `"300"` 分散在初始/重置状态（`frontend/src/pages/console/workspace/tabs/ConnectorTab.tsx:100`、`:143`），提交以 `Number(intervalDraft) \|\| 300` 静默纠错（`:195-201`），范围另写在输入属性（`:464-468`）。 | 低到中。可删除兜底，但需同步显式字段校验。 |
| EA-FE-05 | 重复 | 与 D-07、C-11 的两个历史类型完全相同：`frontend/src/lib/domain.ts:81-89`、`:385-394`。无消费者且前端包为私有包（`frontend/package.json:2-5`），原事实成立，但只能计一次。 | 低。 |
| EA-FE-06 | 降级 | 20 个页面文件重复 `getHeaderGroups().map`，`CatalogTab` 自身有三套（`frontend/src/pages/console/workspace/tabs/CatalogTab.tsx:270`、`:319`、`:370`），重复骨架成立。原报告称架构测试“禁止建立合适抽象”过强：测试确实禁止旧名称和要求权限选择器直接用原生表格（`frontend/src/components/tableArchitecture.test.ts:8-33`、`:74-96`），但没有禁止新的组合式渲染器；权限树表格也可能合理保留专用渲染。应先用两个代表页面验证抽象边界。 | 中到高。批量替换表格会影响分页、树行、可访问性和空态。 |
| EA-FE-07 | 确认 | 门户列表在页面模块内解码并以 `as unknown as` 收尾（`frontend/src/pages/portal/portalListPayload.ts:47-166`）；审批、通知渠道和连接器又各自维护解码器（`PortalApprovalsSection.tsx:609-680`、`IntegrationTab.tsx:460-536`、`ConnectorTab.tsx:873-923`）。同一传输职责散落且无法由类型反推校验完整性。 | 高。需先建立端点契约模块。 |
| EA-FE-08 | 确认 | JS 用 160 毫秒定时器维护进入/退出状态（`frontend/src/pages/portal/components/PermissionSelector.tsx:79-85`、`:734-832`），CSS 另写相同 160 毫秒（`frontend/src/styles/features/permission-selector.css:226-250`），两侧还各自判断减少动效（TSX `:81-85`、CSS `:423-437`）。这是跨层生命周期协议，不是单纯文件大。 | 中。直接删 timer 会让退出行过早卸载。 |
| EA-FE-09 | 确认 | `package.json` 没有 lint 脚本或 ESLint 依赖（`frontend/package.json:6-11`、`:23-37`），源码却有无效的 ESLint 压制（`HandoverWizard.tsx:122`、`:218`）。测试脚本把透传参数附到 `node -e` 且启用 `shell: true`（`package.json:10`），参数解析问题由脚本结构直接支持。 | 中。先建立等价 CI 命令，再删除旧脚本。 |
| EA-FE-10 | 确认 | 用户选择器、顶栏和权限选择器分别注册 document 监听（`frontend/src/components/UserSelect.tsx:42-55`、`:135-153`；`frontend/src/components/shell/Topbar.tsx:37-61`；`PermissionSelector.tsx:356-379`）。Escape 监听范围和焦点恢复行为不同，重复行为层成立。 | 中到高。统一原语前删除任何一处会破坏关闭行为。 |
| H-01 | 未验证 | `useAccessRequestForm` 的提交可用性使用渲染时当前时间，`AccessRequestFields` 的 `min` 只在挂载时生成；但没有假时钟跨界测试证明实际陈旧状态。原报告保留为假设是正确的。 | 中。 |
| H-02 | 未验证 | 映射查询成功后会整体重建草稿，但是否应保留本地脏值是产品冲突策略，不可仅凭静态代码确定。原报告保留为假设是正确的。 | 中。 |

## 五、报告 13：死代码、导出与兼容残留复核

### 5.1 明确死材料

| 报告编号 | 分类 | 复核结论与精确证据 | 删除风险 |
| --- | --- | --- | --- |
| D-01 | 确认 | 旧处理器只在 `src/easyauth/admin_console/permission_templates.py:23-116` 内自洽调用；`admin_console/urls.py` 没有导入或注册它。该模块不符合 Django 自动发现的 `models.py`、`admin.py`、`apps.py` 或 `management/commands/*` 入口形态。 | 低到中。仓库外运维脚本直接导入内部模块的可能性很低但静态搜索不能绝对排除。 |
| D-02 | 确认 | `paginate_items` 只有定义（`src/easyauth/portal/pagination.py:70-85`）；`expiring_grant_items_for_user` 只有定义和导出（`src/easyauth/portal/api_data.py:40`、`:53`）。当前 API 使用数据库分页的 `*_page_for_user`（`api_data.py:63-86`）。 | 低。 |
| D-03 | 确认 | `api_data` 从权威模块导入并再导出旧函数（`src/easyauth/portal/api_data.py:16-20`、`:36`），生产 API 只消费 `access_request_item` 和分页函数。它不是包级稳定 SDK。 | 低。 |
| D-04 | 确认 | 七个符号均只有定义：`accounts/oidc_exchange.py:42`、`admin_console/auto_onboarding_api.py:46`、`admin_console/operations_api.py:52`、`lifecycle/services.py:64`、`workflows/services.py:65`、`notify/models.py:89`、`sdk/python/src/easyauth_app_sdk/manifest.py:38`。最后一个白名单还与实际“接受未来能力”的校验策略相反（`manifest.py:86-100`）。这些均不是 decorator 注册对象。 | 低。 |
| D-05：`create_permission` | 确认 | 仅定义于 `src/easyauth/admin_console/configuration.py:53-70`；该模块的真实调用方只导入审批规则 mutation（`approval_rules_api.py:34-38`、`approval_rule_handlers.py:24-28`）。权限写入走 `permissions_api._create_permission`（`src/easyauth/admin_console/permissions_api.py:47-67`）。 | 低。 |
| D-05：`reset_worker_dispatch` | 确认死代码；“可能缺失接线”矛盾 | 函数只定义于 `src/easyauth/connectors/services.py:145-153`。当前 broker 失败由事务发件箱捕获（`src/easyauth/outbox/services.py:77-99`），并把事件恢复为带退避时间的 `pending`（`:153-169`）；连接器 generation 的任务直到真正执行时才取得并清理 claim（`connectors/services.py:178-212`）。因此它不是必须补到 broker 异常边界的恢复函数，其 docstring 对旧分发模型的描述已过期。 | 低到中。删除前补一条“发件箱失败后重试同一事件”的状态测试即可。 |
| D-06 | 确认 | 文件局部 `_logged_in_superuser` 定义在 `tests/integration/admin_console/test_permission_catalog_write_api_ops1.py:557-561`，同文件调用只使用 `_logged_in_user`（`:550-554`）。它不是 fixture，也不能被其他模块同名函数调用。 | 低。 |
| D-07 | 重复 | 与 EA-FE-05、C-11 相同，定义只在 `frontend/src/lib/domain.ts:81-89`、`:385-394`。 | 低。 |
| D-08 | 重复 | 与 C-11 相同。`readinessLabel`、`readinessTone` 接受历史 `blocked`（`frontend/src/lib/status.ts:42-68`），后端事实源只允许 `blocking`、`warning`、`ready`（`src/easyauth/applications/configuration.py:23-29`）。 | 低。 |
| D-09 | 确认，但只确认“导出面” | 代表性证据：`TABLE_PAGE_SIZE_OPTIONS` 在定义文件内使用（`frontend/src/components/ui/PaginationBar.tsx:7`、`:50`），`TablePagination.tsx:5` 的同名再导出无人导入；`zhCN`/`en` 在 `messages.ts:9`、`:1182` 导出但只在同文件 `:2354-2355` 使用；WebAuthn helper 在 `lib/webauthn.ts:14-27` 导出但只在同文件 `:52-74` 使用；其余内部 helper 定义位于 `lifecycleLabels.ts:101`、`workspace/utils.ts:10`、`useAccessRequestForm.ts:548-606`、`permissionTree.ts:15,56,69`。前端包为私有包，未发现动态模块反射。实现仍被文件内调用，不能删除实现。 | 低。只移除 `export`；`TablePagination.tsx:5` 仅删除无人消费的 `TABLE_PAGE_SIZE_OPTIONS` 再导出，不能删除同一行上仍被消费的 `DEFAULT_TABLE_PAGE_SIZE`。 |
| D-10 | 降级 | 缓存、`.DS_Store`、测试结果和发布包确实被忽略（`.gitignore:1-17`、`dist/.gitignore:1`），`git ls-files` 不跟踪报告所列产物。可是前端散列目录不是普通开发垃圾：Vite 明确输出到该目录（`frontend/vite.config.ts:16-22`），Django 每次渲染从 `.vite/manifest.json` 读取入口（`src/easyauth/frontend_shell.py:25-34`、`:140-166`），缺失会快速失败。 | 缓存低；前端产物在运行中为高，只有“清理后立即重建并重启验证”才可接受；`.env.local`、`db.sqlite3` 始终高。 |

### 5.2 动态入口、公开契约和兼容层

| 报告编号 | 分类 | 复核结论与精确证据 | 删除风险 |
| --- | --- | --- | --- |
| R-01 | 未验证 | `DINGTALK_REF_PREFIX` 确实作为 SDK 顶层公共 API 导出（`sdk/python/src/easyauth_app_sdk/__init__.py:14-21`、`:55-64`），常量标记为 legacy（`client.py:31-36`），仓库内只有测试和文档依赖。顶层导出正是仓库外 `from easyauth_app_sdk import ...` 的稳定入口，不能用仓库零引用证明外部零使用。 | 中到高。需先确认是否实际发布和下游依赖。 |
| R-02 | 确认其为活跃兼容层；必要性未验证 | SDK 仍承诺裸 ID/`dt:<id>` 输入（`sdk/python/src/easyauth_app_sdk/client.py:201-208`、`:262-269`），服务端运行时解析旧前缀（`src/easyauth/notify/services.py:773-787`），公共 README 仍说明兼容。它不是死代码。项目规则称尚未上线，但 SDK 变更记录存在公开导出记录；是否已有外部契约仍需日志或依赖清单。 | 高。需同时迁移 SDK、服务端、数据约束、文档和测试。 |
| R-03 | 确认其为活跃测试兼容层 | `autouse` fixture 修改 `Client.login` 并写 Authentik session（`tests/integration/admin_console/conftest.py:15-40`）；26 个文件共 33 处 `client.login(...)` 依赖该行为。动态 fixture 注册明确，不能按普通函数删除。 | 高。先提供显式 helper 并迁移全部调用。 |
| R-04 | 未验证 | `Command` 位于 Django 约定目录并可被 `manage.py seed_crm_pilot` 动态发现（`src/easyauth/applications/management/commands/seed_crm_pilot.py:47-59`）；仓库内只有专用测试通过 `call_command` 调用，但这不能排除人工运维使用。与 BAS-05 不冲突：平行写入问题已确认，整个产品入口能否删除仍未验证。 | 中到高。 |
| R-05 | 重复 | `itemsFromPayload` 记录原始非法值并返回共享空数组（`frontend/src/lib/api.ts:105-116`）。这是 C-01 的同一契约兜底路径，只新增了隐私/日志侧面，不应作为独立死代码项计数。 | 低到中。删除日志应与改为严格失败同批完成。 |

### 5.3 动态注册误删边界

报告 13 的排除清单总体正确：

- Django `AppConfig`、model 字段和 `Command` 通过框架反射发现，不能按普通调用搜索删除。
- Celery signal `@task_success.connect` 和 pytest `@pytest.fixture` 是显式 decorator 注册。
- `gunicorn`、`psycopg`、TypeScript 类型包和 Docker entrypoint 的使用不以源码 import 为准。

另外必须补充一个动态注册边界：`src/easyauth/applications/models.py:19-26` 导入拆分文件中的 Django models，这些导入不仅是“方便重导出”，还让 Django 自动导入 `applications.models` 时注册这些类。因此 BAS-08 的修复不能机械套用 D-03/D-09 的“删除再导出”方法。

## 六、报告 17：与本次主题相关的交叉项

报告 17 的反馈、国际化文案、移动布局等产品问题不属于死代码/架构复核范围。以下仅列与本次主题直接相关的项目。

| 报告编号 | 分类 | 复核结论与精确证据 | 删除风险 |
| --- | --- | --- | --- |
| C-01 | 重复 | 泛型请求强制断言（`frontend/src/lib/api.ts:97-102`）、非法列表返回 `EMPTY_ITEMS`（`:105-116`）和 E2E `{ items: [...] }` 假数据（`frontend/e2e/visual-alignment.spec.ts:84-120`、`smoke.spec.ts:277-298`）均成立；架构根因已由 EA-FE-07 覆盖，日志侧面由 R-05 覆盖。 | 高。不能只删空数组，需同步真实 envelope、解码器和 E2E。 |
| C-04 | 确认，但仅 console 分支是死代码 | 通知按钮是可达的活跃占位组件（`frontend/src/components/shell/NotificationsButton.tsx:10-34`，由 `Topbar.tsx:73-76` 无条件渲染）；门户设置占位也是活跃路由（`frontend/src/App.tsx:61-68`）。真正不可达的是 `SettingsPlaceholder` 的 `mode === "console"` 分支（`App.tsx:131-145`），因为 console 设置直接使用真实页面（`:95`）。 | console 分支低；通知和门户设置入口为中，需产品决策。 |
| C-06 | 确认 | 国际化上下文已有随 locale 变化的 formatter（`frontend/src/i18n/I18nProvider.tsx:49-69`），`status.ts` 却提供默认 `zh-CN` 的第二实现（`frontend/src/lib/status.ts:149-163`），门户调用不传 locale（`frontend/src/pages/portal/PortalPage.tsx:89`、`:149-160`）。这是职责重复和默认值漂移。 | 中。先迁移所有调用方，不能直接删公共 helper。 |
| C-09 | 确认 | `App.tsx` 同步导入全部 portal/console 页面（`frontend/src/App.tsx:11-24`），生产入口再同步导入 `App`（`frontend/src/main.tsx:1-11`）；没有生产路由 `lazy()`/动态 `import()`。当前忽略产物 `main-CNN3Qfdd.js` 为 826076 字节，与报告数值一致。 | 中到高。按路由拆包需增加 `Suspense`、加载态和构建/真实页面验证。 |
| C-11 | 重复 | 历史类型与 EA-FE-05、D-07 重复；`blocked` 分支与 D-08 重复。 | 低。 |
| C-13 | 确认 | Dialog 直接挂载静态 portal（`frontend/src/components/Dialog.tsx:45-61`），Toast 关闭时立即从数组删除（`frontend/src/components/ui/Toast.tsx:77-84`、`:209-225`）。缺少退出状态是实际组件生命周期设计，不是文件尺寸判断。 | 中。直接加 CSS 不能解决退出前卸载，需先引入 exiting 状态。 |
| H-01 | 未验证 | 通配路由确实静默重定向（`frontend/src/App.tsx:68`、`:96`），但是否违反产品的未知路径策略需要产品口径和深链测试。 | 中。 |
| H-02 | 未验证 | Toast 固定在右上、宽 360 像素且可堆叠（`frontend/src/components/ui/Toast.tsx:209-225`），没有真实窄屏遮挡证据。原报告保留假设是合理的。 | 中。 |

## 七、去重后的处理建议

### 可直接进入低风险删除/收窄批次

- D-01、D-02、D-03、D-04、D-06。
- D-05 的 `create_permission`；`reset_worker_dispatch` 在补足发件箱失败重试测试后删除。
- EA-FE-05/D-07/C-11 的两个历史类型，只处理一次。
- D-08/C-11 的 `blocked` 分支，只处理一次。
- D-09 只收窄导出面，不删除文件内仍被调用的实现。
- C-04 中 `SettingsPlaceholder` 的不可达 console 条件分支。

### 必须先迁移调用方或建立新边界

- BAS-01 至 BAS-04、BAS-06 至 BAS-08、BAS-11、BAS-12。
- EA-FE-01 至 EA-FE-03、EA-FE-06 至 EA-FE-10。
- C-01、C-06、C-09、C-13。
- R-02、R-03。

### 必须先取得外部或产品证据

- R-01：SDK 发布和外部 import 清单。
- R-02：真实 legacy ref 请求比例和迁移窗口。
- R-04：CRM 试点是否仍是人工初始化入口。
- 01 的 HYP-01/HYP-02、05 的 H-01/H-02、17 的 H-01/H-02。

### 清理产物的安全边界

- 可重建缓存可以清理。
- `.env.local`、`db.sqlite3` 不得纳入默认清理。
- `src/easyauth/static/easyauth/frontend/.vite/` 和 `assets/` 只能作为“清理后立即重建”的原子流程处理；按项目规则，重建后还必须重启当前 Django 开发服务并通过真实目标 URL 验证新 manifest 和散列文件已加载。

## 八、复核边界

- 本次使用全仓精确符号搜索、导入搜索、Django 目录约定、前端 ESM import、Git 跟踪/忽略状态和当前生成产物进行复核。
- 没有查询外部 PyPI、私有制品库、下游仓库、生产日志或人工运维记录，因此 R-01、R-02、R-04 不能从“仓库内零调用”升级为“外部零使用”。
- 没有执行删除、构建、测试、服务重启或 HTTP 请求；本次唯一新增内容是本复核文档。
