# EasyAuth 文档索引

## 当前有效文档

1. [EasyAuth 架构设计文档](architecture/easyauth-architecture-design.md)
2. [EasyAuth MVP 实施计划](plans/easyauth-mvp-implementation-plan.md)

## 文档规则

- 当前实现、评审和试点接入以架构设计文档为准。
- 硬性要求：本项目所有文档必须使用中文撰写；代码标识符、文件路径、命令、协议名、HTTP 路径、API 字段、错误码、配置键、产品名和不可翻译专有名词可以保留英文。
- 历史规格、历史技术规划和旧 MVP 方案已删除，避免多个文档同时描述同一决策。
- 新增重大架构决策时，优先更新当前架构文档；如果需要记录独立决策历史，再在 `docs/decisions/` 增加 ADR。
- 新增公共 API 时，必须在架构文档或专门 API 文档中同时记录请求、响应、错误语义和兼容性规则。

## 建议后续文档顺序

1. `docs/README.md`：文档入口和维护规则。
2. `docs/architecture/`：当前架构、模块边界、公共契约和实现顺序。
3. `docs/plans/`：保存从当前架构拆分出的实施计划和阶段任务。
4. `docs/decisions/`：只保存需要长期追踪的架构决策记录。
5. `docs/api/`：实现开始后保存 OpenAPI 或接入文档。
