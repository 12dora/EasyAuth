# Manifest、目录版本与 Readiness 执行计划

> **给执行代理：** 本文依赖领域模型分卷完成。现有 permission template 是历史实现，不得继续作为完整 App 接入契约。

**目标：** 将权限模板升级为完整 App manifest，支持预览、确认导入、版本历史和导出；所有目录配置变更提升 `catalog_version`；readiness 使用新授权模型检查配置完整性。

**架构：** manifest 是 EasyAuth 与下游 App 接入的配置事实入口，包含 App 基本信息、scope、目录分组、原子权限、授权组、授权组 grants 和审批规则。数据库当前状态可以导出为 manifest，导入确认必须提升 `catalog_version`。

**技术栈：** Pydantic schema、Django 服务、签名预览缓存、pytest 集成测试。

---

## 当前事实

- `permission_template_parsing.py` 只解析 `version/groups`。
- `permission_template_storage.py` 只 upsert `PermissionGroup/Permission`，模板缺失 permission 会 deprecated。
- `PermissionTemplateVersion` 保存导入原文和 import summary，但不能代表当前 App 完整配置。
- 控制台模板 API 只有预览、确认导入和版本列表，没有导出。
- `configuration.py` readiness 只检查 active role、active credential、requestable role 审批规则和 role permission。
- `seed_crm_pilot.py` 直接创建 `Role/Permission/RolePermission/ApprovalRule`，不是 manifest 驱动。

## Manifest 契约

请求示例：

```json
{
  "schema_version": 1,
  "app": {
    "app_key": "easytrade",
    "name": "EasyTrade",
    "description": "外贸业务系统"
  },
  "scopes": [
    {"key": "SELF", "name": "本人", "description": "", "is_active": true, "display_order": 10},
    {"key": "MANAGED", "name": "管理范围", "description": "", "is_active": true, "display_order": 20},
    {"key": "ALL", "name": "全部", "description": "", "is_active": true, "display_order": 30}
  ],
  "permission_groups": [
    {"key": "crm.customer", "name": "客户管理", "parent_key": "", "display_order": 10, "is_active": true}
  ],
  "permissions": [
    {
      "key": "customer.profile.view",
      "name": "查看客户资料",
      "description": "",
      "group_key": "crm.customer",
      "supported_scopes": ["SELF", "MANAGED", "ALL"],
      "risk_level": "standard",
      "is_active": true
    }
  ],
  "authorization_groups": [
    {
      "key": "sales",
      "kind": "role",
      "name": "销售",
      "description": "",
      "requestable": true,
      "is_active": true,
      "grants": [
        {"permission": "customer.profile.view", "scope": "SELF"}
      ]
    }
  ],
  "approval_rules": [
    {
      "target_type": "authorization_group",
      "target_key": "sales",
      "approver_userids": ["manager_001"],
      "is_active": true
    }
  ]
}
```

校验规则：

- manifest `app.app_key` 必须等于路径 App。
- 同一 App 内 scope、permission group、permission、authorization group key 各自唯一。
- permission 必须归属有效目录分组。
- permission 的 `supported_scopes` 必须全部引用 manifest 中的 scope。
- authorization group grant 必须引用 manifest 内有效 permission 和 scope。
- authorization group grant 的 scope 必须在 permission `supported_scopes` 中。
- approval rule 目标必须属于同一 App。
- 预览不写库。
- 确认导入写库并提升 `catalog_version`。
- 导出从数据库当前状态生成，不读取上次导入原文。

## 触达文件

- 修改或替换：`src/easyauth/applications/permission_template_types.py`
- 修改或替换：`src/easyauth/applications/permission_template_parsing.py`
- 修改或替换：`src/easyauth/applications/permission_template_flattening.py`
- 修改或替换：`src/easyauth/applications/permission_template_storage.py`
- 修改：`src/easyauth/applications/permission_templates.py`
- 修改：`src/easyauth/admin_console/permission_template_api.py`
- 修改：`src/easyauth/admin_console/permission_template_handlers.py`
- 修改：`src/easyauth/admin_console/permission_template_api_data.py`
- 修改：`src/easyauth/admin_console/permission_catalog_data.py`
- 修改：`src/easyauth/applications/configuration.py`
- 修改：`src/easyauth/applications/management/commands/seed_crm_pilot.py`
- 修改：相关 tests 和 docs

## 任务 1：定义 manifest schema 测试

- [ ] 在 `tests/unit/applications/test_permission_templates_ops1.py` 改写 schema 测试。
- [ ] 覆盖合法 manifest 解析。
- [ ] 覆盖重复 scope key 拒绝。
- [ ] 覆盖 permission 引用未知 group 拒绝。
- [ ] 覆盖 permission supported scope 引用未知 scope 拒绝。
- [ ] 覆盖 authorization group grant 引用未知 permission 拒绝。
- [ ] 覆盖 grant scope 不在 permission supported scopes 中拒绝。
- [ ] 覆盖 approval rule 引用未知 authorization group 拒绝。

运行：

```bash
pytest tests/unit/applications/test_permission_templates_ops1.py -q
```

期望：新增测试先失败。

## 任务 2：实现 manifest 解析与预览差异

- [ ] 将 `PermissionTemplateInput` 升级或替换为 `AppManifestInput`。
- [ ] 保留 `source` 边界、最大原文长度和 JSON/YAML 解析错误处理。
- [ ] 生成预览差异，至少包含 `create/update/deactivate` 的 scopes、permission groups、permissions、authorization groups、approval rules。
- [ ] 预览返回 `preview_id`，继续使用签名缓存和过期时间。
- [ ] developer 可预览、owner 可确认导入的权限边界保持不变，除非产品另有要求。

运行：

```bash
pytest tests/integration/admin_console/test_template_guide_api_ops1.py -q
```

期望：预览新契约测试通过。

## 任务 3：实现确认导入写库

- [ ] 确认导入在 `transaction.atomic()` 内写入 App 基本信息、scopes、permission groups、permissions、authorization groups、authorization group grants、approval rules。
- [ ] 缺失于 manifest 的 active scope、permission、authorization group 不直接硬删；按业务语义停用或 deprecated，并写入摘要。
- [ ] 写入 `ManifestVersion`；若短期复用 `PermissionTemplateVersion`，必须更新字段说明和命名注释，避免把目录模板当完整 manifest。
- [ ] 确认导入成功调用 `bump_catalog_version()`。
- [ ] 写审计事件 `app_manifest_imported`，metadata 不记录敏感凭据。

运行：

```bash
pytest tests/unit/applications/test_permission_templates_ops1.py tests/integration/admin_console/test_template_guide_api_ops1.py -q
```

## 任务 4：实现 manifest 导出

建议新增路由：

- `GET /console/api/v1/apps/{app_key}/manifest`

规则：

- 系统管理员、App owner、App developer 可读。
- 输出当前数据库状态，不输出历史 raw template。
- 排序稳定：scopes 按 `display_order/key`，groups 按 `display_order/key`，permissions 按 `key`，authorization groups 按 `kind/key`，grants 按 `permission/scope`。
- 不导出 credential token、OAuth secret 或任何一次性明文。

测试：

- [ ] 新增导出集成测试。
- [ ] 确认导出的 manifest 可再次预览且无差异。
- [ ] 确认导出不包含 secret/token。

运行：

```bash
pytest tests/integration/admin_console/test_template_guide_api_ops1.py -q
```

## 任务 5：改造 catalog version

- [ ] 删除把 `permission_catalog_data.py` 的 hash 当目录版本的主语义。
- [ ] 所有 catalog payload 返回 `catalog_version = app.catalog_version`。
- [ ] 以下写操作必须提升版本：
  - scope 创建、编辑、停用。
  - permission group 创建、编辑、停用。
  - permission 创建、编辑、停用、deprecated、supported scopes 变更、risk level 变更。
  - authorization group 创建、编辑、停用。
  - authorization group grant 创建、删除、启停。
  - approval rule 对授权目录有效性产生影响时。
  - manifest 确认导入。
- [ ] 版本提升必须走统一服务，不能分散在 view 中手写。

测试：

- [ ] 扩展 `tests/integration/admin_console/test_permission_matrix_version_ops1.py`。
- [ ] 增加 manifest 确认导入提升版本测试。
- [ ] 增加 scope 或 group grant 变更提升版本测试。

运行：

```bash
pytest tests/integration/admin_console/test_permission_matrix_version_ops1.py tests/integration/admin_console/test_template_guide_api_ops1.py -q
```

## 任务 6：改造 readiness

目标检查项：

- `active_credential_missing`
- `active_permission_missing`
- `active_authorization_group_missing`
- `active_owner_missing`
- `requestable_authorization_group_approval_rule_missing`
- `authorization_group_grant_target_inactive`
- `permission_supported_scopes_missing`
- `permission_group_inactive`

执行：

- [ ] 修改 `src/easyauth/applications/configuration.py`。
- [ ] 修改 `src/easyauth/admin_console/apps_api.py` 中 `CONFIGURATION_ISSUE_TARGET_TYPES`。
- [ ] 更新 `tests/unit/applications/test_configuration_readiness_ops1.py`。
- [ ] 更新 `tests/integration/admin_console/test_apps_api_ops1.py` 中 configuration status 断言。

运行：

```bash
pytest tests/unit/applications/test_configuration_readiness_ops1.py tests/integration/admin_console/test_apps_api_ops1.py -q
```

## 任务 7：改造 seed

- [ ] 将 `src/easyauth/applications/management/commands/seed_crm_pilot.py` 改为导入本地 manifest fixture。
- [ ] fixture 应包含 App、scopes、permission groups、permissions、authorization groups、approval rules。
- [ ] seed 创建初始 owner/developer 和凭据。
- [ ] 样例 grant 使用 `AuthorizationGroup` 与 scoped direct grant。
- [ ] 更新 `tests/integration/admin/test_seed_crm_pilot.py`。

运行：

```bash
pytest tests/integration/admin/test_seed_crm_pilot.py -q
```

## 文档更新

- [ ] 更新 `docs/api/easyauth-authorization-operations-api-design.md`。
- [ ] 更新 `docs/architecture/easyauth-authorization-operations-design.md`。
- [ ] 更新 `docs/requirements/easyauth-business-authorization-operations.md`。
- [ ] 删除或降级“权限模板只描述 group/permission 树”和“公共响应不变”的旧表述。

## 真实 HTTP 验证

本分卷修改控制台 API、模板接口和 Django 后端，完成后必须重启 Django 开发服务。

验证：

```bash
curl -i http://127.0.0.1:8000/console/api/v1/apps/{app_key}/configuration-status
curl -i http://127.0.0.1:8000/console/api/v1/apps/{app_key}/manifest
```

浏览器验证：

- `/console/apps/{app_key}?tab=catalog`
- `/console/apps/{app_key}?tab=rules`
- `/console/apps/{app_key}?tab=guide`

## 完成判定

- manifest 可预览、确认导入、查看版本列表和导出。
- 确认导入写入 scopes、permission groups、permissions、authorization groups、approval rules。
- 导出结果可作为下一次导入输入。
- readiness 使用新模型并能指出 blocking 项。
- `catalog_version` 是 App 级持久版本，公共查询和控制台一致使用它。
