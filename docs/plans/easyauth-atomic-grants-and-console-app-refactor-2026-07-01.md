# EasyAuth 原子授权与控制台 App 创建改造设计

> 日期: 2026-07-01
> 范围: 本文件只描述 EasyAuth 侧改造。下游系统只作为 EasyAuth 授权事实的消费者出现,不描述下游实现方案。

---

## 1. 设计结论

EasyAuth 应改造成统一的应用授权运营中心:

```text
App 生命周期管理 + 原子权限目录 + 可授权权限组 + 已展开 grants 查询
```

核心原则:

1. 下游应用只消费 EasyAuth 返回的原子 `grants`。
2. 角色组、权限包、直接授权、审批和撤权全部由 EasyAuth 承担。
3. `PermissionGroup` 只作为权限目录分组,不作为授权对象。
4. 角色是可授权权限组的一种,不再作为独立于权限组的第二套模型。
5. 管理员必须能从 EasyAuth 前端控制台完整创建 App,不能依赖配置文件、seed、shell 或 Django Admin 才能新增业务 App。

---

## 2. 当前代码事实

### 2.1 App 管理现状

当前 `App` 主模型位于 `src/easyauth/applications/models.py`,字段包括 `app_key`、`name`、`description`、`is_active`、`created_at`、`updated_at`。

控制台已有 App 列表和详情读取:

```http
GET /console/api/v1/apps
GET /console/api/v1/apps/{app_key}
```

但控制台缺少:

1. `POST /console/api/v1/apps`。
2. `PATCH /console/api/v1/apps/{app_key}`。
3. 前端“创建应用”按钮。
4. 前端创建应用页面或弹窗。
5. 前端编辑 App 基本信息入口。
6. 创建 App 后初始化 owner 成员关系的闭环。

因此当前无法完全通过管理员 Web 页面添加 App。

### 2.2 权限模型现状

当前模型包括:

1. `Role`: 可申请角色。
2. `Permission`: 原子权限。
3. `PermissionGroup`: 权限目录分组。
4. `RolePermission`: 角色到权限的映射。
5. `ApprovalRule`: 角色或权限的审批规则。
6. `AccessGrant`: 用户在 App 下的授权事实。
7. `AccessGrantRole`: grant 绑定角色。
8. `AccessGrantPermission`: grant 绑定直接权限。

当前公共查询:

```http
GET /api/v1/apps/{app_key}/users/{user_id}/permissions
```

返回字段只有:

```json
{
  "user_id": "u_001",
  "app_key": "easytrade",
  "roles": ["sales"],
  "permissions": ["customer.profile.view"],
  "version": 1,
  "expires_at": "2026-07-01T12:00:00+08:00"
}
```

它不返回:

1. 已展开 `grants` 明细。
2. `scope`。
3. 授权来源 `source`。
4. 可授权组列表。
5. 权限包来源链路。
6. 权限目录版本。

### 2.3 权限模板现状

现有权限模板导入只描述 `PermissionGroup` 和 `Permission` 树:

```text
version
groups
group/permission node
```

它不是完整下游 App manifest,不能描述:

1. App 基本信息。
2. 下游可用 scope。
3. 可授权角色组。
4. 权限包。
5. 角色组到原子权限的 `permission + scope` 映射。
6. 审批规则。
7. 公共查询契约版本。
8. manifest export。

---

## 3. 目标领域模型

### 3.1 App

`App` 仍是应用隔离边界。所有权限、目录、授权组、凭据、审批规则和授权事实都必须归属于单个 App。

需要补齐:

1. 控制台创建。
2. 控制台编辑。
3. owner/developer 管理。
4. 前端创建后进入 App 工作区。
5. 配置完整性检查。

### 3.2 Permission

`Permission` 是唯一运行时授权原子。

建议扩展字段或关联:

1. `supported_scopes`: 当前权限支持的 scope key 列表。
2. `risk_level`: 风险级别。
3. `group`: 继续指向目录分组。

下游接口不得按角色组鉴权,只能按原子 permission 鉴权。

### 3.3 PermissionGroup

`PermissionGroup` 继续表示权限目录分组,用于:

1. 管理控制台目录树。
2. 员工门户申请页展示。
3. manifest 归类。
4. 下游文档和审计归类。

`PermissionGroup` 不可直接授予用户。若需要“一组权限可被授予”,必须使用可授权权限组。

### 3.4 AuthorizationGroup

新增一等“可授权权限组”语义,用于承载角色组和权限包。

推荐模型名:

```text
AuthorizationGroup
```

核心字段:

```text
app
key
kind: role | bundle
name
description
requestable
is_active
created_at
updated_at
```

语义:

1. `kind=role`: 岗位或职责型预置权限组,例如 `sales`、`sales_manager`。
2. `kind=bundle`: 场景型权限包,例如 `temporary_export`、`audit_readonly`。

现有 `Role` 应收敛为 `AuthorizationGroup(kind=role)`。项目尚未投产,最终产品和 API 口径不应长期保留 `Role` 与 `AuthorizationGroup` 两套并行模型。

### 3.5 AuthorizationGroupGrant

新增授权组到原子权限的映射:

```text
authorization_group
permission
scope_key
is_active
created_at
updated_at
```

`scope_key` 是 App 内定义的普通字符串,由下游解释具体业务含义。EasyAuth 只负责存储、校验和返回,不解释资源 owner 范围。

同一个授权组可以包含同一 permission 的不同 scope,但需要同一 App 内唯一约束:

```text
authorization_group + permission + scope_key
```

### 3.6 AppScope

新增 App 内 scope 字典:

```text
app
key
name
description
is_active
display_order
```

示例:

```text
SELF
MANAGED
ALL
```

EasyAuth 只知道这些 scope key 可被授予;下游系统负责解释它们在业务资源上的含义。

---

## 4. 授权事实模型

### 4.1 AccessGrant 保留

`AccessGrant` 继续表示用户在某个 App 下的当前授权版本。

需要补齐:

1. grant version。
2. grant expires at。
3. current/revoked/expired 状态。
4. 审计元数据。

### 4.2 AccessGrantGroup

新增用户被授予的可授权权限组:

```text
grant
authorization_group
created_at
```

它替代长期语义上的 `AccessGrantRole`。

### 4.3 AccessGrantPermission

直接授权仍然保留,但需要支持 scope:

```text
grant
permission
scope_key
source_note
created_at
```

直接授权用于少量例外或临时授权。常规岗位能力应通过 `AuthorizationGroup` 授予。

### 4.4 动态展开规则

EasyAuth 查询授权时按当前有效配置动态展开:

```text
AccessGrantGroup
  -> AuthorizationGroupGrant
  -> Permission + scope

AccessGrantPermission
  -> Permission + scope
```

禁用的 App、用户、授权组、权限、scope 或已废弃权限不得出现在最终 grants 中。

授权组内容变化会影响所有持有该组的用户。因此授权组变更必须:

1. 写审计日志。
2. 提升 App 授权目录版本。
3. 在联调页显示变化后的最终 grants。
4. 触发下游缓存失效依据变化。

---

## 5. 公共查询契约

### 5.1 主响应改为 grants

公共权限查询应返回已展开原子 grants:

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

字段语义:

1. `groups`: 用户当前被授予的可授权组,仅用于展示、审计和排查。
2. `grants`: 下游真正消费的授权事实。
3. `permission`: 原子权限 key。
4. `scope`: App 内 scope key。若某 App 不使用 scope,返回空字符串或约定的 `GLOBAL`。
5. `source_type`: `group` 或 `direct`。
6. `source_key`: 来源授权组 key;直接授权为空字符串。
7. `grant_version`: 用户授权事实版本。
8. `catalog_version`: App 授权目录版本。
9. `snapshot_version`: 下游缓存用版本,由 `grant_version` 与 `catalog_version` 组成。

### 5.2 版本策略

新增 App 级授权目录版本。以下行为必须提升 `catalog_version`:

1. 权限新增、停用、废弃或 scope 变更。
2. 授权组新增、停用或重命名。
3. 授权组 grant 变更。
4. scope 字典变更。
5. manifest 导入确认。

以下行为提升 `grant_version`:

1. 用户新增授权组。
2. 用户移除授权组。
3. 用户新增直接权限。
4. 用户移除直接权限。
5. 授权续期、撤权、过期状态变更。

下游缓存必须以 `snapshot_version` 和 `expires_at` 为准。

### 5.3 旧字段处理

项目尚未投产,主契约应一次性切到 `grants`。如果实施期间需要短迁移窗口,可以临时保留:

```json
"permissions": ["customer.profile.view"],
"roles": ["sales"]
```

但文档和新下游接入不得再把这两个字段作为主契约。迁移窗口结束后应删除或降级为调试字段。

---

## 6. App Manifest 契约

EasyAuth 需要提供统一下游接入 manifest。manifest 由 EasyAuth 导入、校验、版本化和导出。

建议格式:

```json
{
  "schema_version": 1,
  "app": {
    "app_key": "easytrade",
    "name": "EasyTrade",
    "description": "外贸业务系统"
  },
  "scopes": [
    {
      "key": "SELF",
      "name": "本人"
    },
    {
      "key": "MANAGED",
      "name": "管理范围"
    },
    {
      "key": "ALL",
      "name": "全部"
    }
  ],
  "permission_groups": [
    {
      "key": "crm.customer",
      "name": "客户管理",
      "parent_key": "",
      "display_order": 10
    }
  ],
  "permissions": [
    {
      "key": "customer.profile.view",
      "name": "查看客户资料",
      "group_key": "crm.customer",
      "supported_scopes": ["SELF", "MANAGED", "ALL"],
      "risk_level": "standard"
    }
  ],
  "authorization_groups": [
    {
      "key": "sales",
      "kind": "role",
      "name": "销售",
      "requestable": true,
      "grants": [
        {
          "permission": "customer.profile.view",
          "scope": "SELF"
        }
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

manifest 导入要求:

1. 同一 App 内 key 唯一。
2. permission 必须归属有效目录分组。
3. authorization group grant 必须引用有效 permission 和 scope。
4. approval rule 目标必须属于同一 App。
5. 预览不写库。
6. 确认导入必须写 `ManifestVersion` 或扩展现有 `PermissionTemplateVersion`。
7. 导入确认必须提升 `catalog_version`。
8. 必须支持 export,保证前端可下载当前 App 完整 manifest。

---

## 7. 管理员 Web 创建 App

### 7.1 后端 API

新增:

```http
POST /console/api/v1/apps
PATCH /console/api/v1/apps/{app_key}
```

`POST /console/api/v1/apps` 请求:

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

创建规则:

1. 只有系统管理员可以创建 App。
2. `app_key` 必须全局唯一,只允许稳定 key 字符集。
3. 创建 App 和初始 `AppMembership` 必须在同一事务。
4. `owner_user_ids` 不能为空。若前端未填写,后端使用当前 actor 作为 owner。
5. 创建后返回完整 App detail。
6. 写审计事件 `console_app_created`。

`PATCH /console/api/v1/apps/{app_key}` 支持:

1. `name`。
2. `description`。
3. `is_active`。

编辑规则:

1. 系统管理员可以编辑所有字段。
2. App owner 可以编辑 `name` 和 `description`。
3. 只有系统管理员可以修改 `is_active`。
4. 不允许通过普通编辑修改 `app_key`;如确需改 key,应设计单独重命名流程并校验所有外部契约影响。
5. 写审计事件 `console_app_updated`。

### 7.2 前端流程

控制台必须支持从空系统完成 App 创建:

1. `/console` 应用列表增加“新建应用”按钮。
2. 新增 `/console/apps/new` 页面或创建弹窗。
3. 表单字段包含 `app_key`、`name`、`description`、`owner_user_ids`、`developer_user_ids`、`is_active`。
4. 创建成功后跳转 `/console/apps/{app_key}`。
5. App 工作区总览页增加“编辑基本信息”入口。
6. 成员关系管理应在前端可见,至少能新增和停用 owner/developer。
7. 配置完整性面板引导继续完成 manifest 导入、凭据创建和联调。

该流程必须保证管理员不需要访问 Django Admin、shell、seed 或配置文件即可创建并配置业务 App。

---

## 8. 管理控制台改造

### 8.1 Catalog 页

`CatalogTab` 从只读改为可编辑:

1. 创建和编辑权限目录分组。
2. 创建和编辑原子权限。
3. 设置 permission 的 `supported_scopes` 和 `risk_level`。
4. 停用或废弃权限。

### 8.2 授权组页

新增或扩展页面管理 `AuthorizationGroup`:

1. 创建 role 或 bundle。
2. 编辑名称、说明、是否可申请、是否启用。
3. 维护 group 内的 `permission + scope` grants。
4. 显示该 group 展开后的最终原子 grants。

### 8.3 审批规则页

`RulesTab` 从只读改为可编辑:

1. 为 authorization group 配置审批规则。
2. 为直接 permission grant 配置审批规则。
3. 启停审批规则。
4. 高风险权限缺少审批规则时显示 blocking。

### 8.4 Manifest 页

新增 manifest 能力:

1. 粘贴或上传 manifest。
2. 预览差异。
3. 确认导入。
4. 查看版本历史。
5. 导出当前 manifest。

### 8.5 联调页

联调页应展示最终下游会收到的响应:

1. groups。
2. grants。
3. source_type/source_key。
4. grant_version。
5. catalog_version。
6. snapshot_version。
7. expires_at。

---

## 9. 配置完整性检查

App readiness 应新增检查项:

1. App 至少有一个 active credential。
2. App 至少有一个 active permission。
3. App 至少有一个 active authorization group。
4. requestable authorization group 必须有 active approval rule。
5. authorization group grant 引用的 permission 和 scope 必须 active。
6. permission 的 supported scopes 不得为空。
7. active permission 必须归属 active directory group。
8. App 至少有一个 active owner。

这些检查用于控制台引导,不应在查询接口里静默兜底。

---

## 10. 权限与安全边界

控制台写入权限:

1. 创建 App: 系统管理员。
2. 编辑 App 基本信息: 系统管理员或 App owner。
3. 启停 App: 系统管理员。
4. 管理 owner/developer: 系统管理员。
5. 管理凭据: App owner。
6. 管理权限目录、授权组、审批规则、manifest: App owner。
7. 只读查看: 系统管理员、App owner、App developer。

敏感数据规则:

1. 静态 token 明文只返回一次。
2. OAuth client secret 只返回一次。
3. 审计日志不得记录明文 token 或 secret。
4. App 禁用后公共查询必须安全失败。
5. credential 禁用后公共查询必须安全失败。

---

## 11. 测试要求

### 11.1 后端测试

必须覆盖:

1. 系统管理员通过 `POST /console/api/v1/apps` 创建 App。
2. 创建 App 同时写入 owner membership。
3. 非系统管理员不能创建 App。
4. App owner 能编辑 name/description,不能启停 App。
5. 系统管理员能启停 App。
6. manifest preview 不写库。
7. manifest confirm 写入 scopes、permission groups、permissions、authorization groups、approval rules。
8. manifest confirm 提升 catalog version。
9. 公共查询返回 `grants`、source 和版本字段。
10. 禁用权限、scope、authorization group 后不再出现在 grants 中。
11. role/bundle 与 direct grants 混合时去重正确。

### 11.2 前端测试

必须覆盖:

1. `/console` 能看到“新建应用”入口。
2. 管理员能通过前端创建 App 并跳转工作区。
3. 非管理员看不到或无法提交创建 App。
4. 工作区能编辑 App 基本信息。
5. Manifest 导入预览和确认流程可达。
6. 联调页能展示最终 `grants`。

### 11.3 契约测试

必须固定:

1. 公共查询响应字段。
2. manifest schema。
3. App 创建 API payload 和错误码。
4. credential 一次性 secret 返回规则。
5. readiness blocking 项。

---

## 12. 实施顺序

建议按以下顺序实施:

1. 补齐 App 创建和编辑 API。
2. 补齐前端创建 App 流程。
3. 新增 App scope 和 App 授权目录版本。
4. 将 `Role` 语义迁移为 `AuthorizationGroup(kind=role)`。
5. 新增 `AuthorizationGroupGrant` 和带 scope 的 direct grant。
6. 改造 grant 展开服务,输出 `grants`。
7. 改造公共查询响应和联调页。
8. 扩展 manifest import/export。
9. 补齐控制台目录、授权组和审批规则写操作。
10. 删除或降级旧 `roles/permissions` 扁平响应口径。

每一步都必须带测试。涉及 Django 后端、Django 模板、React build 产物或 Vite manifest 的实施变更完成后,必须重启当前 Django 开发服务并用真实 HTTP 响应或浏览器页面验证新代码已加载。

---

## 13. 非目标

本设计不要求 EasyAuth 解释下游业务资源范围。

EasyAuth 不负责:

1. 判断某个客户、订单或单据属于谁。
2. 解释 `SELF / MANAGED / ALL` 的业务含义。
3. 代理下游 API 鉴权。
4. 在下游前端隐藏按钮。

EasyAuth 只负责返回可信、可审计、可版本化的授权事实。

