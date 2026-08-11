# EasyAuth 文档

项目介绍、快速开始和部署命令在仓库根目录的 [`README.md`](../README.md)。这里是深入文档。

## 架构与契约

| 文档 | 什么时候看 |
| --- | --- |
| [架构设计](architecture/easyauth-architecture-design.md) | 想了解模块边界、领域模型、核心流程和安全设计 |
| [异步动作与失败语义](architecture/async-and-failure-semantics.md) | 写 Celery 任务、连接器对账或 Webhook 投递，需要知道"什么算成功" |
| [前端契约](architecture/frontend-contract.md) | 改控制台或门户 UI（视觉、组件、反馈、国际化、浏览器支持） |
| [企业目录与钉钉通知](architecture/platform-directory-notify.md) | 接入 `directory` / `notify` 平台能力 |
| [钉钉 Stream 事件集成](architecture/easyauth-dingtalk-stream-design.md) | 排查目录事件、审批事件或 Stream 进程 |

## API

| 文档 | 面向 |
| --- | --- |
| [公共 API](api/easyauth-public-api.md) | **下游应用**——权限查询、manifest 同步、审批、目录、通知 |
| [控制台私有 API](api/easyauth-console-api.md) | 控制台前端（session + CSRF） |
| [门户私有 API](api/easyauth-portal-react-api.md) | 员工门户前端（session） |

## 接入与部署

- [从零部署全链路](guides/zero-to-full-deployment.md) —— Authentik + EasyAuth + 下游应用的顺序与踩坑
- [Authentik 自动化配置](guides/authentik-easyauth-automation-setup-llm.md) · [Authentik 手动配置](guides/authentik-easyauth-ui-setup-human.md)
- [应用接入向导](guides/easyauth-app-onboarding-wizard.md) —— 自动接入、六步向导、岗位模板修订
- [SDK 集成指南](guides/easyauth-app-sdk-integration.md) —— 下游怎么用 `easyauth-app-sdk`
- [本地超级管理员登录](guides/local-admin-login.md) —— 不依赖 Authentik 的应急通道

> 反代部署形态（`docker-compose.deploy.yml`、七个服务、改代码必须重建镜像）见
> [根 README 的容器化部署](../README.md#容器化部署本仓库自用的反代形态)。

## 运维

- [质量门禁](operations/quality-gates.md) —— CI 作业、静态检查边界与本地等价命令
- [运行健康探针](operations/runtime-health.md) —— `/health/` 与 `/health/readiness/`
- [数据保留与自动清理](operations/data-retention.md) —— 保留矩阵与最小化口径
- [历史迁移的数据保护基线](operations/historical-migration-baseline.md) —— 哪些迁移会 fail-fast 及如何处置
- [前端构建分包与体积预算](operations/frontend-build-budget.md)

## 决策记录

- [ADR-001：业务授权运营边界](decisions/ADR-001-业务授权运营边界.md)
- [ADR-002：`MANAGED_USERS` 管理范围契约](decisions/ADR-002-MANAGED_USERS管理范围契约.md)（含数据交接 v2 的 §36 审批人路由修订）
- [ADR-003：特权入口与产品能力边界](decisions/ADR-003-特权入口与产品能力边界.md)
- [ADR-004：旧兼容形态清理](decisions/ADR-004-旧兼容形态清理.md)
- [ADR-005：NetBird 供给连接器与 management fork 边界](decisions/ADR-005-NetBird供给连接器与management-fork边界.md)

## 进行中的设计

- [`design/data-handover-v2/`](design/data-handover-v2/README.md) —— **数据交接 v2**，跨 EasyAuth /
  EasyTrade / EasyProject 三仓的多代理协作项目。`00`–`09` 是冻结的契约文档，
  [`EXECUTION-HANDOVER.md`](design/data-handover-v2/EXECUTION-HANDOVER.md) 是给下一位指挥 agent 的现状交接，
  `review-artifacts/` 只留尚有未结债务的第四轮产物。

---

## 文档规则

1. **一律中文。** 代码标识符、文件路径、命令、协议名、HTTP 路径、API 字段、错误码、配置键、
   产品名和不可翻译的专有名词保留英文。
2. **只保留当前事实。** 历史规格、已完成的实施计划、任务卡、审计报告和偏差记录都不留在工作
   树里，要追溯就用 Git 历史。
3. **每份文档有唯一权威位置。** 接口字段以 `api/` 为准，实现口径以 `architecture/` 为准，
   不在两处重复同一份契约；发现重复时删掉副本并改为链接。
4. **架构变更优先改现有文档**，只有需要长期追踪"为什么这么定"时才新增 ADR。
5. **新增公共 API 必须同时写清**请求、响应、错误语义和兼容性规则。
6. **改控制台或门户视觉系统**时同步核对[前端契约](architecture/frontend-contract.md)。
7. **`design/` 只放进行中项目的冻结契约**，评审过程产物（findings / verify / fix-report）
   在该轮闭环后删除，结论并入交接文档或 ADR。若某条 finding 被判为"留债"，
   必须先转移进对应仓库的风险清单，产物才能删。
8. **实施计划（若新建 `plans/`）只放尚未实施、有明确负责范围的计划。** 实施完成后把长期有效的
   结论合并进 architecture / api / ADR，然后删除计划文件。
9. **写给人看。** 优先讲清"是什么、为什么、什么时候会踩坑"，不堆砌实现细节和内部编号。
