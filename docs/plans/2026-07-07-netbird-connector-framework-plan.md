# NetBird 接入与出站供给连接器框架 — EasyAuth 改造方案（前后端）

> 日期：2026-07-07
> 状态：设计稿（未开始实施）
> 范围：EasyAuth（后端 + 控制台前端）。NetBird 服务端改造见姊妹篇 `docs/plans/2026-07-07-netbird-server-fork-plan.md`。
> 关联：`ADR-001-业务授权运营边界`、`docs/plans/2026-07-06-lifecycle-approval-teams-plan.md`（站内审批闭环 / 生命周期）、本方案 §6 配套 ADR-003 草案。

本文回答三个问题：

1. NetBird（及未来同类"只能被 API 驱动、不接 SDK"的系统）如何接入 EasyAuth 的授权体系？
2. 如何避免"每接一个系统写一个一次性适配器"导致的代码腐化？——**出站供给连接器（Provisioning Connector）可插拔框架**。
3. 改造完成后，管理员如何**纯图形化**地接入 NetBird？

---

## 0. 背景与目标

- 员工 VPN 准入要求与 EasyTrade 权限同一套体验：**在 EasyAuth 门户申请 → 站内审批 → 生效**；Authentik 保持纯身份源（钉钉 OIDC），不承载任何授权语义。
- EasyTrade 是**拉取模型**（SDK 查权限快照）；NetBird 是网络层系统，不可能接 SDK，必须由 EasyAuth **主动推送**（写 NetBird 管理 API）。这是 EasyAuth 第一次出现"推送供给"类需求，且可预见不会是最后一次（未来的监控、代码仓库、网关等）。
- 因此本方案不做 NetBird 专用适配器，而是建立**连接器框架**：核心一次建好，NetBird 是第一个连接器实现。

**非目标**：不实现 SCIM Provider/Source（维持既有需求边界）；不迁移既有的 Authentik 离职禁号逻辑（保持稳定，见 §5.2）；不改变任何公共 API 契约。

---

## 1. 已核实的现状事实

方案建立在以下经代码核实的事实上（EasyAuth 侧本仓库，NetBird 侧引用姊妹篇 §1）：

| # | 事实 | 证据 | 影响 |
|---|------|------|------|
| F1 | EasyAuth 唯一的出站推送通道是 per-app webhook（HMAC 签名、5 次指数退避重试、投递记录幂等），语义是"通知能收 HTTP 回调的下游 APP"；NetBird 无法消费 | `webhooks/delivery.py:37,82-141`、`tasks/webhooks.py:19-40` | 需要新的"EasyAuth 主动调用外部 API"通道；webhook 的持久化/重试/幂等模式值得复制 |
| F2 | 授权事实变更全部收口在 `GrantService` 六个方法（create/change/revoke/revoke_for_user/emergency_revoke_for_user/expire），事务原子，**无 Django signals**，事件只进审计日志 | `grants/services.py:48-113`、`grants/lifecycle.py:50-165`、`grants/operations.py:91-108` | 连接器事件挂点只需改一处；必须显式埋点（无信号可订阅） |
| F3 | 凭据加密有成熟房子模式：`EncryptedCharField`（`easyauth.config.crypto`，`EASYAUTH_FIELD_ENCRYPTION_KEY`），`IntegrationSettings` 单例演示了 DB 覆盖 env 的运行时配置 | `applications/integration_settings.py:24-119` | 连接器配置中的 token 复用该模式 |
| F4 | 控制台已支持**手工创建 App**（不依赖 manifest-sync），App 工作台是 tabs 结构（Overview/Manifest/Catalog/Credentials/Matrix/Rules/Webhook/Guide/QueryTest），前端 React 19 + TanStack Query/Table + Toast + zh/en i18n | `admin_console/apps_api.py:68-76`、`frontend/src/pages/console/workspace/tabs/`、`frontend/src/components/ui/Toast.tsx` | "图形化接入 NetBird"的载体现成：新增一个工作台 Tab 即可 |
| F5 | 管理端 API 约定：`/console/api/v1/` 命名空间、session + CSRF、`require_console_actor()`、superuser 由 `EASYAUTH_CONSOLE_SUPERUSER_GROUPS` 判定 | `admin_console/request_guards.py`、`identity.py:42-47`、ADR-001 | 连接器管理端点全部落此约定 |
| F6 | **`authentik_user_id` 是跨系统用户主键**（`UserMirror.authentik_user_id` = OIDC sub） | 7-06 方案 §0.4、`accounts/models.py` | 恰好等于 NetBird 外接 IdP 模式下的用户 ID（JWT sub），映射零成本 |
| F7 | Celery beat 在 `config/settings/base.py:309-324` 集中定义，任务名约定 `easyauth.<域>.<动作>`，周期由 `EASYAUTH_*_SECONDS` env 覆盖；钉钉 Stream 已有"5 秒合流去抖"模式 | `tasks/dingtalk_stream.py:72-75` | 连接器的周期对账 + 事件去抖直接套用 |
| F8 | NetBird 侧（fork 后）：用户 `auto_groups` 变更会对已注册设备回溯生效并即时重推网络图（`GroupsPropagationEnabled` 默认开）；预创建的用户会被首次登录原样收养；未预创建的自行登录用户默认 `Blocked+PendingApproval`（天然默认拒绝） | 姊妹篇 §1 | 对账器**只需维护 `user.auto_groups` 一个字段**，无需直接操作组的 peers 列表 |

**ADR-001 兼容性检查**：连接器不产生授权事实（只读 `AccessGrant` 投影到外部系统）、管理端点走 `/console/api/v1/` + session、授权仍只经 `GrantService` 产生——三条核心边界全部满足。"不实现 SCIM Provider/Source"维持不变（连接器是私有 API 驱动，非 SCIM；未来若做 SCIM 连接器需先修订需求边界）。

---

## 2. 总体设计

```
员工 ──申请──▶ EasyAuth 门户 ──站内审批──▶ GrantService（授权事实，唯一来源）
                                              │ on_commit 事件（F2 挂点）
                                              ▼
                                   connectors 框架（新 Django app）
                                   ├─ 注册表：EASYAUTH_CONNECTORS
                                   ├─ ConnectorInstance（per-app 配置，加密）
                                   ├─ ConnectorMapping（授权组 ↔ 外部组）
                                   ├─ 周期对账 + 事件快路径（去抖）
                                   └─ ConnectorSyncRun（运行审计）
                                              │  第一个实现
                                              ▼
                                   NetBird 连接器 ──▶ NetBird 管理 API
                                   （预创建用户 / auto_groups / block）
员工 ──装客户端─▶ Authentik OIDC（纯身份）──▶ NetBird 设备注册，组策略即刻生效
```

三条设计原则（写入 ADR-003，§6）：

1. **连接器是授权事实的只读投影**。它把 `GrantService` 已产生的事实物化到外部执行点，绝不反向产生或修改授权。
2. **对账收敛为主，事件快路径为辅**。幂等全量对账是正确性的唯一依据；grant 事件只用来"提早触发一次对账"，丢失事件不影响最终一致。
3. **连接器失败绝不阻塞授权事务**。全部异步（`transaction.on_commit` + Celery），失败进重试与健康面板，不回滚授权。

---

## 3. 后端设计

### 3.1 新 Django app：`easyauth/connectors/`

```
src/easyauth/connectors/
├── apps.py                 # ConnectorsConfig，注册进 INSTALLED_APPS
├── base.py                 # BaseConnector 抽象接口 + DesiredState/ReconcileReport 数据类
├── registry.py             # 注册表：从 settings.EASYAUTH_CONNECTORS 加载
├── models.py               # ConnectorInstance / ConnectorMapping / ConnectorSyncRun
├── dispatch.py             # grant 事件分发 + 去抖
├── services.py             # 对账编排（desired state 构建、run 记录、错误处理）
├── netbird/
│   ├── connector.py        # NetBirdConnector(BaseConnector)
│   └── client.py           # NetBird 管理 API 薄封装（users/groups/peers）
└── migrations/
```

### 3.2 `BaseConnector` 接口

```python
class BaseConnector(ABC):
    key: str                      # "netbird"
    display_name: str             # "NetBird VPN"
    config_schema: dict           # JSON Schema；"x-secret": true 标记加密字段（前端渲染密码框、后端加密落库）

    @abstractmethod
    def test_connection(self, config: dict) -> ConnectorProbe: ...
    @abstractmethod
    def list_external_groups(self, config: dict) -> list[ExternalGroup]: ...   # 映射选择器数据源
    @abstractmethod
    def reconcile(self, instance: ConnectorInstance, desired: DesiredState) -> ReconcileReport: ...
    def on_user_offboarded(self, instance, user) -> None: ...                  # 可选快路径（默认触发 reconcile）
```

`DesiredState` 由框架统一构建（连接器不直接查 grant 表，保持只读投影边界）：对该 App 的全部 `is_current=True, status=active` 的 `AccessGrant`，经 `ConnectorMapping` 把 `AccessGrantGroup` 引用的授权组映射为外部组名，产出 `{authentik_user_id: {外部组名集合}}`。**v1 约束：连接器型 App 的授权目录只发布授权组（kind=bundle）**，不支持散装 permission 映射（目录里不发布即可，无需代码限制）。

### 3.3 模型

| 模型 | 字段要点 | 说明 |
|------|---------|------|
| `ConnectorInstance` | `app` FK、`connector_key`、`enabled`、`config_encrypted`（EncryptedTextField 存 JSON，`x-secret` 字段整体随载荷加密）、`reconcile_interval_seconds`（默认 300）、`last_reconcile_at/last_status/last_error/consecutive_failures`；unique(app, connector_key) | 配置与健康状态。凭据加密复用 F3 模式 |
| `ConnectorMapping` | `instance` FK、`authorization_group` FK、`external_ref`（外部组名/ID）、`auto_create`（bool，外部组不存在时是否创建）；unique(instance, authorization_group) | 授权组 ↔ 外部组 |
| `ConnectorSyncRun` | `instance` FK、`trigger`（periodic/event/manual/offboard）、`started_at/finished_at`、`status`（success/partial/failed）、`stats`（JSON：users_precreated/groups_added/groups_removed/users_blocked/users_unblocked/skipped）、`error` | 运行审计，控制台展示；保留最近 N 条（清理任务） |

### 3.4 注册与发现（可插拔机制）

```python
# config/settings/base.py
EASYAUTH_CONNECTORS = env_list(
    "EASYAUTH_CONNECTORS",
    default=["easyauth.connectors.netbird.connector.NetBirdConnector"],
)
```

注册表启动时按 dotted-path 导入。新增连接器 = 新增一个实现类 + 一行配置，**零核心代码改动**；第三方包形态（pip 安装后配 env）天然支持。不引入 entry_points 自动发现（隐式加载不利于审计，维持显式配置）。

### 3.5 事件挂点（F2 收口的唯一改动）

`GrantService` 六个方法在事务成功后统一调用：

```python
transaction.on_commit(lambda: dispatch_grant_event(app_id=..., user_id=..., action=...))
```

`dispatch.py` 逻辑：查该 app 是否有 `enabled=True` 的 `ConnectorInstance` → 有则以 **5 秒去抖窗口**（复用 F7 的钉钉 Stream 合流模式，cache 标记）入队 `reconcile_connector_instance` 任务。离职场景额外的快路径：`lifecycle` 的离职编排在调用 `revoke_for_user` 后，对启用实例逐个调 `on_user_offboarded`（NetBird 实现＝立即 block，秒级断连，不等对账周期）。

### 3.6 Celery 任务与 beat

| 任务 | 名称 | 触发 |
|------|------|------|
| 对账单实例 | `easyauth.connectors.reconcile_instance` | 事件去抖 / 手动 / 调度器分发；`acks_late`，实例级分布式锁防并发对账 |
| 周期调度器 | `easyauth.connectors.schedule_reconciles` | beat 每 60 秒，扫描到期实例（`last_reconcile_at + interval`）逐个入队 |
| 运行记录清理 | `easyauth.connectors.prune_sync_runs` | beat 每天 |

失败处理：单次对账失败记入 `ConnectorSyncRun(status=failed)` 与 `consecutive_failures`，不做任务级无限重试（下个周期自然重试）；`consecutive_failures >= 3` 纳入既有 `easyauth.health.run_dependency_health_checks` 的健康面板。

### 3.7 控制台 API（全部 `/console/api/v1/`，superuser）

连接器配置含基础设施凭据，权限对齐 `settings/integration`（superuser-only）；应用负责人可读状态、不可改配置。

| 端点 | 方法 | 用途 |
|------|------|------|
| `/apps/<app_key>/connectors` | GET / POST | 列出实例与可用连接器类型（含 config_schema）/ 创建实例 |
| `/apps/<app_key>/connectors/<id>` | PUT / DELETE | 更新配置、启停 / 删除 |
| `/apps/<app_key>/connectors/<id>/test` | POST | 测试连接（不落库，用请求体里的候选配置） |
| `/apps/<app_key>/connectors/<id>/external-groups` | GET | 外部组列表（映射选择器） |
| `/apps/<app_key>/connectors/<id>/mappings` | GET / PUT | 映射整表读写 |
| `/apps/<app_key>/connectors/<id>/reconcile` | POST | 手动触发对账 |
| `/apps/<app_key>/connectors/<id>/sync-runs` | GET | 运行历史（分页） |

配置变更全部走 `AuditService.record()`（对齐 `settings_api.py:105-110` 模式），敏感字段读接口只回显"已配置"占位。

### 3.8 NetBird 连接器实现

**config_schema 字段**：`api_url`、`api_token`（x-secret）、`precreate_users`（bool，默认 true，依赖 fork 补丁）、`block_users_without_grant`（bool，默认 true）、`blocked_hint_validated`（说明性只读，见姊妹篇 P2）。

**对账算法**（幂等，单实例串行）：

```
desired = 框架构建的 {authentik_user_id → 外部组名集合}
groups  = ensure_external_groups(映射表中 auto_create=true 且不存在的组)      # POST /api/groups
actual  = GET /api/users（过滤 service user；排除 role=owner/admin 的人工账号）
for uid, want in desired:
    if uid not in actual:
        precreate_users ? POST /api/users{id=uid, role=user, auto_groups=want,
                                          name/email ← UserMirror}            # fork 补丁端点
                        : 记 skipped（等首次登录后下轮收敛）
    else:
        managed = actual[uid].auto_groups ∩ 映射表管理的组集合                 # 只动映射内的组
        if managed != want 或 is_blocked: PUT /api/users/{uid}{auto_groups=(auto_groups−managed)∪want,
                                                             is_blocked=false}
for uid in actual − desired（仅 role=user、非 service）:
    移除映射管理的组；block_users_without_grant 且无任何映射组 → is_blocked=true
```

**护栏**（写死在连接器里）：绝不删除 NetBird 用户（保留审计与 peer 归属）；绝不触碰 service user 与 owner；只增删**映射表管理的组**，NetBird 侧手工维护的其他组不受影响；单轮 API 调用设上限（如 500 次）超限报 partial 防失控。

**离职快路径** `on_user_offboarded`：`PUT /api/users/{uid}{is_blocked=true}`，秒级断连；后续周期对账完成组清理。

### 3.9 未授权用户引导（钉钉消息，Phase 2 可选）

对账发现"NetBird 中存在但 desired 中没有"的用户（先装客户端的逆序用户，已被默认拒绝拦住），经 7-06 方案 M3 落地的钉钉出站客户端发工作通知附申请链接。本方案只预留 `ReconcileReport.ungranted_user_ids` 数据口，通知实现挂在钉钉审批中心工作完成之后。

---

## 4. 前端设计（控制台）

### 4.1 工作台新 Tab：`ConnectorTab`

位置：`frontend/src/pages/console/workspace/tabs/ConnectorTab.tsx`，注册进 ConsoleAppWorkspace 的 tabs（对齐 WebhookTab 的接线方式）。三块内容自上而下：

1. **状态卡**：实例启停开关、最近对账时间/结果 Badge、连续失败告警、"立即对账"按钮（toast 反馈，对齐 4f95756 的 toast 约定）。
2. **配置表单**：无实例时展示"选择连接器类型"（registry 下发的类型列表）；表单由 `config_schema` **schema 驱动渲染**——新增通用组件 `components/SchemaForm.tsx`，v1 支持 string/secret/boolean/number/enum 五种字段（够 NetBird 用，也是未来连接器的公共积木）；"测试连接"按钮调 `/test`，成功才允许保存启用。
3. **映射表**：TanStack Table，行 = 授权组（来自该 App 目录）↔ 外部组下拉（数据来自 `/external-groups`，支持"新建 <输入名>"选项即 auto_create）；整表保存。

### 4.2 触点清单

| 文件 | 改动 |
|------|------|
| `pages/console/workspace/tabs/ConnectorTab.tsx` | 新建 |
| `components/SchemaForm.tsx` | 新建（通用 schema 表单） |
| ConsoleAppWorkspace tabs 注册处 | +1 tab（仅 superuser 可见配置区，负责人只读状态） |
| `lib/api.ts` 调用侧 | 新增 connectors 相关请求封装 |
| `i18n/messages.ts` | 新增 `console.connector.*` 键（zh-CN + en 同步，维持 key parity） |

### 4.3 图形化接入 NetBird 的完整动线（验收动线）

1. 控制台 → 应用 → 新建应用 `netbird`（现有手工创建路径，F4）。
2. Catalog Tab：创建授权组，如 `vpn-users`（基础准入）、`vpn-dev`（研发网段），标记 requestable。
3. Rules Tab：配置审批人（站内审批，现有能力）。
4. **Connector Tab：选择 "NetBird VPN" → 填 api_url + token → 测试连接 → 保存**。
5. **映射表：`vpn-users` → NetBird 组 `vpn-users`（新建）**，保存 → 启用实例 → 首轮对账绿灯。
6. 员工在门户申请 `vpn-users` → 审批通过 → 对账推送 → 员工装客户端登录即通。

全程零代码、零 SSH。这条动线即 M4 的端到端验收标准。

---

## 5. 与既有机制的关系

### 5.1 webhooks vs connectors

两者并存、定位互补：**webhook = 通知能收回调的下游 APP**（拉取模型的补充）；**connector = 驱动收不了回调的外部系统**（推送模型）。不合并：webhook 的契约方是 APP 开发者（签名验证、幂等消费），connector 的契约方是外部系统 API（EasyAuth 是客户端），生命周期与错误语义完全不同。

### 5.2 既有 Authentik 出站调用不迁移

`disable_departed_account_task` 调 Authentik 禁号/吊销会话的逻辑**保持原状**——它是身份生命周期动作（ADR-001：Authentik 管身份），不是授权投影，语义上就不属于连接器。将来若出现第二个身份类出站需求再评估，不在本方案强行归一。

### 5.3 SCIM

连接器框架天然为"未来做一个 SCIM 客户端连接器"留了位（一个 `BaseConnector` 实现而已），但那需要先修订需求文档的 SCIM 排除条款，本方案不做、不依赖。

---

## 6. 配套 ADR-003 草案：出站供给连接器边界

方案评审通过后抽取为 `docs/decisions/ADR-003-出站供给连接器边界.md`：

- 连接器是 `GrantService` 授权事实的**只读投影**，任何连接器不得创建/修改授权事实。
- 连接器配置属基础设施凭据，superuser-only，全程审计；管理端点限 `/console/api/v1/`。
- 连接器执行全异步，失败不阻塞授权事务；幂等对账是正确性唯一依据。
- 外部系统是执行点不是事实源：外部侧的手工改动会被对账矫正（映射管理范围内）。
- 新连接器通过 `EASYAUTH_CONNECTORS` 显式注册，禁止隐式自动发现。

---

## 7. 里程碑

| 里程碑 | 内容 | 验收标准 |
|--------|------|---------|
| M1 框架后端 | connectors app、三模型迁移、注册表、GrantService 挂点、任务与 beat、控制台 API | 单测：事件挂点触发去抖入队；对账编排以 FakeConnector 验证 desired 构建与 run 记录 |
| M2 NetBird 连接器 | client.py + connector.py + 对账算法与护栏 | 对 mock NetBird API 的对账单测全绿（含预创建/收养/移组/block/护栏越界用例） |
| M3 控制台前端 | ConnectorTab、SchemaForm、映射表、运行历史、i18n | §4.3 动线 1–5 步可在 UI 完成；Playwright E2E 覆盖配置→测试→映射→启用 |
| M4 端到端联调 | 依赖姊妹篇 fork 部署完成 | §4.3 全动线跑通：申请→审批→对账→客户端接入；离职→秒级 block；逆序用户被默认拒绝 |

M1/M2 可并行于 NetBird fork 工作（姊妹篇），M4 是两条线的汇合点。

---

## 8. 风险与对策

| 风险 | 对策 |
|------|------|
| NetBird API 随版本漂移 | client.py 收敛全部调用点；fork 锁定基线 tag（姊妹篇 §4），升级时先跑 M2 单测 |
| 对账与手工操作打架（管理员直接在 NetBird 改组） | ADR-003 明确"映射管理范围内以 EasyAuth 为准"；范围外的组不触碰 |
| 双写竞态（事件快路径与周期对账并发） | 实例级分布式锁；对账本身幂等 |
| token 泄露面扩大 | EncryptedTextField 落库、读接口不回显、审计变更；NetBird 侧 service user 最小权限 |
| 去抖窗口内密集变更导致对账风暴 | 去抖合流（5s）+ 实例锁天然限频；单轮 API 上限护栏 |

---

## 9. 决策清单

1. 建连接器框架而非 NetBird 专用适配器；NetBird 是第一个实现。（防腐化的结构性回答）
2. 连接器实例配置 superuser-only；应用负责人只读状态。
3. v1 只支持授权组级映射；连接器型 App 目录只发布授权组。
4. 对账只维护 `user.auto_groups` + `is_blocked`，依赖 NetBird `GroupsPropagationEnabled` 完成设备级传播（F8）。
5. 绝不删除 NetBird 用户；只管理映射表内的组。
6. webhooks 与 connectors 并存不合并；Authentik 禁号逻辑不迁移。
7. 事件挂点用 `transaction.on_commit` 显式埋点，不引入 Django signals。
8. 钉钉引导消息（逆序用户）挂 Phase 2，依赖 7-06 方案 M3 的钉钉出站客户端。
