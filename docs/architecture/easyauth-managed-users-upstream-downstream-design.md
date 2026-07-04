# `MANAGED_USERS` 上游与下游改造设计

## 状态

已实现。`MANAGED_USERS` 管理范围授权已落地（`src/easyauth/grants/managed_users.py`、`applications/managed_scope_policy.py`、`admin_console/managed_scope_policy_api.py` 与 `managed_users_preview_api.py`，上游经 `AuthentikDirectoryClient.get_managed_users()` 解析）。约束口径以 [ADR-002：`MANAGED_USERS` 管理范围契约](../decisions/ADR-002-MANAGED_USERS管理范围契约.md) 为准，本文保留为设计背景与推导记录。

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
- `MANAGED_USERS` 的成员标识必须是 active Authentik subject。第一版 subject 来源为 Authentik `User.uid`，但它只能作为部署级 opaque subject 使用，不能被下游解释为业务主键。
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
    "resolved_at": "2026-07-02T12:00:00+08:00",
    "source_stale": false,
    "source_last_synced_at": "2026-07-02T11:58:00+08:00"
  }
}
```

字段规则：

- `resolved.user_ids` 只包含 active Authentik subject。第一版 subject 来源为 `User.uid`，前提是它与 EasyAuth 当前登录链路使用的 Authentik 外部用户 ID 保持一致。
- 找不到下级时返回空数组，不删除 grant。
- 组织目录没有可用快照时不返回扩大后的权限；没有历史有效快照时该 grant 不生效。
- `resolver` 是内部稳定 key，第一版为 `dingtalk_manager_chain`。
- `resolved_at` 是解析时间，用于下游判断本地快照新旧。
- `source_stale` 和 `source_last_synced_at` 来自 Authentik managed-users 响应，用于健康检查、预览和下游诊断。

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

上述 DingTalk 模块是本地二次开发层，不是上游原生 Authentik 模块。后续设计应把“上游原生 Authentik”和“本地 DingTalk 目录适配层”分开看待：可以在 DingTalk 二开层补充通用目录能力，但应避免把 EasyAuth 专属授权语义写入上游原生 core、OAuth provider/token 流程或 Authentik 通用 source 框架。

这些能力还不足以支撑 EasyAuth 的 `MANAGED_USERS`，因为现有 API 缺少稳定的 linked Authentik subject、下级人员列表和递归管理对象输出。

### 职责边界

Authentik 第一版只承担 DingTalk 目录事实归一化和 linked Authentik 用户输出，不承担 EasyAuth 授权策略裁决，也不承担 EasyTrade 业务数据过滤。

具体边界：

- Authentik 负责同步 DingTalk 部门、人员、主管关系，并从本地缓存输出递归下级。
- Authentik 负责把 DingTalk 人员映射到 linked Authentik 用户，并暴露绑定状态、用户 active 状态和目录 stale 状态。
- Authentik 不计算 `AuthorizationGroupGrant` 是否生效，不合并多个授权范围。
- Authentik 不把 inactive、deleted、unbound 人员静默剔除成授权结果；它显式返回状态，由 EasyAuth 决定最终是否进入 `resolved.user_ids`。
- Authentik 第一版不抽象通用组织源模型，不支持 Microsoft Entra 管理链，只把 DingTalk managed-users 实现边界整理成后续可抽象的 service。
- EasyAuth managed-users 代码必须与 Authentik 原有 OAuth source 代码低耦合，避免未来合并上游 Authentik 时频繁冲突。

### 输出契约

#### 管理对象接口

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
  "last_synced_at": "2026-07-02T11:58:00+08:00",
  "resolved_at": "2026-07-02T12:00:00+08:00",
  "users": [
    {
      "source_user_id": "employee_001",
      "source_identifier": "ding_corp_001:employee_001",
      "authentik_subject": "ak_uid_001",
      "authentik_subject_type": "user_uid",
      "authentik_user_active": true,
      "directory_active": true,
      "is_deleted": false,
      "binding_status": "bound",
      "diagnostics": {
        "authentik_user_pk": 123
      }
    }
  ]
}
```

#### 响应字段规则

- `users` 返回递归下级，不包含 manager 本人。
- `source_identifier` 复用 DingTalk 登录绑定标识，格式为 `{corp_id}:{user_id}`。
- `authentik_subject` 是 EasyAuth `resolved.user_ids` 的 canonical ID。
- `authentik_subject_type` 第一版固定为 `user_uid`，表示 subject 来源为 Authentik `User.uid`。
- `diagnostics.authentik_user_pk` 只用于诊断、日志和人工排查，是可选诊断字段，不作为 EasyAuth 对下游暴露的人员 ID。
- `binding_status` 至少包含 `bound`、`unbound`；如果实现需要，也可以扩展 `conflict`、`missing_directory_user` 等诊断状态。
- 未绑定人员返回 `authentik_subject=null`、`binding_status=unbound`。
- inactive、deleted 或未绑定 Authentik 用户的 DingTalk 人员不能进入 EasyAuth 最终 `resolved.user_ids`。
- `stale=true` 时 EasyAuth 只能按陈旧数据规则处理，不能把结果视为新鲜组织事实。
- `last_synced_at` 来自 `DingTalkDirectorySyncStatus.finished_at`，没有成功同步记录时为 `null`。
- `resolved_at` 是本次接口解析时间。

`User.uid` 是 Authentik 根据本地用户 ID 和部署级唯一标识派生的值，不是 DingTalk 原生标识，也不是数据库字段。方案只把它作为当前 Authentik 部署内的 opaque subject；Authentik 内部查找 linked 用户仍使用 `UserSourceConnection` 和 DingTalk `source_identifier`。实现前必须确认 EasyAuth 登录链路中的 Authentik 外部用户 ID 与该 subject 一致；如果不一致，EasyAuth 接入侧必须增加显式映射，不能让 `MANAGED_USERS` 使用第二套人员 ID。

#### 错误与歧义处理

- `source_slug` 不存在或不是 DingTalk source 时返回 `404`。
- 调用者缺少 DingTalk directory user 读取权限时返回 `403`。
- 参数缺失或格式非法时沿用 DRF 字段级 `400 ValidationError`。
- 同一 `source + identifier` 命中多个 `UserSourceConnection` 时返回 `409 Conflict`，不能任选一个用户。
- manager 不存在于目录缓存时返回 `404`，错误码为 `manager_not_found`；manager 存在但没有下级时才返回空 `users`。
- 递归过程中遇到环或超过最大深度时必须停止递归，并在响应或错误中暴露诊断信息。

### 可插拔实现边界

由于 DingTalk 模块本身就是本地二开层，新增 DingTalk 目录 service 或 DingTalk directory API 不会直接增加与上游原生 Authentik 的合并冲突。真正需要隔离的是 EasyAuth 专属契约、授权语义和本地部署启用方式。

第一版采用两层边界：

- DingTalk 目录适配层：负责 DingTalk 目录事实、递归下级、stale、linked Authentik 用户绑定等通用组织目录能力。
- EasyAuth 暴露层：负责面向 EasyAuth 的 API 路由、响应字段命名、错误码和测试，不把授权中心语义反向塞回 DingTalk 登录或 Authentik core。

若预计后续还会有更多本地 Authentik 扩展，EasyAuth 暴露层优先采用聚合 app 模式：

- 新增聚合 app `authentik.custom`，只负责收口本地扩展注册。
- 新增业务 app `authentik.custom.easyauth`，承载 EasyAuth managed-users API、serializer、service、tests。
- 本地 DingTalk directory 代码可以新增通用 managed-users service；但不要依赖 EasyAuth 模型、EasyAuth 配置或 EasyAuth 授权策略。
- 不新增模型，不修改 `DingTalkDirectoryUser`、`DingTalkDirectorySyncStatus`、`UserSourceConnection` schema。
- 不修改 OAuth source 登录、回调、property mapping、provider/token 流程。
- 不在第一版新增 Authentik 管理端 UI tab；联调预览先放在 EasyAuth 控制台。

保留 `authentik` 前缀是为了复用 Authentik 的 API 自动挂载机制：`/api/v3` 会扫描已安装且 app name 以 `authentik` 开头的 Django app，并挂载其 `urls.api_urlpatterns`。

启用方式优先使用部署侧配置，而不是改上游核心 settings：

```python
# data.user_settings 或本地镜像注入的等价 settings
TENANT_APPS = [
    "authentik.custom",
]
```

`authentik/custom/settings.py` 再注册具体业务 app：

```python
TENANT_APPS = [
    "authentik.custom.easyauth",
]
```

如果部署环境无法通过 `data.user_settings` 注入 app，才允许在本地 fork 中做一处最小 settings patch，把 `authentik.custom` 加入 `TENANT_APPS`。之后由 `authentik/custom/settings.py` 继续注册 `authentik.custom.easyauth`。该 patch 必须独立、可重复应用，不能混入业务逻辑。

### 实现拆分

#### API、路由与 service

推荐落点：

- `authentik/custom/apps.py`：定义本地扩展聚合 app config，不承载业务逻辑。
- `authentik/custom/settings.py`：注册 `authentik.custom.easyauth`，后续本地扩展也只改这里。
- `authentik/custom/easyauth/apps.py`：定义 EasyAuth 扩展 app config。
- `authentik/custom/easyauth/urls.py`：通过 `api_urlpatterns` 暴露 API 路由。
- `authentik/custom/easyauth/api/dingtalk_managed_users.py`：定义 managed-users serializer、permission、APIView。
- `authentik/sources/oauth/dingtalk/managed_users.py`：承载递归解析、stale 判断和 linked user 映射，作为 DingTalk 二开层的通用目录 service。
- `authentik/custom/easyauth/dingtalk/managed_users.py`：只做 EasyAuth 响应适配；如果逻辑很薄，可以省略该文件，直接由 API view 调用 DingTalk service。
- `authentik/custom/easyauth/tests/`：放 EasyAuth 扩展自己的 API 和 service 测试。

路由仍保持对 EasyAuth 友好的路径：

```http
/api/v3/sources/oauth/dingtalk-directory/{source_slug}/managed-users/by-manager/{corp_id}/{manager_user_id}/
```

该路径优先由 `authentik.custom.easyauth.urls.api_urlpatterns` 挂载，避免 EasyAuth 专属路由进入 OAuth source app。如果团队希望所有 DingTalk directory API 都集中在 `authentik/sources/oauth/urls.py`，也可以把路由挂在那里；但实现仍应保持“DingTalk service 不依赖 EasyAuth，EasyAuth API 只做契约适配”的分层。

第一版不新增 `EasyAuthSource`，也不改 OAuth provider/token 主流程。`authentik.custom.easyauth` 只读取既有 OAuth/DingTalk 数据模型。

#### DingTalk 人员到 Authentik 用户映射

映射规则：

1. 用 `source_slug` 找到 enabled DingTalk `OAuthSource`。
2. 用 `(source, corp_id, user_id)` 查询 `DingTalkDirectoryUser`。
3. 用 `source_identifier = f"{corp_id}:{user_id}"` 查询 `UserOAuthSourceConnection`。
4. 0 条连接表示 unbound。
5. 1 条连接表示 bound，输出对应 `connection.user.uid` 作为 `authentik_subject`，并输出 `connection.user.is_active`。
6. `connection.user.pk` 只能作为可选 diagnostics 输出。
7. 多条连接表示 binding conflict，接口失败。

当前 `UserSourceConnection` 数据库唯一约束只有 `(user, source)`，没有 `(source, identifier)` 唯一约束。第一版不强行增加全局数据库约束，避免影响 OAuth、SAML、LDAP、Plex 等其他 source connection 历史数据；但 managed-users 查询路径必须严格检测并拒绝重复绑定。后续可以在数据清理完成后评估数据库唯一约束。

#### 递归下级计算

递归计算基于 `DingTalkDirectoryUser.manager_user_id`：

- 入口是 `{corp_id, manager_user_id}`。
- 每一层查询同一 source、同一 corp、`is_deleted=false`、`manager_user_id=<当前 user_id>` 的目录用户。
- 递归结果按 `source_user_id` 去重。
- manager 本人永远不进入结果。
- 需要维护 visited 集合，避免 DingTalk 数据错误导致环。
- 递归深度应设置上限，可复用或对齐现有 manager chain 深度限制。
- 多部门归属只作为诊断和展示字段，第一版递归关系以 `manager_user_id` 为准。

#### stale 与目录状态

stale 判断基于 `DingTalkDirectorySyncStatus`：

- `status=success` 且 `finished_at` 在有效窗口内时视为 fresh。
- 没有成功同步记录、最近同步失败或超过有效窗口时返回 `stale=true`。
- stale 时接口仍可返回最后一次缓存目录计算结果。
- 没有任何目录缓存时不能猜测结果，EasyAuth 不应扩大授权。

第一版继续使用 `last_synced_at` 和 `stale`。`directory_version` 暂不作为前置需求，后续如果 EasyAuth 或下游需要比较快照版本，再在 DingTalk sync status 上补充稳定版本号。

#### API 权限与审计

managed-users 接口会暴露组织关系和 linked Authentik 用户状态，权限不应弱于现有 DingTalk 用户目录 API：

- 需要 source read 权限。
- 需要 `view_dingtalkdirectoryuser` 权限。
- 不暴露 DingTalk `mobile`、`email`、`raw`、`union_id`、`open_id` 等敏感字段，除非后续有明确审计需求。
- 冲突、stale、未绑定等诊断应进入日志或事件，便于 EasyAuth 健康检查和联调排查。

#### 测试覆盖

Authentik 侧测试按职责拆分：

- DingTalk 递归、stale、绑定映射的纯 service 测试放在 `authentik/sources/oauth/tests/` 或 DingTalk 二开层对应测试目录。
- EasyAuth API 路由、响应字段、错误码和启用/未启用行为测试放在 `authentik/custom/easyauth/tests/`。
- 避免把 EasyAuth 授权语义测试混入 DingTalk 目录 service 测试。

至少覆盖：

- 直接下级。
- 多层递归下级。
- 无下级。
- manager 本人不进入结果。
- 未绑定用户返回 `binding_status=unbound`。
- inactive Authentik 用户返回 `authentik_user_active=false`。
- deleted 或 inactive DingTalk 目录用户状态正确。
- stale sync status 返回 `stale=true`。
- 同一 `source + identifier` 绑定多个 Authentik 用户时接口失败。
- 管理链出现环或超过深度限制时不会死循环。

### 短期替代方案

如果 Authentik 暂不提供最终管理对象接口，也可以在 `/users/` 列表中增加 linked Authentik 字段，由 EasyAuth 拉取全量 DingTalk 用户并本地计算递归下级。

该方案只适合短期保留，因为它会把 DingTalk 目录字段完整性、递归算法和用户绑定歧义转移到 EasyAuth。长期推荐 Authentik 提供归一化后的管理对象接口。

### 实现前确认项

- DingTalk 部门用户列表是否稳定返回完整 `manager_user_id` 和 `dept_id_list`。
- 一个用户属于多个部门时，当前同步逻辑是否会覆盖或遗漏部门列表。
- 真实租户中离职、禁用、删除人员在 DingTalk API 中分别如何体现。
- `User.uid` 是否与 EasyAuth 当前登录链路使用的 Authentik 外部用户 ID 一致；如果当前 OIDC provider 的 subject 不是 `User.uid`，需要在 EasyAuth 接入侧统一映射。
- DingTalk 目录 API 是否需要在第二阶段增加 `directory_version`，用于 EasyAuth 和下游判断快照新旧。
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

1. Authentik DingTalk 二开层增加通用 managed-users service，输出递归下级、绑定状态、active 状态和 stale 状态。
2. Authentik 新增 `authentik.custom` 聚合 app，并通过部署侧 settings 或一处最小 settings patch 启用。
3. `authentik.custom.easyauth` 增加 EasyAuth-facing DingTalk 管理对象接口，输出 linked Authentik subject、active 状态和 stale 状态。
4. EasyAuth 增加 `MANAGED_USERS` 策略模型、resolver 注册、配置健康检查和联调预览。
5. EasyAuth 控制台增加 App 默认策略和 `AuthorizationGroupGrant` 覆盖策略配置。
6. EasyAuth 扩展公共权限查询响应，返回 `resolved.user_ids`。
7. EasyAuth 自助申请流程支持管理范围组的动态审批人。
8. EasyTrade 扩展 EasyAuth 客户端模型、快照保存和本地人员映射。
9. EasyTrade 替换旧 `MANAGED` 本地算法，所有 owner 过滤消费 `MANAGED_USERS`。
10. 使用真实 DingTalk 租户数据验证经理、兼职、多部门、无上级、无下级、inactive 用户和 stale 目录场景。

## 验证要求

Authentik：

- 测试 `authentik.custom.easyauth` 未启用时，原 Authentik OAuth/DingTalk directory API 行为不变。
- 测试 `authentik.custom.easyauth` 启用后，managed-users API 通过独立 app `api_urlpatterns` 挂载。
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
- EasyAuth 需要确认当前登录链路中的 Authentik 外部用户 ID 是否已经等于 `User.uid`；不一致时必须在接入侧统一映射，不能让 `MANAGED_USERS` 使用第二套人员 ID。
- EasyTrade 需要排查所有绕过集中 scope resolver 的查询。
- 如果 Authentik 暂不提供管理对象接口，EasyAuth 本地计算方案只能作为保留项，不能长期沉淀为第二套组织源模型。
- Microsoft Entra 支持必须通过通用组织源接口扩展，不能复制 DingTalk 专用字段到授权模型。
