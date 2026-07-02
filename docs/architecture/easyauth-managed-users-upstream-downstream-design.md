# `MANAGED_USERS` 上游与下游改造设计

## 状态

设计稿，等待实现拆分。

## 日期

2026-07-02

## 背景

EasyTrade 需要表达“部门经理可以管理下级人员，并查看被管理人员数据”的权限范围。公司组织树和主管关系来自 DingTalk，但 DingTalk 只是 Authentik 支持的身份来源之一。EasyAuth 必须把组织关系解析成下游可消费的业务授权结果，同时避免让 EasyTrade 在每次业务查询时实时调用 EasyAuth 或 Authentik。

本设计基于对以下代码库的探索结果：

- `/Users/konata/code/Authentik`
- `/Users/konata/code/EasyAuth`
- `/Users/konata/code/EasyTrade`

## 目标

- 在 EasyAuth 增加 `MANAGED_USERS` 授权范围，表示当前用户可管理的下级 active Authentik 用户集合。
- 第一版只支持 DingTalk 主管关系，控制台文案使用“按钉钉主管关系”。
- EasyAuth 控制台支持 App 默认策略和单个 `AuthorizationGroupGrant` 覆盖策略。
- EasyAuth 公共权限查询响应扩展已解析人员集合，供下游应用缓存。
- Authentik 增加稳定的 DingTalk 管理对象输出能力，避免 EasyAuth 依赖不完整的原始字段。
- EasyTrade 使用本地授权快照过滤业务查询，不在业务查询路径实时请求 EasyAuth。

## 非目标

- 不在 EasyAuth 第一版实现通用 ABAC、行级策略引擎或 DingTalk 原生选择器。
- 不让 DingTalk 成为授权事实来源。
- 不让下游应用自行解析 DingTalk 组织树。
- 不在业务查询路径实时调用 EasyAuth、Authentik 或 DingTalk。
- 不在第一版支持 Microsoft Entra 管理链，只保留扩展边界。
- 不在第一版做权限变更主动推送。

## 核心决策

- EasyAuth 是授权事实来源，也是 `MANAGED_USERS` 的解析者。
- Authentik 是身份和组织关系来源，第一版组织源为 DingTalk。
- `MANAGED_USERS` 的成员标识必须是 active Authentik 用户 ID。
- `MANAGED_USERS` 不包含当前用户本人。
- 同一个权限同时存在多个授权范围时，下游按并集处理。
- `MANAGED_USERS` 解析结果为空时保留 grant，并返回空 `resolved.user_ids`。
- 缺少有效管理范围策略时，相关 grant 不生效，并在健康检查中暴露配置问题。
- 下游应用必须保存 EasyAuth 响应中的解析结果，并通过本地 `users.external_user_id` 映射到业务表的本地 `users.id`。

## EasyAuth 契约

### 授权范围语义

`MANAGED_USERS` 是 app-wise、permission-wise 的人员集合范围。某人可能是 A 部门经理，同时也是 B 部门兼职员工，因此管理范围必须按 App 和权限 grant 单独计算，不能把组织关系全局化为用户的一项固定属性。

### 权限查询响应扩展

沿用现有公共接口：

```http
GET /api/v1/apps/{app_key}/users/{user_id}/permissions
```

当 grant 的 scope 为 `MANAGED_USERS` 时，在 grant 项中增加 `resolved`：

```json
{
  "permission": "trade.order.read",
  "scope": "MANAGED_USERS",
  "source_type": "group",
  "source_key": "trade_manager",
  "resolved": {
    "user_ids": ["ak_uid_001", "ak_uid_002"],
    "resolver": "dingtalk_manager_chain",
    "resolved_at": "2026-07-02T12:00:00+08:00"
  }
}
```

字段规则：

- `resolved.user_ids` 只包含 active Authentik 用户 ID。
- 找不到下级时返回空数组，不删除 grant。
- 组织目录没有可用快照时不返回扩大后的权限；没有历史有效快照时该 grant 不生效。
- `resolver` 是内部稳定 key，第一版为 `dingtalk_manager_chain`。
- `resolved_at` 是解析时间，用于下游判断本地快照新旧。

### 策略配置模型

EasyAuth 需要增加管理范围策略配置，建议抽象为 `ManagedScopePolicy` 或同等结构：

- `app_id`
- `target_type`: `app_default` 或 `authorization_group_grant`
- `target_id`
- `scope`: 固定为 `MANAGED_USERS`
- `resolver`: `dingtalk_manager_chain` 或 `disabled`
- `enabled`
- `created_at`
- `updated_at`

生效规则：

- `AuthorizationGroupGrant` 有单独策略时使用单独策略。
- `AuthorizationGroupGrant` 没有单独策略时允许继承 App 默认策略。
- 单独策略和 App 默认策略都不存在时阻断该 grant 生效。
- `disabled` 可以保存为草稿或停用状态，但不能让相关 grant 成为有效授权。
- 含有 `MANAGED_USERS` grant 的 `AuthorizationGroup` 视为管理范围组，必须参与配置健康检查。

### 控制台配置

控制台必须提供图形化配置，不要求用户编辑 JSON。

App 级页面增加“管理范围计算方式”：

- `按钉钉主管关系`
- `不启用`

`AuthorizationGroupGrant` 行增加同名配置：

- `继承应用默认`
- `按钉钉主管关系`
- `不启用`

界面只使用直白文案，避免“钉钉管理链下级”这类不易理解的表达。保存后需要展示当前有效策略、继承来源和健康状态。没有有效策略时必须清楚提示“必须配置管理范围计算方式后才能生效”。

### 自助申请

公司允许员工自助申请管理范围组，并通过定期审计发现违规授权。

当申请包含 `MANAGED_USERS` grant 时：

- 默认审批人动态取申请人的直属上级。
- 用户允许手动重填审批人。
- 如果找不到直属上级，审批人留空，提交前必须由用户补全。
- 最终审批人必须是 active EasyAuth 用户。
- 不需要单独记录审批人来源或重填原因，保留整体申请记录即可。
- 申请类型保留现有 `grant`。

### 失败与陈旧数据

- 当前用户缺少 DingTalk 身份绑定时，不展开 `MANAGED_USERS`。
- 组织目录标记 stale 时，读路径可以使用最后一次有效快照；写入和高风险操作必须阻断。
- 没有任何有效组织快照时，不返回管理范围授权。
- 解析失败必须在健康检查、联调预览和审计日志中可见，不能静默降级为全量人员或旧的本地算法。

### 预览与健康检查

EasyAuth 控制台需要提供按用户、App、授权组预览 `MANAGED_USERS` 的能力，用于上线前验证。

健康检查至少覆盖：

- App 默认策略缺失。
- `AuthorizationGroupGrant` 没有单独策略且无法继承 App 默认策略。
- 组织源不可用或快照陈旧。
- 用户缺少 DingTalk 身份绑定。
- 解析结果中存在未绑定 Authentik 用户或 inactive 用户。

## Authentik 上游改造

### 当前能力

Authentik DingTalk 相关代码已经具备以下能力：

- `authentik/sources/oauth/types/dingtalk.py` 定义 DingTalk OAuth 类型。
- `authentik/sources/oauth/dingtalk/sync.py` 同步 DingTalk 部门和用户。
- `authentik/sources/oauth/dingtalk/client.py` 封装 DingTalk API。
- `authentik/sources/oauth/dingtalk/selectors.py` 提供 DingTalk 目录查询。
- `authentik/sources/oauth/api/dingtalk_directory.py` 暴露 DingTalk 目录 API。
- `User.attributes["dingtalk"]` 保存 `corp_id`、`user_id`、`dept_id_list`、`manager_user_id` 等字段。
- `/api/v3/sources/oauth/dingtalk-directory/<source_slug>/users/` 返回 DingTalk 用户列表。
- `/api/v3/sources/oauth/dingtalk-directory/<source_slug>/users/<corp_id>/<user_id>/org/` 返回当前用户向上的组织上下文。

这些能力还不足以支撑 EasyAuth 的 `MANAGED_USERS`，因为现有 API 缺少稳定的 linked Authentik 用户 ID、下级人员列表和递归管理对象输出。

### 必要输出

Authentik 应向 EasyAuth 暴露一个以 DingTalk 用户为输入的管理对象接口：

```http
GET /api/v3/sources/oauth/dingtalk-directory/{source_slug}/managed-users/by-manager/{corp_id}/{manager_user_id}/
```

建议响应：

```json
{
  "source_slug": "dingtalk",
  "corp_id": "ding_corp_001",
  "manager_user_id": "manager_001",
  "resolver": "dingtalk_manager_chain",
  "stale": false,
  "resolved_at": "2026-07-02T12:00:00+08:00",
  "users": [
    {
      "source_user_id": "employee_001",
      "authentik_user_id": "ak_uid_001",
      "authentik_user_active": true,
      "directory_active": true,
      "is_deleted": false
    }
  ]
}
```

接口规则：

- `users` 返回递归下级，不包含 manager 本人。
- `authentik_user_id` 必须来自 Authentik 用户主键或 OIDC subject 所使用的稳定 UID。
- inactive、deleted 或未绑定 Authentik 用户的 DingTalk 人员不能进入 EasyAuth 的最终 `resolved.user_ids`。
- `stale=true` 时 EasyAuth 只能按陈旧数据规则处理，不能把结果视为新鲜组织事实。
- Authentik 应保证 `source + identifier` 到 Authentik 用户的映射唯一；无法唯一映射时接口应失败，而不是任意选择一个用户。

### 可选替代

如果 Authentik 暂不提供最终管理对象接口，也可以在 `/users/` 列表中增加 linked Authentik 字段，由 EasyAuth 拉取全量 DingTalk 用户并本地计算递归下级。

该方案只适合短期保留，因为它会把 DingTalk 目录字段完整性、递归算法和用户绑定歧义转移到 EasyAuth。长期推荐 Authentik 提供归一化后的管理对象接口。

### 待排查

- DingTalk 部门用户列表是否稳定返回完整 `manager_user_id` 和 `dept_id_list`。
- 一个用户属于多个部门时，当前同步逻辑是否会覆盖或遗漏部门列表。
- `UserSourceConnection` 是否存在 `source + identifier` 唯一约束。
- DingTalk 目录 API 是否需要增加 `directory_version`，用于 EasyAuth 和下游判断快照新旧。
- Microsoft Entra 后续应抽象为通用组织源接口，不应依赖 Authentik 的 Microsoft Entra outbound provider。

## EasyTrade 下游改造

### 当前能力

EasyTrade 当前已经具备以下基础：

- 登录身份通过上游 header 或 JWT 进入 `backend/app/api/v1/current_user.py`。
- 本地用户表包含 `external_source` 和 `external_user_id`，默认 `external_source="authentik"`。
- EasyAuth 客户端位于 `backend/app/domain/authz/easyauth_client.py`。
- 权限快照表为 `authz_user_permission_snapshots`。
- 权限判断集中在 `backend/app/domain/authz/service.py`、`scope_resolution.py` 和 `authz_dependencies.py`。
- 多数业务表用本地 `users.id` 作为 owner 或 actor 外键。

### 必要改造

EasyTrade 必须把 EasyAuth 返回的 `resolved.user_ids` 保存到本地授权快照中，并在本地转换为 `users.id`：

```text
EasyAuth resolved.user_ids
  -> users.external_source = "authentik"
  -> users.external_user_id in resolved.user_ids
  -> users.id
  -> 业务表 owner_user_id / assigned_to_user_id / actor_user_id 过滤
```

需要改造的点：

- `EasyAuthGrantItem` 接受可选 `resolved` 字段。
- 快照保存逻辑保留 `resolved.user_ids`、`resolver`、`resolved_at`、`snapshot_version` 和 `expires_at`。
- 现有 `DataScope.MANAGED` 的 region、segment 本地算法必须移除或改为消费 EasyAuth `MANAGED_USERS`。
- 权限 manifest、种子数据和测试中的管理范围命名应统一到 `MANAGED_USERS`。
- `allowed_owner_user_ids` 等集中式 owner 过滤入口改为使用本地映射后的人员集合。
- 候选 owner、转派人员、任务处理人等用户选择接口需要排查是否应受 `MANAGED_USERS` 限制。

### 性能判断

当前系统用户少于 100 人，下游使用本地快照进行 `IN` 或 `EXISTS` 过滤不会造成明显性能问题。关键约束不是集合大小，而是禁止业务查询路径实时调用 EasyAuth。

推荐实现：

- 登录或权限 TTL 到期时刷新当前用户快照。
- 后台任务定期刷新 active 用户快照。
- 查询时只读取本地快照和本地 `users` 表。
- 对 `users.external_source + users.external_user_id` 建唯一索引。
- 对常用 owner 外键保留现有索引。

若后续人数明显增长，再考虑增加物化表 `authz_user_managed_subject_snapshots`。第一版可以直接从快照 JSON 中解析并缓存到应用内存或请求上下文。

### 失败规则

- 快照过期且无法刷新时，读路径可以按 EasyTrade 现有 TTL 策略使用最后一次有效快照。
- 写入、高风险操作或权限快照从未成功加载时必须阻断。
- 不能回退到旧的 region、segment 管理算法。
- `resolved.user_ids` 映射不到本地 active 用户时，应在日志和授权诊断中暴露，并从本次有效人员集合中剔除。

### 受影响业务区域

需要重点排查以下 owner 或 actor 过滤入口：

- 客户：`customers.owner_user_id`
- 询盘：`inquiries.owner_user_id`
- 订单：`orders.owner_user_id`
- 报价、样品、任务、活动、邮件日志、文档交付中的 owner、assigned 或 actor 字段
- 报表和列表查询中的 owner 范围过滤
- 用户选择、转派、协作人选择等辅助接口

## 落地顺序

1. Authentik 增加 DingTalk 管理对象接口，输出 linked Authentik 用户 ID、active 状态和 stale 状态。
2. EasyAuth 增加 `MANAGED_USERS` 策略模型、resolver 注册、配置健康检查和联调预览。
3. EasyAuth 控制台增加 App 默认策略和 `AuthorizationGroupGrant` 覆盖策略配置。
4. EasyAuth 扩展公共权限查询响应，返回 `resolved.user_ids`。
5. EasyAuth 自助申请流程支持管理范围组的动态审批人。
6. EasyTrade 扩展 EasyAuth 客户端模型、快照保存和本地人员映射。
7. EasyTrade 替换旧 `MANAGED` 本地算法，所有 owner 过滤消费 `MANAGED_USERS`。
8. 使用真实 DingTalk 租户数据验证经理、兼职、多部门、无上级、无下级、inactive 用户和 stale 目录场景。

## 验证要求

Authentik：

- API 测试覆盖直接下级、递归下级、无下级、inactive 用户、未绑定用户、stale 目录。
- 测试 `source + identifier` 映射不唯一时失败。

EasyAuth：

- 模型测试覆盖 App 默认、grant 覆盖、继承、缺失策略、disabled 策略。
- resolver 测试覆盖空结果、排除本人、inactive 剔除、stale 行为。
- 公共 API 测试覆盖 `resolved` 字段和多 scope 并集。
- 控制台测试覆盖图形化配置、健康状态和预览。
- 自助申请测试覆盖默认审批人、手动重填、找不到上级和审批人 inactive。

EasyTrade：

- 客户端 schema 测试覆盖可选 `resolved`。
- 快照测试覆盖 `resolved.user_ids` 持久化。
- scope resolver 测试覆盖 Authentik UID 到本地 `users.id` 的映射。
- 列表查询测试覆盖 owner 过滤。
- 失败测试覆盖无法刷新、无快照和禁止回退旧算法。

## 待办与风险

- Authentik DingTalk 同步字段完整性必须用真实租户确认。
- EasyAuth 需要明确 `authentik_user_id` 与 OIDC subject 是否完全一致。
- EasyTrade 需要排查所有绕过集中 scope resolver 的查询。
- 如果 Authentik 暂不提供管理对象接口，EasyAuth 本地计算方案只能作为保留项，不能长期沉淀为第二套组织源模型。
- Microsoft Entra 支持必须通过通用组织源接口扩展，不能复制 DingTalk 专用字段到授权模型。
