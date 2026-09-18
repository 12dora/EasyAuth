# EasyAuth 管理控制台私有 API 目录

## 范围

管理控制台同源私有 API，统一前缀：`/console/api/v1/`。

**本目录不是下游应用接入契约。** 下游请使用 [`easyauth-public-api.md`](./easyauth-public-api.md)。

## 鉴权与权限

| 机制 | 说明 |
| --- | --- |
| Session | Django session 登录（OIDC 或本地管理员） |
| CSRF | 浏览器写操作需 CSRF（Django 中间件）；测试客户端登录会话同样受保护 |
| ConsoleActor | `require_console_actor`：有效控制台操作者 |
| Superuser | 部分运营/全局接口要求超级用户（`require_superuser`） |
| App 成员 | 多数应用资源：可见性看 membership / superuser |
| App owner | 敏感配置（凭据、webhook、membership 管理等）：`can_manage_app` |

**禁止：** 使用静态 app token / OAuth access token 充当控制台身份。

统一错误：`{ "error": { "code", "message", "details" } }`。  
列表通用：`{ "data": [...], "pagination": { page, page_size, total_items, total_pages } }`。
分页、状态和枚举筛选只有省略或空值时使用默认语义；出现非法值必须返回
`422 VALIDATION_ERROR`，不得静默忽略、截断或返回不可信空列表。

人员对象（PersonRef）`{ user_id, name, department, account_kind, avatar_url }` 一律由
`accounts/person_payload.py` 生成。`account_kind`：

- `directory`：有钉钉绑定的目录用户。
- `local`：已有 UserMirror 但无钉钉绑定（本地管理员、Authentik 内建用户）。
- `unresolved`：只存用户 ID、尚无 UserMirror；不得推断为 `local`。

`avatar_url` 为 `UserMirror.avatar_url`；无照片时为空字符串。有钉钉照片时为 https 地址；
Authentik 生成的首字母图为 `data:image/svg+xml;base64,...` 内联图。写入时真实照片始终优先，
生成图不得覆盖已有照片。照片不会被生成图替换；上游删除照片后旧照片 URL 会保留，只有离职清理会清空（前端 `onError` 回落首字母）。前端 `safeAvatarUrl`
只接受 https、同源路径和白名单内联图。行字段形态为 `{prefix}avatar_url`（如 `user_avatar_url`）。

---

## 应用与配置

| 方法 | 路径 | 权限要点 |
| --- | --- | --- |
| GET/POST | `/apps` | 列表/创建应用 |
| GET/PATCH | `/apps/{app_key}` | 应用详情 |
| POST | `/apps/auto-onboarding` | 自动接入 |
| GET | `/apps/{app_key}/configuration-status` | 配置完整度 |
| GET | `/apps/{app_key}/integration-guide` | 接入指南 |
| GET | `/apps/{app_key}/manifest` | 导出 manifest |
| GET | `/apps/{app_key}/capabilities` | active owner/developer/超管可读；返回各能力 `enabled`、`config` 和顶层 `can_manage` |
| GET | `/apps/{app_key}/capabilities/{capability}` | active owner/developer/超管可读；返回单能力配置和 `can_manage` |
| PUT | `/apps/{app_key}/capabilities/{capability}` | **仅超管**：开通/关闭 `directory` 或 `notify` 并维护 `config` |
| GET/PUT | `/apps/{app_key}/notification-channel` | 可见成员读；**owner** 从权威目录作用域中选择并维护每 App 版本化钉钉通知通道 |
| POST | `/apps/{app_key}/notification-channel/test` | **owner**：测试当前 active 通道连通性 |
| GET/PUT | `/apps/{app_key}/managed-scope-policy` | MANAGED_USERS 策略 |
| GET | `/apps/{app_key}/managed-users-preview` | 管理范围预览 |
| POST | `/apps/{app_key}/permission-query-tests` | 权限查询联调 |

应用列表和详情项返回 `notify_head_bgcolor`：工作通知 OA 头色带，8 位大写 ARGB
（如 `FF1A7F4C`）。空串表示未指定，发送时按应用 id 哈希在六色调色板中取稳定色带。
写入时也接受 `#RRGGBB` / `RRGGBB`，服务端归一成 ARGB。EasyAuth 自身通知固定
`FF1F6FEB`，不受该字段影响。

应用列表和详情项的 `owners` 为人员对象数组（PersonRef：`user_id`、`name`、`department`、
`account_kind`、`avatar_url`），
按姓名再按 `user_id` 排序；整页 owner 成员关系、UserMirror 与部门路径一次性批量解析，不按 App
回源。尚无 UserMirror 的 owner 为 `account_kind: "unresolved"`。`developers` 仍为 Authentik 用户
ID 字符串数组。筛选参数 `owner_user_id` 不变，仍按成员关系的用户 ID 过滤。

应用列表和详情项返回同一份细粒度能力事实：

```json
{
  "can_manage": true,
  "capabilities": {
    "can_view": true,
    "can_edit_basic_info": true,
    "can_toggle_active": true,
    "can_delete": true,
    "can_manage_memberships": true,
    "can_manage_catalog": true,
    "can_manage_credentials": true,
    "can_manage_connectors": true,
    "can_manage_platform_capabilities": true
  }
}
```

前端导航、路由和按钮只能消费这些布尔能力；不得用本地 role 文案、页面位置或历史
`can_manage` 粗粒度字段自行推断。`can_manage` 仅作为 `can_edit_basic_info` 的旧字段别名保留在
同一响应内，新增前端代码必须读取 `capabilities`。

### 配置完整度

`GET /apps/{app_key}/configuration-status` 返回该 App 的配置完整性：`status` 为
`blocking` / `warning` / `ready`，`data` 为风险项列表（`code`、`severity`、`message`、
`subject`、`target_type`）。应用列表的 `configuration_status` 使用同一套判定，只汇总状态、
不展开风险项。

凭据类 blocking 项只约束**入站拉取**场景：下游通过 SDK/公共 API 查询授权时，需要 active
静态 token 或 OAuth2 client。EasyAuth 经启用中的 `ConnectorInstance` **出站推送**供给的应用
（如 NetBird）不把入站凭据列为就绪条件；仅存在停用连接器实例时仍视为未接入连接器。

| `code` | 严重程度 | 含义 |
| --- | --- | --- |
| `app_inactive` | blocking | App 已禁用。 |
| `active_permission_missing` | blocking | active App 至少需要一个 active Permission。 |
| `active_authorization_group_missing` | blocking | active App 至少需要一个 active AuthorizationGroup。 |
| `active_owner_missing` | blocking | active App 至少需要一个 active owner。 |
| `active_credential_missing` | blocking | 未接入连接器的 active App 至少需要一个 active 静态 token 或 OAuth2 client。 |
| `requestable_authorization_group_approval_rule_missing` | blocking | requestable AuthorizationGroup 必须存在 active ApprovalRule。 |
| `authorization_group_grant_target_inactive` | blocking | AuthorizationGroupGrant 不能指向 inactive 授权组或 Permission。 |
| `authorization_group_grant_scope_inactive` | blocking | active AuthorizationGroupGrant 必须引用 active AppScope。 |
| `managed_scope_app_default_policy_missing` | blocking | MANAGED_USERS grant 缺少 app default managed scope policy。 |
| `managed_scope_policy_disabled` | blocking | MANAGED_USERS grant 的 managed scope policy 已禁用。 |
| `permission_supported_scopes_missing` | warning | active Permission 必须声明 supported_scopes。 |
| `permission_group_inactive` | warning | active Permission 不应归属 inactive PermissionGroup。 |

---

## 成员与凭据

| 方法 | 路径 | 权限要点 |
| --- | --- | --- |
| GET/POST | `/apps/{app_key}/memberships` | 成员管理 |
| PATCH/DELETE | `/apps/{app_key}/memberships/{membership_id}` | 成员变更 |
| GET | `/apps/{app_key}/credentials` | 凭据列表（无 secret） |
| POST | `/apps/{app_key}/credentials/static-tokens` | 创建静态 token（明文一次性），可同时授予 credential capabilities |
| POST | `…/static-tokens/{id}/rotate` | 轮换 |
| POST | `…/static-tokens/{id}/disable` 或 `…/credentials/{type}/{id}/disable` | 停用 |
| POST | `/apps/{app_key}/credentials/oauth-clients` | 创建 OAuth client，可同时授予 credential capabilities |
| PUT | `/apps/{app_key}/credentials/{credential_type}/{credential_id}/capabilities` | **owner**：替换单凭据的 `directory` / `notify` 授权集 |

### 应用成员

**GET `/apps/{app_key}/memberships`** 对可见该应用的成员可读。成功体 `{ "data": [...] }`。
列表项：

| 字段 | 说明 |
| --- | --- |
| `id` | 成员关系 ID |
| `user_id` | Authentik 用户 ID |
| `user_name` | 对应用户 `UserMirror.name`；无镜像或镜像无姓名时为空字符串 |
| `user_department` | 对应用户部门路径（与 `GET /user-options` 的 `department` 同口径）；无镜像时为空字符串 |
| `user_account_kind` | `directory` / `local` / `unresolved`，口径见上文人员对象 `account_kind` |
| `user_avatar_url` | 口径见上文人员对象 `avatar_url` |
| `role` | `owner` / `developer` |
| `is_active` | 是否有效 |

`user_name` / `user_department` / `user_account_kind` / `user_avatar_url` 按当前列表一次性批量查询 `UserMirror`，不按行回源。创建与 PATCH 成功体中的
`membership` 使用同一项形状。人员展示字段一律来自 `person_payload` / `person_row_fields`。

App capability 与 credential capability 必须同时开启；manifest 声明只供展示，
不会自动开通 App 能力或授权凭据。
`/capabilities` GET 响应不返回 manifest 声明；列表根对象是
`{"capabilities": [...], "can_manage": bool}`，条目包含 `capability`、`enabled`、`config`
和更新审计字段。`can_manage` 仅对超管为 `true`。

写操作成功后前端必须失效以下派生查询：

| 写操作 | 必须失效 |
| --- | --- |
| 应用基本信息、启停、删除 | 应用列表、应用详情、配置完整度、能力查询 |
| 成员创建/停用 | 成员列表、应用列表、应用详情、配置完整度、能力查询 |
| 权限、scope、权限分组、授权组、MANAGED_USERS 策略 | 对应目录列表、权限树、应用列表、应用详情、配置完整度、能力查询、门户申请目录 |
| 凭据创建、轮换、停用、credential capability 修改 | 凭据列表、应用列表、应用详情、配置完整度、能力查询 |
| App capability、通知通道、连接器配置或映射 | 对应局部查询、应用列表、应用详情、配置完整度、能力查询 |

---

## 权限目录

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/apps/{app_key}/permission-tree` | 目录树 |
| GET/POST | `/apps/{app_key}/permissions` | 权限 |
| GET/PATCH/DELETE | `/apps/{app_key}/permissions/{permission_key}` | 权限详情 |
| GET/POST | `/apps/{app_key}/permission-groups` | 权限分组 |
| GET/PATCH/DELETE | `/apps/{app_key}/permission-groups/{group_key}` | 分组详情 |
| GET/POST | `/apps/{app_key}/scopes` | Scope |
| GET/PATCH/DELETE | `/apps/{app_key}/scopes/{scope_key}` | Scope 详情 |
| GET/POST | `/apps/{app_key}/authorization-groups` | 授权组（替代历史 roles） |
| GET/PATCH/DELETE | `/apps/{app_key}/authorization-groups/{key}` | 授权组详情 |
| POST | `/apps/{app_key}/permission-template-imports/preview` | 模板预览 |
| POST | `…/permission-template-imports/{preview_id}/confirm` | 确认导入 |
| GET | `/apps/{app_key}/permission-template-versions` | 模板版本 |
| GET/POST | `/apps/{app_key}/approval-rules` | 审批规则 |
| GET/PATCH/DELETE | `/apps/{app_key}/approval-rules/{id}` | 规则详情 |

---

## 连接器与 Webhook

| 方法 | 路径 | 权限要点 |
| --- | --- | --- |
| GET/POST | `/apps/{app_key}/connectors` | 连接器 |
| GET/PATCH/DELETE | `/apps/{app_key}/connectors/{instance_id}` | 实例 |
| POST | `…/connectors/test`、`…/external-groups`、`…/mappings`、`…/reconcile`、`…/sync-runs` | 探测与同步 |
| GET/PUT | `/apps/{app_key}/webhook-config` | **owner**：配置 URL/开关/轮换 secret |
| POST | `/apps/{app_key}/webhook-config/test` | **owner**：发送测试事件 |
| GET | `/apps/{app_key}/webhook-deliveries` | **owner**：投递列表 |
| POST | `/apps/{app_key}/webhook-deliveries/{delivery_pk}/redeliver` | **owner**：失败重投 |

**GET/PUT `/apps/{app_key}/webhook-config`** 字段：

| 字段 | 说明 |
| --- | --- |
| `enabled` | 是否启用推送 |
| `approval_callback_url` | 审批完成回调 |
| `handover_url` | 生命周期交接 |
| `onboard_url` | 入职事件 |
| `events_url` | 权限传播事件（`grant.changed` / `catalog.changed`） |
| `rotate_secret` | PUT 时为 true 则轮换密钥 |
| `secret_configured` | GET 是否已配置密钥（明文只在轮换响应出现一次） |

`events_url` 纳入 `allowed_hosts` 推导，与其它 URL 一样必须是公网 HTTPS。manifest 顶层 `webhook.events_url`（绝对地址或相对 `base_url` 的站内路径）会在导入时回填，控制台改过的值优先。

**POST `/apps/{app_key}/webhook-config/test`** 的 `target` 可为 `approval_callback_url`、`handover_url`、`onboard_url` 或 `events_url`。

### 权限传播事件

授权事实变更经 `notify_grant_mutation` 投递 `grant.changed`；权限目录版本提升经 `bump_catalog_version` 投递 `catalog.changed`。目标为 `events_url`。未配置 `events_url` 或 secret 时跳过，不回滚授权。

`grant.changed` 载荷：`event_type`、`app_key`、`user_id`、`grant_version`、`catalog_version`、`snapshot_version`、`changed_at`。

`catalog.changed` 载荷：`event_type`、`app_key`、`catalog_version`、`changed_at`。

签名头与既有 webhook 相同：`X-EasyAuth-Event`、`X-EasyAuth-Delivery`、`X-EasyAuth-Timestamp`、`X-EasyAuth-Signature`。

### Webhook 投递

**GET `/apps/{app_key}/webhook-deliveries`**

查询参数：

| 参数 | 说明 |
| --- | --- |
| `status` | `pending` / `delivered` / `failed` |
| `event_type` | 如 `approval.completed`、`grant.changed`、`catalog.changed`、`webhook.test` |
| `include_payload` | `true` 时附带 `payload`（仅 manage_app） |
| `page` / `page_size` | 分页 |

默认摘要字段（**不含**完整 payload）：

`id`, `delivery_id`, `event_type`, `target_url`, `status`, `attempts`, `generation`, `last_error`（截断）, `created_at`, `updated_at`。

**POST `/apps/{app_key}/webhook-deliveries/{delivery_pk}/redeliver`**

- 仅 `failed` → `pending` 原子迁移
- 成功 200；已非 failed → 409
- 审计：`webhook_delivery_redelivered`

---

## 运营与审批实例

多数运营接口要求 **superuser**。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/operations/access-requests` | 申请运营列表 |
| POST | `/operations/access-requests/{id}/approve` | 代审通过 |
| POST | `/operations/access-requests/{id}/reject` | 代审驳回 |
| POST | `/operations/access-requests/{id}/reassign` | 改派审批人 |
| POST | `/operations/access-requests/{id}/retry-grant` | 重试授权落库 |
| GET | `/operations/access-grants` | 授权运营列表 |
| POST | `/operations/emergency-revokes` | 紧急撤权 |
| GET | `/operations/dependency-health` | 依赖健康 |
| POST | `/operations/dependency-health/checks` | 触发检查 |
| GET | `/operations/approval-instances` | 钉钉审批实例运营列表 |
| POST | `/operations/approval-instances/{instance_id}/redeliver` | 审批结果 webhook 重投 |

### 申请运营列表

**GET `/operations/access-requests`** 列表项在既有字段外提供展示名。`user_name` 为
申请人 `UserMirror.name`（镜像无姓名时为空字符串）；`user_department` 为申请人部门路径
（与 `GET /user-options` 的 `department` 同口径）；`user_account_kind` 为 `directory`、
`local` 或 `unresolved`。`app_name` / `app_alias` 为应用名称与别名。`approvers` 为
`[{ "user_id", "name", "department", "account_kind", "avatar_url" }]`，与既有 `approver_user_ids` 并列。
`decided_by_name` 为决定人姓名；无决定人或镜像中无该用户时为空字符串。

### 授权运营列表

**GET `/operations/access-grants`** 列表项使用与直接授权、当前授权相同的授权行形状
（见下方「授权行」）。查询参数 `current_only` 默认为 `true`，只返回 `is_current=true`
的行；`current_only=false` 才包含历史版本。取值必须是 `true` 或 `false`，否则 422。
既有 `app_key`、`status`、`user_id`、`version`、`current`、`revoked` 等筛选仍然生效。

`user_query` 按授权对象 `UserMirror` 做大小写不敏感模糊匹配，规则与
`GET /user-options` 的 `q` 相同（姓名、邮箱、Authentik 用户 ID、工号；纯字母数字可含空格时
另按姓名全拼/首字母匹配）。省略或空白视为未筛选。`user_id` 仍为精确匹配，可与 `user_query`
同时使用。

省略 `ordering` 时默认按 `user__name`、`app__app_key`、`-version`、主键排序（授权明细按用户姓名）。

### 紧急撤权

**POST `/operations/emergency-revokes`** 请求体含 `user_id`、`app_key`、`reason`。
当前应用授权不存在 → 409，`details.reason="active_grant_not_found"`。
部门来源检查发生在行锁之后、与撤权同一事务：先 `select_for_update` 当前授权，再看成员行。
组织对账若在锁前写入 `source="department"` 成员，撤权会 409，而不会在检查通过后整单撤销。
当前授权含任意 `source="department"` 的成员行 → 409，错误信封：

```json
{
  "error": {
    "code": "CONFLICT",
    "message": "该用户在此应用的权限来自组织授权，请在组织授权中调整。",
    "details": {
      "reason": "department_sourced_grant",
      "user_id": "<authentik uuid>",
      "app_key": "easylearning",
      "department_policy_ids": [1, 2]
    }
  }
}
```

成功路径审计仍为 `emergency_revoke_applied`，冲突拒绝不写该审计。

### 审批实例

**GET `/operations/approval-instances`** 要求 **superuser**。成功体为分页信封
`{ "data": [...], "pagination": { page, page_size, total_items, total_pages } }`。

列表项在既有运营字段外提供展示名：

| 字段 | 说明 |
| --- | --- |
| `originator_name` | 发起人 `UserMirror.name`；镜像无姓名时为空字符串 |
| `originator_department` | 发起人部门路径（与 `GET /user-options` 的 `department` 同口径）；镜像无部门时为空字符串 |
| `originator_account_kind` | `directory` / `local` / `unresolved`，口径见上文人员对象 `account_kind` |
| `app_name` | 应用名称 |
| `app_alias` | 应用别名；未设置时为空字符串 |

`originator_user_id` 仍为 Authentik 用户 ID。前端有姓名时展示姓名，无姓名时再回退到 ID。
发起人四字段来自同一 `person_payload`。
`POST /operations/approval-instances/{instance_id}/redeliver` 成功体中的
`approval_instance` 使用同一项形状。

---

## 审批模板（平台/全局）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET/POST | `/approval-templates` | 模板列表/创建 |
| GET/PATCH/DELETE | `/approval-templates/{template_id}` | 模板维护（可含 process_code） |
| POST | `/approval-templates/{template_id}/test` | 试发起 |

控制台可维护 `dingtalk_process_code` / `form_mapping`；公共 API 对下游**不暴露**这些字段。

---

## 生命周期与团队

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/lifecycle/handover-tasks` | 交接任务 |
| GET/PATCH | `/lifecycle/handover-tasks/{task_id}` | 任务详情 |
| GET | `…/grant-items`、`…/grant-diff`；POST `…/grant-diff/confirm` | 授权差异 |
| POST | `…/actions/{app_key}/{operation}` | 交接动作 |
| PATCH | `…/team-items/{item_id}` | 团队项 |
| GET/POST | `/lifecycle/onboarding-templates` | 入职模板 |
| GET/PATCH | `/lifecycle/onboarding-templates/{id}` | 模板详情 |
| POST | `/lifecycle/onboard` | 发起入职 |
| GET/POST | `/teams`、`/teams/{id}`、`…/members` | 团队与成员 |

交接任务列表与详情保留 `created_by` 原始 ID，并增加 `created_by_person`：能解析到
`UserMirror` 时为人员对象，系统账号或未知 ID 为 `null`。详情里 `escalation.defer_history[]`
保留 `actor_id`，并增加 `actor_person`，口径相同。人员对象由 `person_payload` 生成，
部门路径按本响应一次批量解析。门户交接列表/详情使用同一套字段。

团队详情 `members[]` 与列表 `leaders[]` 均为人员对象：`user_id`、`name`、`department`、
`account_kind`、`avatar_url`（成员项另含 `email`、`status`、`role`、`added_at`）。部门路径与人员选项同口径。

---

## 管理员直接授权与组织授权

全部接口要求 **superuser**。前缀 `/console/api/v1/`。写操作走既有控制台 CSRF。错误信封
`{ "error": { "code", "message", "details" } }`；列表/详情成功体为 `{ "data": ... }`。
`grant-catalog` 与门户申请目录同形，**不**再包一层 `data`。

| 方法 | 路径 | URL name | 说明 |
| --- | --- | --- | --- |
| GET | `/grant-catalog` | `console-grant-catalog` | 管理员授权目录（全量 active 应用/授权组/权限） |
| GET | `/user-options` | `console-user-options` | 被授权人联想或按 ID 回填；项含 `user_id`、`name`、`department`、`account_kind`、`avatar_url`；`include_directory=true` 时另含 `directory_user`，并可出现尚未登录的通讯录人员 |
| POST | `/direct-grants` | `console-direct-grants` | 管理员直接授予，立即合并进用户当前授权 |
| GET | `/users/{user_id}/apps/{app_key}/current-grant` | `console-user-app-current-grant` | 读取该用户在该应用的当前授权行 |
| GET | `/departments/tree` | `console-departments-tree` | 钉钉组织树 |
| GET | `/departments/{dept_id}/grant-policies` | `console-department-grant-policies` | 本部门 + 祖先继承的生效策略 |
| POST | `/departments/{dept_id}/grant-policies` | `console-department-grant-policies` | 在该部门新建预授权策略 |
| PUT | `/department-grant-policies/{id}` | `console-department-grant-policy` | 全量替换策略目标；不可改部门或应用 |
| DELETE | `/department-grant-policies/{id}` | `console-department-grant-policy` | 删除策略，204 |

### 用户选项

**GET `/user-options`** 要求 **superuser**。成功信封 `{ "data": [...] }`。

未传 `include_directory` 或 `include_directory=false` 时，行为与原先一致：项形状为
`{ "user_id", "name", "department", "account_kind", "avatar_url" }`。`department` 为部门路径（如「捷发-安环部」，
多部门按钉钉顺序以 ` / ` 拼接）；人员列表 `GET /users` 的 `department` 同口径。
`account_kind` 为 `directory` / `local` / `unresolved`，口径见上文人员对象；本路径只返回已有
UserMirror 的人员，因此只有 `directory` 或 `local`。
人员对象一律由 `accounts/person_payload.py` 生成。

查询方式：

| 参数 | 说明 |
| --- | --- |
| `user_ids` | 逗号分隔的 Authentik 用户 ID。给出后 `q` 可不传且被忽略，按这些 ID 回填 |
| `q` | 联想搜索关键字；未给 `user_ids` 时不得为空 |
| `purpose` | `employee`（默认）或 `approver`；给出则必须合法 |
| `limit` | 仅联想搜索生效，默认 10、最大 50 |
| `include_directory` | 可选，默认 `false`。只接受字面量 `true` / `false`，其它值 → 400 `VALIDATION_ERROR`（`details.field=include_directory`）。仅允许与 `purpose=employee` 组合，否则 400。与 `user_ids` 同时给出（`include_directory=true`）→ 400。读取全组织通讯录是管理员能力；本接口本身已要求 superuser，非超级管理员仍为 403。仅直接授权页应传 `true` |

`user_ids` 去空白后须为 1–50 个，否则 400 `VALIDATION_ERROR`（`details.field=user_ids`）。
超过 50 个或解析结果为空均拒绝。回填结果只含在职用户；`purpose=employee` 排除本地管理员，
`approver` 可包含。未知 ID、停用用户不出现在 `data` 中，顺序无约定。
`include_directory=true` 与 `user_ids` 不得同时使用，否则 400 `VALIDATION_ERROR`
（`details.field=include_directory`）。

未给 `user_ids` 时保持既有联想：空 `q` 为 422；匹配规则由 `accounts/user_search.py`
统一提供（姓名、邮箱、用户 ID、工号模糊匹配，纯字母数字可含空格时另按姓名全拼/首字母匹配，
如 `huyu`、`hyq` 可命中「胡玉琴A」），运营授权列表 `user_query` 使用同一套规则，
并受 `limit` 截断。非法 `purpose` 无论哪条路径均为 422。

`include_directory=true` 时，结果 = 既有 UserMirror 命中（排在前面，形状见下）+ 钉钉通讯录人员
（`DingTalkUserMirror`：`status=active`、`is_tombstone=false`，且不存在相同
`(dingtalk_source_slug, dingtalk_corp_id, dingtalk_userid)` 三元组的 UserMirror）。
未注册通讯录人员按姓名（包含）、工号（`employee_number`，大小写不敏感全等）和钉钉
`user_id`（精确全等）匹配 `q`；纯字母数字可含空格时另按姓名全拼/首字母匹配，规则与已注册用户相同
（如 `zhangtian`、`zhang`、`zt` 可命中「张甜」）。不按邮箱或 Authentik 用户 ID 匹配。
总数仍受既有 `limit` 截断。

带通讯录时的项形状（UserMirror 命中也带上新字段）：

```json
{
  "user_id": "<authentik uuid>",
  "name": "张甜",
  "department": "<与既有口径相同的部门路径>",
  "account_kind": "directory",
  "avatar_url": "...",
  "directory_user": {"source_slug": "dingtalk", "corp_id": "ding...", "user_id": "0220..."}
}
```

- 已有 UserMirror：`user_id` 为 Authentik uuid；`account_kind` 为 `directory` 或 `local`；`directory_user` 为其钉钉三元组，没有绑定则为 `null`。
- 仅通讯录、尚未登录：`user_id` 为 `null`，`account_kind` 为 `directory_unregistered`，
  `directory_user` 为三元组；部门路径按 `DingTalkUserMirror.department_ids` 走控制台同一套部门标签辅助函数；头像取通讯录行。

### 授权目录

`GET /grant-catalog` 复用门户 `serialize_request_catalog` 形状：`apps`、
`authorization_groups`（含 `grants[]`）、`permission_groups`、`ungrouped_permissions`、
`approver_options`。与门户的差异：

- 所有 `is_active` 应用；所有 active 授权组与未废弃权限，**不**看 `requestable` / 审批规则
- `approver_options` 恒为 `[]`；`default_approver_user_ids` 为 `[]`，
  `approver_resolution_status` 为 `not_required`
- 每个应用有平台内置授权组 `super_admin`（超级管理员）：`kind=role`，
  `requestable=false`，grant 覆盖该应用全部 active、未废弃权限及其受支持的
  active scope。控制台目录会列出该组；门户申请目录因 `requestable=false`
  不会列出。平台用 `is_builtin` 标记该组；已有同 key 的非内置组不会被静默接管。
  控制台不得重命名、停用、删除、占用该 key，也不得改 grant 成员资格
  （含 grant 的 `is_active`）。允许 PATCH 该组已有 grant 上的
  `managed_scope_policy` 覆盖（仅此字段）；平台不会为 `MANAGED_USERS`
  自动写入策略。内置组同步会保留 grant 行上已有的覆盖。manifest 不得声明该
  key。违规返回 `400 VALIDATION_ERROR`，`details.reason="reserved_authorization_group"`

### 直接授权

`POST /direct-grants` 请求体必须且只能指定 `user_id` 或 `directory_user` 其中一项
（同时给出或都缺 → 400 `VALIDATION_ERROR`）：

```json
{
  "user_id": "<authentik id>",
  "app_key": "easytrade",
  "authorization_group_keys": ["sales"],
  "direct_grants": [{"permission": "order.order.view", "scope": "GLOBAL"}],
  "grant_type": "timed",
  "grant_expires_at": "2026-12-31T15:59:59Z",
  "reason": "说明"
}
```

或对尚未登录的钉钉通讯录人员：

```json
{
  "directory_user": {
    "source_slug": "dingtalk",
    "corp_id": "ding...",
    "user_id": "0220..."
  },
  "app_key": "easytrade",
  "authorization_group_keys": ["sales"],
  "direct_grants": [{"permission": "order.order.view", "scope": "GLOBAL"}],
  "grant_type": "timed",
  "grant_expires_at": "2026-12-31T15:59:59Z",
  "reason": "说明"
}
```

`directory_user` 禁止额外字段。解析顺序：先按既有规则校验应用 / 授权组 / 权限 / 期限 / 理由
（此时不写 Authentik）；再要求 `DingTalkUserMirror` 存在、`status=active` 且非 tombstone。
通讯录中无此人 → 404「钉钉通讯录中不存在该人员。」；不是在职 → 409「该人员在钉钉通讯录中不是在职状态。」。
若已有相同三元组的 UserMirror（例如对方刚好登录了），走既有 `user_id` 授权路径。
否则调用 Authentik `materialize` 开通账号并绑定钉钉 source connection，再
`provision_user_from_authentik` 建 UserMirror（建档时仍会跑该用户的部门预授权对账）。
供给结果必须是新建或已存在；其它结果快速失败。Authentik 409 码映射为 409 中文：
`union_id_missing` →「该人员缺少钉钉 unionId,无法开通账号。」；
`username_conflict` / `binding_conflict` →「Authentik 中已有冲突账号,需管理员处理。」；
`directory_user_inactive` 与通讯录非在职相同。传输失败或上游 5xx → 503 `DEPENDENCY_UNAVAILABLE`。
开通账号后若授权写入失败，Authentik 账号与 UserMirror **保留**（重试幂等），不回滚 Authentik。

Authentik 报告新建，或本次新建了 UserMirror 时，写审计 `directory_user_materialized`
（`actor_type=admin`，`target_type=user`，`target_id` 为 Authentik uuid；
metadata：`source_slug`、`corp_id`、钉钉 `user_id`、`created` 布尔）。

校验：以 `user_id` 提交时用户必须存在且 `active`；应用 active；组/权限/范围必须存在、启用且受支持。
管理员授予**忽略** `requestable` 与审批规则。限时必须未来到期，永久必须
`grant_expires_at=null`。控制台表单会预加载被授权人在该应用上的当前用户来源成员，
提交后用户来源集合必须与本次提交相等。

替换语义：本次提交的授权组 / 直接权限即为该用户在该应用上完整的
`source="user"` 成员集合，交给 `GrantService.change_grant`
（无当前授权时由其创建）。管理员去掉的用户来源行会被收回；保留的行若期限未改则沿用原到期时间，
改了则用本次 `grant_expires_at`；新增的行按本次期限写入。部门来源行
（`source="department"`）本路径不会改写：`GrantService.change_grant` /
`replace_memberships` 只替换用户来源成员。

空目标（无授权组、无直接权限）表示清空全部管理员授予的用户来源成员：若仍有部门来源行，
当前授权保持有效且只剩部门行；若没有任何成员剩余，则走既有收回路径撤掉当前授权，
不留下空的当前授权行。没有当前授权时提交空目标仍为 422。

授权组按组落库，不展开为权限。操作者 `actor_type="admin"`。额外审计
`direct_grant_applied`（`target_type=grant`），记录替换后的用户来源组/权限 key
以及被去掉的 key（`removed_authorization_group_keys` / `removed_permission_keys`）。

错误：用户/应用不存在 → 404；用户非在职 → 409；目录/范围问题 → 422
`SEMANTIC_VALIDATION_ERROR`，`details.errors` 为中文列表。**当前**授权含 `MANAGED_USERS`
时，先按 user/app 预热目录缓存，再进入写事务；锁内展开只读这份缓存，不再发目录 HTTP。
预热或展开时组织目录不可用 → **503 `DEPENDENCY_UNAVAILABLE`**，授权写入与
`direct_grant_applied` 成功审计一并回滚，不留下半成功状态。空目标收回最后一条用户来源成员后，
响应展开的是已收回的历史行：只保留权限/范围名称，不解析管理对象名单，也不访问组织目录；
目录不可用不得回滚这次收回。成功 201，
`data` 为 `{ "grant": <授权行> }`，形状见下方「授权行」；行上的 `user_id` 始终是真实 Authentik uuid
（通讯录人员会在开通账号后写入）。

### 当前授权

**GET `/users/{user_id}/apps/{app_key}/current-grant`** 要求 **superuser**。
成功体为 `{ "grant": <授权行> | null }`：无当前有效授权时 `grant` 为 `null`。
用户或应用不存在 → 404 错误信封（`details` 含 `user_id` 或 `app_key`）。

### 授权行

以下接口共用同一授权行形状：`GET /operations/access-grants` 列表项、
`POST /direct-grants` 的 `data.grant`、`GET /users/{user_id}/apps/{app_key}/current-grant`
的 `grant`（非 null 时）。

```json
{
  "id": 6,
  "version": 3,
  "is_current": true,
  "status": "active",
  "user_id": "<authentik uuid>",
  "user_name": "胡玉琴A",
  "user_department": "捷发-安环部",
  "user_account_kind": "directory",
  "app_key": "easylearning",
  "app_name": "EasyLearning",
  "app_alias": "学习工作台",
  "grant_type": "permanent",
  "grant_expires_at": null,
  "authorization_groups": [
    {
      "key": "sales",
      "kind": "role",
      "name": "销售",
      "expires_at": null,
      "source": "user"
    }
  ],
  "direct_grants": [
    {
      "permission": "order.order.view",
      "permission_name": "查看订单",
      "scope": "GLOBAL",
      "scope_name": "全局",
      "expires_at": null,
      "source": "user"
    }
  ],
  "groups": [{"key": "sales", "kind": "role", "name": "销售"}],
  "grants": [
    {
      "permission": "order.order.view",
      "scope": "GLOBAL",
      "source_type": "group",
      "source_key": "sales",
      "permission_name": "查看订单",
      "permission_name_en": "View orders",
      "scope_name": "全局",
      "scope_name_en": "Global"
    }
  ]
}
```

`grant_type` 为 `permanent` / `timed` / `mixed`，语义与门户当前授权生命周期摘要相同。
`grant_expires_at` 为限时成员的最早到期时间，全部永久则为 `null`。
`authorization_groups` / `direct_grants` 来自该授权版本自身的成员行（含
`source`：`user` 或 `department`）。`groups` / `grants` 由该行成员展开，
历史版本同样按该版本展开，不读取后续版本。
**非当前**历史行按展示语义展开：不过滤过期成员，也不按当前目录 `is_active` /
`deprecated_at` 过滤授权组、权限、范围或组映射；生命周期摘要跟这些展示成员走，
因此过期限时或已停用目录行不会把历史行变成 `permanent` / `null`。
历史行上的 `MANAGED_USERS` 只保留权限/范围名称，不解析管理对象名单，也不访问组织目录；
目录不可用不得导致历史行展开失败。
**当前授权**与 SDK 有效快照仍按到期与目录启用状态过滤，并解析 `MANAGED_USERS` 管理对象；
目录不可用仍为 503。
`user_name` 为 `UserMirror.name`，
镜像无姓名时为空字符串。`user_department` 为被授权人部门路径，与人员选项同口径。
`user_account_kind` 为 `directory` / `local` / `unresolved`，口径见上文人员对象 `account_kind`。

### 组织授权

当前只支持**一个**钉钉企业。从 `DingTalkDirectorySyncState` /
`DingTalkDepartmentMirror` 推导 `(source_slug, corp_id)`：尚无部门镜像 → 409
`directory_not_synced`（「尚未同步钉钉组织架构」）；多个企业 → 409，不猜测。

`GET /departments/tree` 返回单根树；多个根（含孤儿部门）挂到主根下。
`member_count` 为该部门的**直接**成员：active 且未 tombstone 的
`DingTalkUserMirror`，`department_ids` 含该部门 ID。

`GET /departments/{dept_id}/grant-policies` 列出本部门策略，再按祖先由近到远继承；
同层按应用别名/名称、id。公司策略会出现在之后新建的子孙部门中，
`inherited=true` 且 `defined_on` 指向公司。镜像中已不存在的部门上的策略不展示。
`affected_user_count` / `subtree_member_count` 统计子树内在职且已绑定钉钉的员工：
`UserMirror.status=active`，对应 `DingTalkUserMirror` 为 active、未 tombstone，
且 `department_ids` 与子树相交。

策略写（POST/PUT/DELETE）与直接授权使用同一套目标校验。每次写入在同一事务内：

1. 审计 `department_policy_created` / `updated` / `deleted`（`target_type=department_policy`）
2. `schedule_department_grant_reconcile(trigger="policy")`，经 outbox 入队
   `easyauth.grants.reconcile_department_grants`

PUT 不得变更策略所属部门或应用，否则 422。

### `source=user` 与 `source=department`

同一 `(用户, 应用)` 只有一条当前 `AccessGrant`。组成员来自两条通道，唯一约束按
`(grant, 目标, source)` 分开：

| source | 写入方 | 含义 |
| --- | --- | --- |
| `user` | 审批通过、交接、入职、管理员直接授予等既有路径 | 显式授予 |
| `department` | **仅**部门对账 `GrantService.sync_department_memberships` | 由部门预授权策略物化 |

用户侧变更只改写 `source=user` 行，不会丢掉部门行。对账只改写部门行。
查询侧的有效授权快照按来源无关合并（永久优先，否则取最晚到期）。

部门策略对子树内在职员工是权威来源：员工加入子树则授予，离开则收回部门行。
在职员工的当前授权若被撤销，下一次对账仍会按生效策略**重新创建**部门行。
离职/非 active / 无钉钉绑定的人期望集合为空。

对账触发：目录同步结束（`trigger=directory-sync`）、策略 CRUD
（`trigger=policy`）、以及定时 beat（默认 30 分钟）。UserMirror 还会由权限查询即时供给
或 `dingtalk-directory-sync` **先于**目录同步的周期镜像创建（`python manage.py mirror_authentik_users`
可运维回填），建档后对账才能把部门预授权物化到「只登录过下游、从未打开门户」的员工。
查找 Authentik 用户必须用 `?uuid=`（OIDC `sub`），不能用 `uid` 散列。
首次见到在职钉钉用户时（`AuthentikSyncService.sync_payload` 建档），
**同步**执行该用户的部门预授权对账，使同一请求内随后的权限查询即可读到
`source=department` 成员；若全量对账锁被占用，短暂等待后经 outbox 回退到
全量对账（`trigger=user-sync`）。调用方须处于 autocommit，每人/应用对在锁内
独立提交。目录同步内的状态回灌（`apply_directory_status`）不走单用户对账：
整轮写入共用同一事务，对账由本轮结束时入队的全量任务完成。
对账失败只记日志并入队全量，不得回滚用户建档。

---

## 用户、审计、设置、安全

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/users`、`/user-options` | 用户检索/选项 |
| GET | `/audit-logs` | 审计日志 |
| GET/PATCH | `/settings/integrations` | 集成设置 |
| POST | `/settings/integrations/authentik/test` | Authentik 连通测试 |
| POST | `/settings/integrations/dingtalk/test` | 钉钉统一认证应用连通测试 |
| POST | `/settings/integrations/dingtalk-notify/test` | 钉钉服务号连通测试 |
| GET | `/security/two-factor` | 二因素状态 |
| POST | `/security/two-factor/totp/*`、`passkeys/*` | TOTP / Passkey |

**GET `/audit-logs`** 列表项在既有 `actor_type` / `actor_id` 之外提供 `actor_person`：
当 `actor_id` 能解析到 `UserMirror` 时为人员对象（`user_id`、`name`、`department`、
`account_kind`、`avatar_url`，由 `person_payload` 生成，与 `actor_type` 无关）；系统账号或未知 ID 为
`null`。人员部门路径按当前页批量解析。

全局 `/settings/integrations` 中的主钉钉凭证（`dingtalk_app_key` / `app_secret` / `agent_id`）
用于目录同步、Stream、登录与审批；`dingtalk_notify_*` 为工作通知专用服务号，GET 返回落库值
（secret 只给 `dingtalk_notify_app_secret_configured`，永不回显明文）。三项均非空才覆盖主应用，
否则发送回退主应用三元组。`dingtalk_notify_work_notice_enabled` 与
`dingtalk_notify_robot_enabled`（布尔，默认均为 `true`）是两个通知渠道开关，分别控制钉钉工作
通知（OA 消息）与服务号机器人一对一推送；两者同时为 `false` 会以 `VALIDATION_ERROR`
422 拒绝，因为那等于关闭全部通知送达。PATCH 为部分更新，secret 省略则保持原密文。
`notify` 业务 App 仍须在自己的 workspace 配置 `notification-channel` 以绑定目录作用域。
每个版本同时绑定 `directory_source_slug` 和 `corp_id`。GET 返回
`notification_channel` 及 `available_directory_scopes`；后者是当前目录同步状态、
用户镜像和部门镜像中作用域的排序并集，也是 owner 可保存值的权威列表。
PUT 必须提交其中一组作用域；控制台使用受校验的下拉框，不接受自由文本。
若历史 active 通道的作用域已不在列表中，页面显示不可选的修复态与错误提示，
owner 选择有效作用域并保存新版本后恢复；此时依赖健康为 unhealthy，越界发送会被拒绝。
首次创建必须提供 secret；后续 PUT 可省略 secret 以复用已有密文。
响应不回显 secret，连通性失败不返回钉钉底层错误原文。

### 连通性测试（三个「测试连接」端点）

设置页每张集成卡片各有一个探针端点，三者共用同一套约定：

| 端点 | 探测内容 |
| --- | --- |
| `POST /settings/integrations/authentik/test` | 带 API token 请求 `GET {base_url}/api/v3/core/users/?page_size=1`，一次调用同时证明 Base URL 可达与 token 可用 |
| `POST /settings/integrations/dingtalk/test` | 统一认证应用：强制刷新一次新版 `POST /v1.0/oauth2/accessToken` |
| `POST /settings/integrations/dingtalk-notify/test` | 服务号：新版 `accessToken` **和**旧版 `GET https://oapi.dingtalk.com/gettoken` 两条授权链路都要过 |

- **权限**：与 `/settings/integrations` 相同，`require_superuser`；仅接受 POST，其它方法 405。
- **限流**：按「目标 + 管理员」固定窗口计数，60 秒内 30 次，超出返回 `THROTTLED` 429。
- **审计**：每次调用落一条 `AuditLog`，`event_type` 分别为 `authentik_connectivity_tested`、
  `dingtalk_connectivity_tested`、`dingtalk_notify_connectivity_tested`，`target_type` 为
  `integration_settings`，`metadata` 只含 `ok` / `error_code` / `error` / `latency_ms`，**不含**任何
  token 或 secret。
- **请求体**（可选，`extra="forbid"`）：表单里尚未保存的「草稿」值。字段留空或缺省表示沿用落库值
  （secret 留空即沿用已存密文），因此探测的永远是"保存后真正会被使用的那组凭证"。
  - Authentik：`authentik_base_url`、`authentik_api_token`；
  - 统一认证应用：`dingtalk_app_key`、`dingtalk_app_secret`、`dingtalk_agent_id`；
  - 服务号：`dingtalk_notify_app_key`、`dingtalk_notify_app_secret`、`dingtalk_notify_agent_id`。
    服务号三项未配齐时按运行时口径**回退到统一认证应用凭证**并探测该组，与发送路径一致。
- **响应**（探测失败同样是 200，`ok=false`；只有权限/方法/限流/参数错误才用错误信封）：

```json
{ "ok": true, "latency_ms": 42, "error_code": "", "error_message": "" }
```

  `error_code` 取值：`NOT_CONFIGURED`（凭证缺失，不发出站请求）、`INSECURE_BASE_URL`
  （Authentik Base URL 非 https 且非本机 localhost，拒绝明文传输管理 token）、`UNAUTHORIZED`
  （上游 401/403）、`REJECTED`（上游其它 4xx/5xx 或 oapi 业务 errcode）、`UNAVAILABLE`
  （网络不可达/超时）。响应与审计都不回显 token/secret。

  服务号机器人的**存在性**不做探测：钉钉开放平台没有"不发消息就能确认企业内部单聊机器人存在"
  的廉价接口，企业内部应用的 `robotCode` 即 AppKey，已由上面两次换票覆盖其凭证有效性。

---

授权对象模型为 **`authorization_groups`**，不是 `roles`。

### 列表排序字段

控制台列表接口通过 `ordering` 接收一个字段名，前缀 `-` 表示降序；未知字段返回 400。应用支持 `app_key`、`name`、`status`、`updated_at`、`owners`、`configuration_status`；团队支持 `name`、`status`、`created_at`、`member_count`、`leaders`；用户支持 `name`、`department`、`status`、`is_console_admin`；交接任务支持 `created_at`、`status`、`kind`、`subject`、`assignee_state`、`blocked`；审批实例支持 `created_at`、`status`、`app_key`、`template`、`biz_key`、`originator`、`dingtalk_process_instance_id`、`delivery`；连接器同步运行支持 `started_at`、`finished_at`、`status`、`error`、`stats`（`stats` 使用连接器写入的 `api_calls` 计数）；权限模板版本支持 `version`、`status`、`imported_at`、`imported_by`；运营访问申请支持 `id`、`user`、`app_key`、`status`、`request_type`、`approvers`、`failure_reason`、`submitted_at`；运营授权支持 `user`、`app_key`、`status`、`groups`、`permission_details`、`grant_expires_at`；审计日志支持 `event_type`、`actor`、`target`、`app`、`created_at`。
`null` 与空字符串在升序、降序下都排在最后，空单元格始终留在表格底部。
