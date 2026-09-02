# ADR-005：NetBird 供给连接器与 management fork 边界

## 状态

已接受（决策于 2026-07-07，实施完成于 2026-07-11）

## 日期

2026-07-07

## 背景

NetBird 是第一个由 EasyAuth 反向**供给**（provisioning）的外部系统：EasyAuth 不只是被下游查询，
还要把授权事实推成 NetBird 侧的用户与组关系。

难点在于 NetBird 社区版对外接 IdP 只有 JIT（just-in-time）路径：未知 JWT `sub` 首次登录时才创建用户，
且 auto_groups 为空。这形成一个 gap——EasyAuth 审批通过后，在员工首次登录 NetBird 之前，
权限无处安放；社区版也没有 SCIM 或等价的预创建接口
（`inviteNewUser` 的 guard 要求存在 idp-manager，而 Authentik idp-manager 的 `CreateUser` 是未实现 stub）。

## 决策

1. **维护一个最小面的 NetBird management 私有 fork**，只加预创建能力，不复刻企业版。
   - 补丁面只有两处：`POST /api/users` 接受可选显式 `id`（复用已有的
     `SaveOrAddUser(addIfNotExists=true)`，不新写业务逻辑、不改 JIT）；
     被拦用户的提示文案改为 `NB_BLOCKED_USER_MESSAGE` 可配置。
   - 预创建时 role 白名单**只允许 `user`**（`owner` 会触发所有权转移，`admin` 不应由供给通道产生），
     并做 id 非空/长度上限与邮箱查重。
   - 客户端（desktop/mobile/CLI）与 dashboard 一律用官方原版，补丁只落在 management。
   - `management/` 是 AGPL-3.0（仓库其余为 BSD-3）。公司内部自用不触发义务；
     **若未来把该管理面作为服务提供给公司外用户，必须依 AGPL 提供含补丁的源码。**

2. **预创建用户的 `id` 必须等于 Authentik user uuid（= 未来的 OIDC `sub`）。**
   首次登录时 NetBird 的 JIT 会原样收养该用户，不覆盖 role 与 API 签发的 auto_groups。
   `sub` 与预创建 `id` 不一致会造成"同邮箱双用户"，属必须告警的对账异常。

3. **授权的唯一来源仍是 EasyAuth 对账，不引入第二条写入通道。**
   - NetBird 的 JWT 组同步**关闭**——否则 JWT 与 API 两个来源会双写 auto_groups。
   - 部署时**删除 Default（All↔All）策略**，网络策略只对 EasyAuth 映射组定义；
     不删则任何设备全网互通，EasyAuth 管不住，这是硬前提。
   - `UserApprovalRequired` 与 `GroupsPropagationEnabled` 都保持默认 `true`：
     前者让未经 EasyAuth 授权而自行登录的人天然落到 `Blocked+PendingApproval`（默认拒绝），
     后者让 auto_groups 变更回溯已注册设备并即时重推网络图。
   - 管理员在 NetBird 侧手工加进映射组的成员，会被下一轮对账矫正移除。

4. **不依赖 NetBird 的事件 API。** 社区版无 webhook，事件 API 无游标；
   EasyAuth 连接器一律走周期性对账 + 离职快路径。

5. **撤权靠对账移组 + peer login expiration 兜底**（建议 12–24h）：
   移组后网络图即时重推，设备立即失去网段访问；即便撤权前有存活会话，到期也会强制重认证，
   而此时 Authentik 侧账号已禁用。

## 备选方案

### 只用 JIT，不 fork

优点：完全不维护补丁，升级无成本。

缺点：审批通过到权限生效之间存在不可控 gap（取决于员工什么时候第一次登录 VPN），
且首次登录后还要等下一轮对账才入组。授权体验与"审批通过即权限就位"的产品承诺不符。

结论：拒绝。改为把补丁面压到最小（两处、行数极小）来控制升级成本。

### 复刻企业版 SCIM

优点：走标准协议，接口面更"正规"。

缺点：实现量远超需要；EasyAuth 只需要"按显式 id 建用户并绑组"这一个动作。

结论：拒绝。

### 在 NetBird 侧开 JWT 组同步，由 Authentik 携带组信息

优点：不需要 EasyAuth 对账。

缺点：授权事实来源会从 EasyAuth 漂到 Authentik claim，违反 ADR-001 的边界；
且 JWT 与 API 两套 auto_groups 来源难以合并。

结论：拒绝。

## 后果

- EasyAuth 侧的实现落在 `src/easyauth/connectors/netbird/`：
  `client.create_user()` 在 `POST /api/users` 的 body 里携带 `id`；
  连接器配置项为 `api_url`、`api_token`（service user PAT，加密落库）、
  `precreate_users`、`block_users_without_grant`。
- NetBird 是出站推送供给，不是下游拉取授权。启用中的 `ConnectorInstance` 即表示该 App
  已接入连接器；配置完整性不把入站静态 token / OAuth2 client 列为 blocking
  （`active_credential_missing` 只约束未接入连接器的 App）。
- `precreate_users=false` 时连接器退化为纯 JIT 收敛（等员工首次登录后下一轮对账），
  这是**对接官方原版 management 时的可用降级路径**——预创建能力依赖 fork 补丁。
- PAT 只发给 EasyAuth 连接器，需定期轮换。
- fork 升级流程：在新的上游稳定 tag 上 rebase 两个补丁 commit → 跑 Go 单测 → 重建
  `netbird-management-jiefakj:local` 镜像 → 本机联调复验预创建收养与默认拒绝两个场景，再上生产。
- 本 ADR 由 `docs/plans/2026-07-07-netbird-server-fork-plan.md` 归档而来。
  补丁实现、部署基线清单与联调场景矩阵留在 fork 仓库
  （`12dora/netbird`，commit `0c83bc5fd` 预创建 API、`e931f0897` 可配置文案，
  配套 `infrastructure_files/jiefakj-lab/` 与其 `PRODUCTION.md`）。
