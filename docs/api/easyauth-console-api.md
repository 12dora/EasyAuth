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

### Webhook 投递

**GET `/apps/{app_key}/webhook-deliveries`**

查询参数：

| 参数 | 说明 |
| --- | --- |
| `status` | `pending` / `delivered` / `failed` |
| `event_type` | 如 `approval.completed`、`webhook.test` |
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

---

## 用户、审计、设置、安全

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/users`、`/user-options` | 用户检索/选项 |
| GET | `/audit-logs` | 审计日志 |
| GET/PUT | `/settings/integrations` | 集成设置 |
| POST | `/settings/integrations/dingtalk/test` | 钉钉连通测试 |
| GET | `/security/two-factor` | 二因素状态 |
| POST | `/security/two-factor/totp/*`、`passkeys/*` | TOTP / Passkey |

全局 `/settings/integrations` 中的钉钉 agent 配置只用于旧配置迁移、审批等仍属全局的能力；
`notify` 业务 App 必须在自己的 workspace 配置 `notification-channel`。
每个版本同时绑定 `directory_source_slug` 和 `corp_id`。GET 返回
`notification_channel` 及 `available_directory_scopes`；后者是当前目录同步状态、
用户镜像和部门镜像中作用域的排序并集，也是 owner 可保存值的权威列表。
PUT 必须提交其中一组作用域；控制台使用受校验的下拉框，不接受自由文本。
若历史 active 通道的作用域已不在列表中，页面显示不可选的修复态与错误提示，
owner 选择有效作用域并保存新版本后恢复；此时依赖健康为 unhealthy，越界发送会被拒绝。
首次创建必须提供 secret；后续 PUT 可省略 secret 以复用已有密文。
响应不回显 secret，连通性失败不返回钉钉底层错误原文。

---

授权对象模型为 **`authorization_groups`**，不是 `roles`。
