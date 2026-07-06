# 员工生命周期 / 钉钉审批中心 / 团队管理范围 — 解决方案设计

> 日期：2026-07-06
> 状态：设计稿（未开始实施）
> 修订 v2（2026-07-06）：澄清——EasyAuth 自身的权限审批为**站内闭环**（审批人来自 EasyAuth 人员），钉钉审批中心**仅服务下游 APP 的业务审批**；原 M2 重构为"站内审批闭环"，钉钉相关工作全部并入 M3。
> 修订 v3（2026-07-06）：生命周期增加**离职缓冲**（无接收人时交接单无限期等待、数据原地保留）、**管理员手动建单与分批交接**、**转岗场景**；新增界面文案原则（§5.4）；消除全部备选方案，§7 改为确定决策清单。
> 修订 v4（2026-07-06）：交接改为**五步向导**；**权限转移支持逐条勾选**——不止 APP 维度，每个 APP 内的具体授权（授权组/权限+范围）均可选择是否转给接收人（基于建单时的授权快照）。
> 范围：EasyAuth（前端 + 后端 + SDK）、Authentik（定制 fork）、EasyTrade（作为首个接入 APP）

本文回答三个问题：

1. 员工离职/转岗的数据与权限交接（含无人接手的缓冲期、管理员手动交接）、入职一键授权，放在哪里？SDK 是否要提供交接对接？
2. 下游 APP 触发钉钉审批流的对接服务放在哪里？
3. 下游 APP（如 EasyTrade）的团队功能（经理可看下属数据、可配置 A 管 B/C/D）放在哪里？

---

## 0. 已核实的现状事实

方案建立在以下经代码核实的事实上（不是假设）：

### 0.1 调用关系现状

```
钉钉开放平台
   ▲  ▲
   │  └── OAuth 登录（用户扫码/免登）
   │
   │  通讯录 API（唯一真正的钉钉 API 出站调用点）
   │
Authentik (auth.jiefakj.com, 定制 fork)
   │  · sources/oauth/dingtalk/client.py — 仅封装通讯录 API（部门、部门用户）
   │  · sources/oauth/dingtalk/sync.py — 同步部门/用户，含 manager_userid、active，
   │    用户消失→软删 is_deleted（离职信号源）
   │  · custom/easyauth/api/dingtalk_managed_users.py — 给 EasyAuth 的
   │    "按主管查递归下属" API（dingtalk_manager_chain 解析器的数据源）
   │
   │  Authentik REST API（目录拉取、用户管理）
   ▼
EasyAuth (iam.jiefakj.com, Django + Celery + React)
   │  · integrations/authentik/directory_sync.py — 镜像目录；发现 departed
   │    → UserMirror.status=departed → 自动撤销全部 AccessGrant
   │  · integrations/dingtalk/callbacks.py + signature.py — 钉钉回调接收端
   │    （验签完整，现无任何能匹配的来源；按本方案转为下游 APP 审批中心专用，见 §3）
   │  · grants/managed_users.py — MANAGED_USERS 解析，唯一 resolver =
   │    dingtalk_manager_chain
   │
   │  权限查询 API（拉取模型，无任何反向推送通道）
   ▼
EasyTrade (etrade.jiefakj.com, FastAPI + Next.js)
      · authz/easyauth_client.py — 拉权限快照并缓存（expires_at）
      · authz/service.py filter_owner_query — 按 grant.resolved.user_ids
        过滤 owner_user_id（MANAGED_USERS 消费管道完整）
      · customer_owner_events — 客户 owner 转移机制（claim/transfer/auto_release）
```

### 0.2 关键缺口（三个问题的技术根源）

| # | 事实 | 证据 | 影响 |
|---|------|------|------|
| F1 | **EasyAuth 没有任何钉钉 API 出站调用**（无 gettoken、无 processinstance）；只有回调接收端 | 全仓 grep 无命中；`integrations/dingtalk/` 只有 callbacks.py / signature.py / urls.py | 面向下游 APP 的钉钉审批中心缺出站能力 |
| F2 | `AccessRequest` 提交后 `dingtalk_process_instance_id` 永远为空；回调按此字段反查，永远匹配不到 | `access_requests/services.py:_submit_access_request`（只建记录）；`inbound_callbacks.py:_locked_request` | 早期"权限审批走钉钉"方向的遗留死代码；按产品意图权限审批应站内闭环（§3.0），待清理复用 |
| F3 | 全系统没有任何审批操作入口：portal 无"待我审批"收件箱，控制台运营页只读 | `admin_console/urls.py` 与 portal 路由均无 approve/reject | 申请永远停在 submitted，"前端不 functional"的主要来源 |
| F4 | MANAGED_USERS 唯一 resolver 是 `dingtalk_manager_chain`，数据源是钉钉"直属主管"字段，EasyAuth 侧只读 | `grants/managed_users.py:40-106`；`ManagedScopePolicy.resolver` 取值仅 dingtalk_manager_chain/disabled | 团队不可自行配置 |
| F5 | 离职链路只做了"撤 EasyAuth 授权 + Authentik 目录缓存软删"，**没有禁用 Authentik User 本体、没有吊销会话** | `directory_sync.py:89-119`；Authentik `dingtalk/sync.py` 只更新 DirectoryUser 缓存 | 安全缺口：离职者登录态未掐断 |
| F6 | EasyAuth → APP 没有任何通知/回调通道（纯拉取模型） | SDK 只有 `query_user_permissions` + descriptor helpers | 离职迁移、审批结果投递都需要新通道 |
| F7 | EasyTrade 的 MANAGED_USERS 消费端和 owner 转移机制均已完整 | `filter_owner_query`；`customer_owner_events` | 问题 3 下游零改动，问题 1 执行端有现成积木 |

### 0.3 前端现状澄清

盘点结论：**前端页面本身大多已接到真实后端接口**（portal 四个页面、控制台 App 管理/目录/授权矩阵/管理范围/审批规则/运营/设置均已接线可用），"不 functional"的体感主要来自**业务闭环断在后端缺腿**（F2/F3：申请提交后永远没有下文）。真正的前端缺口清单：

| 缺口 | 位置 | 归属 |
|------|------|------|
| portal "待我审批"收件箱（审批人处理入口）不存在 | portal | 本方案 M2 必做 |
| 管理员代审/驳回/改派操作 | 控制台运营-访问请求页 | 本方案 M2 必做 |
| 人员版块（人员列表、离职/转岗交接、入职授权）完全不存在 | 控制台（目前仅有 `console_user_search` 搜索端点） | 本方案 M4 新建 |
| 团队管理页 | 控制台 | 本方案 M1 新建 |
| 钉钉凭证/审批模板/审批实例运营页 | 控制台 | 本方案 M3 新建 |
| portal `/portal/settings` 纯占位 | portal | 非阻塞，顺手 |
| 凭证管理只能在接入向导里创建，工作台 Credentials Tab 只读 | 控制台 | 非阻塞，顺手 |
| 硬编码中文未走 i18n（`ConsoleAppWorkspace.tsx:214-334`、`AccessRequestForm.tsx:51-66`） | 控制台/portal | 非阻塞，顺手 |

### 0.4 ID 体系约定

**authentik_user_id 是跨系统用户主键**（已是事实标准，本方案全部沿用）：

- EasyAuth：`UserMirror.authentik_user_id`；`resolved.user_ids` 返回的就是它
- EasyTrade：`users.external_user_id`（OIDC sub）
- 钉钉 userid：仅 EasyAuth 持有映射（`UserMirror.dingtalk_userid`），**不外泄给下游 APP**——这也是审批中心必须放 EasyAuth 的硬理由之一

---

## 1. 要不要改 Authentik 的钉钉适配器？

直接回答：**三个问题都不改 Authentik。** 审批由 EasyAuth 自建出站钉钉客户端（§1.1）；离职禁号由 EasyAuth 调 Authentik 标准 API 完成（§1.2）；团队数据在 EasyAuth 本地（§1.3）。

### 1.1 审批：为什么不借道 Authentik

"目前只有 Authentik 真正在调钉钉 API"是事实（F1），但它调的是**通讯录 API**，用的是 OAuth source 的凭证，职责是身份目录。审批 API（创建 OA 审批实例、查询审批记录）是业务流程能力，走 Authentik 有三个代价：

1. **fork 维护成本**：Authentik 是带 enterprise_patch 的定制 fork，每加一块非上游功能，后续 rebase 上游版本就重一分。通讯录同步是身份职责、值得放进去；审批不是。
2. **多一跳**：EasyAuth → Authentik → 钉钉，链路上多一个故障点和一套自定义 API 契约。
3. **回调归属割裂**：钉钉审批事件回调端（含验签）已经在 EasyAuth 里建好了（`integrations/dingtalk/`），发起端若放 Authentik，一条流程劈在两个系统里。

正确做法：**给 EasyAuth 补一个很小的出站钉钉客户端**（获取 access_token + 创建审批实例 + 查询实例，约 200 行以内），与已有的回调接收端配成完整一对，专供下游 APP 审批中心（§3.2）使用。凭证按 `IntegrationSettings.authentik_api_token` 的现成 `EncryptedCharField` 模式加密落库。

凭证决策（§7 决策 1）：**复用 Authentik 登录用的那个钉钉企业内部应用**——在钉钉后台给它追加"OA 审批"（及后续工作通知）权限，EasyAuth 加密保存同一份 AppKey/Secret。运维件数最少；将来若要做权限隔离，换成专用应用也只是换一份凭证，不影响本设计。钉钉后台的**事件订阅回调地址指向 EasyAuth**（`https://iam.jiefakj.com/integrations/dingtalk/callback`），与现有验签代码吻合。

### 1.2 生命周期：Authentik 零改动

补 F5 缺口（离职禁号 + 吊销会话）的决策：**由 EasyAuth 的离职编排调用 Authentik 标准 API 完成**——用已有的 Authentik API token 调 `PATCH /api/v3/core/users/{pk}/` 置 `is_active=false`，再删该用户 sessions。逻辑收敛在 EasyAuth 编排层，可审计、可重试，Authentik fork 不新增任何差异。

### 1.3 团队：Authentik 不动

`easyauth_team` resolver 的数据完全在 EasyAuth 本地表（§4），不依赖 Authentik。现有的 `custom/easyauth/api/dingtalk_managed_users.py` 继续只服务 `dingtalk_manager_chain`。

---

## 2. 问题 1：员工离职/转岗交接 & 一键入职

### 2.1 场景与放置决策

覆盖三类人事变动：

| 场景 | 触发 | 账号处理 | 数据与权限 |
|------|------|----------|-----------|
| 离职 | 钉钉移除 → 目录同步检出 departed 自动建单；管理员也可提前手动建单 | 立即禁用 Authentik 账号、吊销会话、撤销全部授权 | 数据进入缓冲（原地保留），交接单无限期等待接收人 |
| 转岗 | 仅管理员手动发起（目录同步检出部门变更时在人员列表提示，不自动建单） | 账号保持可用 | 按新岗位模板做权限差异调整 + 可选数据交接 + 团队调整 |
| 入职 | 目录同步出现新人 | — | 一键套用岗位模板批量授权 |

职责放置：

| 职责 | 归属 | 理由 |
|------|------|------|
| 编排（谁离职/转岗、接收人是谁、每个 APP 交接到什么状态） | **EasyAuth 新增 `lifecycle/` 模块** | 只有它知道全量事实：接入了哪些 APP（`App`）、当事人有哪些授权（`AccessGrant`）、离职信号与部门变更镜像都在这里 |
| 数据交接执行（客户转交、订单换 owner） | **各下游 APP** | 只有 APP 懂业务语义；EasyTrade 已有 `customer_owner_events` 转移机制可复用 |
| 信号源 + 账号禁用 | Authentik / 钉钉 | 离职信号已有；禁号由 EasyAuth 调 Authentik 标准 API 完成（§1.2，Authentik 零改动） |

### 2.2 交接的三条铁律

1. **安全动作与数据交接解耦**：离职检出后立即撤权、禁号，不等交接；数据交接可以慢慢来。
2. **缓冲是常态**：离职后往往没有现成的接手人。交接单停在"待交接"没有期限，期间数据原地保留、不自动转移（APP 自身的业务策略如 EasyTrade 公海自动回收照常生效，不受交接单影响）。
3. **每个 APP 独立交接**：不同 APP 可以指定不同接收人、在不同时间执行；先有人接客户就先交客户，互不阻塞。
4. **权限按需转移，不整锅端**：接收人拿到哪些权限由管理员逐条勾选——粒度到每个 APP 内的具体授权（授权组 / 权限+范围），默认全选、可逐条取消（§7 决策 12）。

### 2.3 SDK 交接对接（方案核心）

现有 SDK 是纯拉取模型（F6）。数据交接必须由 EasyAuth 主动调 APP，因此新建 **EasyAuth → APP 反向 webhook 通道**（与问题 2 审批结果投递共用，规范见 §5.1，随 M3/M4 中先实施者落地）。

**Manifest 扩展**（descriptor `/.well-known/easyauth-app.json` 新增节）——离职与转岗共用同一个交接钩子，靠 `kind` 区分：

```json
{
  "lifecycle": {
    "handover_url": "/api/v1/easyauth/lifecycle/handover",
    "onboard_url": null,
    "capabilities": ["preview", "reassign"]
  },
  "webhook": { "signing": "hmac-sha256" }
}
```

**交接钩子协议**（两阶段、幂等）：

```
POST {handover_url}
{
  "task_id": "uuid",                  // 幂等键，重复调用必须安全
  "kind": "offboard" | "transfer",
  "from_user_id": "<authentik_user_id>",
  "to_user_id": "<authentik_user_id> | null",   // 选择释放公海时可为空
  "mode": "preview" | "execute",
  "policy": { "unowned_strategy": "transfer" | "release_to_pool" }
}

preview 响应（不落库，只报影响面）：
{ "assets": [ {"type": "customer", "count": 23, "label": "名下客户"},
              {"type": "order_in_transit", "count": 4, "label": "在途订单"} ] }

execute 响应：200（同步完成，带交接摘要） 或 202 + 状态查询 URL
```

**SDK 新增**（`easyauth-app-sdk`）：

- `verify_webhook(secret, headers, raw_body) -> WebhookEvent`（验签 + 时间戳防重放，§5.1）
- FastAPI helper：`easyauth_lifecycle_router(on_handover_preview=..., on_handover_execute=...)`，APP 只写业务回调函数
- manifest 构建函数支持 `lifecycle` / `webhook` 节

### 2.4 EasyAuth 后端

**新模块 `src/easyauth/lifecycle/`**，数据模型：

```
HandoverTask       kind(offboard|transfer), subject_user FK UserMirror,
                   status(pending|in_progress|completed|cancelled),
                   created_by, reason, created_at
                   （离职单由目录同步自动创建；管理员可随时手动建单、
                     对已取消的重新建单）
HandoverAppAction  task FK, app FK, to_user FK nullable（每 APP 独立指定接收人）,
                   policy JSON, status(pending|previewed|executing|done|
                   failed|skipped), preview_payload JSON, result_payload JSON,
                   attempts, last_error
                   （无接收人时停在 pending，无期限；各 APP 执行互不阻塞）
HandoverGrantItem  task FK, app FK, 授权快照(authorization_group key 或
                   permission key + scope_key, grant_type, 期限),
                   selected bool(默认 true), status(pending|done|skipped)
                   （建单时对当事人现有授权做快照——离职单的授权在检出时
                     已被立即撤销，向导的展示与转移都基于该快照）
TransferPlan       task FK（kind=transfer 专用）, new_template FK
                   OnboardingTemplate, grant_diff JSON（将撤销/新增/保留，
                   确认时逐条可勾选）, team_changes JSON
OnboardingTemplate      name, description, is_active
OnboardingTemplateItem  template FK, app FK, authorization_group FK 或
                        (permission FK + scope_key), grant_type, duration_days
AppWebhookConfig   app OneToOne, secret(EncryptedCharField), enabled,
                   handover_url / onboard_url / approval_callback_url
                   （接入时从 manifest 读入，可在控制台覆盖）
```

**离职流程**（Celery 编排，全程审计）：

1. 触发：目录同步检出 `departed` 自动建交接单；管理员也可对在职员工提前手动建单（离职前主动交接）。
2. 立即项（自动执行，不等交接）：撤销全部 AccessGrant（现有逻辑）＋ 调 Authentik API 禁号/吊销会话（§1.2）＋ 移出所有团队；若当事人是团队 leader，团队转交列为交接单里的一项。
3. 缓冲：交接单停在"待交接"，无期限；数据原地保留。
4. 交接（经向导，§2.5，按 APP 独立进行）：管理员选本次要交接的 APP → 指定接收人（或选择释放公海）→ 逐条勾选要转移的权限（来自建单快照）→ preview 展示数据影响面 → 确认 → execute：EasyAuth 内部为接收人创建勾选的授权（AccessGrant 的 source_note 记录来源交接单），同时调 APP 钩子交接数据；失败指数退避重试，单 APP 失败不影响其他 APP。
5. 所有 APP 均 done/skipped（未声明钩子的 APP 自动 skipped 并明示）→ 交接单完成。

**转岗流程**：

1. 管理员手动发起；目录同步检出部门变更时在人员列表给"部门已变更"提示作为线索，但不自动建单——转岗是人事决策，系统不猜。
2. 权限调整（EasyAuth 内部完成，无需钩子）：选新岗位模板 → 系统生成授权差异清单（默认规则：不在新模板内的现有授权撤销、新模板缺的补上）→ 管理员逐条可勾选调整 → 确认执行。
3. 数据交接（可选）：与离职共用 §2.3 钩子和向导，`kind=transfer`，账号不禁用；接手旧职责的人同样可按勾选获得旧职责相关权限。
4. 团队调整：从旧团队移出/加入新团队，在交接单内一并操作。

**入职**：不需要反向钩子（APP 首次登录自建本地用户、权限靠拉取）。控制台"一键入职"= 选人 + 选 `OnboardingTemplate` → 按模板项批量创建 AccessGrant（复用现有 grant 创建与审计）。`onboard_url` 在 manifest 里保留为可选，将来有 APP 需要预建档案再用。

**新增控制台 API**（`/console/api/v1/`）：

```
GET/POST   lifecycle/handover-tasks               列表/建单（离职或转岗）
GET        lifecycle/handover-tasks/{id}           详情（含各 APP 交接状态）
PATCH      lifecycle/handover-tasks/{id}           指定/修改各 APP 接收人、取消
GET/PATCH  lifecycle/handover-tasks/{id}/grant-items  权限转移清单（按 APP 分组，勾选/取消）
POST       lifecycle/handover-tasks/{id}/actions/{app_key}/preview | /execute | /retry
                                                     （execute 含该 APP 已勾选权限的转授）
POST       lifecycle/handover-tasks/{id}/grant-diff/confirm    转岗本人权限差异确认
GET/POST/PATCH  lifecycle/onboarding-templates
POST       lifecycle/onboard                       一键入职（user + template）
GET        users                                   人员列表（分页，状态筛选 +
                                                   部门变更提示；现仅有搜索端点，需扩展）
GET/PUT    apps/{app_key}/webhook-config           webhook 密钥与 URL 管理
```

### 2.5 EasyAuth 前端（控制台新增"人员"版块）

界面文案原则见 §5.4（业务语言、不暴露技术状态）。三个页面：

1. **人员列表**：状态只用"在职 / 已停用 / 已离职"三个词；部门变更的人有一枚"部门已变更"提示标；已离职且交接未完成的行直接给"去交接"按钮。复用现有表格 + `ListPayload` 分页模式。
2. **交接向导**（离职/转岗共用，标题分别为"离职交接""转岗交接"）：
   - 工单总览：谁、哪种交接、每个应用一张状态卡（"已交接给 张三"/"待交接——数据保持原状，可稍后处理"），「继续交接」进入向导。列表与卡片不显示内部状态机枚举。
   - 向导五步，每步一句话说明当前在做什么，任何一步可「保存，稍后继续」（缓冲是常态）：
     1. **选应用**：本次要交接哪些应用（可只选一部分，其余留在待交接）；
     2. **选接收人**：默认统一接收人、可按应用分别指定（复用 `UserSelect`）；EasyTrade 可改选"释放到公海"；
     3. **选权限**：按应用分组的授权清单（来自建单快照），以业务名称展示（授权组名/权限名 + 范围名），默认全选、逐条可取消，顶部说明"接收人将获得勾选的权限"；
     4. **预览数据**："EasyTrade：23 个客户、4 笔在途订单将转给 张三"；未声明钩子的应用显示"该应用无需数据交接"；
     5. **确认执行**：汇总页（给谁、几项权限、多少数据）→ 执行进度；失败一句人话＋「重试」按钮，重试次数/投递日志收进"详情"折叠。
   - 转岗向导额外两步：**本人权限调整**（新模板差异清单："将收回 n 项、新增 m 项、保留 k 项"，逐条可勾选）和**团队调整**。
3. **入职授权**：模板管理（模板项编辑复用授权矩阵的"权限 + 范围"选择组件）＋"一键入职"对话框（选人 → 选模板 → 预览将授予的权限清单 → 确认）。

另：App 工作台新增 **Webhook Tab**（密钥生成/轮换、URL 展示、"发送测试事件"按钮）——面向接入开发者的页面，允许技术术语。均沿用现有技术栈模式（TanStack Query、`/src/lib/api.ts` 集中声明端点、`domain.ts` 类型、i18n 走 `messages.ts`）。

### 2.6 EasyTrade 侧

1. 实现交接钩子（用 SDK 的 FastAPI helper，离职/转岗同一实现）：
   - preview：统计 `owner_user_id = 交出人` 的客户数、在途订单数、进行中商机数、未完结单据数。
   - execute：客户转给接收人（写 `customer_owner_events`，type=transfer）或释放公海（复用 auto_release 路径）；在途订单/商机 owner 转给接收人；历史已完结数据不动。
2. manifest 导出（已有 `easyauth_manifest_export.py`）追加 `lifecycle` / `webhook` 节。
3. 配置 webhook secret（env + 后台设置）。

### 2.7 验收标准

- **离职缓冲**：钉钉移除测试员工 → 自动出现离职交接单；此刻该员工已无法登录、授权已全撤，但 EasyTrade 数据原地未动；一周后指定接收人执行交接 → 客户/在途订单归接收人，`customer_owner_events` 有 transfer 记录，交接单完成，审计成链。
- **手动与分批**：管理员对在职员工手动建离职交接单可用；同一交接单先交接 EasyTrade、其他 APP 留待以后，互不阻塞。
- **权限逐条勾选**：接入两个以上 APP 时，向导中只选其中一个 APP、且只勾选其部分权限 → 接收人仅获得勾选的那几项授权（source_note 指向交接单），未勾选的不转移，其余 APP 留在待交接。
- **转岗**：转岗单执行后——账号仍可登录、旧岗位多余授权被收回、新模板授权生效、勾选保留的授权未动、数据按选择交接、团队从旧组移到新组。
- **幂等**：对同一 task_id 重复 execute 不产生重复交接。

---

## 3. 问题 2：钉钉审批中心（纯为下游 APP 服务）＋ 站内审批闭环

### 3.0 方向澄清：EasyAuth 自身的权限审批是站内闭环，不走钉钉

产品意图（v2 修订确认）：

- **权限申请（AccessRequest）由申请时选定的审批人在 EasyAuth 站内处理**。审批人候选只从 EasyAuth 人员（`UserMirror`）里选——现有 portal 提交表单已按此设计（`approver_user_ids` 必填校验、`ApprovalRule` 提供默认审批人、`console_user_search` 供搜索），缺的只是审批人的处理入口（F3）。
- **钉钉审批流专为下游 APP 的业务审批服务**（如 EasyTrade 的财务操作需要走钉钉审批），与 EasyAuth 权限审批互不掺和。

因此修复自助申请闭环（F2/F3）＝补站内审批，与钉钉完全无关（M2）：

1. **站内审批 API（portal 侧）**：
   - `GET  /portal/api/v1/me/approvals?status=pending` — 我是审批人的待办列表
   - `GET  /portal/api/v1/me/approvals/{request_id}` — 申请详情（申请人、目标授权、scope、期限、理由）
   - `POST /portal/api/v1/me/approvals/{request_id}/approve | /reject`（驳回必填意见）
   - 鉴权：当前用户 ∈ `request.approver_user_ids`；多审批人语义：任一人处理即生效，不做会签（§7 决策 7）。
2. **状态机复用**：`access_requests/inbound_callbacks.py` 里的加锁流转与授权应用逻辑（`_mark_approved` → `apply_approved_access_request`）与触达方式无关，重构为独立 service，站内审批与管理员操作共用，actor 如实记审批人。
3. **管理员兜底（控制台）**：`POST /console/api/v1/operations/access-requests/{id}/approve | /reject | /reassign`（审批人离职/休假时代审或改派审批人，actor_type=console_admin，审计留痕）。
4. **钉钉遗留清理**：`AccessRequest.dingtalk_process_instance_id` 字段与 `inbound_callbacks.py` 的钉钉回调映射是早期方向的遗留（F2）——字段标记废弃、后续迁移移除；`integrations/dingtalk/callbacks.py` + `signature.py` 保留，转为审批中心（§3.2）专用。
5. **审批人触达（可选增强，依赖 M3 出站客户端）**：钉钉工作通知"你有一条待审批"深链到 portal 待办页。第一版先做 portal 导航角标。

### 3.1 审批中心放置决策

**放 EasyAuth，作为平台级"审批中心"模块；不改 Authentik（§1.1），不建独立微服务，不让各 APP 直连钉钉。**

- 各 APP 直连的问题：凭证分散、钉钉回调地址只有一个没法分、每个 APP 重复实现验签/重试/token 管理；且发起审批必须把 authentik_user_id 换算成钉钉 userid，这份映射只有 EasyAuth 有（§0.4），不应复制给每个 APP。
- 独立微服务对当前规模是负资产（多一个部署单元）；模块边界画清楚，将来要拆随时能拆。
- 与站内权限审批（§3.0）职责互斥、边界干净：审批中心只做"APP → 钉钉"的通道，不承载 EasyAuth 自身的权限审批。

### 3.2 审批中心设计（M3）

**出站钉钉客户端** `integrations/dingtalk/api_client.py`：token 获取与缓存（Redis，提前刷新）、创建审批实例、查询实例详情。直接用钉钉新版 v1.0 workflow API（`api.dingtalk.com/v1.0/workflow/processInstances`），不接旧 topapi（§7 决策 2）。

**凭证配置**：`IntegrationSettings` 增加 `dingtalk_app_key`、`dingtalk_app_secret(EncryptedCharField)`、`dingtalk_agent_id`；控制台设置页加"钉钉集成"区块（含"发起测试审批"连通性按钮）。

数据模型（新模块 `src/easyauth/workflows/`）：

```
ApprovalTemplate  app FK(nullable=平台共用), key, name,
                  dingtalk_process_code, form_schema JSON(声明业务字段),
                  form_mapping JSON(业务字段→钉钉表单控件映射), is_active
ApprovalInstance  id(uuid), app FK, template FK, biz_key(app 内幂等键),
                  originator_user FK UserMirror,
                  dingtalk_process_instance_id,
                  status(created|submitted|approved|rejected|canceled|failed),
                  form_values JSON(快照), delivery_status(投递给 APP 的状态),
                  timestamps
                  UNIQUE(app, template, biz_key)
```

对 APP 的 API（复用现有 app 凭证认证）：

```
POST /api/v1/apps/{app_key}/approval-instances
     { template_key, originator_user_id, form, biz_key }   → 201 { instance_id, status }
GET  /api/v1/apps/{app_key}/approval-instances/{instance_id}   （轮询兜底）
```

回调路由：钉钉回调入口保持唯一（现有 `/integrations/dingtalk/callback`），按 `process_instance_id` 匹配 `ApprovalInstance`（该通道与 AccessRequest 不再有任何关系）→ 更新状态并经 webhook 通道（§5.1）把 `approval.completed` 事件推给发起 APP，投递失败重试 + APP 侧轮询兜底。

SDK 新增：

```python
client.create_approval(template_key, originator_user_id, form, biz_key) -> dict
client.get_approval(instance_id) -> dict
# webhook 验签复用 §2.3 的 verify_webhook
```

**边界纪律**：EasyAuth 只做"通道 + 状态跟踪 + 结果投递"。审批通过后的业务后果（改订单状态、放行折扣）永远在发起 APP 侧。EasyAuth 不做表单设计器、不做审批流引擎——流程本身在钉钉后台配（process_code），EasyAuth 只存映射。

### 3.3 前端工作项

1. portal 新增"待我审批"页（待办列表 + 详情 + 同意/驳回带意见；导航角标显示待办数）——M2。
2. 控制台运营-访问请求页升级：管理员代审/驳回/改派操作 + 确认对话框——M2。
3. 控制台设置页"钉钉集成"区块（凭证、agent_id、连通性测试）——M3。
4. 审批模板管理页（列表 + CRUD：key/名称/process_code/字段映射 JSON 编辑器 + "发起测试审批"）——M3。
5. 运营版块新增"审批实例"页（跨 APP 实例列表：状态、发起 APP、发起人、钉钉实例号、投递状态、失败重投按钮）——M3。

### 3.4 验收标准

**M2（站内闭环，全程不依赖钉钉）**：
- portal 提交权限申请 → 审批人在"待我审批"看到待办并同意 → 授权自动生效，申请状态 grant_applied；驳回时申请人可见驳回理由。
- 非指定审批人无法操作他人待办；管理员代审/改派留有 actor_type=console_admin 的审计记录。

**M3（审批中心）**：
- EasyTrade 用 SDK 对 demo 模板发起一笔审批（同 biz_key 重复调用只产生一个实例）→ 发起人在钉钉看到审批卡片 → 处理后 EasyTrade 收到验签通过的 `approval.completed` 回调；审批实例运营页可见全程状态与投递结果。

---

## 4. 问题 3：团队（可配置管理范围）

### 4.1 放置决策

**从属关系放 EasyAuth，实现为 MANAGED_USERS 的第二个 resolver（`easyauth_team`）；EasyTrade 零改动。**

- 根因（F4）：现在唯一 resolver 是钉钉"直属主管"链，只读推导，所以"看得见配不了"。
- "A 管 B/C/D"是跨 APP 组织事实，今天 EasyTrade 要，明天别的 APP 也会要，放 IAM 一处维护。
- `ManagedScopePolicy.resolver` 字段天然就是多 resolver 扩展点；换 resolver 对 APP 完全透明（ADR-002 契约红利）——EasyTrade 的 `resolved.user_ids → filter_owner_query` 管道原样工作。
- 判断标准（记入 ADR）：**用于权限可见范围的从属关系 → EasyAuth；用于业务统计口径的分组（如销售大区）→ 留在 APP 业务表。**

### 4.2 数据模型（新模块 `src/easyauth/teams/`）

```
Team        id, name, description, is_active, created_by, timestamps
TeamMember  team FK, user FK UserMirror, role(leader|member),
            added_by, added_at
            UNIQUE(team, user)
```

第一版刻意从简：扁平结构（不做嵌套，将来要层级再加 parent_team）；全局团队（不按 app 隔离，§7）；允许多 leader、允许一人多团队。

### 4.3 resolver 扩展

`ManagedScopePolicy.resolver` 枚举扩展为四值，沿用现有"app 默认 + 按授权组覆盖"两级配置：

| resolver | 语义 |
|----------|------|
| `dingtalk_manager_chain` | 现状：钉钉直属主管递归链 |
| `easyauth_team` | 新增：本人为 leader 的所有 active 团队的 active 成员并集（去重、排除本人） |
| `union` | 新增：上两者并集——适合"钉钉汇报线为主、个别人手工补挂"的过渡期 |
| `disabled` | 现状 |

`resolve_managed_users()`（`grants/managed_users.py`）按 policy 分支。`easyauth_team` 是本地表查询：**不依赖目录新鲜度，没有 stale-503 问题**（比钉钉链更可靠）；`union` 分支钉钉侧失败时按现有 503 语义处理，团队侧照常返回。响应中 `resolver` 字段如实回填，EasyTrade 快照里可见来源。现有 `managed-users-preview` 端点顺带支持新 resolver，控制台可直接预览验证。

### 4.4 前端工作项（控制台）

1. **团队管理页**（新导航项，后端配套 `GET/POST/PATCH /console/api/v1/teams`、成员增删接口）：团队列表 → 详情（leader 区 + 成员区，复用 `UserSelect`/`UserMultiSelect` 增删人）→ 停用团队二次确认（提示影响：leader 的管理范围将收缩）。
2. **Managed-Scope Tab**：现有三态 UI 加两个选项，界面文案用业务语言（§5.4）——"按钉钉汇报线（自动）""按自定义团队""合并两者""停用"，不出现 resolver 内部名；选中团队类选项时内联提示"成员在〈团队管理〉维护"并给跳转链接。该 Tab 的硬编码中文（`ConsoleAppWorkspace.tsx:214-334`）借本次改动一并迁入 i18n。
3. **预览**：授权矩阵/管理范围页的 managed-users 预览直接复用，管理员改完团队立即能看到某 leader 的解析结果。

### 4.5 与生命周期联动（依赖 M4，规则先定）

- 成员离职 → 目录同步时自动移出所有团队（审计记录）。
- leader 离职 → 其领导的团队列入离职交接单：接收人接任 leader 或团队停用，管理员在单内选。
- 转岗 → 团队变动在转岗单的"团队调整"区一并处理（§2.4）。

### 4.6 EasyTrade 侧

- **必改：无。** 换 resolver 后快照里 `resolved.user_ids` 即为团队成员，`filter_owner_query` 原样生效；仪表盘 `scope=team` 视图原样生效。
- "经理只看部分数据"不需要新机制，是 **permission 粒度 × scope 的组合**：授 `customer:view` @ MANAGED_USERS、不授 `customer:finance:view`，即"能看下属客户但看不到财务字段"。字段级裁剪本来就在 EasyTrade 按 permission 判断。
- 可选优化：快照 TTL 内团队变更有延迟窗口，如需即时生效可在控制台改团队时顺带失效相关用户快照（M3 webhook 通道就绪后发 `grants.changed` 事件，列为后续增强）。

### 4.7 验收标准

- 控制台建团队"华东销售组"（leader=A，成员=B/C/D），EasyTrade 的授权组 policy 切到 `easyauth_team` → A 在 EasyTrade 客户列表看到 B/C/D 名下客户；从团队移除 D 并等快照过期（或手动刷新）后 A 不再看到 D 的客户。全程不改 EasyTrade、不动钉钉后台。
- `union` 模式下，钉钉汇报线下属 + 手工挂的团队成员同时可见。
- preview 端点对四种 resolver 均返回正确结果。

---

## 5. 横切设计

### 5.1 EasyAuth → APP webhook 通道规范（问题 1/2 共用，随 M3 落地；若 M4 先行则随 M4）

```
POST {app 配置的目标 URL}
Headers:
  X-EasyAuth-Event:      lifecycle.handover.preview | lifecycle.handover.execute |
                         approval.completed | webhook.test
  X-EasyAuth-Delivery:   事件唯一 ID（APP 侧幂等去重键）
  X-EasyAuth-Timestamp:  unix 秒
  X-EasyAuth-Signature:  hex(HMAC-SHA256(secret, timestamp + "." + raw_body))
```

- 验签规则：拒绝 |now − timestamp| > 300s；常数时间比较。SDK `verify_webhook` 封装，APP 不手写。
- 投递：Celery 异步、指数退避重试（如 1m/5m/30m/2h/6h，共 5 次），最终失败在控制台 Webhook Tab 红标 + 可手动重投。
- 密钥：每 APP 一份（`AppWebhookConfig.secret`，加密落库），控制台可轮换（轮换后旧签名立即失效，文档提示 APP 先更新再轮换）。
- 每种事件均有"测试投递"能力（控制台按钮 → APP 收到 `webhook.test`）。

### 5.2 安全清单

- 离职：撤授权（已有）＋ Authentik 禁号/吊销会话（§1.2，**本方案必须项**）＋ EasyTrade 快照过期窗口（现有 TTL，可接受）。
- 钉钉 AppSecret / webhook secret 全部走 `EncryptedCharField`，不进环境变量明文清单。
- 站内审批/管理员代审、离职执行、团队变更、密钥轮换全部写 AuditLog（现有 append-only 体系，补充新 event_type 常量）。
- 回调与 webhook 均幂等：钉钉回调按 process_instance_id + 状态机去重；APP 侧按 X-EasyAuth-Delivery 去重。

### 5.3 顺手技术债（非阻塞，随相邻改动一并处理）

- 硬编码中文迁 i18n：Managed-Scope Tab 随 M1 改动顺手迁；AccessRequestForm 随 M2。
- 工作台 Credentials Tab 补创建/禁用操作（后端 API 已有，纯前端）。
- portal `/portal/settings` 占位页：暂缓，与本方案无关。

### 5.4 界面文案与易用性原则（所有新页面适用）

- **业务语言，不用技术名词**：界面上不出现 resolver、grant、webhook、payload、mirror 这类词。对照：`dingtalk_manager_chain`→"按钉钉汇报线（自动）"；`easyauth_team`→"按自定义团队"；`union`→"合并两者"；AccessGrant→"授权"；HandoverTask→"交接单"。
- **状态给人看，不给状态机看**：对外只暴露少量业务状态（交接单：待交接/交接中/已完成/已取消；申请：待审批/已通过/已驳回）。重试次数、投递状态、内部枚举一律收进"详情"折叠；出错时一句人话说明 + 明确的动作按钮（重试/查看详情），不堆技术细节。
- **空状态给下一步指引**：无接收人→"暂未指定接收人，数据保持原状，可稍后处理"；无待办→"暂无需要你审批的申请"。正常的等待态不用倒计时、不用红色告警。
- **开发者页面例外**：App 工作台的 Webhook/凭证/Manifest 等面向接入开发者的 Tab 允许技术术语。
- 既有页面硬编码中文迁 i18n 时（§5.3），顺手按本原则重写文案。

---

## 6. 实施顺序

依赖关系：M1、M2 相互独立，且都不碰钉钉；M3 落地出站钉钉客户端与 webhook 通道（§5.1）；M4 复用该通道——若业务上需要 M4 先行，把 §5.1 通道基建从 M3 提到 M4 即可，两者共享同一规范。

| 里程碑 | 内容 | 改动面 |
|--------|------|--------|
| **M1 团队** | Team/TeamMember 模型与 API、resolver 四值扩展、preview 支持；控制台团队管理页 + Managed-Scope Tab 加选项 | EasyAuth 前后端；Authentik/EasyTrade/SDK 均不动。改动最小、见效最快，直接解决问题 3 |
| **M2 站内审批闭环** | portal"待我审批"收件箱 + 审批/驳回 API、管理员代审/改派、审批状态机从钉钉遗留代码中提炼复用、`dingtalk_process_instance_id` 等遗留标记废弃 | 仅 EasyAuth 前后端；不碰钉钉/Authentik/SDK。修复 F2/F3，portal 自助申请第一次真正闭环 |
| **M3 钉钉审批中心** | 出站钉钉客户端与凭证配置、ApprovalTemplate/ApprovalInstance、APP 发起 API、回调路由（专属 ApprovalInstance）、AppWebhookConfig + 签名投递框架 + 测试事件、SDK（create/get_approval + verify_webhook）；控制台钉钉集成设置/模板管理/实例运营页 | EasyAuth 前后端 + SDK + EasyTrade 首个业务审批点（修复 F1）；可选增强：审批人钉钉工作通知 |
| **M4 生命周期** | lifecycle 模块（离职/转岗交接单、缓冲、权限转移勾选清单、转岗权限差异调整、入职模板）、Authentik 禁号（标准 API 调用）、控制台"人员"版块三页（含五步交接向导）+ Webhook Tab、SDK lifecycle helper、EasyTrade 交接钩子、团队联动 | 全部四个代码面；依赖 M3 的 webhook 通道 |

每个里程碑的验收标准见各节（§4.7、§3.4、§2.7）。

## 7. 设计决策清单（已定，不留备选）

| # | 决策点 | 决定 |
|---|--------|------|
| 1 | 钉钉凭证 | 复用登录用的企业内部应用，钉钉后台追加审批（及工作通知）权限（§1.1） |
| 2 | 钉钉 API 版本 | 用 v1.0 workflow API，不接旧 topapi |
| 3 | 审批表单映射 | form_mapping 用 JSON 配置（控制台文本编辑器），不做可视化映射器 |
| 4 | 团队作用域 | 全局团队，不按 APP 隔离（scope policy 已有 per-app/per-grant 两级，足够） |
| 5 | 离职缓冲语义 | 交接单无限期等待接收人；缓冲期数据原地保留、不自动转移；APP 自身业务策略（如公海回收）照常生效 |
| 6 | 离职数据策略粒度 | 交接单按 APP 一档策略（转接收人 / 释放公海），不做逐条资产指定 |
| 7 | 多审批人语义 | 任一审批人通过即生效，不做会签/依次审批 |
| 8 | 转岗触发 | 仅管理员手动发起；目录同步的部门变更只提示、不自动建单 |
| 9 | 转岗权限调整规则 | 默认"撤销不在新模板内的授权 + 补齐新模板"，确认时逐条可勾选 |
| 10 | 审批人触达 | portal 待办角标；钉钉工作通知深链列为 M3 后增强，第一版不做 |
| 11 | 快照即时失效 | 第一版不做；M3 通道就绪后以 `grants.changed` 事件增强 |
| 12 | 权限转移规则 | 粒度到每个 APP 内的具体授权（授权组/权限+范围），默认全选、逐条可取消；类型与期限照抄原授权；离职单基于建单时的授权快照（原授权已被立即撤销） |
