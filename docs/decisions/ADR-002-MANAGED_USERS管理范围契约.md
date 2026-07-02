# ADR-002：`MANAGED_USERS` 管理范围契约

## 状态

已接受

## 日期

2026-07-02

## 背景

EasyTrade 需要让部门经理查看和管理下级人员数据。主管关系来自 DingTalk，并由 Authentik 同步和透传。EasyAuth 既不能把 DingTalk 当成授权事实来源，也不能要求 EasyTrade 在业务查询时实时调用 EasyAuth 或解析 DingTalk 组织树。

同时，DingTalk 只是 Authentik 支持的认证和目录来源之一。第一版可以只支持 DingTalk，但授权模型必须保留未来接入 Microsoft Entra 等组织源的空间。

## 决策

新增授权范围 `MANAGED_USERS`，表示当前用户在某个 App、某个权限下可管理的 active Authentik 用户集合。

具体决策：

- EasyAuth 是 `MANAGED_USERS` 的解析者和对下游的契约提供者。
- Authentik 是身份和组织关系来源，第一版提供 DingTalk 主管关系。
- `MANAGED_USERS` 成员使用 Authentik 用户 ID，不使用 DingTalk ID、手机号、邮箱或工号作为授权主键。
- `MANAGED_USERS` 不包含当前用户本人。
- 管理范围按 App 和 `AuthorizationGroupGrant` 配置；`AuthorizationGroupGrant` 可继承 App 默认策略，也可单独覆盖。
- 没有有效策略时，相关 grant 不生效，且健康检查必须报错。
- 第一版 resolver key 为 `dingtalk_manager_chain`，控制台文案为“按钉钉主管关系”。
- EasyAuth 公共权限查询响应扩展 `resolved.user_ids`，下游应用保存本地快照后再过滤业务数据。
- 下游应用不得在每次业务查询时实时调用 EasyAuth、Authentik 或 DingTalk。
- EasyTrade 的业务表继续使用本地 `users.id` 外键，授权快照中的 Authentik 用户 ID 通过 `users.external_user_id` 映射到本地用户。
- 自助申请允许申请管理范围组，默认审批人动态取申请人的直属上级，并允许用户手动重填；最终审批人必须是 active EasyAuth 用户。

## 备选方案

### 在 EasyTrade 中解析 DingTalk 组织树

优点：

- EasyAuth 公共 API 改动较少。

缺点：

- EasyTrade 需要理解 DingTalk 字段和组织递归规则。
- 后续接入 Microsoft Entra 时每个下游应用都要重复改造。
- 业务查询容易出现实时远程调用或本地算法漂移。

结论：拒绝。组织解析集中在 EasyAuth。

### 在 Authentik 中直接产生业务授权

优点：

- Authentik 已经持有身份和组织关系。

缺点：

- Authentik 会从身份源变成业务授权事实源。
- 授权组、审批、审计和撤权会分裂到两个系统。
- EasyAuth 的授权边界被破坏。

结论：拒绝。Authentik 只输出身份和组织事实。

### 下游每次业务查询实时调用 EasyAuth

优点：

- 下游本地缓存逻辑较少。

缺点：

- 列表和报表查询会放大远程调用次数，引发卡顿。
- EasyAuth 临时不可用会影响所有业务读路径。
- 无法稳定复用数据库索引和查询计划。

结论：拒绝。下游必须使用本地授权快照。

### 使用 DingTalk ID 作为管理对象主键

优点：

- 组织源字段直接可用。

缺点：

- DingTalk 不是唯一身份源。
- EasyTrade 当前生产身份使用 Authentik 外部 ID。
- 离职、换绑和多来源身份会导致授权主体不一致。

结论：拒绝。公共契约使用 Authentik 用户 ID。

## 后果

- EasyAuth 公共权限响应需要扩展 `resolved` 字段。
- Authentik 需要提供 DingTalk 管理对象或足够完整的 linked 用户目录。
- EasyAuth 控制台需要新增 App 默认策略和 grant 覆盖策略的图形化配置。
- EasyTrade 需要改造权限快照、scope resolver 和 owner 查询过滤。
- 原 EasyTrade 本地 `MANAGED` 的 region、segment 算法必须废弃，不能作为失败回退。
- 后续 Microsoft Entra 支持应复用组织源抽象，不改变 `MANAGED_USERS` 下游契约。
