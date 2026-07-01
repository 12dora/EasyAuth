# React 控制台与门户执行计划

> **给执行代理：** 本文依赖后端契约稳定。前端改造必须先更新类型，再改页面；不要让 `RoleItem` 与 `AuthorizationGroupItem` 长期并存为两个产品口径。

**目标：** 控制台支持创建和编辑 App、管理成员、scope、权限目录、授权组、manifest、审批规则和 grants 联调；门户支持按授权组和 scoped direct grant 申请，并展示 expanded grants。

**架构：** `frontend/src/lib/domain.ts` 是前端契约事实入口。页面组件只消费后端新契约，不在前端推导旧角色-权限展开。

**技术栈：** React、TypeScript、Vite、Vitest、Testing Library、Playwright。

---

## 当前事实

- `ConsoleAppList` 只读展示 `GET /console/api/v1/apps`，没有“新建应用”入口。
- `ConsoleAppWorkspace` 的 tab 只有 `overview/catalog/matrix/rules/credentials/test/guide`。
- `CatalogTab` 只读展示 permission tree、roles、permissions。
- `MatrixTab` 是 `Role x Permission` 复选框矩阵，无法表达 scope 或 bundle。
- `RulesTab` 只读展示审批规则。
- `QueryTestTab` 直接显示原始 JSON，前端类型仍是 `roles/permissions/version/expires_at`。
- `PortalPage` 申请 payload 是 `role_keys + permission_keys`。
- `GrantTable` 展示 `roles/permissions/version/grant_type/grant_expires_at`。
- `domain.ts` 没有 `AppScopeItem`、`AuthorizationGroupItem`、`AuthorizationGroupGrantItem`、`ExpandedGrantItem`、App 创建/编辑 payload 类型。

## 目标页面与交互

- `/console`：显示“新建应用”入口，管理员可见，普通用户不可提交创建。
- `/console/apps/new` 或创建弹窗：填写 `app_key/name/description/owner_user_ids/developer_user_ids/is_active`，成功跳转 `/console/apps/{app_key}`。
- `/console/apps/{app_key}` 总览：显示配置状态、编辑基本信息、成员管理入口。
- catalog：可管理 permission groups、permissions、supported scopes、risk level。
- authorization groups：创建 role 或 bundle，维护 `permission + scope` grants，展示展开预览。
- rules：为 authorization group 或 scoped direct permission 配审批规则。
- manifest：粘贴或上传 manifest、预览差异、确认导入、查看版本、导出。
- test：结构化展示公共查询最终 `groups/grants/grant_version/catalog_version/snapshot_version/expires_at`。
- `/portal`：展示 expanded grants 与来源。
- `/portal/request`：按 authorization group 与 direct scoped permission 申请。

## 触达文件

- 修改：`frontend/src/lib/domain.ts`
- 修改：`frontend/src/lib/api.ts`
- 修改：`frontend/src/pages/console/ConsoleAppList.tsx`
- 修改：`frontend/src/pages/console/ConsoleAppWorkspace.tsx`
- 新增：`frontend/src/pages/console/ConsoleAppList.test.tsx`
- 修改：`frontend/src/pages/console/ConsoleAppWorkspace.test.tsx`
- 修改：`frontend/src/pages/console/workspace/tabs/OverviewTab.tsx`
- 修改：`frontend/src/pages/console/workspace/tabs/CatalogTab.tsx`
- 修改或替换：`frontend/src/pages/console/workspace/tabs/MatrixTab.tsx`
- 修改：`frontend/src/pages/console/workspace/tabs/RulesTab.tsx`
- 修改：`frontend/src/pages/console/workspace/tabs/QueryTestTab.tsx`
- 新增：manifest 相关 tab 或组件
- 修改：`frontend/src/pages/portal/PortalPage.tsx`
- 修改：`frontend/src/pages/portal/hooks/useAccessRequestForm.ts`
- 修改：`frontend/src/pages/portal/components/AccessRequestForm.tsx`
- 修改：`frontend/src/pages/portal/components/RequestTargetPicker.tsx`
- 修改：`frontend/src/pages/portal/components/PermissionSelector.tsx`
- 修改：`frontend/src/pages/portal/components/GrantTable.tsx`
- 修改：`frontend/e2e/smoke.spec.ts`

## 任务 1：更新前端类型

- [ ] 在 `domain.ts` 新增 `AppCreatePayload`、`AppUpdatePayload`。
- [ ] 新增 `AppMembershipItem`，包含 `id/user_id/role/is_active`。
- [ ] 新增 `AppScopeItem`，包含 `key/name/description/is_active/display_order`。
- [ ] 新增 `AuthorizationGroupItem`，包含 `key/kind/name/description/requestable/is_active/grants`。
- [ ] 新增 `AuthorizationGroupGrantItem`，包含 `permission/scope/is_active`。
- [ ] 扩展 `PermissionItem`：`supported_scopes/risk_level/deprecated_at`。
- [ ] 新增 `ExpandedGrantItem`：`permission/scope/source_type/source_key`。
- [ ] 新增公共查询结果类型：`groups/grants/grant_version/catalog_version/snapshot_version/expires_at`。
- [ ] 门户 catalog 类型从 `roles` 迁到 `authorization_groups`。
- [ ] 删除新代码对 `RoleItem` 的依赖；若短期保留，必须只用于迁移兼容测试。

运行：

```bash
cd frontend && pnpm vitest frontend/src/lib/api.test.ts frontend/src/lib/status.test.ts
```

## 任务 2：实现 App 创建与编辑 UI

- [ ] 给 `ConsoleAppList` 增加管理员可见的“新建应用”按钮。
- [ ] 新增创建页面或弹窗组件。
- [ ] 表单字段：`app_key`、`name`、`description`、`owner_user_ids`、`developer_user_ids`、`is_active`。
- [ ] 提交 `POST /console/api/v1/apps`。
- [ ] 成功后跳转 `/console/apps/{app_key}`。
- [ ] 在 `OverviewTab` 增加“编辑基本信息”入口。
- [ ] 编辑表单提交 `PATCH /console/api/v1/apps/{app_key}`。
- [ ] 成员管理复用现有 memberships API，至少支持查看、新增、停用 owner/developer。

测试：

- [ ] 新增 `ConsoleAppList.test.tsx` 覆盖管理员看到新建入口。
- [ ] 覆盖非管理员不可见或提交后被拒绝。
- [ ] 扩展 `ConsoleAppWorkspace.test.tsx` 覆盖编辑基本信息。
- [ ] 覆盖创建成功跳转。

运行：

```bash
cd frontend && pnpm vitest frontend/src/pages/console/ConsoleAppList.test.tsx frontend/src/pages/console/ConsoleAppWorkspace.test.tsx
```

## 任务 3：改造 catalog、scope 与 authorization groups

- [ ] `CatalogTab` 显示并编辑 permission groups。
- [ ] `CatalogTab` 显示并编辑 permissions 的 `supported_scopes` 与 `risk_level`。
- [ ] 新增 scope 字典管理区，支持创建、编辑、停用。
- [ ] 将 `MatrixTab` 替换为授权组管理，或新增 `AuthorizationGroupsTab` 并移除旧矩阵主入口。
- [ ] 授权组表单支持 `kind=role|bundle`、`requestable`、`is_active`。
- [ ] grant 编辑器使用 permission selector 和 scope selector 维护 `permission + scope`。
- [ ] 展示授权组展开后的 grants 预览。

测试：

- [ ] 扩展 `ConsoleAppWorkspace.test.tsx` 覆盖 scope 列表和授权组列表渲染。
- [ ] 新增 grant 草稿工具测试，替代旧 `useMatrixDraft` 的角色-权限二维逻辑。
- [ ] 覆盖保存 payload 包含 `permission + scope`。

运行：

```bash
cd frontend && pnpm vitest frontend/src/pages/console/ConsoleAppWorkspace.test.tsx
```

## 任务 4：改造 rules、manifest 与联调页

- [ ] `RulesTab` 支持新建、编辑、启停审批规则。
- [ ] 审批规则目标支持 `authorization_group` 和 scoped direct permission。
- [ ] 高风险 permission 缺少审批规则时显示 blocking 状态。
- [ ] 新增 manifest tab：粘贴、上传、预览差异、确认导入、版本历史、导出。
- [ ] `QueryTestTab` 结构化展示 groups 和 grants 表格。
- [ ] 保留调试 JSON，但它不能替代结构化展示。

测试：

- [ ] 覆盖 manifest 预览成功后显示差异。
- [ ] 覆盖确认导入后刷新 `catalog_version`。
- [ ] 覆盖联调结果展示 source 和 snapshot version。

运行：

```bash
cd frontend && pnpm vitest frontend/src/pages/console/ConsoleAppWorkspace.test.tsx
```

## 任务 5：改造门户

- [ ] `useAccessRequestForm` payload 从 `role_keys/permission_keys` 改为 `authorization_group_keys/direct_grants`。
- [ ] `RequestTargetPicker` 文案从“角色”改为“可申请权限组”，并展示 `kind=role|bundle`。
- [ ] direct permission 选择必须选择 scope；若 permission 只有一个 supported scope，可默认选中但仍显示。
- [ ] `GrantTable` 展示 expanded grants、source、grant_version、catalog_version、snapshot_version。
- [ ] `/portal/requests` 的申请详情展示新目标结构。

测试：

- [ ] 扩展 `PortalPage.test.tsx` 覆盖 authorization group 申请。
- [ ] 覆盖 direct scoped grant 申请。
- [ ] 覆盖我的权限展示 groups/grants/source。
- [ ] 扩展 `permissionTree.test.ts`，确认 `PermissionGroup` 仍只做目录展示。

运行：

```bash
cd frontend && pnpm vitest frontend/src/pages/portal/PortalPage.test.tsx frontend/src/pages/portal/permissionTree.test.ts
```

## 任务 6：E2E 与响应式验证

- [ ] 扩展 `frontend/e2e/smoke.spec.ts`。
- [ ] 覆盖 `/console` 新建入口。
- [ ] 覆盖 `/console/apps/{app_key}` 编辑基本信息。
- [ ] 覆盖 manifest tab 可进入。
- [ ] 覆盖 query test tab 显示 grants。
- [ ] 覆盖 `/portal/request` 新申请流程。
- [ ] 桌面和移动端都要验证文本不溢出、不遮挡。

运行：

```bash
cd frontend && pnpm playwright test frontend/e2e/smoke.spec.ts
```

## 真实浏览器验证

涉及 React build 产物或 Vite manifest 后，必须重启 Django 开发服务，并用浏览器验证：

- `/console`
- `/console/apps/new` 或创建弹窗
- `/console/apps/{app_key}/`
- `/console/apps/{app_key}?tab=catalog`
- `/console/apps/{app_key}?tab=matrix` 或新的授权组页
- `/console/apps/{app_key}?tab=rules`
- `/console/apps/{app_key}?tab=test`
- `/portal`
- `/portal/request`
- `/portal/requests`

验证重点：

- 表单错误不会被吞掉。
- 移动端长 `permission` key 和 `scope` key 不撑破按钮或表格。
- 创建 App 后跳转正确。
- 联调页结构化 grants 与原始 JSON 一致。
- 门户申请提交 payload 与后端新契约一致。

## 完成判定

- 前端主类型已切到 `AuthorizationGroup`、scope 和 expanded grants。
- 管理员能从空系统创建 App 并进入工作区。
- 工作区能完成基本信息、成员、目录、scope、授权组、manifest、审批规则和联调操作。
- 门户能按新授权模型申请和查看授权。
- Vitest、Playwright 和真实浏览器验证通过。
