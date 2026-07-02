# EasyAuth 领域词表

## 授权事实

授权事实是 EasyAuth 已经落库并可被下游应用查询的权限结果。授权事实只能由 EasyAuth 的授权服务产生，不能由 Authentik、DingTalk 或下游应用直接写入。

## 授权范围

授权范围是某个权限在业务数据上的可见或可操作边界。`Permission.key` 表示能力，授权范围表示这项能力可以作用到哪些业务对象或人员。

## `MANAGED_USERS`

`MANAGED_USERS` 是一个人员集合范围，表示当前用户在指定 App、指定权限下可以管理的下级人员集合。集合成员使用 active Authentik 用户 ID 表示，不包含当前用户本人。

## 管理范围计算方式

管理范围计算方式是 EasyAuth 将组织关系解析成 `MANAGED_USERS` 的策略。第一版支持 `dingtalk_manager_chain`，控制台展示为“按钉钉主管关系”。

## 管理对象快照

管理对象快照是 EasyAuth 在权限查询响应中返回的已解析人员集合。下游应用必须把它保存到本地授权快照中，用本地数据过滤业务查询，不能在每次业务查询时实时请求 EasyAuth。

## 组织源

组织源是 Authentik 向 EasyAuth 暴露的公司组织关系来源。第一版只接入 DingTalk 目录；后续可以扩展到 Microsoft Entra，但 EasyAuth 的授权模型不直接依赖某个组织源的原始字段。

## 下游授权快照

下游授权快照是 EasyTrade 等应用从 EasyAuth 拉取并落地的权限结果，包含 `snapshot_version`、`expires_at`、授权 grant 列表以及 `MANAGED_USERS` 的解析结果。业务查询只能依赖本地快照。
