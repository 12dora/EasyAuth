# EasyAuth 文档索引

## 当前有效文档

1. [EasyAuth 架构设计文档](architecture/easyauth-architecture-design.md)
2. [EasyAuth 公共 API（下游应用契约）](api/easyauth-public-api.md)
3. [EasyAuth 管理控制台私有 API 目录](api/easyauth-console-api.md)
4. [EasyAuth 员工门户 React 私有 API](api/easyauth-portal-react-api.md)
5. [平台用户目录与钉钉通知能力设计](design/platform-directory-notify/README.md)
6. [EasyAuth 钉钉 Stream 事件集成设计](architecture/easyauth-dingtalk-stream-design.md)
7. [EasyAuth 前端视觉契约](architecture/easyauth-frontend-visual-contract.md)
8. [ADR-001：业务授权运营边界](decisions/ADR-001-业务授权运营边界.md)
9. [ADR-002：`MANAGED_USERS` 管理范围契约](decisions/ADR-002-MANAGED_USERS管理范围契约.md)

## 待实施设计

- [NetBird 服务端改造方案](plans/2026-07-07-netbird-server-fork-plan.md)：只涉及外部 NetBird management fork，本仓库无法证明已实施，保留为待执行设计。

## 文档规则

- 当前实现、评审和试点接入以架构设计文档为准。
- 硬性要求：本项目所有文档必须使用中文撰写；代码标识符、文件路径、命令、协议名、HTTP 路径、API 字段、错误码、配置键、产品名和不可翻译专有名词可以保留英文。
- 历史规格、已完成实施计划、实施任务卡、审计与偏差记录均不在工作树保留，需要追溯时使用 Git 历史。
- 新增重大架构决策时，优先更新当前架构文档；如果需要记录独立决策历史，再在 `docs/decisions/` 增加 ADR。
- 新增公共 API 时，必须在架构文档或专门 API 文档中同时记录请求、响应、错误语义和兼容性规则。
- 新增或修改控制台、员工门户视觉系统时，必须同步核对 [EasyAuth 前端视觉契约](architecture/easyauth-frontend-visual-contract.md)。
- 只有尚未实施且有明确负责范围的计划才可保留在 `docs/plans/`；实施完成后应把长期有效结论合并到架构、API 或 ADR 后删除计划。

## 本地开发登录

本地开发免登入口(`/auth/dev-login/`)已移除。开发过程中需要登录态时，统一使用本地超级管理员账号：

```bash
DJANGO_DEBUG=1 .venv/bin/python manage.py create_local_admin admin --password admin123
DJANGO_DEBUG=1 .venv/bin/python manage.py runserver
```

然后访问 `/auth/local/` 用 `admin` / `admin123` 登录。首次登录会强制跳转到 `/auth/local/change-password/` 修改密码，改完后即可正常进入 `/portal/` 与 `/console/`（本地管理员会话按 `EASYAUTH_CONSOLE_SUPERUSER_GROUPS` 绑定，天然是 console 超管）。详见 [本地超级管理员登录指南](guides/local-admin-login.md)。生产 OIDC 登录仍使用 `/auth/login/` 和 `/auth/callback/`。

## 建议后续文档顺序

1. `docs/README.md`：文档入口和维护规则。
2. `docs/architecture/`：当前架构、模块边界、公共契约和实现顺序。
3. `docs/api/`：保存当前接口契约与接入目录。
4. `docs/design/`：保存已实施且仍需维护的专题设计契约。
5. `docs/decisions/`：只保存需要长期追踪的架构决策记录。
6. `docs/plans/`：只保存待实施计划，不保存已完成任务。
