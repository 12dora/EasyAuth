# EasyAuth 文档索引

## 当前有效文档

1. [EasyAuth 架构设计文档](architecture/easyauth-architecture-design.md)
2. [EasyAuth MVP 实施计划](plans/easyauth-mvp-implementation-plan.md)
3. [EasyAuth 业务授权运营增强需求方案](requirements/easyauth-business-authorization-operations.md)
4. [EasyAuth 业务授权运营增强架构设计](architecture/easyauth-authorization-operations-design.md)
5. [EasyAuth 业务授权运营页面 API 设计](api/easyauth-authorization-operations-api-design.md)
6. [ADR-001：业务授权运营边界](decisions/ADR-001-业务授权运营边界.md)
7. [EasyAuth 员工门户 React 私有 API](api/easyauth-portal-react-api.md)

## 文档规则

- 当前实现、评审和试点接入以架构设计文档为准。
- 硬性要求：本项目所有文档必须使用中文撰写；代码标识符、文件路径、命令、协议名、HTTP 路径、API 字段、错误码、配置键、产品名和不可翻译专有名词可以保留英文。
- 历史规格、历史技术规划和旧 MVP 方案已删除，避免多个文档同时描述同一决策。
- 新增重大架构决策时，优先更新当前架构文档；如果需要记录独立决策历史，再在 `docs/decisions/` 增加 ADR。
- 新增公共 API 时，必须在架构文档或专门 API 文档中同时记录请求、响应、错误语义和兼容性规则。
- MVP 实施阶段使用 `MVP-1`、`MVP-2` 这类前缀；业务授权运营增强阶段使用 `OPS-1`、`OPS-2` 这类前缀，避免不同计划中的“阶段 4”混淆。
- 每个阶段说明至少包含阶段目标、交付物或任务、验收标准、阶段约束和验证方式。

## 本地开发登录

开发过程中需要先 mock 上游 Authentik 身份、暂不做真实联调时，可以仅在本地开发环境启用受控入口：

```bash
DJANGO_DEBUG=1 EASYAUTH_ENABLE_DEV_LOGIN=1 .venv/bin/python manage.py runserver
```

启动后访问 `/auth/dev-login/?next=/portal/` 会创建或更新 `dev-user`，写入门户 session，并跳转到 `/portal/`。如果需要指定测试用户，可访问 `/auth/dev-login/?user_id=alice&next=/portal/`。

该入口是本地 mock Authentik 的开发能力，不是生产登录方式。它必须同时满足 `DEBUG=True` 和 `EASYAUTH_ENABLE_DEV_LOGIN=1` 才可用；默认关闭。`next` 只接受站内绝对路径，外部地址会回退到 `/portal/`，避免开放重定向。生产 OIDC 登录仍使用 `/auth/login/` 和 `/auth/callback/`。

## 建议后续文档顺序

1. `docs/README.md`：文档入口和维护规则。
2. `docs/architecture/`：当前架构、模块边界、公共契约和实现顺序。
3. `docs/plans/`：保存从当前架构拆分出的实施计划和阶段任务。
4. `docs/requirements/`：保存独立产品需求、边界核对和验收标准。
5. `docs/decisions/`：只保存需要长期追踪的架构决策记录。
6. `docs/api/`：实现开始后保存 OpenAPI 或接入文档。
