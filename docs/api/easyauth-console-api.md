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
| GET/PUT | `/apps/{app_key}/managed-scope-policy` | MANAGED_USERS 策略 |
| GET | `/apps/{app_key}/managed-users-preview` | 管理范围预览 |
| POST | `/apps/{app_key}/permission-query-tests` | 权限查询联调 |

---

## 成员与凭据

| 方法 | 路径 | 权限要点 |
| --- | --- | --- |
| GET/POST | `/apps/{app_key}/memberships` | 成员管理 |
| PATCH/DELETE | `/apps/{app_key}/memberships/{membership_id}` | 成员变更 |
| GET | `/apps/{app_key}/credentials` | 凭据列表（无 secret） |
| POST | `/apps/{app_key}/credentials/static-tokens` | 创建静态 token（明文一次性） |
| POST | `…/static-tokens/{id}/rotate` | 轮换 |
| POST | `…/static-tokens/{id}/disable` 或 `…/credentials/{type}/{id}/disable` | 停用 |
| POST | `/apps/{app_key}/credentials/oauth-clients` | 创建 OAuth client |

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

---

## 与历史文档的关系

- 授权对象模型为 **`authorization_groups`**，不是 `roles`
- 更细的字段级设计草稿见 [`easyauth-authorization-operations-api-design.md`](./easyauth-authorization-operations-api-design.md)；**以本文件与实现代码为准**
