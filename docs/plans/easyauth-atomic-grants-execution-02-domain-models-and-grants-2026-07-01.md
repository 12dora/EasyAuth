# 领域模型与授权事实执行计划

> **给执行代理：** 本文是后续公共查询、manifest、门户和前端的模型前置条件。执行前必须确认不会建立长期 `Role` 与 `AuthorizationGroup` 双模型。

**目标：** 建立 App scope、可授权权限组、scoped group grant、scoped direct grant 和 App 级目录版本，替换旧 `Role + RolePermission + AccessGrantRole` 运行时语义。

**架构：** `AuthorizationGroup` 是唯一可授权组模型，`kind=role|bundle` 区分岗位型角色组与场景型权限包。`AuthorizationGroupGrant` 负责把可授权组展开到 `permission + scope_key`。`AccessGrantGroup` 保存用户持有的可授权组，`AccessGrantPermission` 保存 scoped direct grant。

**技术栈：** Django models、数据库约束、数据库迁移、pytest 模型测试。

---

## 当前事实

- `src/easyauth/applications/models.py` 中 `Role` 仍是一等授权对象。
- `RolePermission` 只表达 `role -> permission`，没有 scope。
- `Permission` 没有 `supported_scopes` 和 `risk_level`。
- `App` 没有 `catalog_version`。
- `src/easyauth/grants/models.py` 中 `AccessGrantRole` 绑定 `Role`。
- `AccessGrantPermission` 不带 `scope_key`。
- `AccessGrant` 已有 `version/status/grant_expires_at/is_current`，可保留并扩展审计元数据。
- `src/easyauth/access_requests/models.py` 中 `AccessRequestRole/AccessRequestPermission` 仍是不带 scope 的旧目标。

## 目标模型

### `App`

新增：

- `catalog_version: PositiveIntegerField(default=1)`

规则：

- 所有目录、scope、授权组、授权组 grant、permission 风险和 manifest 确认导入变更都必须通过服务函数提升该版本。

### `AppScope`

字段：

- `app`
- `key`
- `name`
- `description`
- `is_active`
- `display_order`
- `created_at`
- `updated_at`

约束：

- `(app, key)` 唯一。
- `key` 使用稳定字符集，建议与 `app_key` 同样只允许大写字母、数字和下划线，示例为 `SELF/MANAGED/ALL/GLOBAL`。

### `AuthorizationGroup`

字段：

- `app`
- `key`
- `kind`
- `name`
- `description`
- `requestable`
- `is_active`
- `created_at`
- `updated_at`

约束：

- `(app, key)` 唯一。
- `kind` 只允许 `role` 或 `bundle`。

迁移策略：

- 项目尚未投产，主代码口径直接切到 `AuthorizationGroup`。
- 数据迁移可以把旧 `Role` 迁为 `AuthorizationGroup(kind="role")`，但不保留长期旧 API 主路径。

### `AuthorizationGroupGrant`

字段：

- `authorization_group`
- `permission`
- `scope_key`
- `is_active`
- `created_at`
- `updated_at`

约束：

- `(authorization_group, permission, scope_key)` 唯一。
- `permission.app_id == authorization_group.app_id`。
- `scope_key` 必须引用同 App 下 active 或存在的 `AppScope.key`；是否要求 active 由写入场景决定，公共查询必须过滤 inactive scope。
- `scope_key` 必须包含在 `Permission.supported_scopes` 中。

### `Permission`

新增：

- `supported_scopes: JSONField(default=list)`
- `risk_level: CharField(default="standard")`

规则：

- active permission 的 `supported_scopes` 不得为空。
- `risk_level` 初始允许 `standard/high`，后续如需扩展必须先更新 readiness 与审批规则。

### `AccessGrantGroup`

字段：

- `grant`
- `authorization_group`
- `created_at`

约束：

- `(grant, authorization_group)` 唯一。
- `authorization_group.app_id == grant.app_id`。

### `AccessGrantPermission`

新增：

- `scope_key`
- `source_note`

约束：

- `(grant, permission, scope_key)` 唯一。
- `permission.app_id == grant.app_id`。
- `scope_key` 必须引用 grant App 下的 scope，并且在 `permission.supported_scopes` 中。

### Access request 目标

将长期目标改为：

- `AccessRequestGroup(request, authorization_group)`
- `AccessRequestPermission(request, permission, scope_key)`

旧 `AccessRequestRole` 只允许作为迁移来源，不能作为新主路径。

## 触达文件

- 修改：`src/easyauth/applications/models.py`
- 修改：`src/easyauth/applications/ops_models.py`
- 修改：`src/easyauth/grants/models.py`
- 修改：`src/easyauth/access_requests/models.py`
- 修改：`src/easyauth/applications/admin.py`
- 新增：`src/easyauth/applications/migrations/0009_atomic_authorization_models.py`
- 新增：`src/easyauth/grants/migrations/0002_scoped_grants.py`
- 新增：`src/easyauth/access_requests/migrations/0004_scoped_targets.py`
- 修改：`tests/unit/applications/test_models.py`
- 修改：`tests/unit/grants/test_models.py`
- 修改：`tests/unit/access_requests/test_models.py`

## 任务 1：写模型测试

- [ ] 在 `tests/unit/applications/test_models.py` 增加 `AppScope` 唯一约束测试。
- [ ] 增加 `AuthorizationGroup.kind` 只接受 `role/bundle` 的测试。
- [ ] 增加 `AuthorizationGroupGrant` 阻止跨 App permission 的测试。
- [ ] 增加 `AuthorizationGroupGrant` 阻止未支持 scope 的测试。
- [ ] 增加 active permission 的 `supported_scopes` 不能为空的测试。
- [ ] 在 `tests/unit/grants/test_models.py` 增加 `AccessGrantGroup` 阻止跨 App group 的测试。
- [ ] 增加 `AccessGrantPermission(permission, scope_key)` 唯一约束测试。
- [ ] 在 `tests/unit/access_requests/test_models.py` 增加 scoped request target 测试。

运行：

```bash
pytest tests/unit/applications/test_models.py tests/unit/grants/test_models.py tests/unit/access_requests/test_models.py -q
```

期望：新增测试失败，失败原因是模型不存在或约束缺失。

## 任务 2：新增应用侧模型与迁移

- [ ] 给 `App` 增加 `catalog_version`。
- [ ] 增加 `AppScope`。
- [ ] 增加 `AuthorizationGroup`。
- [ ] 增加 `AuthorizationGroupGrant`。
- [ ] 扩展 `Permission.supported_scopes` 与 `Permission.risk_level`。
- [ ] 更新 `__all__` 和 Django admin 注册。
- [ ] 生成并审阅 `applications` migration。

迁移注意：

- 对已有测试数据创建默认 `GLOBAL` scope。
- 将旧 `Role` 数据迁移为 `AuthorizationGroup(kind="role")`。
- 将旧 `RolePermission` 数据迁移为 `AuthorizationGroupGrant(scope_key="GLOBAL")`。
- 迁移仅服务开发数据和测试数据，不作为长期兼容层。

运行：

```bash
python manage.py makemigrations applications
python manage.py migrate --check
pytest tests/unit/applications/test_models.py -q
```

期望：应用侧模型测试通过。

## 任务 3：新增授权事实模型与迁移

- [ ] 增加 `AccessGrantGroup`。
- [ ] 扩展 `AccessGrantPermission.scope_key` 与 `source_note`。
- [ ] 将旧 `AccessGrantRole` 数据迁移为 `AccessGrantGroup`。
- [ ] 将旧 direct permission grant 迁移为 `scope_key="GLOBAL"`。
- [ ] 保留 `AccessGrant.version/status/grant_expires_at/is_current`。
- [ ] 评估是否新增 `revoked_at/expired_at/last_changed_by/last_change_reason`；若本阶段加入，必须同步更新 lifecycle 测试。

运行：

```bash
python manage.py makemigrations grants
python manage.py migrate --check
pytest tests/unit/grants/test_models.py -q
```

期望：授权事实模型测试通过。

## 任务 4：新增申请目标模型与迁移

- [ ] 增加或改造 `AccessRequestGroup`。
- [ ] 扩展 `AccessRequestPermission.scope_key`。
- [ ] 将旧 `AccessRequestRole` 数据迁移为 `AccessRequestGroup`。
- [ ] 将旧 request direct permission target 迁移为 `scope_key="GLOBAL"`。

运行：

```bash
python manage.py makemigrations access_requests
python manage.py migrate --check
pytest tests/unit/access_requests/test_models.py -q
```

期望：申请模型测试通过。

## 任务 5：建立目录版本提升服务

- [ ] 新增应用侧服务函数，建议命名为 `bump_catalog_version(app, *, actor_id, reason, metadata)`。
- [ ] 该函数使用数据库原子更新提升 `App.catalog_version`。
- [ ] 写审计事件，建议事件名为 `app_catalog_version_bumped`。
- [ ] 不允许调用方直接手写 `app.catalog_version += 1`。
- [ ] 在模型写 API、manifest 确认导入和授权组 grant 写 API 中统一调用；具体调用点见后续分卷。

测试：

- [ ] 增加服务单测，验证版本从 `1` 到 `2`。
- [ ] 验证审计 metadata 包含 `reason`。

运行：

```bash
pytest tests/unit/applications -q
```

## 任务 6：清理旧主语义

- [ ] 搜索 `Role`、`RolePermission`、`AccessGrantRole`、`role_permissions`、`grant_roles`。
- [ ] 把新主路径切到 `AuthorizationGroup`、`AuthorizationGroupGrant`、`AccessGrantGroup`。
- [ ] 如果迁移期间暂留旧类，必须在注释和文档中标明“仅迁移期使用”，不得被新 API 调用。
- [ ] 不新增长期 `roles` API 的新能力；新能力只进 `authorization_groups` 口径。

搜索命令：

```bash
rg -n "Role|RolePermission|AccessGrantRole|role_permissions|grant_roles" src tests
```

## 验证命令

```bash
python manage.py check
python manage.py makemigrations --check
python manage.py migrate --check
pytest tests/unit/applications/test_models.py tests/unit/grants/test_models.py tests/unit/access_requests/test_models.py -q
```

## 完成判定

- 新模型能表达 role、bundle、permission、scope 和 direct grant。
- 同一 permission 可在同一授权组下以不同 scope 授予。
- `AccessGrant` 可保存 group grant 与 scoped direct grant。
- 旧 `PermissionGroup` 仍只表示目录分组。
- 所有模型约束测试通过。
