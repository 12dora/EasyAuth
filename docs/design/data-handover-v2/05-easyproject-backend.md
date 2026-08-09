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

**数据交接则处于"有壳无肉"的状态**（这与本文件早期版本写的"完全未接入"不同，以此处为准）：

- `backend/app/api/v1/easyauth_lifecycle.py` 已存在，router 已在 `api/v1/router.py:56` 挂载
  （`# M06 lifecycle handover`）。
- `backend/app/domain/authz/lifecycle.py` 已有 `HandoverRequest` / `HandoverContributor` /
  `HandoverReceiptStore` 框架，但：
  - 用的是 **v1 payload**（`to_user_id` 单接收人，无 `assignments`）
  - 幂等靠 **`InMemoryHandoverReceiptStore`** —— 进程重启即失忆，多实例部署直接失效
  - **contributor 是空的**，注释写明"G2 由各领域注册"，至今未注册
  - 有 partial-success 语义（`ContributorCount.failures`），与契约 §10.5「整事务成败一致」冲突

所以真实工作量是**把占位实现改写为 v2**，不是从零新建：删掉 v1 payload 解析、换掉内存幂等、
去掉 partial-success、把 contributor 真正实现出来。改写时按 `AGENTS.md`「不保留历史错误形态」
一次性替换，不留兼容分支。

### 1.1 两个必须先修的阻塞项

| # | 问题 | 位置 | 后果 |
|---|---|---|---|
| ~~P1~~ | `MANAGED_USERS` 不消费 EasyAuth 快照，而是自己递归调下属接口推算 | `backend/app/domain/authz/managed_users.py:19` | **本期降级为已知偏差，不修**。它确实违反 EasyAuth 下游契约（`CONTEXT.md`「管理对象快照」条），但原本的修复依据是代管授权，而代管已整体废弃（契约 §7）。本项与数据交接无关，另行立项 |
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
3. 用该 dtuid 回填 `authentik_user_id`。**不得复用登录绑定路径**：
   `user_repo.bind_or_refresh()` 会同时写 `first_login_at` / `last_login_at`
   （`infra/repositories/directory.py:675,676`），webhook 触发时写这两个字段等于**伪造登录事实**，
   会污染"从未登录"的判定与相关统计。
   需要**新增**一个"已验证 sub 的纯绑定"用例：只写 `authentik_user_id`，复用既有的冲突检测
   （dtuid↔sub 不一致时拒绝，`domain/identity/binding.py` 的 `platform_sub_mismatch` /
   `local_binding_conflict` 逻辑），**不碰任何时间戳**。
4. 仍解析不到 → 抛 `IdentityUnmappedError`，API 层转 **HTTP 409**，错误码 `IDENTITY_UNMAPPED`，
   错误体沿用本仓库标准 `ErrorBody`（契约 §10.6 只规范状态码，见 §5.3）。

**禁止**按姓名/邮箱模糊匹配（违反不变量 1）。**禁止**静默跳过或返回空统计 —— 那会让 EasyAuth 误判
"此人在 EasyProject 无数据"。

### 2.2 ~~修 P1~~ —— **本期取消**

见 §1.1。代管废弃后本项失去依据，`domain/authz/managed_users.py` 与 `service.py` **一行不改**。
该偏差记入 `docs/design/09-分期计划与风险清单.md`。

### 2.3 `hint` 是硬要求，不是可选项

代管废弃后，主管**只能靠交接单里的明细判断归属**。`items` 响应里每条的 `hint`（≤120 字符）
承担全部判断依据：

| `asset_type` | `hint` 必须包含 |
|---|---|
| `project_owned` / `project_member` | 项目状态 + 截止日期 + 成员数 |
| `task_assigned` / `task_assigner` | 所属项目 + 截止日期 + 当前状态 |
| `task_collaborator` | 所属项目 + 任务标题 |
| `recurring_assignee` / `recurring_assigner` / `recurring_collaborator` | 周期规则 + 下次生成时间 |
| `work_record_participant` | 关联项目/任务 + 记录日期 |

**`hint` 为空或只有 ID 视为未完成本项**，验收用例须逐类断言。

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

### 3.1.1 两类**不做**独立资产的裁定（复核后修正）

早期版本把下面两项列成了 `asset_type`，都是错的，已删除：

| 原资产类型 | 为什么错 | 正确处理 |
|---|---|---|
| `approval_pending`（我发起的待审批） | 两处都错：一、活跃状态是 `CREATED` / `SUBMITTED`（`infra/repositories/approvals.py:187`），不是 "pending"。二、`requester_dingtalk_user_id` 是**发起人**（历史事实），不是当前审批人；改它**根本不会**改变谁该审批 —— 审批责任在 EasyAuth/钉钉一侧 | **EasyProject 侧不做**。审批责任的改派已由 **EasyAuth 承担**（契约 §11.1、`01` §4.5）：EasyAuth 自身的权限申请审批人必改；钉钉审批规则的审批人必替换；在途钉钉实例作为只读清单显式呈现待人工转办。EasyProject 无需为此新增任何 asset_type |
| `reminder_occurrence`（待发提醒） | recipient 不是一个可以脱离任务角色单独搬的字段：它由 `payload_snapshot.recipientRole` 在入队时**重新解析**并与任务当前角色比对（`infra/jobs/reminder_enqueue.py:269-310`）。把它当独立资产、脱离任务改派单独转移，只会制造角色与收件人不一致 | **不做独立资产**，改为任务/模板改派的**连带副作用**（见 §4.3.1）。**这一步不是可选的**，见下方警告 |



### 3.1.2 终态谓词（必须冻结在共享选择器里）

上表的"口径"列是规范。复核发现只有 `task_assigned` 一行写明了终态条件，其余全缺，必须补齐并
冻结在 `HandoverAssetSpec` 的查询定义里，preview / items / execute 共用：

| 类型 | 完整谓词 |
|---|---|
| `project_owned` / `project_member` | 项目状态不在 `{COMPLETED, CANCELLED}` |
| `task_assigned` / `task_assigner` / `task_collaborator` | 任务状态不在 `{COMPLETED, CANCELLED}` |
| `recurring_assignee` / `recurring_assigner` / `recurring_collaborator` | 模板 `is_enabled = true` |
| `work_record_participant` | 工作记录 `status = 'OPEN'` |

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

**分层：`domain` 不得出现 `Select` / `AsyncSession`**（`AGENTS.md` 后端分层：domain 不导入
FastAPI / SQLAlchemy model / SDK DTO）。因此上面的签名是**示意**，真实形态必须是：

- `domain/handover/assets.py`：只持有 `type_key` / `label` / `detail_supported` / `releasable`
  与一个**领域端口协议**（`HandoverAssetPort`），不碰任何 SQLAlchemy 类型。
- `infra/repositories/handover.py`：实现该端口，SQL 语句、`AsyncSession`、`Select` 全在这里。
- `domain/handover/service.py`：编排（校验 assignments、按 action 分派、汇总 summary）。

### 4.1.1 归属改写必须走各领域的显式命令，**不得跨表裸 UPDATE**

这是本仓库最硬的一条约束（`AGENTS.md` 不变量 3「显式状态命令」、不变量 4「网络副作用出事务」）：
任务/项目的状态与责任变更必须走领域命令端点，禁止 `PATCH status` 式的裸改。
交接同样不能例外 —— 裸 UPDATE 会绕过版本号、assignment history、activity 时间线、提醒物化
与审批锁，产生一堆自相矛盾的数据。

因此：

> **每个涉及的领域模块各自提供一个 `system_handover` 命令用例**，由 M06 的交接服务调用。
> 命令内部锁聚合根、走既有状态机、写全套副作用（history / activity / 站内通知 / 提醒重物化），
> 并对 `APPROVAL_PENDING` / `FIELD_LOCKED` 等锁状态返回明确的领域错误。

M06 **只做编排与契约适配**，一行业务 UPDATE 都不写。

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

`project_owned` 与 `project_member` 必须在**同一事务**内处理，否则会出现"项目负责人不是项目成员"
的破损状态。两条硬性规定：

1. **`project_member` 的谓词必须显式排除 OWNER 行**（`role != 'OWNER'`），否则同一条成员关系
   会被 `project_owned` 和 `project_member` 各算一次，统计重复。
2. **OWNER 的升级顺序不能反**：`ProjectMemberRow` 上"每项目至多一个 OWNER"是**部分唯一索引且非
   deferrable**，先把接收人升为 OWNER 会立即撞唯一约束。正确顺序是
   **先删除/降级离职者的 OWNER 行 → flush → 再升级接收人 → 最后同步 `ProjectRow.owner_`**。

### 4.3.1 提醒的连带重物化（取代原先的独立资产类型）

> **⚠ 不做这一步的后果是「整组提醒静默全灭」，不是「少发一条」。**
>
> 入队任务会逐行按 `recipientRole` 重解当前归属并与任务上的角色比对
> （`infra/jobs/reminder_enqueue.py:276-309`）。`ASSIGNEE` 角色的行若
> `row.recipient_dingtalk_user_id != task.assignee_dingtalk_user_id` 即判为 stale；
> 而 `:313-315` 是**整组 fail-closed** —— 只要该组里有任何一行 stale 或 inactive，
> **这一组的全部 occurrence 都被标 `SKIPPED` 并直接返回，一条提醒都不发**。
>
> 也就是说：改了任务负责人却不管 occurrence，接收人**收不到任何提醒，而且没有任何报错**。
> 这正是本次改造要消灭的那类"看起来成功、实际什么都没发生"。

任务/周期模板的角色改派完成后，**同一事务内**必须：

1. 取消该任务/模板下所有**未发送**的 `ReminderOccurrenceRow`（不只是 recipient 为离职者的那些）；
2. 复用领域既有的物化用例按新角色重新物化（`infra/jobs/reminder_materialize.py`），
   **不要**在交接代码里手写 INSERT。

**为什么是"取消+重物化"而不是"直接 UPDATE recipient"**：
`ASSIGNEE` / `ASSIGNER` 两种角色直接改 recipient 确实能重新对上，但 `MANAGER` 角色的收件人是
**负责人的主管**（`reminder_enqueue.py:292-306` 还要校验 `assignee_state[1] == manager_dtuid`），
换了负责人就得换成新负责人的主管，UPDATE 一个字段解决不了。统一走重物化对三种角色都正确，
也不需要在交接代码里复刻角色解析逻辑。

> 顺带更正一处早期表述：本文件先前写的"直接 UPDATE recipient 会被判 `RECIPIENT_STALE`"是反的 ——
> **不更新才会 stale**。真正的理由是上面的 `MANAGER` 角色问题，以及不该在交接代码里重写角色解析。

### 4.3.2 统计口径

返回统计沿用契约 §10.5 冻结的**五元** `{transferred, released, skipped, merged, failed}`。
本应用 `released` 恒为 0（全部 `releasable=false`）、`failed` 恒为 0（整事务成败一致）；
`merged` 是复合主键合并的正常结果，**必须如实上报**，不得并进 `transferred` 掩盖。

### 4.4 幂等

契约 §10.5 的幂等键是 `(task_id, generation, batch_id)`。复用既有幂等基础设施
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

`api/v1/easyauth_descriptor.py` 的 `lifecycle` 段按契约 §9.1 的形状扩展 —— **不新增嵌套对象**，
而是在既有 `lifecycle` 下：

- `capabilities` 数组里加入 `"handover.v2"`；
- 新增 `handover_asset_types` 数组，逐项 `{type, label, detail_supported, releasable}`，
  由 §4.1 注册表生成（与 preview/items/execute 共用同一常量，杜绝漂移）；
- `handover_url` 指向 §4.2 的端点。

全部 9 类 `releasable` 均为 `false`（EasyProject 没有「无主」这一合法状态）。

> 契约 §9.1 已废弃早期的嵌套 `lifecycle.handover` 对象与独立的 `capability` 字段；
> 能力判定的**唯一**依据是 `capabilities` 里是否出现 `"handover.v2"`。

> 这**不影响部分交接**：契约 §10.5 的 `default_action="skip"` + 逐条 `action="transfer"` 这条路径
> 与 `releasable` 无关，因此本应用的 9 类资产同样支持逐条改派。`releasable=false` 只是禁掉
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
| `HANDOVER_CONFLICT` | 409 | 保留，用于归属改写时的业务冲突、快照失效、迟到 generation | 已有 |

> **401 与 403 的定级冲突需一并裁定**：本仓库的 webhook 验签失败返回 **401
> `WEBHOOK_SIGNATURE_INVALID`**（`contracts/test-vectors/webhook-hmac.json` 的反例已冻结），
> 而契约 §10.6 把验签失败列在 401/403 同一行。两者语义一致、EasyAuth 侧处置相同（`failed` 且不可重试），
> **以本仓库的 401 为准**，无需改动，但 CCR 里要写明这一裁定，避免后续被当成不一致。
| `VALIDATION_ERROR` | 422 | 保留，payload 结构不合法 | 已有 |

CCR 内容（按 `contracts/workflow.md` §6 的六要素）：

1. **冲突描述**：既有 `x-error-codes` 仅三项，无法表达契约 v2 的身份解析失败、事件不支持、体积超限等失败面。
2. **不能模块内适配的原因**：`x-error-codes` 是基线字段，模块无权直接改，改了门禁即判漂移。
3. **影响面**：1 个既有操作的元数据；**0 个新增操作、0 个新增权限码、0 个 schema 变更**。
4. **兼容方案**：纯增量补充错误码，既有三项保留不动，无破坏性变更。
5. **同步修改清单**：`contracts/openapi-baseline.json` 该操作条目；`contracts/test-vectors/webhook-hmac.json`
   补 handover 事件的正反例向量（复用既有 `testSecret`）；
   **`contracts/tools/generate_baseline.py` 本身**（它是基线的权威再生入口，不改则下次再生会把
   新增错误码覆盖掉）。
6. **回滚方式**：还原该操作条目即可，无数据与代码耦合。

**这份 CCR 应在开工第一天就提**（周期长于代码实现）。

**CCR 批准前的可做/不可做边界**（按 `contracts/workflow.md` §6「AG-00 批准前所有 Agent 继续用旧契约」）：

| 可以先做 | 必须等 CCR APPROVED |
|---|---|
| §2.2 修 P1（消费快照，纯内部实现） | 交接端点的 v2 改写 |
| §2.1 修 P2（身份映射，纯内部实现） | 新错误码的实现与返回 |
| 领域侧 `system_handover` 命令用例（§4.1.1，各模块内部） | descriptor 输出变更 |
| 单元测试 | 测试向量更新、契约测试 |

即：**CCR APPROVED 是 M06 交接端点实施的门禁**，不是"边做边等"。

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
的**响应体扩展 `lifecycle` 段**（`capabilities` 增项 + 新增 `handover_asset_types`，见 §4.6）。同 §5.4 的理由：响应 schema 不在基线内，
**不需要 CCR**。

但需同步更新 `docs/design/easyproject-manifest.draft.json` —— 该文件是 descriptor 内容的设计来源，
且 `contracts/test-vectors/webhook-hmac.json` 的 `sources` 引用了它的 `webhook.signing` 段。
不同步会造成设计与实现脱节。

### 5.6 目录在职状态：**后端无需改动**（复核后修正）

早期版本要求"给目录响应补 `isActive`"，这是错的 —— **该字段早就有了**：
`backend/app/api/v1/directory.py:170,193,221,262,357` 的 DTO 均含 `is_active`，
生成的前端 TS 类型里也有。

真正缺的是**调用方没有按用途传 `includeInactive`**：
`backend/app/api/v1/directory.py:292` 已提供 `includeInactive` query 参数
（`infra/repositories/directory.py:239,244` 据此决定是否过滤），默认 `False`。

因此这一项**没有任何后端改动，也不需要 CCR**，纯粹是前端按场景传参（见 `06` §3.2、§4）。
后端唯一要做的是**在 API 文档里把两种用途写清楚**，避免前端继续用默认值。

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
| `backend/tests/unit/identity/test_handover_identity.py` | **P2**：已绑定命中；未绑定走目录补绑；冲突绑定被拒；解析不到抛 `IdentityUnmappedError` |
| `backend/tests/unit/handover/test_assets_registry.py` | 11 类 count 口径；注册表与 descriptor 用同一常量断言 |
| `backend/tests/unit/handover/test_items_pagination.py` | 排序稳定、连续翻页不漏不重、`total` 与 preview 一致 |
| `backend/tests/integration/handover/test_execute_composite_keys.py` | §4.3 四类合并场景；OWNER 升级；每项目一个 OWNER 的部分唯一索引不被违反；`merged` 如实上报 |
| `backend/tests/integration/handover/test_execute_transaction.py` | §4.5：事务内无网络调用；失败整体回滚 |
| `backend/tests/integration/handover/test_idempotency.py` | `(task_id, generation, batch_id)` 幂等；不同 generation 真正重执行 |
| `backend/tests/contract/test_handover_v2_golden.py` | 从 `easyauth_app_sdk.contract_samples` 包内资源读取样本逐字段比对；样本缺失必须 fail |

golden 样本取用：**随 SDK 分发**（`easyauth_app_sdk.contract_samples` 包内资源，版本与 SDK 绑定），
用 `importlib.resources` 读取。**不得**依赖 `../EasyAuth/` 兄弟目录路径 —— 本仓库 CI 独立检出，
那条路径必然不存在，测试会稳定退化成 skip。**样本缺失必须让测试失败**，不允许 skip 通过。

pytest 使用既有 async auto 模式与 unit/integration/contract 标记（`backend/pyproject.toml:70`）。
全量门禁：合入后跑**完整**的 `scripts/quality-gate.sh`（Ruff、migration smoke、PostgreSQL 实库 pytest、
secret 扫描、前端检查、契约检查）。**不存在只跑"前端段"这种用法**，不要在文档或 CI 里那样写。

---

## 7. 交付顺序

1. ~~§2.2 修 P1~~ —— 本期取消（代管废弃）
2. §2.1 身份映射（修 P2）+ §2.3 `hint`
3. §5.2 提 CCR（**与 1/2 并行提，通过周期较长，越早越好**）；同时向 AG-00 核实 §5.6 的前提
4. §4.1 注册表 + §4.6 descriptor（共用常量，同一提交）
5. §4.2 端点 + preview / items
6. §4.3 §4.4 §4.5 execute
7. §6 测试补齐

每完成一项立即单独 commit。§3.4 的 `WorkRecordRow` 缺口必须写进 PR 描述与
`docs/design/09-分期计划与风险清单.md`，不得默默留着。
