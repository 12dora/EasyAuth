# 05 · EasyProject 后端接入设计

> 基准文档：`00-overview-and-contract.md`（下称「契约」）。
> 契约中的事件名、payload 形状、错误码、身份规则是**冻结**的，本文件不重复定义，只给 EasyProject 落地方案。
> 本仓库改造与 EasyAuth、EasyTrade **完全并行**，唯一耦合点是契约 §10 的 webhook 形状与
> `EasyAuth/tests/contract_samples/handover_v2/` 下的 golden JSON。

---

## 1. 现状与差距

EasyProject 已接入 EasyAuth 的四个适配器：目录（`infra/easyauth_directory/`）、授权
（`infra/easyauth_authz/`）、审批（`infra/easyauth_approval/`）、通知（`infra/easyauth_notify/`），
descriptor 已暴露在 `GET /.well-known/easyauth-app.json`（`api/v1/easyauth_descriptor.py:50`）。

**唯独没有接入数据交接。** 后果按契约 §1.1 第 1 条：在 EasyAuth 的交接单上，EasyProject 这一行
与"确实没有该员工数据"完全无法区分，且显示为已完成。契约 v2 之后它会变成 `blocked`，整张单无法完成。

### 1.1 两个必须先修的阻塞项

| # | 问题 | 位置 | 后果 |
|---|---|---|---|
| P1 | **`MANAGED_USERS` 不消费 EasyAuth 快照**，而是自己递归调下属接口推算（depth 20，5 分钟缓存） | `backend/app/domain/authz/managed_users.py:19`、`domain/authz/service.py:184` | 离职者不是任何人的下属 → 代管授权对 EasyProject **完全无效**（契约 D4 失效）。同时这本身就违反 EasyAuth 下游契约（`CONTEXT.md`「管理对象快照」条：下游必须落地快照并用本地数据过滤） |
| P2 | 从未登录过 EasyProject 的员工，`directory_users.authentik_user_id` 为 `NULL` | `infra/repositories/directory.py:45`、`m07_001_directory_tables.py:51` | 契约 payload 里的 `from_user_id`/`to_user_id` 是 Authentik `sub`，这类人**解析不到本地行** |

P1 与 webhook 实现相互独立，应作为第一个可单独验证、单独上线的提交。

---

## 2. 身份映射（契约 §5.2）

### 2.1 规则

契约规定跨系统 payload 中的人员字段一律是 Authentik `sub`。EasyProject 的业务外键是
`directory_users.dingtalk_user_id`（dtuid，`AGENTS.md` 不变量 1），因此每次收到 payload 都要解析。

新增 `backend/app/domain/identity/handover_identity.py`：

```python
async def resolve_dtuid(uow, *, authentik_sub: str) -> str:
    """把契约里的 Authentik sub 解析为本地 dtuid; 解析不到抛 IdentityUnmappedError。"""
```

解析顺序：

1. 查 `directory_users where authentik_user_id = sub` → 命中即返回 dtuid。
2. 未命中 → 调 EasyAuth 目录接口按 sub 取用户详情
   （SDK `easyauth_directory` 适配器已封装，`domain/ports/easyauth.py:23` 的用户引用协议本就同时接受
   `sub` 与 `dt:<dtuid>`），拿到其 dtuid。
3. 用该 dtuid 走既有的绑定路径回填 `authentik_user_id`
   （`domain/identity/binding.py:109`，已实现"存在未绑定行则补绑、冲突则拒绝"的原子逻辑），再返回。
4. 仍解析不到 → 抛 `IdentityUnmappedError`，API 层转 **HTTP 409**，错误码 `IDENTITY_UNMAPPED`，
   错误体沿用本仓库标准 `ErrorBody`（契约 §10.6 只规范状态码，见 §5.3）。

**禁止**按姓名/邮箱模糊匹配（违反不变量 1）。**禁止**静默跳过或返回空统计 —— 那会让 EasyAuth 误判
"此人在 EasyProject 无数据"。

### 2.2 修 P1：改为消费快照

`domain/authz/service.py:184` 与 `domain/authz/managed_users.py` 当前的递归下属遍历整段删除，改为：

```
MANAGED_USERS 的成员集合 = 权限快照响应里已解析的人员集合
  → 按 §2.1 的规则把每个 sub 映射为本地 dtuid
  → 映射不到的剔除并计数 + structlog 记录（不得静默）
  → 不得以 directory_users.is_active == False 为由剔除（契约 §7.3）
```

`scope_predicate.py:20` 编译 SQL 谓词的方式不变（仍然是 SQL 层过滤，不做 Python 后过滤）。
快照缓存沿用既有的 5 分钟软 / 15 分钟硬 TTL 与 fail-closed 行为
（`domain/authz/service.py:45,127`），只是集合来源变了。

**验证**：构造一个 `is_active=false` 的 `directory_users` 行 A，令快照的 `MANAGED_USERS` 含 A 的 sub，
断言项目/任务列表能查到 A 名下的数据。

---

## 3. 资产类型清单（契约 §11 要求的三列判定）

### 3.1 活的责任 —— 转移

| `asset_type` | 中文名 | 字段 | `releasable` | 口径与注意事项 |
|---|---|---|---|---|
| `project_owned` | 负责的项目 | `ProjectRow.owner_dingtalk_user_id`（`infra/repositories/projects.py:77`，非空） | **false** | 同时必须调整 `ProjectMemberRow` 里 `role=OWNER` 的那一行，见 §4.3 |
| `project_member` | 参与的项目 | `ProjectMemberRow.dingtalk_user_id`（PK `(project_id, user)`，`projects.py:117`） | **false** | 复合主键，接收人可能已是成员，见 §4.3 |
| `task_assigned` | 指派给我的未完成任务 | `TaskRow.assignee_dingtalk_user_id`（`tasks.py:105`，非空） | **false** | 仅非终态任务 |
| `task_assigner` | 我指派待我验收的任务 | `TaskRow.assigner_dingtalk_user_id`（`tasks.py:110`，非空） | **false** | 这是**活的验收权**（无独立 approver 字段），非历史署名，必须转移 |
| `task_collaborator` | 协作的任务 | `TaskCollaboratorRow.dingtalk_user_id`（PK `(task_id, user)`，`tasks.py:194`） | **false** | 复合主键，同 §4.3 |
| `recurring_assignee` | 周期任务模板负责人 | `RecurringTemplateRow.assignee_dingtalk_user_id`（`recurrence.py:81`，非空） | **false** | 不转移会持续生成指给离职者的任务 |
| `recurring_assigner` | 周期任务模板指派人 | `RecurringTemplateRow.assigner_dingtalk_user_id`（`recurrence.py:90`，非空） | **false** | 同上 |
| `recurring_collaborator` | 周期任务模板协作人 | `RecurringTemplateCollaboratorRow`（PK `(template_id, user)`，`recurrence.py:138`） | **false** | 会被复制进生成的任务，必须转移 |
| `work_record_participant` | 参与的工作记录 | `WorkRecordParticipantRow.dingtalk_user_id`（PK `(record_id, user)`，`work_records.py:102`） | **false** | 复合主键，同 §4.3 |
| `approval_pending` | 我发起的待审批 | `ApprovalRequestRow.requester_dingtalk_user_id`（`approvals.py:61`，非空） | **false** | 仅 pending 状态；契约 §11 判例：待审批属活的责任 |
| `reminder_occurrence` | 待发提醒 | `ReminderOccurrenceRow.recipient_dingtalk_user_id`（`reminders.py:48`，参与自然唯一键） | **false** | 仅未发送的；`$MANAGER` 占位符行不转移（它本就动态解析） |

### 3.2 历史事实 —— 一律不动

`ProjectRow.created_by_`、`ProjectMemberRow.added_by_`、`TaskRow.created_by_`、
协作人 `added_by_`、指派历史 `from_`/`to_`/`changed_by_`、状态流转 `actor_`、
评审 `submitted_by_` 与已决策的 `reviewer_`（`tasks.py:252` —— 该字段只在做出决定时写入，
是决策署名而非待办责任）、时间线 `TaskActivityRow.actor_` 与 `TaskActivityMentionRow.mentioned_`、
附件与项目文件上传人、任务关联创建人、周期模板创建人、提醒预设/规则创建人、
工时记录 `time_entries.user`、集成设置 `updated_by`、幂等记录 actor、审计日志 actor。

### 3.3 个人配置 —— 不转移

- `UserTaskViewRow`（`task_views.py:26`）：个人任务视图，唯一 `(user, name)` + 每人一个默认视图。
- `NotificationRecipientRow`（`notifications.py:63`）：站内信收件箱、已读/归档、外发状态，纯个人。
  契约 §11 判例已裁定订阅/通知类不转移。

### 3.4 特别裁定：`WorkRecordRow.created_by_dingtalk_user_id`

该字段名是历史式的，但实际充当工作记录的**当前归属**：更新/删除鉴权与 MANAGED 范围过滤都打在它上面
（`work_records.py:86,235`）。

**本次不转移，也不改名。** 理由：改动它等于同时改写"谁写的"与"谁负责"两个语义，且需要新增显式
owner 列与数据迁移，超出交接改造的范围。工作记录的可见性在代管期内由 §2.2 的快照修复覆盖
（主管能看到离职者的记录），足以支撑交接期业务。

若后续要转移，必须先补一次独立的领域改造：新增 `owner_dingtalk_user_id` 列 + 迁移 + 鉴权切换，
再作为一个新的 `asset_type` 加入注册表。**此项作为已知缺口写入本设计，不得默默忽略。**

---

## 4. 后端实现

### 4.1 资产注册表（新文件 `backend/app/domain/handover/assets.py`）

与 EasyTrade 同构：descriptor、preview、items、execute 四处共用一张表，杜绝漂移。

```python
@dataclass(frozen=True, slots=True)
class HandoverAssetSpec:
    type_key: str
    label: str
    detail_supported: bool
    releasable: bool                     # 本应用全部为 False, 见 §3.1
    count_stmt: Callable[[str], Select]           # dtuid -> count 语句
    items_stmt: Callable[[str, str], Select]      # (dtuid, q) -> 明细语句(稳定排序)
    render_item: Callable[[Any], tuple[str, str, str]]
    # (session, from_dtuid, to_dtuid|None, 限定的 asset_id 集合|None) -> 统计
    # to_dtuid=None 仅在 releasable=True 时出现; 本应用全部 False, 故实际恒为非 None
    reassign: Callable[[AsyncSession, str, str | None, Sequence[str] | None], Awaitable[ReassignResult]]
```

分层归属：注册表放 `domain/`（纯业务判定，不 import FastAPI / SQLAlchemy model 以外的东西——
按 `AGENTS.md` 后端分层，实际 SQL 语句构造下沉到 `infra/repositories/handover.py`，
`domain` 只持有 spec 与编排）。

### 4.2 API 端点（新文件 `backend/app/api/v1/easyauth_lifecycle.py`）

```
POST /api/v1/easyauth/lifecycle/handover
```

- 用 SDK 的 `lifecycle_http_response()` 内核做验签与事件分发（三个事件：preview / items / execute）
- 请求体上限 256 KiB（契约 §10.1）
- 直接使用 SDK 的 `handover_payloads` TypedDict，**禁止**手抄字段名
- 请求/响应模型**不继承** `app/core/schemas.ApiModel`：webhook 的 JSON 体由 EasyAuth 定义，是
  **snake_case**，与本仓库 camelCase 约定不同。详见 §5.4 的裁定与理由。

### 4.3 复合主键与唯一约束的处理（本仓库特有难点）

四类资产的表以 `(实体, 人)` 为复合主键，接收人**可能已经在里面**：

| 表 | 冲突场景 | 处理 |
|---|---|---|
| `ProjectMemberRow` | 接收人已是该项目成员 | 合并：删除离职者行；若离职者是 `OWNER` 而接收人是 `MEMBER`，把接收人行升级为 `OWNER`（满足"每项目一个 OWNER"的部分唯一索引，`m13_001_project_tables.py:127`）。计入 `merged` |
| `TaskCollaboratorRow` | 接收人已是协作人 | 直接删除离职者行，计入 `merged` |
| `RecurringTemplateCollaboratorRow` | 同上 | 同上 |
| `WorkRecordParticipantRow` | 同上 | 同上 |

`project_owned` 与 `project_member` 必须在**同一事务**内处理：改 `ProjectRow.owner_` 的同时调整
`ProjectMemberRow` 的 OWNER 行，否则会出现"项目负责人不是项目成员"的破损状态。
实现上把这两类合并到一个 `reassign` 实现里，由 `project_owned` 驱动，`project_member` 只处理
**非 OWNER** 的参与关系。

`reminder_occurrence` 的 recipient 参与自然唯一键，转移前需检查目标是否已有同一 occurrence，
已有则删除离职者行（计入 `merged`），避免唯一键冲突。

返回统计因此是四元：`{"transferred": n, "merged": m, "released": 0, "skipped": k}`。
`merged` 是 EasyProject 特有的合法结果，**必须如实上报**，不得并进 `transferred` 掩盖。

### 4.4 幂等

契约 §10.5 的幂等键是 `(task_id, generation)`。复用既有幂等基础设施
（`infra/repositories/reliability.py` 的幂等记录表），键为 `handover:{task_id}:{generation}`。
同键重放返回首次 `summary`；不同 `generation` 必须真正执行。

### 4.5 事务与网络副作用

按 `AGENTS.md` 不变量 4：execute 的业务写入（归属改写 + audit/activity + 站内通知）在一个事务内完成；
对 EasyAuth 的任何反向 HTTP 调用（如 §2.1 第 2 步的目录查询）**必须在事务外先做完**，
再进事务写库。**禁止持业务行锁调网络。**

因此 execute 的编排是：

```
1. 事务外: 解析 from/to 的全部 sub -> dtuid（可能触发目录查询与补绑）
2. 事务内: 校验 -> 逐 asset_type 改写 -> 写 audit/activity/站内通知 -> 写幂等记录
3. 事务后: 无网络副作用（交接结果由 EasyAuth 收敛）
```

### 4.6 descriptor（契约 §9.1）

`api/v1/easyauth_descriptor.py` 输出增加 `lifecycle.handover` 段，`asset_types` 由 §4.1 注册表生成，
`capability="declared"`，`url` 指向 §4.2 的端点。全部 11 类 `releasable` 均为 `false`（EasyProject 没有「无主」这一合法状态）。

> 这**不影响部分交接**：契约 §10.5 的 `default_action="skip"` + 逐条 `action="transfer"` 这条路径
> 与 `releasable` 无关，因此本应用的 11 类资产同样支持逐条改派。`releasable=false` 只是禁掉
> `action="release"` 这一种处置方式。

### 4.7 迁移

| 迁移 | 内容 |
|---|---|
| `mNN_001_handover_idempotency.py` | 幂等记录扩展以支持 `handover:{task_id}:{generation}` 键（若既有表已足够通用则本迁移可省，需在 PR 说明中明确结论） |

- 遵循 `AGENTS.md` 不变量 6：Alembic 是唯一 schema 入口，revision 命名 `mNN_###_description`，
  空库必须可 `upgrade head`，merge revision 只由 AG-00 创建。
- **本次不新增业务列**（§3.4 已说明为何不给 `WorkRecordRow` 加 owner 列）。

## 5. API 改造方案

### 5.1 好消息：端点已在冻结基线里，无需新增操作

核对 `contracts/openapi-baseline.json` 后确认，交接端点**早已被预留**，只是从未实现：

```json
"/api/v1/easyauth/lifecycle/handover": {
  "post": {
    "operationId": "postEasyauthLifecycleHandover",
    "summary": "EasyAuth 交接 preview/execute",
    "tags": ["M06"],
    "x-owner-agent": "AG-06",
    "x-owner-module": "M06",
    "x-auth": "easyauth-hmac",
    "x-required-permissions": [],
    "x-scope": null,
    "x-idempotency-key-required": false,
    "x-concurrency": null,
    "x-error-codes": ["WEBHOOK_SIGNATURE_INVALID", "HANDOVER_CONFLICT", "VALIDATION_ERROR"],
    "responses": { "default": { "$ref": "#/components/responses/ErrorResponse" } },
    "security": [{ "easyauthHmac": [] }]
  }
}
```

结论：

- **不需要新增操作，不需要新增权限码**（`x-required-permissions` 为空，端点靠 HMAC 验签鉴权）。
- **实现责任人是 AG-06 / M06**，不是新起的模块。
- `contracts/test-vectors/webhook-hmac.json` 的 `scheme.protectedEndpoints` **已经把本端点列入**
  受 HMAC 保护的端点，签名规范（Unix 秒十进制字符串、小写 hex 无前缀、300 秒容差、恒定时间比较）
  与契约 §10.1 **完全一致**，可直接复用 M20 审批 webhook 的既有验签实现。

### 5.2 需要 CCR 的部分（很小，但不可省）

只有一项：给这个既有操作的 `x-error-codes` 补齐条目。当前三个不足以覆盖契约 v2 的失败面。

| 错误码 | HTTP | 触发 | 现状 |
|---|---|---|---|
| `WEBHOOK_SIGNATURE_INVALID` | 401 | 验签失败 | 已有 |
| `WEBHOOK_TIMESTAMP_INVALID` | 400 | 时间戳超 300 秒容差 | **补** |
| `WEBHOOK_PAYLOAD_CONFLICT` | 409 | 同 delivery id 不同 payload hash | **补** |
| `EVENT_UNSUPPORTED` | 422 | `X-EasyAuth-Event` 不是 preview/items/execute/test | **补** |
| `IDENTITY_UNMAPPED` | 409 | §2.1 解析不到 dtuid | **补** |
| `ASSET_TYPE_UNDECLARED` | 422 | 请求里的 `asset_type` 不在注册表中 | **补** |
| `REQUEST_BODY_TOO_LARGE` | 413 | 超 256 KiB | **补** |
| `HANDOVER_CONFLICT` | 409 | 保留，用于归属改写时的业务冲突 | 已有 |
| `VALIDATION_ERROR` | 422 | 保留，payload 结构不合法 | 已有 |

CCR 内容（按 `contracts/workflow.md` §6 的六要素）：

1. **冲突描述**：既有 `x-error-codes` 仅三项，无法表达契约 v2 的身份解析失败、事件不支持、体积超限等失败面。
2. **不能模块内适配的原因**：`x-error-codes` 是基线字段，模块无权直接改，改了门禁即判漂移。
3. **影响面**：1 个既有操作的元数据；**0 个新增操作、0 个新增权限码、0 个 schema 变更**。
4. **兼容方案**：纯增量补充错误码，既有三项保留不动，无破坏性变更。
5. **同步修改清单**：`contracts/openapi-baseline.json` 该操作条目；`contracts/test-vectors/webhook-hmac.json`
   补 handover 事件的正反例向量（复用既有 `testSecret`）。
6. **回滚方式**：还原该操作条目即可，无数据与代码耦合。

**这份 CCR 应在开工第一天就提**（周期长于代码实现），但**不阻塞** §2.1/§2.2 两项修复的开发与合入。

### 5.3 错误体形状：不改，走状态码对齐

契约 §10.6 已裁定：**HTTP 状态码是唯一规范部分，响应体是参考信息**，EasyAuth 原样存入
`action.last_error` 并展示，不解析字段名。

因此本端点继续返回 EasyProject 标准错误体 `{"detail":{"code","message","traceId"}}`
（`components/schemas/ErrorBody`），**不需要**为 EasyAuth 另造一套 `{"error":{...}}` 信封。
基线里 `responses.default → ErrorResponse` 的声明保持不变，也无需 CCR。

> 这是本次改造中一处刻意的"不统一"：两个下游的错误码风格不同（EasyTrade 小写下划线、
> EasyProject 全大写），强行统一会产生一个纯粹为了好看的破坏性变更。按状态码对齐即可满足全部功能需求。

### 5.4 成功响应体：外部契约，走 snake_case 例外

三个事件的**成功**响应体形状由契约 §10.3/§10.4/§10.5 规定，是 **snake_case**
（`asset_types`、`page_size`、`default_to_user_id`…），与 `AGENTS.md` 不变量 5 的 camelCase 约定不同。

裁定：本端点的请求/响应模型**不继承 `ApiModel`**（不走 camelCase 别名生成），改用显式 snake_case
的 Pydantic 模型，文件头注释标明"外部系统冻结契约，属不变量 5 的例外"。

由于基线**不收敛响应 schema**（`components.schemas` 只有 `ErrorBody` 与 `Pagination` 两项），
这一例外**不产生基线漂移**，无需 CCR。

### 5.5 descriptor 输出变更

`GET /.well-known/easyauth-app.json`（基线中 `x-auth: descriptor-bearer`，owner 同为 AG-06）
的**响应体新增** `lifecycle.handover` 段（§4.6）。同 §5.4 的理由：响应 schema 不在基线内，
**不需要 CCR**。

但需同步更新 `docs/design/easyproject-manifest.draft.json` —— 该文件是 descriptor 内容的设计来源，
且 `contracts/test-vectors/webhook-hmac.json` 的 `sources` 引用了它的 `webhook.signing` 段。
不同步会造成设计与实现脱节。

### 5.6 目录用户响应补 `isActive`（供前端 §06 使用）

前端改造（`06-easyproject-frontend.md`）需要人员对象携带在职状态。涉及 M07 目录模块的
`getDirectoryUsers` 等响应体。

同样因为**响应 schema 不在基线内**，此项**大概率不需要 CCR**。但有一个前提必须先向 AG-00 核实：

> `contracts/tools/generate_baseline.py` 在再生基线时是否会把响应 schema 收敛进
> `components.schemas`。若会，则新增字段会造成基线漂移，需并入 §5.2 的 CCR 一起提。

**开工前必须拿到这个确认**，不要靠猜。若确认不需要 CCR，则该字段由 AG-07（M07 owner）实现，
前端生成物由 AG-00 再生。

### 5.7 共享热点（必须走 AG-00）

按 `AGENTS.md` 不变量 7，以下文件**只提交补丁，不直接并发编辑**：

| 文件 | 用途 |
|---|---|
| `backend/app/api/v1/router.py` | 注册交接 router |
| `backend/app/main.py` | 若 descriptor 路由需调整 |
| `contracts/openapi-baseline.json` | §5.2 CCR 通过后由 AG-00 更新 |
| `contracts/test-vectors/webhook-hmac.json` | 同上 |
| `frontend/src/lib/api/generated/openapi.d.ts` | 生成物，AG-00 再生 |
| `backend/app/infra/job_registry.py` | 本次**不涉及**（交接无定时任务），列此备查 |

---

## 6. 测试

| 文件 | 覆盖 |
|---|---|
| `backend/tests/unit/authz/test_managed_users_from_snapshot.py` | **P1**：集合来自快照而非递归遍历；inactive 成员保留；映射不到的剔除且有计数日志 |
| `backend/tests/unit/identity/test_handover_identity.py` | **P2**：已绑定命中；未绑定走目录补绑；冲突绑定被拒；解析不到抛 `IdentityUnmappedError` |
| `backend/tests/unit/handover/test_assets_registry.py` | 11 类 count 口径；注册表与 descriptor 用同一常量断言 |
| `backend/tests/unit/handover/test_items_pagination.py` | 排序稳定、连续翻页不漏不重、`total` 与 preview 一致 |
| `backend/tests/integration/handover/test_execute_composite_keys.py` | §4.3 四类合并场景；OWNER 升级；每项目一个 OWNER 的部分唯一索引不被违反；`merged` 如实上报 |
| `backend/tests/integration/handover/test_execute_transaction.py` | §4.5：事务内无网络调用；失败整体回滚 |
| `backend/tests/integration/handover/test_idempotency.py` | `(task_id, generation)` 幂等；不同 generation 真正重执行 |
| `backend/tests/contract/test_handover_v2_golden.py` | 直接比对 `EasyAuth/tests/contract_samples/handover_v2/*.json` |

golden 样本取用：CI 用环境变量指向 EasyAuth 仓库；本地按 `../EasyAuth/...` 相对路径读取，
**找不到时跳过并显式报告 skip 原因**，不得静默通过。

pytest 使用既有 async auto 模式与 unit/integration/contract 标记（`backend/pyproject.toml:70`）。
全量门禁：`scripts/quality-gate.sh`。

---

## 7. 交付顺序

1. **§2.2 修 P1**（独立、最高价值、单独可上线；不改它则代管授权对本应用永远无效）
2. §2.1 身份映射（修 P2）
3. §5.2 提 CCR（**与 1/2 并行提，通过周期较长，越早越好**）；同时向 AG-00 核实 §5.6 的前提
4. §4.1 注册表 + §4.6 descriptor（共用常量，同一提交）
5. §4.2 端点 + preview / items
6. §4.3 §4.4 §4.5 execute
7. §6 测试补齐

每完成一项立即单独 commit。§3.4 的 `WorkRecordRow` 缺口必须写进 PR 描述与
`docs/design/09-分期计划与风险清单.md`，不得默默留着。
