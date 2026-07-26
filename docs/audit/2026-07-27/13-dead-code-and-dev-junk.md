# EasyAuth 死代码与开发残留审计

## 1. 审计范围与结论

本报告审计 `/Users/konata/code/EasyAuth` 在
`18cd9363854efd9dfb0dce82291543c43b517add` 上的 Python、TypeScript、React、SDK、
配置、脚本、资产及工作区残留。审计只读代码和本地文件元数据，未读取
`.env.local`、`db.sqlite3` 的内容，未删除或修改业务实现。

结论摘要：

- 已确认 1 个整文件旧控制台处理器没有仓库内调用方。
- 已确认 4 个后端函数、7 个后端常量或类型别名、1 个测试辅助函数没有仓库内调用方。
- 已确认 2 个前端历史类型和 `blocked` 配置就绪状态兼容分支已失去当前契约生产者。
- Knip 报告 17 个未被其他模块消费的前端导出；实现多数仍在本文件内使用，应收窄导出面，
  不能把它们误删为整段死代码。
- 工作区存在 1158 个 `.pyc`、78 个 `__pycache__`、构建包、测试结果、旧前端构建和
  29 MiB 本地数据库；这些均被忽略，未提交进 Git。
- 未发现已提交的 `.pyc`、缓存目录、`.DS_Store`、`db.sqlite3`、wheel、sdist、
  `tsconfig.tsbuildinfo` 或前端散列构建产物。
- Ruff 的 `F401`、`F841`、`ARG`、`ERA`、`T10`、`FIX`、`TD` 检查通过；未发现已提交源码中的
  `TODO`、`FIXME`、`HACK`、`XXX` 或明显注释掉的代码块。
- Knip 未报告未使用或未声明的前端依赖；Python 直接依赖也都有源码、测试、Django 配置、
  Docker 入口或运行时驱动用途，未确认可直接删除的依赖。

严重级别：

- **高**：会持续掩盖真实行为、扩大安全或发布风险。
- **中**：形成明显维护负担、错误兼容面或可能隐藏缺失接线。
- **低**：不影响当前行为，但增加噪声、误导和清理成本。

置信度：

- **高**：静态工具和全仓精确调用方搜索一致，且没有框架反射入口。
- **中**：仓库内无调用，但公开 SDK、Django/Celery 反射或外部消费者仍可能使用。
- **低**：需要真实环境或产品决策才能判断。

## 2. 检查方法

使用的只读检查包括：

- `git ls-files`、`git status --ignored`、`git check-ignore`：区分已提交文件和本地忽略残留。
- Ruff：`F401`、`F811`、`F841`、`ARG`、`ERA`、`T10`、`FIX`、`TD`。
- BasedPyright：提取 `reportUnusedImport`、`reportUnusedVariable`、
  `reportUnusedClass`、`reportUnusedFunction`。
- Vulture：先以 80% 置信度扫描，再以 60% 置信度生成候选；Django model、Pydantic
  validator、Celery task、signal、pytest fixture 等反射入口均人工排除。
- Knip：扫描前端未使用文件、导出、依赖、未声明依赖和无法解析导入。
- TypeScript：额外启用 `--noUnusedLocals --noUnusedParameters` 做只读编译检查。
- `rg`：对每个候选进行全仓符号、导入、路由、任务名、脚本及资产引用复核。

静态“零调用”不等于外部公开 API 零使用。因此公开 SDK、管理命令、兼容输入和测试基础设施
单独放在“需要运行态或外部契约确认”一节。

## 3. 已确认的死材料与开发残留

### D-01 整个旧权限模板表单处理器没有调用方

- **证据**：
  - `src/easyauth/admin_console/permission_templates.py:23` 定义
    `PermissionTemplateConsoleResult`。
  - `src/easyauth/admin_console/permission_templates.py:33` 定义
    `handle_permission_template_post`，分派 `preview_permission_template` 和
    `apply_permission_template` 旧表单动作。
  - 文件共 116 行；全仓搜索
    `easyauth.admin_console.permission_templates`、`handle_permission_template_post`、
    `PermissionTemplateConsoleResult` 只命中该文件自身。
  - `src/easyauth/admin_console/urls.py` 没有导入或注册该模块；当前模板导入由独立 JSON API
    处理。
- **严重级别**：中。
- **置信度**：高。该模块不是 Django `apps.py`、`admin.py`、management command、signal
  或 Celery task，不存在已知框架反射入口。
- **不使用证明**：类、公开函数、模块路径均无仓库内外部命中，文件内其余函数只服务于
  `handle_permission_template_post`。
- **删除风险**：低到中。仓库内删除风险低，但需要确认没有运维脚本直接导入内部模块。
- **建议动作**：整文件删除，同时用现有权限模板 JSON API 测试证明 preview/apply 路径完整；
  不保留转发层或兼容入口。

### D-02 门户旧的“全量后内存分页”辅助函数已被 QuerySet 分页取代

- **证据**：
  - `src/easyauth/portal/pagination.py:70` 的 `paginate_items` 全仓只有定义，没有调用。
  - `src/easyauth/portal/api_data.py:53` 的 `expiring_grant_items_for_user` 全仓只有定义和
    `src/easyauth/portal/api_data.py:40` 的 `__all__` 字符串。
  - 当前路径在 `src/easyauth/portal/api_data.py:63`、`:69` 使用
    `current_grant_page_for_user`、`expiring_grant_page_for_user`。
  - `src/easyauth/portal/api_data.py:82-86` 先对 QuerySet 做数据库切片，再构造页面；注释
    `:64` 明确说明这样才能约束单次工作量。
- **严重级别**：低。
- **置信度**：高。
- **不使用证明**：两个符号的全仓精确搜索均无调用；API 只导入 `*_page_for_user`。
- **删除风险**：低。
- **建议动作**：删除 `paginate_items`、`expiring_grant_items_for_user` 及对应 `__all__`
  项；不要保留内存分页兼容路径。

### D-03 `api_data` 中存在没有消费者的兼容再导出

- **证据**：
  - `src/easyauth/portal/api_data.py:16-20` 从 `access_request_data` 导入三个符号。
  - `src/easyauth/portal/api_data.py:36` 再导出 `access_request_items_for_user`。
  - 生产 API 在 `src/easyauth/portal/api.py:34-39` 只通过该模块导入
    `access_request_item`、`access_request_page_for_user` 和两个授权分页函数。
  - 唯一实际调用位于
    `tests/integration/portal/test_access_request_s14.py:39,233`，且直接从
    `easyauth.portal.access_request_data` 导入。
- **严重级别**：低。
- **置信度**：高。
- **不使用证明**：`api_data` 的再导出路径没有导入方；实际测试绕过该再导出。
- **删除风险**：低。
- **建议动作**：从 `api_data` 删除该导入和 `__all__` 项，保留权威定义
  `access_request_data.access_request_items_for_user`。

### D-04 后端有 7 个孤立常量或类型别名

| 证据 | 状态与不使用证明 |
| --- | --- |
| `src/easyauth/accounts/oidc_exchange.py:42` `REASON_ID_TOKEN_REQUIRED` | 全仓只命中定义；实际 `id_token` 缺失由 `_required_json_string` 的通用错误路径处理。 |
| `src/easyauth/admin_console/auto_onboarding_api.py:46` `BASE_URL_INVALID_MESSAGE` | 全仓只命中定义；`:65-73` 已直接使用 `require_secure_url` 的异常消息。 |
| `src/easyauth/admin_console/operations_api.py:52` `ConsoleApiResult` | 全仓只命中定义。 |
| `src/easyauth/lifecycle/services.py:64` `TASK_ALREADY_OPEN_MESSAGE` | 全仓只命中定义；同一区域其他冲突消息仍有调用。 |
| `src/easyauth/workflows/services.py:65` `FORM_MAPPING_INVALID_MESSAGE` | 全仓只命中定义。 |
| `src/easyauth/notify/models.py:89` `CREDENTIAL_TYPE_OAUTH_CLIENT` | 全仓只命中定义；生产请求直接保存认证主体的 `credential_type`。 |
| `sdk/python/src/easyauth_app_sdk/manifest.py:38` `ALLOWED_PLATFORM_CAPABILITIES` | 全仓只命中定义；`:86-100` 为前向兼容而只校验非空字符串和去重，没有使用白名单。 |

- **严重级别**：低。
- **置信度**：高。
- **不使用证明**：逐个做了带单词边界的全仓精确搜索，均只有上述定义。
- **删除风险**：低。
- **建议动作**：直接删除；不要为了“也许以后会用”保留未接线常量。若产品要恢复白名单校验，
  应新增明确契约与测试，而不是让孤立常量暗示不存在的行为。

### D-05 4 个后端函数没有调用方，其中一个可能暴露缺失接线

| 证据 | 不使用证明 | 删除风险 | 建议 |
| --- | --- | --- | --- |
| `src/easyauth/admin_console/configuration.py:54` `create_permission` | 全仓唯一函数调用形式是定义本身；当前权限写入走 `permission_write_helpers.py` 和 API handler。 | 低 | 删除旧 mutation 入口，不增加转发层。 |
| `src/easyauth/connectors/services.py:145` `reset_worker_dispatch` | 全仓只命中定义；docstring 声称 broker 投递失败时复位 claim，但任务和 dispatch 层均未调用。 | 中 | 先审计 broker 发送失败路径。若确实缺失恢复动作，应把逻辑接到唯一失败边界并补测试；若当前状态机已不需要，则删除。 |
| `src/easyauth/portal/api_data.py:53` `expiring_grant_items_for_user` | 见 D-02。 | 低 | 与旧分页路径一起删除。 |
| `src/easyauth/portal/pagination.py:70` `paginate_items` | 见 D-02。 | 低 | 与旧分页路径一起删除。 |

- **严重级别**：`reset_worker_dispatch` 为中，其余为低。
- **置信度**：高。以上均不是 decorator 注册函数或协议方法。
- **建议动作**：删除前三类明确替代路径；`reset_worker_dispatch` 必须先判断是死代码还是遗漏的
  故障恢复接线，不能机械删除。

### D-06 一个测试辅助函数从未被同文件测试调用

- **证据**：
  - `tests/integration/admin_console/test_permission_catalog_write_api_ops1.py:557`
    定义 `_logged_in_superuser`。
  - 同文件实际测试只使用 `:550` 的 `_logged_in_user`；BasedPyright 报告
    `:557` 为 `reportUnusedFunction`。
  - 全仓有许多同名文件局部 helper，但 Python 模块作用域彼此独立，其他文件的同名调用不能调用
    此定义。
- **严重级别**：低。
- **置信度**：高。
- **不使用证明**：以文件为作用域检查没有调用；函数不是 pytest fixture。
- **删除风险**：低。
- **建议动作**：删除该函数。

### D-07 前端两个历史领域类型无任何消费者

- **证据**：
  - `frontend/src/lib/domain.ts:81-89` 定义并标注“历史兼容”的 `RoleItem`。
  - `frontend/src/lib/domain.ts:385-394` 定义并标注“历史兼容”的
    `PortalCatalogRole`。
  - 全仓精确搜索两个类型名都只命中各自定义。
  - 当前权威类型紧邻其后，分别为 `AuthorizationGroupItem` 和
    `PortalCatalogAuthorizationGroup`。
- **严重级别**：低。
- **置信度**：高。
- **不使用证明**：TypeScript 源码、测试、后端、SDK 和文档均无消费。
- **删除风险**：低；前端包在 `frontend/package.json:4` 标记为私有包。
- **建议动作**：直接删除两个类型，不保留别名。

### D-08 配置就绪状态仍接受后端不再产生的 `blocked`

- **证据**：
  - `frontend/src/lib/status.ts:48-50` 明确注释 `blocked` 是历史兼容，并在
    `readinessLabel` 中与 `blocking` 合并。
  - `frontend/src/lib/status.ts:63-64` 在 `readinessTone` 中重复该兼容。
  - 后端权威类型
    `src/easyauth/applications/configuration.py:23-29` 只允许
    `blocking`、`warning`、`ready`。
  - 后端列表和详情响应在
    `src/easyauth/admin_console/apps_api.py:192,421,511` 直接输出
    `readiness.status`。
  - 集成测试
    `tests/integration/admin_console/test_apps_contract_compat.py:63,309`
    断言值为 `blocking`；没有测试向就绪状态 helper 输入 `blocked`。
- **严重级别**：低。
- **置信度**：高。
- **不使用证明**：当前生产者、类型和契约测试均不产生 `blocked`。其他领域仍有
  `health_status: "blocked"`，但它们不经过这两个 readiness helper，不能作为保留理由。
- **删除风险**：低。
- **建议动作**：删除两个 `case "blocked"`；同时把
  `ConfigurationStatus.status` 从任意 `string` 收紧为当前字面量联合类型，让未来漂移在编译期失败。

### D-09 前端有 17 个未被其他模块消费的导出

Knip 报告下列导出没有外部消费者；全仓逐个搜索确认这些符号要么只在定义文件内使用，要么只是
重复再导出。因此死的是“导出面”，不是这些函数的实现。

| 证据 | 文件内状态 |
| --- | --- |
| `frontend/src/components/ui/PaginationBar.tsx:7` `TABLE_PAGE_SIZE_OPTIONS` | 仍在本文件 `:50` 使用。 |
| `frontend/src/components/ui/TablePagination.tsx:5` `TABLE_PAGE_SIZE_OPTIONS` | 对上项的重复再导出，无消费者。 |
| `frontend/src/i18n/messages.ts:9` `zhCN` | 仍在同文件构造 `MESSAGES`。 |
| `frontend/src/i18n/messages.ts:1182` `en` | 仍在同文件构造 `MESSAGES`。 |
| `frontend/src/lib/webauthn.ts:14` `base64urlToBytes` | 仍在同文件 `:52,55,58` 使用。 |
| `frontend/src/lib/webauthn.ts:27` `bytesToBase64url` | 仍在同文件 `:70,73,74` 使用。 |
| `frontend/src/pages/console/lifecycle/lifecycleLabels.ts:101` `actionReleasesToPool` | 仍在同文件 `:113,128` 使用。 |
| `frontend/src/pages/console/workspace/utils.ts:10` `isPermissionGroup` | 仍在同文件 `:6` 使用。 |
| `frontend/src/pages/portal/hooks/useAccessRequestForm.ts:548` `directGrantSelectionScopeKey` | 仅本文件使用。 |
| `frontend/src/pages/portal/hooks/useAccessRequestForm.ts:584` `permissionSelectionKeys` | 仅本文件使用。 |
| `frontend/src/pages/portal/hooks/useAccessRequestForm.ts:588` `permissionScopeSelectionKey` | 仅本文件使用。 |
| `frontend/src/pages/portal/hooks/useAccessRequestForm.ts:594` `permissionScopeKeys` | 仅本文件使用。 |
| `frontend/src/pages/portal/hooks/useAccessRequestForm.ts:599` `selectedScopeKeysForPermission` | 仅本文件使用。 |
| `frontend/src/pages/portal/hooks/useAccessRequestForm.ts:606` `nextPermissionScopeSelection` | 仅本文件使用。 |
| `frontend/src/pages/portal/permissionTree.ts:15` `collectPermissions` | 仅本文件使用。 |
| `frontend/src/pages/portal/permissionTree.ts:56` `filterGroupByApp` | 仅本文件使用。 |
| `frontend/src/pages/portal/permissionTree.ts:69` `filterPermissionByApp` | 仅本文件使用。 |

- **严重级别**：低。
- **置信度**：高。
- **不使用证明**：Knip 与全仓调用方搜索一致；没有其他模块 import 这些导出。
- **删除风险**：低。不能删除仍在文件内使用的实现。
- **建议动作**：移除不必要的 `export`；删除
  `TablePagination.tsx:5` 未消费的 `TABLE_PAGE_SIZE_OPTIONS` 再导出。建议在前端质量门槛中固定
  Knip，防止私有 helper 再次扩大为伪公共 API。

### D-10 工作区积累大量已忽略开发产物，但没有提交

- **文件证据**：
  - 1158 个 `.pyc`，分布在 78 个 `__pycache__`；示例：
    `__pycache__/manage.cpython-312.pyc`、
    `tests/unit/api/__pycache__/test_directory_views.cpython-312-pytest-8.4.2.pyc`。
  - `.pytest_cache/` 约 220 KiB；`.ruff_cache/` 约 840 KiB。
  - `dist/easyauth-0.1.0-py3-none-any.whl` 与
    `dist/easyauth-0.1.0.tar.gz` 合计约 1.9 MiB。
  - `frontend/test-results/.last-run.json` 所在目录约 112 KiB。
  - `frontend/tsconfig.tsbuildinfo` 约 132 KiB。
  - `src/easyauth/static/easyauth/frontend/assets/main-CNN3Qfdd.js` 所在前端构建目录约
    1.0 MiB。
  - `.DS_Store`、`docs/.DS_Store`、`docs/design/.DS_Store` 均存在。
  - `db.sqlite3` 约 29 MiB；`.env.local` 存在。本审计未读取二者。
  - `.gitignore:1-17` 覆盖上述类型，`dist/.gitignore:1` 覆盖发布包；
    `git status --ignored` 均显示为 `!!`。
  - `git ls-files` 对上述类别无任何命中。
- **严重级别**：低；`.env.local` 和 `db.sqlite3` 的误删风险另计。
- **置信度**：高。
- **不使用证明**：这些是编译缓存、测试结果、发布包、本地数据或可重建前端产物，不是已提交源码；
  前端权威构建由 `frontend/vite.config.ts:16-22` 生成。
- **删除风险**：
  - 缓存、`dist/`、`test-results/`、`tsbuildinfo`、前端散列产物、`.DS_Store`：低。
  - `db.sqlite3`：高，可能含未迁移的本地事实。
  - `.env.local`：高，可能含无法恢复的本地密钥。
- **建议动作**：提供显式 `clean` 命令，只清理可重建类别；默认绝不删除
  `.env.local` 和 `db.sqlite3`。若要清理数据库，先单独备份并由开发者确认。

## 4. 需要运行态、外部契约或产品决策确认的候选

### R-01 SDK 公开导出仅为 legacy 的 `DINGTALK_REF_PREFIX`

- **证据**：
  - `sdk/python/src/easyauth_app_sdk/client.py:35-36` 把它标为
    `Legacy-only/deprecated`。
  - `sdk/python/src/easyauth_app_sdk/__init__.py:15,59` 将其公开导出。
  - 仓库内真实代码没有用该常量解析或构造引用；仅
    `sdk/python/tests/test_client_directory_notify.py:14,88` 断言它等于 `"dt:"`。
  - `docs/design/platform-directory-notify/06-SDK接口设计.md:98` 明确写明旧常量仅保留兼容。
  - `sdk/python/CHANGELOG.md:37` 表明它曾进入发布面。
- **严重级别**：中。
- **置信度**：中。仓库内用途已确认只剩导出和测试，但已发布 SDK 的外部消费者不可由仓库静态搜索证明。
- **不使用证明**：仓库内除定义、再导出、变更记录和常量值测试外无命中。
- **删除风险**：中到高，可能破坏外部应用导入。
- **建议动作**：先核对 SDK 发布记录、下游依赖锁和代码搜索；若项目确实尚未被外部使用，按项目
  “不保留历史错误形态”的约束直接删除导出、常量、测试和文档兼容说明。若已有外部契约，则必须
  把它写入 legacy 白名单，并明确移除版本和遥测条件。

### R-02 legacy 目录引用兼容仍是活跃契约，缺少移除条件

- **证据**：
  - `sdk/python/src/easyauth_app_sdk/client.py:205,265` 声明裸 `user_id` 和旧
    `dt:<id>` 是 deprecated 兼容输入。
  - `src/easyauth/notify/services.py:773-787` 仍在运行时识别并解析该输入。
  - `src/easyauth/notify/models.py:279-285` 为缺少目录 scope 的 legacy 行保留单独唯一约束。
  - `docs/api/easyauth-public-api.md:318,547`、`sdk/python/README.md:156`
    仍把兼容行为写入公共契约。
  - 多个通知和目录测试仍直接构造 `dt:<id>`，例如
    `tests/unit/notify/test_recipient_resolve.py:69`、
    `tests/unit/api/test_directory_views.py:219`。
- **严重级别**：中。
- **置信度**：高，确认它仍活跃；是否有真实下游依赖为低到中。
- **不使用证明**：不能证明无运行态调用；恰恰存在大量测试和公共文档，因此本项不能归入死代码。
- **删除风险**：高。
- **建议动作**：查询真实请求日志中 legacy ref 占比，并登记外部系统契约。若项目确实尚未上线且无
  下游，应该一次性移除解析分支、legacy 数据约束、样例、SDK 说明和测试；若存在迁移窗口，则写明
  最后接受日期、拒绝后的错误码和数据库清理条件。

### R-03 管理控制台测试通过 autouse fixture 桥接旧 Django 登录

- **证据**：
  - `tests/integration/admin_console/conftest.py:15-40` 的
    `bridge_legacy_client_login_to_authentik_session` 自动 monkeypatch
    `django.test.Client.login`，把 Django 用户登录隐式桥接成 Authentik session。
  - `tests/integration/admin_console/` 有 26 个文件、33 处 `client.login(...)`，依赖该隐藏桥接。
  - fixture 名本身标记 `legacy`，且项目登录事实已转向 Authentik session。
- **严重级别**：高。它不是死代码，但会让大量测试验证的登录路径与真实生产路径不同。
- **置信度**：高，确认测试依赖；是否所有测试都应改走同一个 Authentik helper 需测试设计确认。
- **不使用证明**：不适用；这是活跃兼容层。
- **删除风险**：高，直接删除会使大量测试失效。
- **建议动作**：先提供显式、权威的 Authentik session 测试 helper，逐文件迁移 33 处调用，再删除
  autouse monkeypatch。不要用新的兼容 fixture 包裹旧 fixture。

### R-04 已提交的 CRM 试点种子属于产品入口还是开发样例尚不明确

- **证据**：
  - `src/easyauth/applications/management/commands/seed_crm_pilot.py:33-38`
    硬编码 `crm`、试点用户、owner、developer 和 fixture 路径。
  - `:48-59` 暴露可执行 Django management command，并输出一次性静态 token。
  - `src/easyauth/applications/management/commands/fixtures/crm_pilot_manifest.json:1-7`
    是明确的 CRM 试点样例。
  - 仓库内调用只来自
    `tests/integration/admin/test_seed_crm_pilot.py:36-124`；Docker、Compose、CI、
    README 和接入指南均不调用该命令。
- **严重级别**：低到中。
- **置信度**：中。它是可执行且有测试的功能，不是静态死代码；是否仍有产品试点用途无法从仓库证明。
- **不使用证明**：没有部署、CI 或文档调用，只存在命令自身和专用测试。
- **删除风险**：中，可能仍是人工试点初始化入口。
- **建议动作**：由产品负责人确认 CRM 试点是否仍存在。若不存在，一次性删除命令、fixture 和专用
  测试；若存在，补充中文运行文档、适用环境和清理方式，并禁止在生产部署自动执行。

### R-05 开发环境 `console.warn` 会记录不符合契约的原始 payload

- **证据**：
  - `frontend/src/lib/api.ts:105-116` 在 `payload.data` 非数组时返回共享空数组。
  - `frontend/src/lib/api.ts:111-113` 在开发环境执行
    `console.warn(..., items)`，直接输出原始值。
  - 该 helper 被大量控制台列表调用，例如
    `frontend/src/pages/console/OperationsPage.tsx:195` 和
    `frontend/src/pages/console/lifecycle/ConsolePeopleList.tsx:94`。
- **严重级别**：中。
- **置信度**：高，确认日志语句存在；原始值是否含敏感人员或运维数据取决于触发时的响应。
- **不使用证明**：不适用；该语句有可达调用方。
- **删除风险**：低。
- **建议动作**：不要记录原始 payload。契约违规应抛出结构化错误并让页面进入失败态，或只记录固定
  错误码和字段类型；同时删除当前静默空数组兜底，避免错误响应看起来像“空列表成功”。

## 5. 已排除的误报与确认无问题项

以下项目经复核不应作为死代码删除：

- Vulture 报告的 Django `apps.py` 配置类、model `Meta`、model 字段和 management command
  `Command` 由 Django 反射使用。
- `src/easyauth/config/celery.py:31-36` 的 `_record_critical_task_success` 由
  `@task_success.connect` 注册。
- `tests/conftest.py:7-13`、
  `tests/unit/config/test_crypto.py:10-15`、
  `tests/unit/webhooks/test_transport.py:69-83` 等由 `@pytest.fixture` 注册。
- Protocol 的 `__exit__` 参数虽然被 Vulture 标为未使用，但属于上下文管理器签名，不是死变量。
- `psycopg[binary]` 是生产 PostgreSQL 驱动；`gunicorn` 由 `Dockerfile:68` 启动；
  两者无需在 Python 源码中直接 import。
- 前端 `@types/node`、`@types/react`、`@types/react-dom` 是 TypeScript 类型包，不以业务 import
  次数判断是否使用。
- `deploy/webhook-worker-entrypoint.sh` 在 `Dockerfile:51,58` 复制并授权，并由
  `docker-compose.deploy.yml:106,135` 作为两个 worker 的入口。
- 9 张 `docs/assets/screenshots/*.png` 均各有中文文档引用；品牌资源
  `frontend/public/assets/brand/jiefa_logo.webp` 有多个前端引用。
- `frontend/src/lib/api.ts:113` 是唯一 `console.*` 调试类输出，已列为 R-05；未发现
  `console.log`、`console.debug`、`debugger`、`breakpoint()`、`pdb` 或 `ipdb`。

## 6. 建议处理顺序

1. 先处理 D-01、D-02、D-03、D-04、D-06、D-07、D-08：删除风险低，能直接缩小错误表面。
2. 对 D-05 的 `reset_worker_dispatch` 做一次 broker 失败路径审计，再决定接线或删除。
3. 收窄 D-09 的前端导出面，并把 Knip 加入持续集成。
4. 改造 R-03 的认证测试基础设施和 R-05 的契约失败行为；这两项比单纯删除代码更影响事实可信度。
5. 通过外部依赖清单和运行日志决定 R-01、R-02、R-04，不能只凭仓库静态搜索删除公开 SDK 或
   可执行管理命令。
6. 增加安全的工作区清理命令；默认保留 `.env.local` 和 `db.sqlite3`。

本报告只记录审计结果，没有执行删除、业务代码修改、依赖变更或提交。
