# 控制台 App 创建与编辑执行计划

> **给执行代理：** 执行前必须读取 `AGENTS.md`、总览文档和设计文档第 7 节。本文只覆盖控制台 App 创建、编辑和 owner 初始化闭环；不要在本阶段改造授权组或公共查询模型。

**目标：** 管理员可以通过控制台 API 创建 App，并在同一事务内初始化 owner/developer；系统管理员和 App owner 可以按权限编辑 App 基本信息。

**架构：** 复用现有 `App`、`AppMembership`、`ConsoleActor`、`can_view_app()`、`can_manage_app()` 和审计服务。`POST /console/api/v1/apps` 只允许系统管理员；`PATCH /console/api/v1/apps/{app_key}` 允许系统管理员编辑全部可编辑字段，允许 App owner 编辑 `name/description`。

**技术栈：** Django view、Pydantic payload、Django 事务、pytest 集成测试。

---

## 当前事实

- `src/easyauth/admin_console/urls.py` 已有 `path("api/v1/apps", console_apps)` 和 `path("api/v1/apps/<str:app_key>", console_app_detail)`。
- `src/easyauth/admin_console/apps_api.py` 目前只处理 `GET /console/api/v1/apps` 和 `GET /console/api/v1/apps/{app_key}`。
- `src/easyauth/applications/ops_models.py` 已有 `AppMembership`，角色为 `owner/developer`，唯一约束为 `(app, user_id, role)`。
- `src/easyauth/admin_console/memberships_api.py` 已有后续成员管理 API，但它不是创建 App 的同事务闭环。
- `tests/integration/admin_console/test_apps_api_ops1.py` 已覆盖 App 列表、详情、configuration status 和 membership API，缺少 create/update App 测试。

## API 契约

### `POST /console/api/v1/apps`

请求：

```json
{
  "app_key": "easytrade",
  "name": "EasyTrade",
  "description": "外贸业务系统",
  "is_active": true,
  "owner_user_ids": ["owner_001"],
  "developer_user_ids": ["dev_001"]
}
```

规则：

- 只有系统管理员可以创建 App。
- `app_key` 全局唯一，只允许小写字母、数字、短横线和下划线，长度沿用模型上限 64。
- `name` 必填，去除首尾空白后不能为空，长度沿用模型上限 128。
- `description` 可为空字符串。
- `is_active` 缺省为 `true`。
- `owner_user_ids` 为空或缺失时，后端使用当前 actor 的 `user_id` 作为 owner。
- `developer_user_ids` 可为空。
- 创建 `App`、owner membership 和 developer membership 必须包在同一个 `transaction.atomic()` 中。
- owner 与 developer 列表要去重；同一 user 同时出现在 owner 和 developer 时保留 owner，避免重复创建相同用户的双角色初始关系。
- 成功后返回与 `GET /console/api/v1/apps/{app_key}` 一致的完整 App detail。
- 写审计事件 `console_app_created`，metadata 至少包含 `app_key`、`owner_user_ids`、`developer_user_ids`、`is_active`。

建议响应：

```json
{
  "app": {
    "id": 1,
    "app_key": "easytrade",
    "name": "EasyTrade",
    "description": "外贸业务系统",
    "is_active": true,
    "owners": ["owner_001"],
    "developers": ["dev_001"],
    "can_manage": true,
    "configuration_status": "blocking",
    "configuration_summary": {
      "status": "blocking",
      "issue_count": 0,
      "blocking_count": 0,
      "warning_count": 0
    }
  }
}
```

### `PATCH /console/api/v1/apps/{app_key}`

请求：

```json
{
  "name": "EasyTrade 业务系统",
  "description": "外贸业务系统",
  "is_active": false
}
```

规则：

- 系统管理员可以修改 `name`、`description`、`is_active`。
- App owner 只能修改 `name`、`description`。
- App developer 不能修改。
- 不允许通过此接口修改 `app_key`。
- payload 至少包含一个允许字段。
- 成功后返回完整 App detail。
- 写审计事件 `console_app_updated`，metadata 记录变更字段和新值，不记录无关字段。

## 触达文件

- 修改：`src/easyauth/admin_console/apps_api.py`
- 修改：`src/easyauth/admin_console/urls.py`
- 可选新增：`src/easyauth/admin_console/app_payloads.py`
- 修改：`tests/integration/admin_console/test_apps_api_ops1.py`
- 修改：`tests/integration/admin_console/test_apps_contract_compat.py`
- 后续前端联动见 `05-frontend-console-portal`

## 任务 1：先补失败测试

- [ ] 在 `tests/integration/admin_console/test_apps_api_ops1.py` 增加系统管理员创建 App 的测试。

覆盖断言：

- 响应状态是 `201 CREATED`。
- `App.objects.get(app_key="ops1-api-create-crm")` 存在。
- owner membership 与 developer membership 存在且 `is_active=True`。
- 响应 `app.owners`、`app.developers` 与数据库一致。
- `AuditLog` 存在 `event_type="console_app_created"`。

- [ ] 增加 owner 为空时默认当前 actor 为 owner 的测试。

覆盖 payload：

```json
{
  "app_key": "ops1-api-create-default-owner",
  "name": "CRM"
}
```

期望：

- 当前 actor 成为 owner。
- 返回 `owners` 包含当前 actor。

- [ ] 增加非系统管理员不能创建 App 的测试。

期望：

- owner/developer 普通用户 `POST /console/api/v1/apps` 返回 `403`。
- 不落库 App。

- [ ] 增加重复 `app_key`、非法 `app_key`、空 `name` 的测试。

期望：

- 重复 `app_key` 返回 `409` 或现有项目约定的语义错误状态。
- 非法 `app_key` 返回 `400`。
- 空 `name` 返回 `400`。

- [ ] 增加 `PATCH` 权限测试。

覆盖：

- App owner 能修改 `name/description`。
- App owner 修改 `is_active` 返回 `403`，数据库不变。
- 系统管理员能修改 `is_active`。
- developer 修改任意字段返回 `403`。
- payload 带 `app_key` 返回 `400`。
- 成功更新写入 `console_app_updated`。

运行：

```bash
pytest tests/integration/admin_console/test_apps_api_ops1.py -q
```

期望：新增测试先失败，失败原因指向缺少 POST/PATCH 或校验逻辑。

## 任务 2：实现 payload 校验

- [ ] 在 `src/easyauth/admin_console/app_payloads.py` 新增 `AppCreatePayload` 与 `AppPatchPayload`，或放入 `apps_api.py` 中保持局部实现。
- [ ] `AppCreatePayload` 字段：`app_key`、`name`、`description=""`、`is_active=True`、`owner_user_ids=[]`、`developer_user_ids=[]`。
- [ ] `AppPatchPayload` 字段：`name | None`、`description | None`、`is_active | None`。
- [ ] 增加 `_normalize_user_ids()`：去除空白、过滤空字符串、保持稳定顺序去重。
- [ ] 增加 `_validate_app_key()`：只接受 `^[a-z0-9][a-z0-9_-]{1,63}$`，避免首字符为空或标点。
- [ ] 对 JSON 解析失败返回项目统一错误响应，不泄露 Python 异常。

运行：

```bash
pytest tests/integration/admin_console/test_apps_api_ops1.py -q
```

期望：payload 相关测试通过，API 路由测试仍可能失败。

## 任务 3：实现 `POST /console/api/v1/apps`

- [ ] 修改 `console_apps(request)`，按 `request.method` 分派：
  - `GET` 保留现有列表逻辑。
  - `POST` 调用 `_create_app(request)`。
  - 其他方法返回 `405`。
- [ ] `_create_app()` 调用 `require_console_actor(request)`。
- [ ] 非 `actor.is_superuser` 返回 `PERMISSION_DENIED`。
- [ ] 解析 payload 后检查 `App.objects.filter(app_key=payload.app_key).exists()`。
- [ ] 在 `transaction.atomic()` 内创建 `App` 与 memberships。
- [ ] owner 缺省使用当前 actor；developer 中与 owner 重复的用户不创建 developer membership。
- [ ] 复用 `_app_detail_item(actor, app)` 构造响应，状态码为 `201`。
- [ ] 使用 `AuditService.record()` 写 `console_app_created`。

运行：

```bash
pytest tests/integration/admin_console/test_apps_api_ops1.py::test_ops1_apps_api_superuser_creates_app_with_memberships -q
```

期望：通过。

## 任务 4：实现 `PATCH /console/api/v1/apps/{app_key}`

- [ ] 修改 `console_app_detail(request, app_key)`，按 `request.method` 分派：
  - `GET` 保留现有详情逻辑。
  - `PATCH` 调用 `_patch_app(request, app_key)`。
  - 其他方法返回 `405`。
- [ ] 查不到 App 或不可见时继续按现有逻辑返回 `404`。
- [ ] App developer 和无 membership 用户返回 `403`。
- [ ] App owner 修改 `is_active` 返回 `403`。
- [ ] 系统管理员可修改 `is_active`。
- [ ] 更新后返回 `_app_detail_item(actor, app)`。
- [ ] 写 `console_app_updated` 审计。

运行：

```bash
pytest tests/integration/admin_console/test_apps_api_ops1.py -q
```

期望：本文件全部通过。

## 任务 5：补契约兼容测试

- [ ] 在 `tests/integration/admin_console/test_apps_contract_compat.py` 固定 `POST` 成功响应字段。
- [ ] 固定 `PATCH` 成功响应字段。
- [ ] 固定错误响应使用项目统一 `error.code`。
- [ ] 确认现有列表与详情字段没有被破坏。

运行：

```bash
pytest tests/integration/admin_console/test_apps_contract_compat.py -q
```

期望：通过。

## 任务 6：真实 HTTP 验证

本阶段修改 Django 后端代码，完成后必须重启当前 Django 开发服务。

重启后验证：

```bash
curl -i http://127.0.0.1:8000/console/api/v1/apps
curl -i http://127.0.0.1:8000/console/api/v1/apps/{app_key}
```

如果本地有已登录浏览器会话，还需要打开：

- `/console`
- `/console/apps/{app_key}/`

确认新创建的 App 出现在列表中，详情可读取。

## 完成判定

- 系统管理员可以仅通过 API 创建 App 并初始化 owner。
- App owner 可以编辑基本信息，但不能启停 App。
- 系统管理员可以启停 App。
- 非系统管理员不能创建 App。
- 所有写操作有审计。
- 局部测试与真实 HTTP 验证均通过。
