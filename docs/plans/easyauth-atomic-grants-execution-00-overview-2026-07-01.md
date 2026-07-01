# EasyAuth 原子授权与控制台 App 创建执行总览

> **给执行代理：** 必须先读取 `AGENTS.md` 与 `docs/plans/easyauth-atomic-grants-and-console-app-refactor-2026-07-01.md`。执行本系列文档时使用 `superpowers:subagent-driven-development` 或 `superpowers:executing-plans` 逐项推进；步骤使用 checkbox 语法跟踪。

**目标：** 将 EasyAuth 从 `Role + Permission` 扁平授权模型改造成“App 生命周期管理 + 原子权限目录 + 可授权权限组 + 已展开 grants 查询”的统一授权运营中心。

**架构：** `App` 仍是隔离边界，所有 scope、目录、授权组、审批规则、凭据和授权事实归属于单个 App。`PermissionGroup` 只保留目录分组语义，运行时授权统一通过 `AuthorizationGroup` 与 scoped direct grant 展开为原子 `grants`。公共查询主契约一次性切到 `groups + grants + grant_version + catalog_version + snapshot_version`。

**技术栈：** Django 5.2、DRF、PostgreSQL、Pydantic、pytest、React、Vite、Vitest、Playwright。

---

## 分卷

本次改造横跨后端模型、公共查询、控制台、manifest、门户和前端。为避免单份计划过长，拆成以下执行文档：

- `docs/plans/easyauth-atomic-grants-execution-01-console-app-api-2026-07-01.md`：控制台 App 创建、编辑、owner 初始化和基础 HTTP 验证。
- `docs/plans/easyauth-atomic-grants-execution-02-domain-models-and-grants-2026-07-01.md`：领域模型、迁移、授权事实和版本骨架。
- `docs/plans/easyauth-atomic-grants-execution-03-public-query-portal-requests-2026-07-01.md`：公共查询、grant 展开、门户“我的权限”、申请目录和审批落库。
- `docs/plans/easyauth-atomic-grants-execution-04-manifest-readiness-catalog-2026-07-01.md`：manifest 导入/导出、`catalog_version`、readiness 和 seed 收口。
- `docs/plans/easyauth-atomic-grants-execution-05-frontend-console-portal-2026-07-01.md`：React 控制台、门户前端类型、页面和浏览器验证。

## 子代理阅读结论

- 领域模型：`AccessGrant` 已有 `version/status/grant_expires_at/is_current`，但授权核心仍是 `Role + RolePermission + AccessGrantRole + AccessGrantPermission`，没有 `AppScope`、`AuthorizationGroup`、`AuthorizationGroupGrant` 和 scoped direct grant。
- 控制台后端：`GET /console/api/v1/apps` 与 `GET /console/api/v1/apps/{app_key}` 已存在；`POST /console/api/v1/apps`、`PATCH /console/api/v1/apps/{app_key}` 和创建时 owner 事务闭环不存在。
- 公共查询与门户：公共查询、联调页、门户“我的权限”和申请流程都固化了 `roles/permissions/version/expires_at`，没有来源、scope、目录版本或权限包来源链。
- manifest：现有权限模板只导入 `PermissionGroup + Permission` 树，`PermissionTemplateVersion` 不是当前 App 完整配置事实，也没有导出能力。
- 前端：`domain.ts`、控制台工作区、矩阵页、联调页和门户页面都以 `Role` 为核心类型；创建 App、编辑 App、scope 字典、授权组管理和展开 grants 展示均缺失。

## 全局不变量

- 不建立长期 `Role` 与 `AuthorizationGroup` 双模型。项目尚未投产，主代码路径应一次性切到 `AuthorizationGroup(kind=role|bundle)`。
- `PermissionGroup` 不得作为授权对象，也不得被复用为权限包。
- scope 是 App 内字典 key，EasyAuth 只负责存储、校验和返回，不解释 `SELF/MANAGED/ALL` 的业务含义。
- 禁用的 App、用户、授权组、权限、scope 或已废弃权限不得出现在公共查询 `grants` 中。
- `catalog_version` 必须是 App 级持久版本，不得用当前权限矩阵 hash 或 `PermissionTemplateVersion.version` 近似替代。
- 公共查询主契约以 `grants` 为准；若实施期间临时输出 `roles/permissions`，只能作为短迁移窗口的兼容字段，不写入新主文档。
- 修改 Django 后端、模板、React build 产物或 Vite manifest 后，必须重启当前 Django 开发服务，并用真实 HTTP 响应或浏览器页面验证新代码已加载。

## 推荐阶段顺序

### 阶段 0：控制台 App 创建闭环

**对应文档：** `01-console-app-api`

- [ ] 增加 `POST /console/api/v1/apps`。
- [ ] 增加 `PATCH /console/api/v1/apps/{app_key}`。
- [ ] 创建 App 与初始 `AppMembership(owner/developer)` 在同一事务中完成。
- [ ] 创建成功返回完整 App detail，前端可直接跳转工作区。
- [ ] 写入 `console_app_created` 与 `console_app_updated` 审计。

### 阶段 1：模型与迁移底座

**对应文档：** `02-domain-models-and-grants`

- [ ] 增加 `App.catalog_version`。
- [ ] 增加 `AppScope`、`AuthorizationGroup`、`AuthorizationGroupGrant`。
- [ ] 扩展 `Permission.supported_scopes` 与 `Permission.risk_level`。
- [ ] 用 `AccessGrantGroup` 替代长期语义上的 `AccessGrantRole`。
- [ ] 让 `AccessGrantPermission` 支持 `scope_key`。
- [ ] 改造 access request 目标模型，为后续申请和审批落库提供 scoped target。

### 阶段 2：授权展开与公共查询

**对应文档：** `03-public-query-portal-requests`

- [ ] `resolve_user_permissions()` 返回 `groups + grants`。
- [ ] 公共 API 响应切换到 `grant_version/catalog_version/snapshot_version`。
- [ ] mixed group/direct grant 去重以 `permission + scope + source` 为基础。
- [ ] 续期、撤权、变更校验使用 group 集合和 scoped grant 集合，不再使用扁平 permission set。

### 阶段 3：manifest、目录版本和 readiness

**对应文档：** `04-manifest-readiness-catalog`

- [ ] 将现有权限模板升级为 App manifest。
- [ ] 支持 manifest 预览、确认导入、版本历史和导出。
- [ ] 所有目录、scope、授权组、授权组 grant 和 manifest 确认导入变更都提升 `catalog_version`。
- [ ] readiness 切到 active owner、active permission、active authorization group、supported scopes、审批规则和引用有效性。
- [ ] `seed_crm_pilot` 改为导入 manifest，而不是硬编码 `RolePermission`。

### 阶段 4：React 控制台与门户

**对应文档：** `05-frontend-console-portal`

- [ ] `domain.ts` 引入 App 创建/编辑、scope、authorization group、scoped grant 和新版公共查询类型。
- [ ] `/console` 增加新建应用入口。
- [ ] 工作区增加编辑基本信息、成员管理、scope、授权组、manifest 和 grants 联调展示。
- [ ] 门户申请从 `role_keys/permission_keys` 迁到 `authorization_group_keys/direct_grants`。
- [ ] 门户“我的权限”展示 expanded grants、source 和版本字段。

## 全局验证命令

每个阶段先运行对应分卷中的局部命令。全部阶段完成后运行：

```bash
python manage.py check
python manage.py makemigrations --check
python manage.py migrate --check
pytest tests/unit/applications tests/unit/grants tests/unit/access_requests
pytest tests/integration/api tests/integration/admin_console tests/integration/portal
cd frontend && pnpm test
cd frontend && pnpm playwright test
```

## 真实服务验证

涉及运行页面响应的文件变更后，执行代理必须重启当前 Django 开发服务。重启后至少验证：

```bash
curl -i http://127.0.0.1:8000/console/api/v1/apps
curl -i http://127.0.0.1:8000/console/api/v1/apps/{app_key}
curl -i http://127.0.0.1:8000/console/api/v1/apps/{app_key}/configuration-status
curl -i http://127.0.0.1:8000/api/v1/apps/{app_key}/users/{user_id}/permissions
```

浏览器验证页面：

- `/console`
- `/console/apps/new` 或创建弹窗入口
- `/console/apps/{app_key}/`
- `/console/apps/{app_key}?tab=catalog`
- `/console/apps/{app_key}?tab=matrix` 或新的授权组页
- `/console/apps/{app_key}?tab=rules`
- `/console/apps/{app_key}?tab=test`
- `/portal`
- `/portal/request`

## 完成判定

- 管理员不需要 Django Admin、shell、seed 或配置文件即可创建并配置业务 App。
- 下游公共查询只需要消费 `grants`，不用理解 role、bundle、目录或权限包配置。
- 前端控制台能完整运营 App、scope、权限目录、授权组、审批规则、manifest、凭据和联调。
- 员工门户可按 `AuthorizationGroup` 与 scoped direct grant 发起申请，并能查看展开后的授权事实。
- 文档中的主契约全部切到新模型，旧 `roles/permissions` 只在明确短迁移说明中出现。
