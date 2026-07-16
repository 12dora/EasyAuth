# NetBird 服务端改造方案（management fork）

> 日期：2026-07-07
> 状态：设计稿（未开始实施）
> 范围：**仅 NetBird management 服务端**。硬约束：客户端（desktop/mobile/CLI）与 dashboard 保持官方原版，不做任何改动。
> 源码：`/Users/konata/code/netbird`（浅克隆，main@`47352e6e`，2026-07-06，v0.75.0-rc.5 之后）
> 姊妹篇：`EasyAuth/docs/plans/2026-07-07-netbird-connector-framework-plan.md`（消费本 fork 能力的 EasyAuth 连接器）

---

## 0. 目标与非目标

**目标**：

1. 消除外接 IdP 的 JIT gap——允许 EasyAuth 在员工首次登录前**预创建用户并绑定组**，审批通过即权限就位（P1）。
2. 未授权用户被拦时给出可引导的提示文案（P2，服务端返回、客户端原样显示，不改客户端）。
3. 给出与 EasyAuth 连接器配套的部署基线配置（§3）与 fork 工程化流程（§4）。

**非目标**：不复刻企业版 SCIM；不动客户端与 dashboard；不启用 JWT 组同步（授权只来自 EasyAuth，见姊妹篇）；不引入本地用户/内嵌 IdP（身份唯一来源是 Authentik）。

---

## 1. 已核实的源码事实（main@47352e6e）

改造建立在以下经源码核实的事实上（路径相对克隆根目录）：

| # | 事实 | 证据 |
|---|------|------|
| N1 | JIT：未知 JWT `sub` 首登时创建 `NewRegularUser`（role=user、**空 auto_groups**）；**已存在同 ID 用户则原样复用**，不覆盖 role/email/API 签发的 auto_groups，仅刷新 LastLogin | `management/server/account.go:1767,1309,1363`、`types/user.go:244`、`user.go:231-249` |
| N2 | JWT 组同步（若开启）只增删 `Issued=="jwt"` 的组，API 签发的组不受影响 | `account.go:1603,2082-2102` |
| N3 | 阻止预创建的 guard 是**运行时判断**非构建标签：`inviteNewUser` 里 `idpManager == nil` 即报错；Authentik idp-manager 的 `CreateUser` 也是未实现 stub | `user.go:82-84`、`idp/authentik.go:331-333` |
| N4 | **业务层已具备预创建能力**：`SaveOrAddUser(ctx, accountID, initiator, user, addIfNotExists=true)` 支持显式 ID + auto_groups 建用户，含组校验与审计事件，已在 `account.Manager` 接口上，只是 HTTP 层从未以 true 调用 | `user.go:559,836-854,925-934`、`account/manager.go:51` |
| N5 | `UserCreateRequest` DTO 无 `id` 字段（email/name/role/auto_groups/is_service_user） | `shared/management/http/api/openapi.yml:565-593`、`types.gen.go:5510` |
| N6 | auto_groups：新设备注册时即入组；`GroupsPropagationEnabled`（新账户默认 true）下变更会**回溯已注册设备**并即时重推网络图 | `peer.go:698`、`user.go:806-827,682-687`、`account.go:2050` |
| N7 | 新账户默认 `UserApprovalRequired=true`：JIT 自行登录的用户自动 `Blocked+PendingApproval`（天然默认拒绝）；Blocked 用户设备注册被拒 | `account.go:2054-2056,1372-1375`、`peer.go:684-686` |
| N8 | 组成员是 **peers**（无 user 成员概念），用户与组的关系仅通过 `User.AutoGroups` | `types/group.go:15-33`、`types/user.go:87-88` |
| N9 | 用户状态非持久列：只持久化 `Blocked`/`PendingApproval`；"invited"是从 IdP 元数据推导的展示态 | `types/user.go:91-94,166-181` |
| N10 | `management/` 目录许可证为 **AGPL-3.0**（仓库其余 BSD-3）；相关路径无企业版构建标签 | `LICENSE`、`management/LICENSE`、`go.mod:82` |
| N11 | 社区版无 webhook；事件 API 无游标（最多 10000 条倒序）；首次 dashboard 登录不发事件 | `handlers/events/events_handler.go:24-25`、`types/user.go:114-116` |

---

## 2. 改造项

### P1：预创建常规用户 API（核心，~25–40 行）

允许 `POST /api/users` 携带显式 `id`（= 未来 JWT sub = Authentik user uuid）预创建常规用户。

**改动 1 — OpenAPI 契约**：`shared/management/http/api/openapi.yml` 的 `UserCreateRequest` 增加可选字段 `id`（string），按仓库既有流程重新生成 `types.gen.go`（确认 `make generate` / oapi-codegen 入口）。

**改动 2 — handler 分支**：`management/server/http/handlers/users/users_handler.go` `createUser`（:139-187）：

```go
if req.Id != nil && !req.IsServiceUser {
    // 预创建路径：绕过邀请 guard，直接落库；首登由 JIT 原样收养（N1/N4）
    user := &types.User{
        Id: *req.Id, Role: role, AutoGroups: autoGroups,
        Email: email, Name: name,
        Issued: types.UserIssuedAPI, CreatedAt: time.Now().UTC(),
        Blocked: false, // 预创建即已获 EasyAuth 授权，绕过 PendingApproval 属预期语义（N7）
    }
    return h.accountManager.SaveOrAddUser(ctx, accountID, initiatorID, user, true)
}
// 原有路径（service user / 邀请）保持不动
```

**校验规则**（handler 内，全部必须）：

| 规则 | 原因 |
|------|------|
| `role` 白名单：仅允许 `user` | `role=owner` 会触发所有权转移（`user.go:856-866`）；admin 不该由供给通道产生 |
| `id` 非空、trim、长度上限 | 主键卫生 |
| 邮箱重复主动校验（复用邀请路径的检查，`user.go:172-188`） | 预创建路径原生不查重，避免 dashboard 展示混乱 |
| `CreatedAt` 显式赋值 | `SaveOrAddUser` 创建路径原样使用传入结构（`user.go:844`） |

**语义确认**：预创建用户 `Blocked=false` 即"已授权"；未预创建者走 JIT 默认拒绝（N7）——两条路径合成"只有 EasyAuth 授权过的人能用 VPN"。

### P2：被拦用户提示文案（可选，~10 行）

Blocked/PendingApproval 用户设备注册被拒时（`peer.go:684-686` 及 dashboard 侧 `user.go:1409-1411`），错误信息替换为可配置文案，新增 env（如 `NB_BLOCKED_USER_MESSAGE`，默认保持原文案）：

> `无 VPN 权限，请前往 https://iam.jiefakj.com 申请`

客户端与 dashboard 显示的均为服务端返回文本，**无需改客户端**；CLI 完整显示、桌面托盘可能截断——展示效果列入 §5 联调验证项，若截断严重则文案缩短为纯 URL。

### 明确不做

- 不实现 SCIM 端点（企业版能力，不复刻）。
- 不改 JIT 创建逻辑本身（N1 行为正是收养预创建用户所依赖的）。
- 不改事件 API（EasyAuth 连接器用周期对账，不依赖事件，见姊妹篇 §3.6）。

---

## 3. 部署基线配置（非代码，与补丁同等重要）

| 配置项 | 值 | 原因 |
|--------|-----|------|
| IdP | Authentik OIDC（`https://auth.jiefakj.com/application/o/netbird/`），单账户模式 | 纯身份源；单账户保证 JIT 与预创建落同一 account（`account.go:1853-1855`） |
| **默认策略** | **删除 Default（All↔All）策略** | 不删则任何设备全网互通，EasyAuth 管不住（硬前提）；删除前先建好自定义组策略 |
| 网络策略 | 仅对映射组（`vpn-users`/`vpn-dev`…）定义 | 授权粒度全部由 EasyAuth 映射决定 |
| `UserApprovalRequired` | 保持默认 true | 默认拒绝（N7） |
| `GroupsPropagationEnabled` | 保持默认 true | auto_groups 回溯已注册设备（N6） |
| JWT 组同步 | **关闭** | 授权只来自 EasyAuth，避免双写来源 |
| Peer login expiration | 12–24h | 撤权兜底：即便 block 前有存活会话，到期强制重认证 |
| Service user + PAT | 专用 service user（admin 权限），PAT 交 EasyAuth 连接器配置 | 对账通道；PAT 定期轮换 |

---

## 4. Fork 工程化

1. **补全仓库**：当前是浅克隆——`git fetch --unshallow && git fetch --tags`。
2. **基线选择**：不基于 main（rc 波动），切到最新稳定 tag（v0.75.0 正式发布后以其为基线；否则退到 v0.74 最新 patch）。cherry-pick 验证 §1 事实在基线 tag 上成立（均为存在已久的稳定路径，预期无漂移）。
3. **分支模型**：`jiefakj/base-v0.75.x` 上叠两个独立 commit（P1、P2），补丁面刻意最小化以便升级 rebase。
4. **镜像构建**：仿照 `authentik-dingtalk:local` 的本地定制模式，构建 `netbird-management-jiefakj:local`（仓库自带 Dockerfile）；signal/relay/dashboard/client 全部用官方镜像。
5. **升级流程**：新版本发布 → 在新 tag 上 rebase 两个 commit → 跑 §5 单测 → 重建镜像 → 先在本机联调环境验证 §5 场景矩阵再上生产。
6. **AGPL 合规**（N10）：`management/` 为 AGPL-3.0。公司内部自用无义务触发；**若未来把该管理面作为服务提供给公司外用户，须依 AGPL 提供含补丁的源码**。补丁仓库建议私有 fork + 保留完整许可证文件。

---

## 5. 测试与联调

**Go 单测**（随补丁提交）：P1 handler 分支——预创建成功/重复 ID/role=owner 拒绝/邮箱重复拒绝；P2 文案 env 覆盖。

**场景矩阵**（本机联调环境，配合 EasyAuth 连接器 M4）：

| # | 场景 | 预期 |
|---|------|------|
| 1 | EasyAuth 审批通过 → 预创建 → 员工首次登录 | 用户被原样收养，设备注册即入映射组，策略即刻生效（零 gap） |
| 2 | 未申请员工直接装客户端登录 | JIT 创建 → Blocked+PendingApproval，设备注册被拒，显示 P2 文案（记录 CLI/托盘实际展示效果） |
| 3 | 在线用户被 EasyAuth 撤权 | 对账移组 → 网络图即时重推，设备失去网段访问（不需重新登录）；无剩余组则 block |
| 4 | 离职 | 快路径 block → 存活会话到 login expiration 强制掉线；Authentik 侧账号已禁用，无法重认证 |
| 5 | 管理员在 NetBird 手工把用户加进映射组 | 下轮对账矫正移除（映射范围内以 EasyAuth 为准） |
| 6 | fork 升级 rebase 后 | 单测全绿 + 场景 1/2 复验 |

---

## 6. 风险与对策

| 风险 | 对策 |
|------|------|
| 基线 rc 不稳定 | §4.2：锁稳定 tag，不跟 main |
| `sub` 与预创建 `id` 不一致（OIDC 配置变更） | 联调时固化断言：Authentik user uuid == NetBird JIT user id；EasyAuth 连接器对账发现"同邮箱双用户"时告警 |
| 上游重构 users handler 导致 rebase 冲突 | 补丁面仅两处、行数极小；每次升级跑单测兜底 |
| P2 文案在桌面客户端被截断 | 联调验证；必要时文案退化为纯 URL |
| 误用预创建接口制造特权账号 | role 白名单仅 `user`；PAT 只发给 EasyAuth 连接器，配置 superuser-only（姊妹篇 §3.7） |

---

## 7. 决策清单

1. 只改 management 服务端；客户端与 dashboard 保持官方原版（用户硬约束）。
2. P1 复用 `SaveOrAddUser(addIfNotExists=true)`，不新写业务逻辑，不动 JIT。
3. 预创建用户 `Blocked=false` 直接生效；未预创建者靠 `UserApprovalRequired` 默认拒绝——不另设准入开关。
4. role 白名单仅 `user`。
5. 基线锁稳定 tag，两个独立小 commit，升级走 rebase + 场景复验。
6. JWT 组同步关闭，授权单一来源为 EasyAuth 对账。
7. 不复刻 SCIM，不依赖事件 API。
