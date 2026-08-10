# 05 · EasyProject 后端接入设计

> 基准文档：`00-overview-and-contract.md`（下称「契约」）。
> 契约中的事件名、payload 形状、错误码、身份规则是**冻结**的，本文件不重复定义，只给 EasyProject 落地方案。
> **开工条件：AG-00 批准 [`08`](08-easyproject-ag00-rulings.md) 的两份裁定 + [`09`](09-easyproject-ccr.md)
> 的 CCR APPROVED + M03 发布 SDK vNext**（三道门禁各管一段，见 §5.2 与 `08` §1.6）。
> 之后与 EasyAuth、EasyTrade 的实现并行推进，唯一耦合点是契约 §10 的 webhook 形状与
> SDK 包内的契约样本（`easyauth_app_sdk.contract_samples.handover_v2`，用 `importlib.resources` 读）。
> **不要**去 `../EasyAuth/tests/` 找样本 —— 本仓库 CI 独立检出，兄弟目录必然不存在，测试会稳定退化成 skip。

---

## 1. 现状与差距

EasyProject 已接入 EasyAuth 的四个适配器：目录（`infra/easyauth_directory/`）、授权
（`infra/easyauth_authz/`）、审批（`infra/easyauth_approval/`）、通知（`infra/easyauth_notify/`），
descriptor 已暴露在 `GET /.well-known/easyauth-app.json`（`api/v1/easyauth_descriptor.py:50`）。

**数据交接则处于「有壳无肉」的状态**：

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

P2 与 webhook 实现相互独立，且**不受 A5 阻塞与 CCR 门禁的限制**（纯内部实现，不碰契约），
应作为第一个可单独验证、单独上线的提交。

---

## 2. 身份映射（契约 §5.2）

### 2.1 规则

契约规定跨系统 payload 中的人员字段一律是 Authentik `sub`。EasyProject 的业务外键是
`directory_users.dingtalk_user_id`（dtuid，`AGENTS.md` 不变量 1），因此每次收到 payload 都要解析。

新增 `backend/app/domain/identity/handover_identity.py`：

```python
async def resolve_dtuid(*, authentik_sub: str, purpose: Literal["source", "target"]) -> str:
    # 把契约里的 Authentik sub 解析为本地 dtuid; 解析不到抛 IdentityUnmappedError
    # 注意: 不接收 uow/session —— 三段边界见下
```

> **不要把 `uow` 传进来。** 「本地 SELECT → 调 EasyAuth 目录 → 回填」三步如果共用一个 session，
> 第一次 SELECT 就已经 autobegin，**整个 HTTP 等待期间都占着一个连接和一个打开的事务**
> （`AGENTS.md` 不变量 4 明确禁止），并发几个 webhook 就能把连接池耗干，
> execute 连进业务事务的机会都没有。
>
> 三段边界写死：
>
> | 段 | 边界 |
> |---|---|
> | ① 查本地映射 | 短只读 session，查完**立刻 rollback/close** |
> | ② 调 `DirectoryPort` | **手上没有任何 DB session** |
> | ③ 纯绑定回填 | 另开一个短写事务 |
>
> 全部人员解析完成之后，**才**新开 execute 的业务事务。禁止复用跨 HTTP `await` 的 session。

解析顺序：

1. 查 `directory_users where authentik_user_id = sub` → 命中即返回 dtuid。
2. 未命中 → 用**既有的** `DirectoryPort.get_user(user_ref)`，把裸 Authentik `sub` 直接当
   `user_ref` 传进去，拿到其 dtuid。

   > **这条路现在就能走通，不用等 SDK vNext。** EasyAuth 侧的
   > `parse_user_ref()`（`accounts/directory_references.py:58`）对**不以 `dt:` 开头**的引用
   > 一律解释为 `kind="authentik"`，随后 `resolve_directory_user()`（`:89-97`）直接按
   > `UserMirror.authentik_user_id` 查。所以裸 sub 是这个接口本来就接受的一种输入形态。
   >
   > SDK vNext 可以补一个语义更清楚的别名与文档，但**那不是 P2 的前置依赖** ——
   > 把 P2 挂在 SDK 上会让"从未登录过 EasyProject 的员工"这批人白白多等一个交付周期。
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

下面两项**看起来像**该转移的资产，实际都不是。逐条说明为什么，避免有人再把它们加回来：

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
owner 列与数据迁移，超出交接改造的范围。

> **这是一个真实的缺口，不要用"有别的东西覆盖了"来自我安慰。** 本文件早期版本写的是
> 「可见性由 §2.2 的快照修复在代管期内覆盖」—— 代管与 P1 都已整体砍掉（契约 §7），
> 这个理由**已经不成立**。
>
> 缺口的准确表述是：离职者名下的工作记录，在交接完成后**仍然挂在他的
> `created_by_dingtalk_user_id` 上**，接收人既看不到也改不了，主管只能在交接单的
> `work_record_participant` 明细里看到他**参与**的记录，看不到他**创建**的记录。
> 契约 §11.1 已把这一条登记为 D11 的两条显式例外之一。

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

> **每个涉及的领域模块各自提供一个专用 `system_handover` 命令用例**，由 M06 的交接服务调用。
> 命令内部锁聚合根、**保住业务不变量**，并对审批锁 / 终态 / 归属已变返回明确的领域错误。

**六个命令的确切签名、逐条保证、以及每张表允许写哪些列，由 AG-00 裁定冻结，见
[`08-easyproject-ag00-rulings.md`](08-easyproject-ag00-rulings.md) §1.3。本节只讲原则。**

两条容易写反的原则：

1. **不得复用会改变状态的人类命令。** 现有 task `reassign` 会把任务重新推回 `PENDING_ACCEPTANCE`
   （`domain/tasks/state_machine.py:56-69`）。交接只转**责任**，不改状态 ——
   `status` / `state_version` / `accepted_at` / review 状态一律保持不变。
2. **只写适用的 history / activity / 提醒重物化，不发逐对象站内通知。**
   本文件早期版本写的"写全套副作用（含站内通知）"是错的：普通改派每任务发一条通知
   （`domain/tasks/commands.py:980-997`），批量交接调用它就是一场通知风暴。
   完成通知由 EasyAuth 在 action / 整单收敛后合并发送（契约 §13）。

M06 **只做编排与契约适配**，一行业务 UPDATE 都不写。

### 4.2 API 端点（**改写既有文件** `backend/app/api/v1/easyauth_lifecycle.py`）

```
POST /api/v1/easyauth/lifecycle/handover
```

**这不是新建。** 该文件与 route 已存在（`api/v1/easyauth_lifecycle.py:55-92`），
router 也已在 `api/v1/router.py:49-56` 挂载。工作是把 v1 占位实现**原地改写**为 v2，
保留既有 route 与 `operationId`（`postEasyauthLifecycleHandover` 已在冻结基线里）。

- 用 SDK 的 `lifecycle_http_response()` 内核做验签、`event_type` 一致性校验与事件分发
  （三个事件：preview / items / execute）
- 请求体上限 256 KiB（契约 §10.1）。**必须用 SDK 的 `read_bounded_body()`，
  禁止 `await request.body()`** —— 后者在验签之前就把整个体读进内存，
  不持有 secret 的人也能用超大或 chunked body 反复打内存，上限形同虚设。
  测试同时覆盖伪造 `Content-Length` 与 chunked 超限
- 直接使用 SDK 的 `handover_payloads` TypedDict，**禁止**手抄字段名
- **业务错误一律抛 SDK 的 `HandoverBusinessError(status_code, code, message)`**（`01` §8 第 6.1 条）。
  现有回调协议只返回 dict，内核一律包成 200 或 500 —— §5.2 那些错误码里除验签外
  **一个都发不出去**。API 层再把它映射成本仓库标准 `ErrorBody`
- 请求/响应模型**不继承** `app/core/schemas.ApiModel`：webhook 的 JSON 体由 EasyAuth 定义，是
  **snake_case**，与本仓库 camelCase 约定不同。详见 §5.4 的裁定与理由。

> **⚠ 上面三条 SDK 能力现在一个都没有。**
> vendored SDK 当前只有 preview / execute 两个事件、`DEFAULT_MAX_BODY_BYTES = 64 KiB`、
> 没有 `handover_payloads`，`manifest.py:101-118` 的 `_validate_lifecycle()` 白名单还会
> **拒绝** `handover_asset_types`。
>
> 因此这是一条硬依赖：**M03 先升级 vendored SDK（`08` §1.2），A5 才能引用 items 回调、
> v2 payload 类型与 256 KiB 常量。** 在那之前写这些代码只会得到 ImportError。

### 4.3 复合主键与唯一约束的处理（本仓库特有难点）

四类资产的表以 `(实体, 人)` 为复合主键，接收人**可能已经在里面**：

| 表 | 冲突场景 | 处理 |
|---|---|---|
| `ProjectMemberRow` | 接收人已是该项目成员 | 合并：**删除**离职者行（**不得降级为 `MEMBER`** —— 降级会让离职者留在 `project_members` 里，而项目可见性只看成员行是否存在（`infra/repositories/project_queries.py:115`），交接完成后他照样看得到这个项目）；若离职者是 `OWNER` 而接收人是 `MEMBER`，把接收人行升级为 `OWNER`（满足「每项目一个 OWNER」的部分唯一索引，`m13_001_project_tables.py:135-142`）。计入 `merged` |
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

**只有任务（`task_assigned` / `task_assigner`）的角色改派需要这一步**，**同一事务内**必须：

1. **先算出新集合，再按自然键做差集**（`08` §1.3 M18 已冻结的三分支）：

   | 情形 | 处理 |
   |---|---|
   | 自然键在新集合里也存在 | **原位保持/恢复 `PENDING`**，刷新 `payload_snapshot`，不删不插 |
   | 旧行的自然键不在新集合里 | 标 `SKIPPED` / `HANDOVER_SUPERSEDED` |
   | 新集合里的全新自然键 | INSERT |

2. 复用领域既有的物化用例按新角色计算新集合（`infra/jobs/reminder_materialize.py`），
   **不要**在交接代码里手写 INSERT。

> **不能"先把未发送的全部 SKIP 再重物化"。**
> `uq_reminder_occurrences_natural` 与 `uq_reminder_occurrences_dedup_key` 都是
> **永久唯一键、不按 status 过滤**（`alembic/versions/m18_001_reminder_tables.py:243-251`），
> 被标 `SKIPPED` 的旧行仍然占着自然键；而现有插入用的是 `ON CONFLICT DO NOTHING`
> （`infra/repositories/reminders.py:339`）—— 结果是**静默不插入，最终一条 PENDING 提醒都没有**。
> 典型触发：assignee A→B 而 assigner 本来就是 B，新旧集合必然有自然键重叠。

具体由 M18 的 `refresh_after_system_handover()` 承担（`08` §1.3），M06 不直接改 occurrence。

> **周期模板改人不走这一步，也走不了。** `reminder_occurrences` 的外键是
> `(rule_id, task_id) → task_reminder_rules(id, task_id)`（`infra/repositories/reminders.py:97-105`），
> **表里根本没有 template_id 这一维**，无从按模板去筛。
> 模板改人之后，由它生成的**新任务**天然带新角色，提醒随新任务正常物化；
> 已经生成出来的历史任务则各自作为独立任务参与交接。
> 本文件早期版本写的「取消该任务/**模板**下所有未发送 occurrence」，对模板那半是无法实现的。

**为什么是"取消+重物化"而不是"直接 UPDATE recipient"**：
`ASSIGNEE` / `ASSIGNER` 两种角色直接改 recipient 确实能重新对上，但 `MANAGER` 角色的收件人是
**负责人的主管**（`reminder_enqueue.py:292-306` 还要校验 `assignee_state[1] == manager_dtuid`），
换了负责人就得换成新负责人的主管，UPDATE 一个字段解决不了。统一走重物化对三种角色都正确，
也不需要在交接代码里复刻角色解析逻辑。

### 4.3.2 统计口径

返回统计沿用契约 §10.5 冻结的**五元** `{transferred, released, skipped, merged, failed}`。
本应用 `released` 恒为 0（全部 `releasable=false`）、`failed` 恒为 0（整事务成败一致）；
`merged` 是复合主键合并的正常结果，**必须如实上报**，不得并进 `transferred` 掩盖。

### 4.3.3 `snapshot_token` 的生成与校验（契约 §10.5.1，**原设计整段缺失**）

`preview` 必须返回它，`items` 与 `execute` 必须回带并校验它。三处**共用同一个生成函数**：

### items 的参数上界（与 `03` §3.5 同规格，契约 §10.4）

**任何身份解析、事务或 SQL 之前**先校验，违反直接 `422`，**不要钳制后继续查**：

| 参数 | 约束 |
|---|---|
| `page` | `1 ≤ page ≤ 100000` |
| `page_size` | `1 ≤ page_size ≤ 200` |
| `q` | 去空白后 UTF-8 ≤ 128 字节 |

排序必须稳定（按主键兜底），否则翻页会漏项/重项。
验签后按**签名覆盖的 body 指纹**做 300 秒响应缓存或 single-flight，超限返回 `429 RATE_LIMITED`；
**不能只按 `delivery_id` 去重** —— 那个头不在签名里。

preview 的 9 类 count 与 token、items 的 token 校验与 total/rows，
**各自必须在一个 `REPEATABLE READ READ ONLY` 事务里完成**，共用同一份物化基础集合。
默认隔离级别下，先数出 187 条、随后并发新增第 188 条、再算出包含 188 条的 token ——
界面上确认的是 187 条，而 execute 的 token 校验会通过，第 188 条按默认动作被一起搬走。

```python
async def build_snapshot_token(session, *, from_dtuid: str) -> str:
    # 遍历 §3.1 的 9 类, 用 §3.1.2 的同一批共享选择器取
    # (type_key, asset_id, 当前归属 dtuid, 影响谓词的状态列)
    # 按 (type_key, asset_id) 排序拼串 -> SHA-256 -> 前 32 hex (≤128 字节)
    ...
```

> **不能用"最大 updated_at"或"版本号"糊弄。** 本应用 9 类里有 5 类是复合主键关联表
> （`project_members` / `task_collaborators` / `recurring_template_collaborators` /
> `work_record_participants`，以及 OWNER 那一行），**这些表没有 `updated_at`、没有版本列**，
> 改法是 delete + insert。preview 之后新增一条协作关系，时间戳型 token **纹丝不动** ——
> execute 于是通过校验，把一条从没人看过的关系按 `default_action` 一起处理掉，
> 然后返回的条数比 preview 多，EasyAuth 的守恒校验才发现不对。那时**数据已经改完了**。

校验时机与失败码：

- `execute`：在业务事务内、按 `08` §2.2 的锁序**锁定受影响集合之后**重算，
  不一致 → **HTTP 412**（不是 409），且**零写入**；
- `items`：不一致同样 **412**；
- **逐条校验是独立的第二层**：每个被改写的 asset_id 必须当前仍属于 `from_user_id`
  且仍满足该类型谓词，任一不满足 → 整体 `409 HANDOVER_CONFLICT`。
  **不允许**跳过该条继续处理其余条目。

> 412 与 409 的分工是契约 §10.6 定死的：412 让 EasyAuth 把 action **退回 `pending` 重新预演**，
> 409 判 `failed`。混用会让"清单变了"被永久标成失败。

### 4.4 幂等

契约 §10.5.2 的幂等键是**三元组** `(task_id, generation, batch_id)`。复用既有的
`IdempotencyRecordModel`（`infra/repositories/reliability.py:55`，唯一约束
`(principal_key, operation, idempotency_key)`），三个字段固定取值：

| 列 | 值 |
|---|---|
| `principal_key` | `"system:easyauth-handover"` |
| `operation` | `"postEasyauthLifecycleHandover"` |
| `idempotency_key` | `f"handover:v2:{task_id}:{generation}:{batch_id}"`（列宽 `String(128)`；契约 §5.4 已把 `task_id` 限到 64 字节，放得下） |
| `request_sha256` | canonical payload 的 SHA-256（既有列，直接用） |
| `response_json` | 首次成功的 `{"summary": ...}` 整体 |

> **`batch_id` 一个都不能少。** 早期版本写的是 `handover:{task_id}:{generation}`，
> 这会让同一 generation 内的**第二批**被当成第一批的重放：接口返回第一批的 `summary`、
> HTTP 200，而第二批的数据**一条都没搬**。EasyAuth 那边看到的是"成功"。
> 这正是 413 分批执行（契约 §10.6）必然触发的路径，不是边角情况。

三条行为规定，缺一不可：

| 情形 | 行为 |
|---|---|
| 同三元组重放，payload 的 canonical SHA-256 相同 | 返回**与首次完全相同**的 `summary`，HTTP 200，不重复执行 |
| 同三元组重放，payload hash 不同 | HTTP 409 `WEBHOOK_PAYLOAD_CONFLICT`，**不得**按新 payload 执行 |
| `generation` 小于本 `task_id` 见过的最大值 | HTTP 409 `HANDOVER_CONFLICT`（迟到的旧一轮，见契约 §10.5.2） |

因此幂等记录行除了键与 `summary`，还必须存 **canonical payload 的 SHA-256**；
另需按 `task_id` 维护**已见最大 `generation`**，并且**读它必须在 task 级串行化之后**
（同一 `task_id` 上先取一把行锁或 advisory lock），否则两个并发的旧请求会互相"看不见"对方，
双双通过判定。推进最大轮次、写 payload hash、写回执、业务改写**必须在同一事务内**完成。
**落法已由 `08` §1.4 裁定，不再二选一**：用 M06 自有的新表
`easyauth_handover_generations`（迁移 `m06_003_handover_generation_watermarks`）加行锁。

> **不能塞进通用幂等表。** `IdempotencyRecordModel` 的记录是**永久墓碑** ——
> `COMPLETED` 之后 `store_response` 直接返回，行不可更新
> （`infra/idempotency/guard.py:136-175`）。水位是要反复推进的可变值，放进去第一次写完就再也改不动。

必须有测试：**按 `generation=2` → `generation=1` 的顺序投递，第二个请求返回 409 且零写入。**
这不是理论场景 —— outbox 里 generation 1 的旧记录被 worker 延迟取出时会用**当前时间**重新签名，
300 秒重放窗口拦不住它，而它的三元幂等键此前并不存在，"不同 generation 必须真正执行"
这条规则会让它被当成一次新请求执行下去。

canonical 的定义固定为：对 JSON 体做 key 排序、去空白、UTF-8 编码后取 SHA-256
（`json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")`）。
**必须用解析后的对象重新序列化，不能直接哈希原始字节** —— 否则 EasyAuth 侧无意义的空白差异
会被误判成 payload 冲突。

### 4.5 事务与网络副作用

按 `AGENTS.md` 不变量 4：execute 的业务写入在一个事务内完成；
对 EasyAuth 的任何反向 HTTP 调用（如 §2.1 第 2 步的目录查询）**必须在事务外先做完**，
再进事务写库。**禁止持业务行锁调网络。**

execute 的编排：

```
1. 事务外: 解析 from/to 的全部 sub -> dtuid（可能触发目录查询与补绑）
2. 事务内: 锁 generation 水位 -> 校验 -> 按 08 §2.2 的固定锁序逐 asset_type
          调各领域 system_handover 命令 -> 写 audit/activity
          -> 写 OpenProject 投影 outbox -> 写幂等记录
3. 事务后: 由 M33 worker 异步消费投影 outbox；不发任何逐对象站内通知
```

三条容易漏的：

**① actor 是谁 —— 见 `08` §2.1。**
webhook 没有人类操作人。审计与 activity 的 `actor_dingtalk_user_id` 一律写 `NULL`，
执行者身份放进 `metadata_json.executor = "SYSTEM:EASYAUTH_HANDOVER"`。
`task_assignment_history.changed_by_dingtalk_user_id` **当前非空**
（`infra/repositories/tasks.py:226`），需要 `m10_002_task_handover_actor` 迁移改为 nullable。
**不要造哨兵 dtuid** —— 它会进目录外键与人员查询，在界面上伪装成一名真实员工。

**② "谁在 EasyAuth 发起的"这件事，本期记不下来。**
冻结的 execute payload 里没有 initiator / operator 字段（契约 §10.5）。
EasyProject 只记 `trigger_system=EasyAuth` 与 `handover_task_id`，
**具体发起人以 EasyAuth 自己的审计为权威**（契约 §12）。
**不得**用 `from_user_id`、接收人或签名身份去推断 —— 那是编造。
若产品确实需要，另提跨系统 CCR 在 payload 加 `initiator_user_id`。

**③ 改了任务负责人之后，还要把人同步到 OpenProject。**

任务的 assignee 与协作人会投影成 OpenProject 的自定义字段，而对账**不会**回写人员字段
—— 只改本地不投影的话，OpenProject 那边会永久停在离职者身上且无人修复。

**完整理由、outbox 的列定义、版本护栏、claim 的 owner-CAS、失败重投路径，
全部在 [`08`](08-easyproject-ag00-rulings.md) §1.2 与 §1.3 的 M32/M33 条 —— 以那里为准，本节不重复。**

M06 这一侧只需要知道两件事：

1. 业务事务内**只写 outbox**，一个网络请求都不发；
2. **execute 的本地成功以 outbox 落库为界**，不等 OpenProject 返回。

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

**三条并行 revision，各由自己的 owner 创建**（`08` §1.4 已冻结）。当前唯一 head 是
`m46_001_record_task_order`：

| revision | owner | 内容 |
|---|---|---|
| `m06_003_handover_generation_watermarks` | M06 | 建 `easyauth_handover_generations`（generation 水位，§4.4） |
| `m10_002_task_handover_actor` | M10 | 把 `task_assignment_history.changed_by_dingtalk_user_id` 改为 **nullable**（system actor 无 dtuid） |
| `m32_002_handover_projection_outbox` | M32 | 建 `op_handover_projection_outbox`（OpenProject 人员投影，§4.5 ③） |

三条 `down_revision` 都指向 `m46_001_record_task_order`；落地后由 **AG-00** 创建
`m00_004_data_handover_v2_heads` 合并。

- **`idempotency_records` 不需要迁移**：既有列已够用（§4.4）。真正需要新表的是 generation 水位。
- 遵循 `AGENTS.md` 不变量 6：Alembic 是唯一 schema 入口，revision 命名 `mNN_###_description`，
  空库必须可 `upgrade head`，merge revision 只由 AG-00 创建。
- **本次不新增业务列**（§3.4 已说明为何不给 `WorkRecordRow` 加 owner 列）。
- downgrade 前置：确认没有 NULL 的 assignment-history actor、没有未消费的 OP outbox 行。

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
**新增 10 个，保留既有 3 个，共 13 个。**

| 错误码 | HTTP | 触发 | 现状 |
|---|---|---|---|
| `WEBHOOK_SIGNATURE_INVALID` | 401 | 验签失败 | 已有 |
| `HANDOVER_CONFLICT` | 409 | 保留，用于归属改写时的业务冲突、迟到 generation。**快照失效不走这个码**，走 412 `SNAPSHOT_STALE` | 已有 |
| `VALIDATION_ERROR` | 422 | 保留，payload 结构不合法 | 已有 |
| `WEBHOOK_TIMESTAMP_INVALID` | 400 | 时间戳超 300 秒容差 | **补** |
| `WEBHOOK_PAYLOAD_CONFLICT` | 409 | 同 `(task_id, generation, batch_id)` 不同 payload hash | **补** |
| `EVENT_UNSUPPORTED` | 422 | `X-EasyAuth-Event` 不是 preview/items/execute/test | **补** |
| `EVENT_MODE_MISMATCH` | 422 | `X-EasyAuth-Event` 与 body **`event_type`** 不一致（契约 §10.1 的强制补偿校验）。码名沿用「mode」是历史原因，判定依据已是 `event_type`，见 `09` §5.2 | **补** |
| `IDENTITY_UNMAPPED` | 409 | §2.1 解析不到 dtuid | **补** |
| `ASSET_TYPE_UNDECLARED` | 422 | 请求里的 `asset_type` 不在注册表中 | **补** |
| `REQUEST_BODY_TOO_LARGE` | 413 | 超 256 KiB | **补** |
| `SNAPSHOT_STALE` | **412** | `snapshot_token` 与当前数据不一致（§4.3.3） | **补** |
| `HANDOVER_TEMPORARILY_LOCKED` | **423** | 项目审批锁期间禁止写。**可恢复**：EasyAuth 退回 `pending`，人解除审批后重新预演（`08` §2.4）。领域层照旧抛 `PROJECT_LOCKED(409)`，**M06 在边界转译** —— `PROJECT_LOCKED` 是全局冻结码，不能改它的状态码 | **补** |
| `RATE_LIMITED` | **429** | `items` 触发限流（契约 §10.4） | **补** |

> **为什么 `EVENT_MODE_MISMATCH` 要独立成码、不并进 `VALIDATION_ERROR`**：
> 这条校验是契约 §10.1 针对「签名不覆盖 `X-EasyAuth-Event` 头」这一已知弱点的**安全补偿**。
> 并进通用校验错误会让一次可能的头部替换尝试，在日志里与普通的字段写错完全无法区分。
> 独立错误码是这条补偿唯一的可观测出口。
>
> **适用于全部四个事件**（`preview` / `items` / `execute` / `webhook.test`）。
> 判定依据是 body 里签名覆盖的 `event_type` 与 `X-EasyAuth-Event` 是否逐字相同，
> **校验必须早于 `mode` 解析、事件分发、以及 `webhook.test` 的短路**（契约 §10.1、`01` §8）。
> `mode` 只是 preview/execute 的一层额外结构校验，**不是**判定依据。

> **401 与 403 的定级裁定**：本仓库的 webhook 验签失败返回 **401 `WEBHOOK_SIGNATURE_INVALID`**
> （`contracts/test-vectors/webhook-hmac.json` 的反例已冻结），而契约 §10.6 把验签失败列在
> 401/403 同一行、§10.1 只写了 403。三者语义一致、EasyAuth 侧处置相同（`failed` 且不可重试），
> **以本仓库的 401 为准**，本仓库无需改动；契约 §10.1 已同步改为「401 或 403（下游各自既有约定）」。
> CCR 里要写明这一裁定，避免后续被当成不一致。

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

**可直接提交的 CCR 全文见 [`09-easyproject-ccr.md`](09-easyproject-ccr.md)**，本节只保留清单与理由。

**这份 CCR 应在开工第一天就提**（周期长于代码实现）。

> **批准后必须先改 `contracts/tools/generate_baseline.py`，再重新生成基线。**
> 该脚本是基线的权威再生入口，endpoint 元数据硬编码在里面；
> **只手改 `openapi-baseline.json` 会在下次再生时被静默覆盖**，而且不会有任何报错。

**CCR 批准前的可做/不可做边界**（按 `contracts/workflow.md` §6「AG-00 批准前所有 Agent 继续用旧契约」）：

| 可以先做 | 必须等 CCR APPROVED |
|---|---|
| §2.1 修 P2（身份映射，纯内部实现） | 交接端点的 v2 改写 |
| §2.3 `hint` 的取数实现（只读查询） | 新错误码的实现与返回 |
| §3.1.2 终态谓词的共享选择器（只读） | descriptor 输出变更 |
| 领域侧 `system_handover` 命令用例（§4.1.1，各模块内部）——**但这一列还另外受 AG-00 所有权裁定阻塞**，见 `08` §1.6 | 测试向量更新、契约测试 |
| 上述各项的单元测试 | 端到端与契约测试 |

> **两道门禁是独立的，不要混为一谈**：CCR 管的是「契约基线能不能改」，
> AG-00 的两份裁定管的是「A5 能不能碰别的模块的表」。
> 只有 §2.1 / §2.3 / §3.1.2 这三项同时不受两道门禁限制，可以立刻开工。

即：**CCR APPROVED 是 M06 交接端点实施的门禁**，不是"边做边等"。

### 5.3 错误体形状：不改，走状态码对齐

契约 §10.6 已裁定：**HTTP 状态码是唯一规范部分，响应体是参考信息** ——
EasyAuth 不解析你的字段名做任何逻辑分支。

因此本端点继续返回 EasyProject 标准错误体 `{"detail":{"code","message","traceId"}}`
（`components/schemas/ErrorBody`），**不需要**为 EasyAuth 另造一套 `{"error":{...}}` 信封。

> **注意 EasyAuth 不会原样展示你的响应体**（契约 §10.6）：它只把白名单提取
> （`code`/`message`/`traceId`）+ 截断 + 脱敏后的内容给普通用户看。
> EasyProject 侧不需要为此改动，但不要按「反正会原样展示」来设计 message 内容。
基线里 `responses.default → ErrorResponse` 的声明保持不变，也无需 CCR。

> 这是本次改造中一处刻意的"不统一"：两个下游的错误码风格不同（EasyTrade 小写下划线、
> EasyProject 全大写），强行统一会产生一个纯粹为了好看的破坏性变更。按状态码对齐即可满足全部功能需求。

### 5.4 成功响应体：外部契约，走 snake_case 例外

三个事件的**成功**响应体形状由契约 §10.3/§10.4/§10.5 规定，是 **snake_case**
（`handover_asset_types`、`page_size`、`default_to_user_id`…），与 `AGENTS.md` 不变量 5 的 camelCase 约定不同。

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

**该字段早就有了**，不需要新增：
`backend/app/api/v1/directory.py:170,193,221,262,357` 的 DTO 均含 `is_active`，
生成的前端 TS 类型里也有。

真正缺的是**调用方没有按用途传 `includeInactive`**：
`backend/app/api/v1/directory.py:292` 已提供 `includeInactive` query 参数
（`infra/repositories/directory.py:239,244` 据此决定是否过滤），默认 `False`。

因此这一项**本期没有任何交付物**：后端不改，而 `06`（前端）已整体取消，不会有人去改调用方。

> **不要把它写成"等前端传参"的待办** —— 那会变成一个无人负责的交付项。
> 现状如实记录：目录接口默认只返回在职人员；需要看已离职人员时调用方要显式传
> `includeInactive=true`。等到确实有界面需要它的那一期再一并处理。
>
> 交接本身**不依赖**这个参数：交接单的资产明细由 `items` 事件提供，走的是本文件 §4 的路径，
> 与目录接口无关。

### 5.7 共享热点（必须走 AG-00）

按 `AGENTS.md` 不变量 7，以下文件**只提交补丁，不直接并发编辑**：

| 文件 | 用途 |
|---|---|
| `backend/app/api/v1/router.py` | 注册交接 router |
| `backend/app/main.py` | 若 descriptor 路由需调整 |
| `contracts/openapi-baseline.json` | §5.2 CCR 通过后由 AG-00 更新 |
| `contracts/test-vectors/webhook-hmac.json` | 同上 |
| `frontend/src/lib/api/generated/openapi.d.ts` | 生成物，AG-00 再生 |
| `backend/app/infra/job_registry.py` | **本次涉及**：M33 必须导出 `openproject-handover-projection` JobSpec（轮询 + 重试 `op_handover_projection_outbox`），并在此注册。**不注册就没有消费者** —— execute 写完 outbox 之后再没人处理，OpenProject 永久留着离职者。注册补丁与 composition 变更交 AG-00 合并 |

---

## 6. 测试

| 文件 | 覆盖 |
|---|---|
| `backend/tests/unit/identity/test_handover_identity.py` | **P2**：已绑定命中；未绑定走目录补绑；冲突绑定被拒；解析不到抛 `IdentityUnmappedError` |
| `backend/tests/unit/handover/test_assets_registry.py` | 9 类 count 口径（§3.1 全表逐类）；§3.1.2 终态谓词逐类断言；注册表与 descriptor 用同一常量断言 |
| `backend/tests/unit/handover/test_items_pagination.py` | 排序稳定、连续翻页不漏不重；**`total` 的两种口径**：`q=""` 时等于 preview 的 `count`，`q!=""` 时等于**过滤后**的数量。不要写成"始终等于 preview count" |
| `backend/tests/integration/handover/test_execute_composite_keys.py` | §4.3 四类合并场景；OWNER 升级；每项目一个 OWNER 的部分唯一索引不被违反；`merged` 如实上报 |
| `backend/tests/integration/handover/test_execute_transaction.py` | §4.5：事务内无网络调用；失败整体回滚 |
| `backend/tests/integration/handover/test_idempotency.py` | `(task_id, generation, batch_id)` 幂等；不同 generation 真正重执行 |
| `backend/tests/contract/test_handover_v2_golden.py` | 从 `easyauth_app_sdk.contract_samples` 包内资源读取样本逐字段比对；样本缺失必须 fail |

golden 样本取用：**随 SDK 分发**（`easyauth_app_sdk.contract_samples` 包内资源，版本与 SDK 绑定），
用 `importlib.resources` 读取。**不得**依赖 `../EasyAuth/` 兄弟目录路径 —— 本仓库 CI 独立检出，
那条路径必然不存在，测试会稳定退化成 skip。**样本缺失必须让测试失败**，不允许 skip 通过。

pytest 使用既有 async auto 模式与 unit/integration/contract 标记（`backend/pyproject.toml:70`）。
全量门禁：合入后跑**完整**的 `scripts/quality-gate.sh`（Ruff、migration smoke、PostgreSQL 实库 pytest、
secret 扫描、前端检查、契约检查）。**不存在只跑「前端段」这种用法**，不要在文档或 CI 里那样写。

> **该脚本本身要先修**：它在一个 pnpm 仓库里执行 `npm ci`（`scripts/quality-gate.sh:33`），
> 后端全绿也会被前端安装步骤稳定打红。改成 `pnpm install --frozen-lockfile`，
> 这属于本次的前置修复项（补丁交 AG-00 合并）。

**两份现有 v1 测试必须重写，不是新增**：
`backend/tests/unit/authz/test_lifecycle_handover.py` 仍在断言 v1 的 partial-success 语义
（`:86`），与契约 §10.5「整事务成败一致」直接冲突；不改的话新实现一定把它跑挂，
而改错方向（为了让它绿而保留 partial success）就更糟。

---

## 7. 交付顺序

0. **前置（不做完 A5 无法开工）**：AG-00 批准 [`08`](08-easyproject-ag00-rulings.md) 的两份裁定；
   AG-00 提交 [`09`](09-easyproject-ccr.md) 的 CCR；M03 发布含 v2 能力的 vendored SDK
1. ~~§2.2 修 P1~~ —— 本期取消（代管废弃）
0.5. **修 `scripts/quality-gate.sh`**：它在 pnpm 仓库里执行 `npm ci`（`:33`），
   后端全绿也会被前端安装步骤稳定打红。改成 `pnpm install --frozen-lockfile`，
   补丁交 AG-00 合并。**不受任何门禁限制，第一天就能做**，且不做的话后面每次跑门禁都白跑。
2. §2.1 身份映射（修 P2）+ §2.3 `hint` + §3.1.2 终态谓词选择器（这三项**不受任何门禁限制**，可立刻开工）
3. §5.2 提 CCR（**与 1/2 并行提，通过周期较长，越早越好**），正文见 [`09`](09-easyproject-ccr.md)
4. §4.1 注册表 + §4.6 descriptor（共用常量，同一提交）
5. §4.2 端点 + preview / items
6. §4.3 §4.4 §4.5 execute
7. §6 测试补齐

每完成一项立即单独 commit。§3.4 的 `WorkRecordRow` 缺口必须写进 PR 描述与
`docs/design/09-分期计划与风险清单.md`，不得默默留着。
