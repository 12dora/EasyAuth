# 公共查询、门户与申请执行计划

> **给执行代理：** 本文依赖领域模型分卷完成。不要在旧 `RolePermission` 展开逻辑上继续叠加功能；授权查询、门户和申请必须共享新的 scoped grant 语义。

**目标：** 公共查询返回下游可直接消费的 expanded grants；门户和 access request 使用 `AuthorizationGroup` 与 scoped direct grant；续期、撤权和变更比较使用 group 集合与 scoped grant 集合。

**架构：** `grants/query.py` 是授权展开内核。公共 API、控制台联调页和门户“我的权限”都应复用同一个展开结果，避免出现多个版本的权限聚合逻辑。

**技术栈：** Django 查询服务、DRF serializer、pytest 单元与集成测试。

---

## 当前事实

- `GET /api/v1/apps/{app_key}/users/{user_id}/permissions` 当前返回 `roles/permissions/version/expires_at`。
- `resolve_user_permissions()` 从 `AccessGrantRole + RolePermission + AccessGrantPermission` 展开扁平 permission set。
- `portal/api_data.py` 与 `portal/permission_aggregation.py` 也返回 `roles/permissions/version/grant_type/grant_expires_at`。
- `portal/request_catalog.py` 用 `Role(is_active=True, requestable=True)` 作为可申请对象。
- `access_requests/submission_validation.py` 的 change/revoke/renew 校验使用角色集合和扁平有效权限集合。
- `access_requests/application_grants.py` 审批通过后写回 `AccessGrantRole/AccessGrantPermission`。

## 新公共查询契约

响应：

```json
{
  "user_id": "u_001",
  "app_key": "easytrade",
  "groups": [
    {
      "key": "sales",
      "kind": "role",
      "name": "销售"
    }
  ],
  "grants": [
    {
      "permission": "customer.profile.view",
      "scope": "SELF",
      "source_type": "group",
      "source_key": "sales"
    },
    {
      "permission": "customer.profile.export",
      "scope": "SELF",
      "source_type": "direct",
      "source_key": ""
    }
  ],
  "grant_version": 3,
  "catalog_version": 12,
  "snapshot_version": "3.12",
  "expires_at": "2026-07-01T12:00:00+08:00"
}
```

展开规则：

- 当前用户不存在、离职或禁用时，返回空 `groups/grants`，但不暴露用户存在性。
- 当前 grant revoked/expired 时，返回空 `groups/grants`，保留最新 `grant_version`。
- App inactive 时公共查询安全失败，不返回空成功。
- `AccessGrantGroup -> AuthorizationGroupGrant -> Permission + scope` 动态展开。
- `AccessGrantPermission(permission, scope_key)` 作为 direct grant 展开。
- 过滤 inactive authorization group、inactive group grant、inactive permission、deprecated permission、inactive scope。
- 去重基准是 `permission + scope + source_type + source_key`；同一 permission/scope 来自 group 和 direct 时保留两条来源，便于排查。
- `snapshot_version = f"{grant_version}.{catalog_version}"`。

## 触达文件

- 修改：`src/easyauth/grants/query.py`
- 修改：`src/easyauth/api/views.py`
- 修改：`src/easyauth/api/serializers.py`
- 修改：`src/easyauth/admin_console/query_test_api.py`
- 修改：`src/easyauth/portal/permission_aggregation.py`
- 修改：`src/easyauth/portal/api_data.py`
- 修改：`src/easyauth/portal/request_catalog.py`
- 修改：`src/easyauth/portal/access_request_payloads.py`
- 修改：`src/easyauth/access_requests/submission_validation.py`
- 修改：`src/easyauth/access_requests/target_validation.py`
- 修改：`src/easyauth/access_requests/application_grants.py`
- 修改：`src/easyauth/grants/services.py`
- 修改：`src/easyauth/grants/lifecycle.py`
- 修改：`src/easyauth/grants/operations.py`
- 修改：相关测试文件

## 任务 1：重写查询测试

- [ ] 在 `tests/unit/grants/test_query.py` 增加 group grant 展开测试。
- [ ] 增加 direct scoped grant 展开测试。
- [ ] 增加同一 permission 不同 scope 同时返回的测试。
- [ ] 增加 group 与 direct 混合来源测试。
- [ ] 增加 inactive authorization group、inactive permission、deprecated permission、inactive scope 被过滤的测试。
- [ ] 增加 `catalog_version` 与 `snapshot_version` 测试。

运行：

```bash
pytest tests/unit/grants/test_query.py -q
```

期望：新增测试先失败。

## 任务 2：实现 expanded grant 查询内核

- [ ] 将 `PermissionSnapshot` 改为包含 `groups`、`grants`、`grant_version`、`catalog_version`、`snapshot_version`、`grant_expires_at`。
- [ ] 定义 `GroupSnapshot` 数据结构：`key/kind/name`。
- [ ] 定义 `ExpandedGrant` 数据结构：`permission/scope/source_type/source_key`。
- [ ] `resolve_user_permissions()` 使用新模型查询 `AccessGrantGroup` 与 `AccessGrantPermission`。
- [ ] 查询时用 `select_related()` 降低 N+1 风险。
- [ ] 所有排序稳定：groups 按 `key`，grants 按 `permission/scope/source_type/source_key`。
- [ ] 保留现有用户状态和 grant 状态的安全返回语义。

运行：

```bash
pytest tests/unit/grants/test_query.py -q
```

期望：通过。

## 任务 3：切换公共 API 响应

- [ ] 修改 `src/easyauth/api/serializers.py`，固定新版字段。
- [ ] 修改 `src/easyauth/api/views.py` 构造新版 payload。
- [ ] 审计 metadata 从 `role_count/permission_count/version` 改为 `group_count/grant_count/grant_version/catalog_version/snapshot_version`。
- [ ] 更新 `tests/integration/api/test_permission_query.py`。
- [ ] 更新 `tests/integration/api/test_permission_query_ops1.py`。
- [ ] 若确需短迁移字段，测试必须明确它们是兼容字段，不作为主断言。

运行：

```bash
pytest tests/integration/api/test_permission_query.py tests/integration/api/test_permission_query_ops1.py -q
```

期望：新版契约测试通过。

## 任务 4：改造 grant 生命周期

- [ ] 将 `GrantService.create_grant()`、`change_grant()` 的输入从 roles/direct permissions 改为 authorization groups 和 scoped direct grants。
- [ ] `replace_memberships()` 改为重建 `AccessGrantGroup` 与 scoped `AccessGrantPermission`。
- [ ] `revoke_grant()`、`revoke_for_user()`、`expire_grant()` 保持版本与状态语义。
- [ ] 续期、撤权、变更不再比较扁平 permission set。
- [ ] scoped direct grant 的等价比较以 `(permission_id, scope_key)` 为准。

测试文件：

- `tests/unit/grants/test_services.py`
- `tests/unit/grants/test_revoke_for_user_s10.py`
- `tests/unit/grants/test_emergency_revoke_s13.py`
- `tests/unit/grants/test_expiration_cleanup_s13.py`

运行：

```bash
pytest tests/unit/grants -q
```

## 任务 5：改造 access request 提交与审批落库

新提交 payload 建议：

```json
{
  "app_key": "easytrade",
  "request_type": "grant",
  "authorization_group_keys": ["sales"],
  "direct_grants": [
    {
      "permission": "customer.profile.export",
      "scope": "SELF"
    }
  ],
  "grant_type": "timed",
  "grant_expires_at": "2026-07-01T12:00:00+08:00",
  "reason": "临时导出客户资料"
}
```

- [ ] `portal/access_request_payloads.py` 解析 `authorization_group_keys` 与 `direct_grants`。
- [ ] `target_validation.py` 校验 group、permission、scope 都属于同一 App 且 active。
- [ ] `submission_validation.py` 对 grant/change/revoke/renew 使用 group set 与 scoped direct grant set。
- [ ] `application_grants.py` 审批通过后写入新 grant service。
- [ ] 保留 `PermissionGroup` 只做申请目录展示，不作为提交目标。

测试文件：

- `tests/unit/access_requests/test_target_validation.py`
- `tests/unit/access_requests/test_services_ops4.py`
- `tests/unit/access_requests/test_services_ops4_application.py`
- `tests/unit/access_requests/test_services_ops4_application_target_stale.py`
- `tests/unit/access_requests/test_services_ops4_application_lifecycle_target_stale.py`
- `tests/unit/access_requests/test_services_ops4_application_scope.py`

运行：

```bash
pytest tests/unit/access_requests -q
```

## 任务 6：改造门户 API

- [ ] `portal_request_catalog()` 返回 `authorization_groups`，而不是 `roles`。
- [ ] 目录返回 active permission groups 和 direct grant 可选 scope。
- [ ] 目录 payload 增加 `catalog_version`。
- [ ] “我的权限”返回 groups、grants、grant_version、catalog_version、snapshot_version、grant_type、grant_expires_at。
- [ ] `portal/permission_aggregation.py` 只作为新版 expanded grants 的格式适配，不再独立展开旧 role permissions。

测试文件：

- `tests/integration/portal/test_my_permissions_ops2.py`
- `tests/integration/portal/test_request_catalog_api.py`
- `tests/integration/portal/test_portal_api_ops4_permissions.py`
- `tests/integration/portal/test_portal_api_ops2.py`
- `tests/integration/portal/test_portal_api_ops4.py`
- `tests/integration/portal/test_access_request_s14.py`

运行：

```bash
pytest tests/integration/portal -q
```

## 任务 7：改造控制台联调 API

- [ ] `src/easyauth/admin_console/query_test_api.py` 返回真实公共查询新版结构。
- [ ] 联调 audit metadata 使用新版本字段。
- [ ] 旧模板 `_integration_guide.html` 和 React 联调页更新见前端分卷。

运行：

```bash
pytest tests/integration/admin_console/test_query_tester_ops1.py tests/integration/admin_console/test_app_detail_ops1.py -q
```

## 真实 HTTP 验证

本分卷修改公共 API、控制台 API 和门户 API，完成后必须重启 Django 开发服务。

验证：

```bash
curl -i -H "Authorization: Bearer ${EASYAUTH_TEST_APP_TOKEN}" \
  http://127.0.0.1:8000/api/v1/apps/{app_key}/users/{user_id}/permissions

curl -i http://127.0.0.1:8000/portal/api/v1/me/grants
curl -i http://127.0.0.1:8000/portal/api/v1/request-catalog
```

浏览器验证：

- `/portal`
- `/portal/request`
- `/console/apps/{app_key}?tab=test`

## 完成判定

- 公共查询主响应返回 `groups/grants/grant_version/catalog_version/snapshot_version/expires_at`。
- inactive 或 deprecated 对象不会进入 grants。
- change/revoke/renew 不再误把同一 permission 的不同 scope 当成同一授权。
- 门户申请可以提交 authorization group 和 scoped direct grant。
- 控制台联调页拿到的响应与公共 API 一致。
