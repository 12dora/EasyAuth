# 08 · EasyProject AG-00 裁定（A5 开工前置）

> **这份文件是 A5 解除阻塞的钥匙。** 它包含两份裁定，体例沿用 `EasyProject/contracts/ownership.md`
> 里既有的「W3 并行裁定」段落（日期 + AG-00 + 门禁 + 逐条裁定）。
>
> **落地方式**：AG-00 审核通过后，把 §1 与 §2 的正文追加进 `EasyProject/contracts/ownership.md`，
> 把 §1.1 的 M40 条目补进该文件的模块矩阵。本文件是设计侧的权威副本，两边必须一致。
>
> **两道门禁是独立的**：本裁定管「A5 能不能碰别的模块的表」；`09-easyproject-ccr.md` 管
> 「冻结契约基线能不能改」。裁定通过后 A5 即可实施 M06 编排与只读部分；
> 冻结基线、生成器、测试向量、错误码的改动仍须等 CCR APPROVED。

---

## 1. 所有权裁定

### 数据交接 v2 并行裁定（2026-08-10，AG-00，A5 开工前置）

**基准**：跨系统 payload、事件、summary、幂等、HTTP 状态码以 `00-overview-and-contract.md` 为唯一基准。
`05-easyproject-backend.md` 只解释实现，不得覆盖冻结契约。

**开工结论**：A5 解除「无法开始」的阻塞，但**只获准**实现 M06 的契约适配、编排、只读资产选择器
与 M06 自有账本；其他模块的业务写入必须等对应 owner 交付 §1.3 的命令。

### 1.1 表 / 列 / owner 清单

| 表 | 本次允许写入的列 | owner / 形态 |
|---|---|---|
| `directory_users` | **仅** `authentik_user_id`、`updated_at`；**不得**写 `first_login_at` / `last_login_at` | M07。现有登录绑定会写登录时间（`infra/repositories/directory.py:643-708`），因此必须新增**纯绑定**命令 |
| `easyauth_handover_generations`（**新表**） | `task_key_sha256`、`task_id`、`max_generation`、`updated_at` | M06 自有。契约 §10.5.2 要求记录每个 `task_id` 见过的最大 generation |
| `idempotency_records` | 既有列；`actor_dingtalk_user_id = NULL` | M08 既有通用端口，**不新增领域命令**。唯一键 `(principal_key, operation, idempotency_key)`，`idempotency_key` 列宽 128（`infra/repositories/reliability.py:55-78`） |
| `audit_logs` | 新增 append-only 行；`actor_dingtalk_user_id = NULL`，上下文进 `metadata_json` | M08 既有审计端口。actor 本就允许空（`reliability.py:81-98`） |
| `projects` | `owner_dingtalk_user_id`、`version`、`updated_at` | **M13 命令** |
| `project_members` | **删除**来源关系行（`project_owned` 场景**只能删，不能降级为 MEMBER**）；目标不存在时插入目标行，`created_at = now`、**`added_by_dingtalk_user_id = NULL`**（见下方「不得复制历史署名」）；目标已存在且需要成为 OWNER 时才调整 `role` | **M13 命令**。复合主键 + `uq_project_members_one_owner` 部分唯一索引（`alembic/versions/m13_001_project_tables.py:135-142`）要求在同一命令内合并 |
| `tasks` | `assignee_dingtalk_user_id`、`assigner_dingtalk_user_id`、`assignment_version`、`version`、`updated_at`；**明确不改** `status`、`state_version` | **M10 命令** |
| `task_collaborators` | 删除来源行；目标不存在时插入，`created_at = now`、`added_by = NULL` | **M10 命令**。复合主键 `(task_id, dingtalk_user_id)` |
| `task_assignment_history` | assignee 变化时新增完整历史行，`changed_by_dingtalk_user_id = NULL` | **M10 命令**；该列**当前非空**（`infra/repositories/tasks.py:226`），须迁移改为 nullable |
| `task_state_transitions` | **不写** | 交接不改变任务状态，不得制造虚假的状态流转记录 |
| `task_activities` | 新增 `activity_type="ASSIGNMENT"` 行，`actor_dingtalk_user_id = NULL`，`payload_json.action="SYSTEM_HANDOVER"` | M11 既有 writer。actor 已允许空 |
| `task_reminder_rules` | 角色变化任务对应规则的 `next_trigger_at`、`version`、`updated_at` | **M18 命令**，复用既有物化计算 |
| `reminder_occurrences` | 未发送的旧行置 `status=SKIPPED`、`processed_at`、`last_error="HANDOVER_SUPERSEDED"`；再插入按新角色算出的新行 | **M18 命令** |
| `recurring_task_templates` | `assignee_dingtalk_user_id`、`assigner_dingtalk_user_id`、`version`、`updated_at` | **M19 命令** |
| `recurring_template_collaborators` | 删除来源行；接收人不存在时插入 | **M19 命令** |
| `work_record_participants` | 删除来源行；接收人不存在时插入 | **M40 命令** |
| `work_records` | **不写** `created_by_dingtalk_user_id` | 契约 §11.1 已列为 D11 的显式例外，本期不转移 |
| `op_handover_projection_outbox`（**新表**） | `id`、三元组、`task_id`、人员快照、状态、重试与时间字段 | **M32 表 + M33 写路径**。见 §1.2 的 OpenProject 条 |
| `tasks.op_lock_version` / `tasks.op_synced_at` | outbox worker 成功后更新 | M32 数据模型 / M33 worker，既有投影锚点列 |
| `op_sync_conflicts` | worker 重试耗尽时写 `APPLY_FAILED` 行，**去重维度用 `outbox_id`** | M32 既有表。不加这一条，worker 按清单实施时无处记录最终失败 |
| `notifications` / `notification_recipients` / `notification_outbox` | **不写** | M14 本次只做评审方。逐对象通知会造成通知风暴；完成通知由 EasyAuth 合并发送（契约 §13） |

#### work-record 所有权补登记（`contracts/ownership.md` 当前缺失）

现有矩阵登记到 M38 即进入汇总与共享热点，**没有 M40 / work-record 表的条目**。补：

```markdown
### M40 工作记录（AG-40 / W11）
- 表：work_categories、work_records、work_record_participants、
  work_record_visible_departments、work_record_types
- 文件：/backend/app/domain/work_records/**、
  /backend/app/infra/repositories/work_records.py、
  /backend/app/infra/repositories/work_categories.py、
  /backend/app/api/v1/work_records.py
- 禁：跨模块改 projects/tasks 的归属列；把 created_by 当可转移 owner；
  绕过 WorkRecordService 直接全量替换参与人。
```

同时给 M32 补登记 `op_handover_projection_outbox`（M32 当前只登记 `op_sync_state`、`op_sync_conflicts`
与锚点列；M33 当前写的是「表：无」）。

### 1.2 实施形态裁定（逐模块）

**判定原则**：只要该表存在复合唯一键、活跃人员校验、终态谓词或 OWNER 不变量，
就必须由 owner 提供命令，**M06 不得裸改表**。反之（纯通用基础设施）复用既有端口。

| 模块 | 形态 |
|---|---|
| **M03 SDK** | 不写业务表。owner 升级 vendored SDK：items 事件、256 KiB、v2 TypedDict、`handover_asset_types` manifest 白名单、`event_type` 一致性校验。当前 SDK 只有 preview/execute、64 KiB，`manifest.py:101-118` 的白名单会拒绝新字段 |
| **M05 / M07 身份** | M05 提供 handover identity 用例，M07 提供**纯绑定**仓储命令；M06 只在**事务外**调用。禁止复用登录绑定路径 |
| **M06** | 可直接维护自有的 generation 水位表，并通过 M08 既有端口写幂等与审计；**不得**更新任何其他模块的业务表 |
| **M08** | **不新增** `system_handover` 命令。A5 调用既有 `IdempotencyGuard`（`infra/idempotency/guard.py`）与审计仓储，不得裸写 SQL |
| **M13 / M10 / M19 / M40** | **必须各自提供 `system_handover` 命令**（签名见 §1.3）。虽然有的表只改一个人员列，但均带不变量 |
| **M11** | 不新造并行 activity 实现；由 M10 命令调用 M11 既有 writer，写一条 actor 为空的系统活动 |
| **M18** | 提供提醒重物化命令。M06 不直接改 occurrence —— 既有 `reminder_enqueue.py:269-316` 把人员不一致视为 stale 并**整组 fail-closed** |
| **M14** | **不提供**交接写命令。职责是**评审** M10/M13/M19/M40 的命令确实没有调用逐对象通知 writer |
| **M32 / M33** | M32 提供 durable outbox 表与仓储，M33 提供入队端口与 worker。M06 只在业务事务内入队，**不直接发 OpenProject 网络请求** |

> **OpenProject 人员投影是本次最容易整体漏掉的一项。**
> `domain/openproject/mapping.py:82-83` 明确把
> `assignee_dingtalk_user_id → cf:assignee_dtuid`、
> `collaborator_dingtalk_user_ids → cf:collaborators_dtuid` 投影到 OpenProject 自定义字段；
> 而 M34 对账在文件头不变量里写死「**永不改…人员字段**」（`domain/openproject/reconcile.py:4`）。
>
> 也就是说：交接改了 assignee 却不投影，OpenProject 侧会**永久停留在离职者身上，且没有任何自动修复路径**。
>
> 又不能直接复用既有写穿：`write_through.py:668-724` 的 `_run_transition` 是**持任务锁发网络请求**，
> 与 `AGENTS.md` 不变量 4「网络副作用出事务」冲突。
> 因此裁定为 durable outbox：业务事务内入队，事务提交后由 worker 异步投影。
> **execute 的本地成功以 outbox 落库为界**，不等 OpenProject 返回。

**角色划分**：M03/M05/M07/M08/M11/M14/M18/M32/M33 是支持模块；M13/M10/M19/M40 是资产 owner；
**A5 仍然只拥有 M06**。

### 1.3 新增命令接口（本裁定冻结）

以下签名是**新增接口**，不是对现有 API 的描述。现有命令无法复用，理由逐条附后。

公共上下文由 M06 放在 `backend/app/domain/handover/types.py`：

```python
@dataclass(frozen=True, slots=True)
class SystemHandoverContext:
    handover_task_id: str
    generation: int
    batch_id: int
    delivery_id: str
    trace_id: str
    kind: str            # offboard | pre_offboard | reassign | transfer

@dataclass(frozen=True, slots=True)
class SystemHandoverResult:
    transferred: int
    merged: int
    aggregate_version: int | None
```

**这个上下文里没有伪造的人类 actor**，因为冻结的 execute payload 本身就不含 initiator/operator 字段
（契约 §10.5）。详见 §2.1。

#### M05 / M07 · 身份

```python
# backend/app/domain/identity/handover_identity.py
async def resolve_handover_identity(
    *, authentik_sub: str,
    purpose: Literal["source", "target"],          # 不能省
    directory: EasyAuthDirectoryPort,
    users: DirectoryUserRepository, now: datetime,
) -> str: ...

# backend/app/domain/identity/directory_repo.py
async def bind_verified_authentik_sub(
    self, *, dingtalk_user_id: str, authentik_user_id: str, now: datetime,
) -> DirectoryUserRecord: ...
```

保证：只做精确 sub↔dtuid 映射（禁止姓名/邮箱模糊匹配，契约 §5.2）；冲突或解析不到抛
`IdentityUnmappedError` → API 映射 `409 IDENTITY_UNMAPPED`；**不得修改任何登录时间戳**。

**`purpose` 决定 active 的要求，这个参数不能省**：

| purpose | active 要求 |
|---|---|
| `source`（`from_user_id`） | **不要求 active** —— 离职者早就被目录同步置成 `is_active=false` 了 |
| `target`（各接收人） | **必须 active**，且各 owner 命令在**锁内**再校验一次 |

> 没有这个参数就只能二选一，两个都是错的：要求 active 的话，**所有正常的离职交接都失败**；
> 不要求的话，接收人可以是一个停用账号。
> **也不得**把「source 是 inactive」当成 `IDENTITY_UNMAPPED` —— 那是能解析到的，只是不活跃。

#### M13 · 项目

```python
# backend/app/domain/projects/commands.py
async def system_handover(
    self, session: AsyncSession, *,
    project_id: UUID,
    from_dingtalk_user_id: str,
    owner_to_dingtalk_user_id: str | None,
    member_to_dingtalk_user_id: str | None,
    context: SystemHandoverContext,
) -> SystemHandoverResult: ...
```

保证：

- `project_owned` 与 `project_member` 在**同一项目锁、同一事务**内处理，member 选择器**排除 OWNER 行**；
- OWNER 转移顺序固定：**删除旧 OWNER 行 → flush → 升级或插入目标 OWNER → 最后同步
  `projects.owner_dingtalk_user_id`**（部分唯一索引非 deferrable，顺序反了立刻撞约束）；
- **旧 OWNER 只能删除，不得"降级为 MEMBER"**：降级会让离职者以成员身份继续拥有项目可见性，
  而这条新产生的 MEMDER 关系**从来没有出现在 preview 里** —— 用户以为交接干净了，实际没有；
- 反方向也要小心：`project_member` 转给一个**已经是 OWNER** 的接收人时，
  **只删除来源 MEMBER 行并计 `merged`，绝不修改目标的 `role`** —— 改了就变成项目没有 OWNER；
- 保持「每项目恰有一个 OWNER」；**已存在**的目标关系行，其 `added_by` / `created_at` 一个字节不动；
- 项目终态、来源已非 owner/member、目标 inactive → 抛 `ProjectHandoverConflict` → `409 HANDOVER_CONFLICT`；
- **审批锁 → `423`**（见 §2.4）；**全局 snapshot 摘要不匹配 → `412`**，由 M06 在任何领域写入之前统一判定，不进领域命令；
- **不发**成员逐条通知。

> 现有 `replace_members` 强制传入的 OWNER 等于旧 owner，且会全量重写成员关系，无法承担该职责。

#### M10 · 任务

```python
# backend/app/domain/tasks/commands.py
async def system_handover(
    self, session: AsyncSession, *,
    task_id: UUID,
    from_dingtalk_user_id: str,
    assignee_to_dingtalk_user_id: str | None,
    assigner_to_dingtalk_user_id: str | None,
    collaborator_to_dingtalk_user_id: str | None,
    context: SystemHandoverContext,
    reason: str,
) -> SystemHandoverResult: ...
```

保证：

- 锁住任务行**之后**再读 `version` / `state_version` / `assignment_version`，并重新校验来源人仍承担所选角色；
- **保持 `status`、`state_version`、`accepted_at` 与 review 状态不变**；
- assignee 变化时 `assignment_version += 1` 并写 assignment history；一次命令内任一角色变化只把
  `version` 加一次；
- collaborator 目标已存在 → 删除来源行并计入 `merged`（**保持目标行原有的 `added_by`/`created_at` 不动**）；否则新建目标行，`created_at = now`、`added_by = NULL`；
- **合并后的 collaborator 集合不得包含最终 assignee**（既有不变量
  `assignee_cannot_be_collaborator`，`domain/tasks/commands.py:1757`）：
  若转入目标恰好等于该任务最终的 assignee，**只删除来源关系并计 `merged`，不插入 collaborator 行**。
  直接插入会造出普通 API 明令禁止的双重角色；
- 写一条 M11 activity（actor 为 NULL，payload 带三元组）；
- **不写** `task_state_transitions`，**不发** `TASK_REASSIGNED` 通知；
- 终态、来源不再匹配、目标 inactive、版本或唯一约束竞争 → `TaskHandoverConflict` → `409 HANDOVER_CONFLICT`；
  **审批锁 → `423`**；**全局 snapshot 不匹配由 M06 前置判定并返回 `412`**，不进领域命令。

> **为什么不能复用现有 `reassign`**：它会把任务重新推回 `PENDING_ACCEPTANCE`
> （`domain/tasks/state_machine.py:56-69`），并产生逐任务通知。交接只转责任，不改状态。

#### M18 · 提醒

```python
# backend/app/domain/reminders/handover.py
async def refresh_after_system_handover(
    self, session: AsyncSession, *, task_id: UUID, context: SystemHandoverContext,
) -> ReminderHandoverResult: ...
```

保证：

- **只在任务 assignee 或 assigner 变化时调用**；
- 任务已由 M10 锁定，M18 再按规则 UUID 升序锁定相关规则；
- **先算出新集合，再按自然键做差集**，不能"先全部 SKIP 再全部 INSERT"：
  `uq_reminder_occurrences_natural (rule_id, scheduled_for, occurrence_kind, recipient_dingtalk_user_id)`
  与 `uq_reminder_occurrences_dedup_key` 都是**永久唯一键，不按 status 过滤**
  （`alembic/versions/m18_001_reminder_tables.py:244-251`）。
  被标成 `SKIPPED` 的旧行仍然占着自然键，同一个自然键再 INSERT 会冲突；
  若实现用了 `ON CONFLICT DO NOTHING`，结果是**静默不插入，最终一条 PENDING 提醒都没有**。

  正确的三分支：

  | 情形 | 处理 |
  |---|---|
  | 自然键在新集合里也存在 | **原位保持/恢复 `PENDING`**，刷新 `payload_snapshot`，不删不插 |
  | 旧行的自然键不在新集合里 | 标 `SKIPPED` / `HANDOVER_SUPERSEDED` |
  | 新集合里的全新自然键 | INSERT |

  典型触发场景：assignee A→B 而 assigner 本来就是 B —— 新旧集合会有自然键重叠。
- 推进规则游标；
- 任一失败使整个 execute 数据库事务回滚；领域竞争 → `409 HANDOVER_CONFLICT`，意外故障按契约 §10.6 返回 5xx。

> **周期模板（recurrence）的人员变化不调用本命令。**
> `reminder_occurrences` 的外键是 `(rule_id, task_id) → task_reminder_rules(id, task_id)`
> （`infra/repositories/reminders.py:97-105`），**根本没有 template_id 这一维**。
> 模板改人之后，由模板生成的**新任务**自然带新角色，无需也无法直接处理 occurrence。
> `05` §4.3.1 早期写的「取消该任务/**模板**下所有未发送 occurrence」对模板那半是错的。

#### M19 · 周期任务

```python
# backend/app/domain/recurrence/service.py
async def system_handover(
    self, session: AsyncSession, *,
    template_id: UUID,
    from_dingtalk_user_id: str,
    assignee_to_dingtalk_user_id: str | None,
    assigner_to_dingtalk_user_id: str | None,
    collaborator_to_dingtalk_user_id: str | None,
    context: SystemHandoverContext,
) -> SystemHandoverResult: ...
```

保证：模板须 `is_enabled=true`；锁内重新校验角色与目标 active；目标 collaborator 已存在则合并；
**目标等于模板最终 assignee 时只删来源关系、不插入**（同 M10，`domain/recurrence/service.py:215,381` 有同样的不变量）；
一次命令只把模板 `version` 加一次；**不修改历史 occurrence**；不发逐模板通知；冲突 → `409 HANDOVER_CONFLICT`。

> 现有 recurrence patch 的 DTO 不含人员字段，无法复用。

#### M40 · 工作记录参与人

```python
# backend/app/domain/work_records/service.py
async def system_handover_participant(
    self, session: AsyncSession, *,
    record_id: UUID,
    from_dingtalk_user_id: str,
    to_dingtalk_user_id: str,
    context: SystemHandoverContext,
) -> SystemHandoverResult: ...
```

保证：仅 `status='OPEN'` 的记录；锁记录后只处理参与人关系；目标已存在则删除来源并计 `merged`；
**不得修改** `created_by_dingtalk_user_id`；其余冲突 → `409 HANDOVER_CONFLICT`。

> **目标恰好是该记录的 creator 时，按「合并」处理，不是报错。**
> 既有 participant 归一化会把 creator 排除在参与人之外（`domain/work_records/service.py:120`），
> 所以不能插入这一行 —— 但也**不能因此整批 409**：
> EasyAuth 在 preview 阶段无从得知"默认接收人恰好创建过其中某几条记录"，
> 一次正常的批量转移会因为这个巧合整体失败，而 409 还是不可重试的。
> 正确结果是：**不插入 participant，删除来源 participant，计入 `merged`** ——
> creator 本来就对该记录有可见性，目的已经达到。

#### M32 / M33 · OpenProject 投影

```python
# backend/app/domain/openproject/handover_projection.py
async def enqueue_system_handover_projection(
    self, session: AsyncSession, *,
    task_id: UUID,
    assignee_dingtalk_user_id: str,
    collaborator_dingtalk_user_ids: tuple[str, ...],
    context: SystemHandoverContext,
) -> UUID: ...
```

`op_handover_projection_outbox` 的列**在此冻结**（M32 建表，M33 消费）：

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | UUID PK | |
| `handover_task_id` / `generation` / `batch_id` | text / int / int | 溯源三元组 |
| `task_id` | UUID | 本地任务 |
| `assignee_dingtalk_user_id` | text | 入队时的人员快照 |
| `collaborators_hash` | char(64) | 协作人集合的规范摘要 |
| `expected_task_version` / `expected_assignment_version` | int | **版本护栏**，见下 |
| `op_work_package_id` | int NULL | 入队时已知则填 |
| `op_lock_version_at_enqueue` | int NULL | 同上 |
| `status` | text | `PENDING` \| `CLAIMED` \| `APPLIED` \| `SUPERSEDED` \| `CANCELLED` \| `APPLY_FAILED` |
| `attempts` / `next_attempt_at` | int / timestamptz | 指数退避 |
| `claim_owner` / `claim_expires_at` | text / timestamptz | worker 抢占 |
| `last_error` | text | |
| `created_at` / `updated_at` | timestamptz | |

唯一键 `(handover_task_id, generation, batch_id, task_id)`。

保证：

- 在 M10 的业务事务内**只写 outbox**，不发任何网络请求；
- worker 消费时**必须先取既有的 `task_lock_key(task_id)` advisory lock**，与普通写穿共用同一把锁；
- **版本护栏的判据只看人员，不看 `task.version`**：取锁后比对 `assignment_version` 与
  `collaborators_hash`。**`task.version` 只作诊断，不得单独触发 `SUPERSEDED`** ——
  它在任何普通字段修改时都会递增（`domain/tasks/commands.py:1677`），而那种修改的 OP PATCH
  根本不含人员字段（`write_through.py:1088`）：一次改标题就会让人员投影被标 `SUPERSEDED`
  而永久丢失，M34 又不回写人员，再也没人补。
  人员确实已经前进时，**投影锁内读到的当前本地权威值**，而不是简单丢弃；
  只有任务已删除、没有 OP 锚点、或已有更新的 outbox 明确接管时才允许 `SUPERSEDED`；
- **claim 与终态都要 owner-CAS**：claim 只选 `status='PENDING'` 或已过期的 `CLAIMED`；
  `renew` / 重试 / `APPLIED` / `SUPERSEDED` / `APPLY_FAILED` 的每一次更新都必须带
  `WHERE id = ? AND status = 'CLAIMED' AND claim_owner = ?`。
  HTTP 可能跨越 lease 时先续租；**CAS 影响 0 行的旧 worker 不得写任何终态或冲突账**。
  拿不到 task advisory lock 时，只由当前 owner CAS 回 `PENDING` 并设 `next_attempt_at`；
- 通过护栏才 PATCH OpenProject 的 `assignee_dtuid` / `collaborators_dtuid` 两个 CF，
  成功后用短事务更新 `op_lock_version` / `op_synced_at` 锚点；
- 重试耗尽 → 写 M32 的 `op_sync_conflicts`（`APPLY_FAILED`）。
  **现有表没有可用的去重维度**：仓储按 `(entity_type, entity_id, op_id, kind)` 命中未解决行
  （`infra/repositories/op_sync.py:66,173-194`），generation 2 的同一任务失败会撞上
  generation 1 那条未解决的记录，**新的错误详情被静默丢弃**。
  因此 `m32_002` 给该表加 `handover_outbox_id` 外键并对非空值建唯一索引，
  新增 `record_handover_apply_failed(..., outbox_id)`；**M34 既有的去重语义不动**。
  §1.1 的允许写表清单里加上 `op_sync_conflicts`；
- **不得依赖 M34 对账自动修复** —— 它明确不回写人员字段。

> **没有版本护栏会发生什么**：交接入队"改成 B" → 人工又把负责人改成 C 并已写穿 OP →
> 延迟的 worker 再 PATCH 一次旧快照 B，把 OP 改回去；worker 还会更新 `op_lock_version`，
> 于是 M34 对账命中 ECHO 抑制，**永远不会发现也不会修复**。

> **execute 仍返回 200，但必须如实说明这一点。**
> OP 投影是**异步的内部债务**，不在 execute 的成败判定里 ——
> EasyAuth 的 action 会在本地数据搬完时就变成 `done`，而 OP 那边可能还没同步、甚至最终失败。
> 因此这一项**必须写进 EasyProject 的风险清单**，并配：重试耗尽的**告警**、
> `op_sync_conflicts` 的运维查询入口、以及人工重投的操作步骤。
> **不允许**只写进台账就当没事 —— 那正是本次改造要消灭的静默失败。
> （改成 202 + 状态轮询在语义上更干净，但那需要给 EasyProject 新增一条状态查询 path，
> 属于新增 operation，要另走一次 CCR。本期取 200 + 显式债务。）

### 1.4 迁移与 revision 裁定

当前唯一 Alembic head 是 `m46_001_record_task_order`。需要**四个并行 revision**，各由自己的 owner 创建：

| revision | down_revision | 内容 | owner |
|---|---|---|---|
| `m06_003_handover_generation_watermarks` | `m46_001_record_task_order` | 建 `easyauth_handover_generations(task_key_sha256 CHAR(64) PK, task_id TEXT NOT NULL, max_generation INTEGER NOT NULL, updated_at TIMESTAMPTZ NOT NULL)` | M06 |
| `m10_002_task_handover_actor` | `m46_001_record_task_order` | 把 `task_assignment_history.changed_by_dingtalk_user_id` **与 `task_collaborators.added_by_dingtalk_user_id`** 都改为 **nullable**，ORM 同步为 `Mapped[str \| None]` | M10 |
| `m13_003_project_handover_actor` | `m46_001_record_task_order` | 把 `project_members.added_by_dingtalk_user_id` 改为 **nullable**，ORM 同步 | M13 |
| `m32_002_handover_projection_outbox` | `m46_001_record_task_order` | 建 `op_handover_projection_outbox`，唯一约束 **`(handover_task_id, generation, batch_id, task_id)`** —— 与 §1.3 冻结的列名一致（早期这里写的是 `handover_task_key_sha256`，那一列根本不存在，照写 upgrade 当场失败）。同时给 `op_sync_conflicts` 加 `handover_outbox_id UUID NULL REFERENCES op_handover_projection_outbox(id)` 与非空部分唯一索引 | M32 |

**四条**并行分支落地后，**由 AG-00 创建** merge revision：

```python
revision = "m00_004_data_handover_v2_heads"
down_revision = (
    "m06_003_handover_generation_watermarks",
    "m10_002_task_handover_actor",
    "m13_003_project_handover_actor",
    "m32_002_handover_projection_outbox",
)
```

`idempotency_records` **不需要迁移**（既有列已够用），但**不得**用一条固定的
`handover:{task_id}:maxgen` 记录来维护水位 —— 通用幂等记录是**永久墓碑**，
`COMPLETED` 之后 `store_response` 直接返回，**不可更新**（`infra/idempotency/guard.py:136-175`）。
水位必须走 M06 自己的 `easyauth_handover_generations` 表 + 行锁。

**downgrade 的前置条件**：确认 `task_assignment_history.changed_by_*`、
`task_collaborators.added_by_*`、`project_members.added_by_*` **三列都没有 NULL**，
且没有未消费的 OP outbox 行。

> **这两个 `added_by` 的 nullable 是硬前置。** §1.1 要求新建的关系行写
> `added_by = NULL`（不复制来源人的历史署名），而这两列现在都是 `NOT NULL`
> （`alembic/versions/m13_001_project_tables.py:98`、`m10_001_task_core_tables.py:195`）——
> 接收人原先不是成员/协作人时 INSERT 就是 `NotNullViolation`，**整批回滚成 5xx**。
已有生产交接记录时**保留兼容 schema，走应用级补偿，不删历史**。

### 1.5 评审、签署与回滚

| 改动 | 实现/自测 | 必须签署 | 故障回滚 |
|---|---|---|---|
| SDK v2 | M03 | M03 + M06 + AG-00 | 回退 SDK 版本，并从 descriptor 移除 `handover.v2` |
| 身份纯绑定 | M07 / M05 | M07 + M05 + AG-00 | 停用目录补绑路径；**已验证的 sub 绑定不反向清除**（会破坏登录映射） |
| 项目命令 | M13 | M13 + M06 + AG-00 | 停 execute；已执行的数据用**新 generation 的补偿性交接**转回；不删审计、不恢复旧成员行时间戳 |
| 任务 / 活动 / 提醒 | M10 / M11 / M18 | 三个 owner + M06 + AG-00 | 停 execute；补偿性交接恢复人员；保留 assignment history 与 activity；错误的未发送 occurrence 标 SKIPPED 后重物化 |
| recurrence | M19 | M19 + M06 + AG-00 | 补偿性交接模板角色；不动已生成的 occurrence 与历史任务 |
| work-record participant | M40 | M40 + M06 + AG-00 | 补偿性交接 participant；**不得**把 `created_by` 当 owner 回写 |
| 幂等 / 水位 | M06 / M08 | M06 + M08 + AG-00 | 应用回退后**保留**水位与幂等墓碑 —— 删掉它们等于允许旧 generation 再次执行 |
| OP outbox | M32 / M33 | M32 + M33 + M06 + AG-00 | 先停 worker；保留已投递记录；未投递行置 CANCELLED；已写 OP 的用补偿投影恢复，不直接删锚点 |
| contract / 生成器 / 向量 | AG-00 | AG-00 最终签署 | 先让 EasyAuth 停发 v2（移除 capability），再回退生成器、重生成基线与向量 |

**回滚的统一原则：一律用「新一轮补偿性交接」把数据转回去，绝不回写历史事实。**
契约 §10.5.2 规定旧 generation 必须被拒绝，所以"重放上一轮"这条路本来就不通。

### 1.6 A5 的边界与交付顺序

**A5 可以**：

- 改 M06 所属的 `backend/app/api/v1/easyauth_lifecycle.py`、`backend/app/domain/authz/lifecycle.py`，
  或按本裁定迁入 `backend/app/domain/handover/**`；
- 实现 preview/items 的只读注册表、稳定分页、snapshot 校验、execute 编排、summary 汇总、
  M06 水位仓储，以及对各 owner 命令的**端口调用**；
- 向共享热点（router、contracts、生成物）**提交补丁**，由 AG-00 统一应用。

**A5 不可以**：

- 直接改 M07/M10/M11/M13/M18/M19/M32/M33/M40 的业务表、repository 或命令实现；
- 复用人类 `reassign`、伪造 dtuid actor、绕过审批锁、修改历史署名、发送逐对象通知；
- 直接改冻结 OpenAPI、生成器、测试向量，或创建 merge revision。

**交付顺序**：

1. AG-00 批准本裁定，并提交 `09` 的 CCR；
2. M03 先交 SDK v2；M05/M07 交纯身份解析；M06/M08 交水位与幂等适配；
3. M13、M10/M11/M18、M19、M40、M32/M33 按 §1.3 的签名**并行**交付命令、迁移、单测与错误映射；
4. A5 逐个接收 owner 的 handoff：接口签名、错误类型、锁序、不变量测试、migration revision、回滚说明；
5. A5 完成 M06 编排与集成测试（冻结契约的改动仍等 CCR APPROVED）；
6. AG-00 创建 merge revision、应用共享热点补丁、改生成器并再生基线与类型，最后由 M24 跑系统测试。

---

## 2. system-actor 语义裁定

### 数据交接 v2 system-actor 并行裁定（2026-08-10，AG-00，A5 开工前置）

### 2.1 系统 actor 的身份表示

**执行者固定表示为 `SYSTEM:EASYAUTH_HANDOVER`，但这个字符串不写进任何 dtuid / FK 列。**

| 位置 | 取值 |
|---|---|
| `audit_logs.actor_dingtalk_user_id` | `NULL`；`metadata_json.executor = "SYSTEM:EASYAUTH_HANDOVER"` |
| `task_activities.actor_dingtalk_user_id` | `NULL`；`payload_json.action = "SYSTEM_HANDOVER"` |
| `task_assignment_history.changed_by_dingtalk_user_id` | `NULL`（需 `m10_002` 迁移改为 nullable） |
| `created_by_*` / `added_by_*` 等历史署名 | **一律不改写**；关系转移时**继承来源关系**的历史元数据（D11） |

**不得把来源关系的历史署名复制到新关系行。**

早期版本写的是"新建目标行时原样继承来源行的 `added_by` / `created_at`"。那会造出一段
**从未发生过的历史**：主管 X 一年前把 A 加进项目，今天系统把 A 的成员关系交接给 B，
新的 `(project, B)` 行却显示"X 在一年前添加了 B"。审计和界面都会对着一个假事实做断言，
真出事追责时也分不清哪条是原始记录、哪条是交接造出来的。

规矩：

| 情形 | `added_by` / `created_at` |
|---|---|
| 目标关系**已存在**（合并场景） | 一个字节不动 |
| **新建**目标关系 | `created_at = now`；`added_by = NULL`（系统行为，需把该列改为 nullable） |

来源关系的原始元数据连同三元组写进 **append-only 审计**，历史不丢，但不冒充成新关系的署名。

**明确否决「哨兵 dtuid」方案**：哨兵值会进入 directory 外键与人员查询，在 UI 上伪装成一名真实员工。
而 audit / activity 的 actor 本来就允许为空，只有 assignment history 需要一次 nullable 迁移 ——
代价远小于往人员体系里塞一个假人。

审计 `metadata_json` 的固定字段：

```json
{
  "executor": "SYSTEM:EASYAUTH_HANDOVER",
  "trigger_system": "EasyAuth",
  "handover_task_id": "...",
  "generation": 1,
  "batch_id": 1,
  "delivery_id": "...",
  "kind": "offboard",
  "from_user_id": "...",
  "to_user_ids": ["..."]
}
```

**「谁触发」与「谁执行」是两件事，本期只能记住后者。**
冻结的 preview / execute payload 里**没有 initiator / operator 字段**（契约 §10.3、§10.5），
所以 EasyProject 无从可靠得知是主管、当事人还是超管按的按钮。
它只记录 `trigger_system=EasyAuth` 与 `handover_task_id`；**具体发起人以 EasyAuth 自己的审计为权威**
（契约 §12 有完整事件链）。

> **不得**用 `from_user_id`、接收人或签名身份去"推断"发起人 —— 那是编造。
> 若产品确实需要 EasyProject 展示发起人，另提**跨系统** CCR，在 payload 增加 `initiator_user_id`。

UI 表现：管理审计列表对 NULL actor 已显示 `SYSTEM`；任务时间线需由 M11 前端补一条文案映射
`SYSTEM_HANDOVER → 「EasyAuth 数据交接（系统）」`，否则会落到 generic 兜底文案。

### 2.2 `state_version` 与乐观锁

- **system handover 命令不要求调用方传 `state_version`。** 现有任务命令要求
  `expected_state_version`，那是**人类客户端的快照**，冻结 webhook payload 里没有它。
- 每个 owner 命令必须在 repository 层 `SELECT ... FOR UPDATE` 拿到聚合根**之后**再读当前版本。
  **禁止**在 M06 事务外预读版本号再当作 expected version 传下去 —— 那是把一个必然过期的值当真。
- **固定跨模块锁序**（全局唯一，所有实现共用）：

  ```
  generation 水位行
    → projects（UUID 升序；集合 = 显式的项目类资产 ∪ **所有待写 task 的非空 project_id**）
    → tasks（UUID 升序）
    → recurring_task_templates（UUID 升序）
    → work_records（UUID 升序）
    → task_reminder_rules（UUID 升序）
    → 幂等响应行
  ```

- 锁内重新校验：来源人仍拥有该角色、对象仍满足终态谓词、目标仍 active、snapshot 仍匹配、审批锁未出现。

> **`projects` 的锁集合必须把待写任务的父项目也算进来**，哪怕这一批里一个项目类资产都没有。
> 现有任务写路径是先锁 task、再**无锁** SELECT project（`infra/repositories/tasks.py:460,1232-1244`），
> 而审批发起会 `FOR UPDATE` 锁项目并写锁态（`infra/repositories/projects.py:877`）。
> 只锁 task 的话：handover 锁住 T、读到 P 还没上锁，并发审批把 P 锁上，handover 照样改了 T ——
> **审批期间的写保护就这么被穿透了，而且不会返回 423。**
- 并发者先提交并改变了归属或 snapshot → 返回 `409 HANDOVER_CONFLICT`。
  **不得**在已经变化的对象上"尽量搬一搬"。
- handover 先持锁时，随后到达的人类命令按其 expected version 走**原有的**版本冲突路径；
  system handover **不返回**伪造的 `state_version`。
- 任务人员交接：`state_version` 不变，`version` +1，assignee 变化时 `assignment_version` +1，
  状态流转表不写。

### 2.3 幂等键映射

冻结三元组是 `(task_id, generation, batch_id)`（契约 §10.5.2），同 generation 可以有多批。

映射固定为：

| 列 | 值 |
|---|---|
| `principal_key` | `"system:easyauth-handover"` |
| `operation` | `"postEasyauthLifecycleHandover"` |
| `idempotency_key` | `f"handover:v2:{task_id}:{generation}:{batch_id}"` |
| `request_sha256` | canonical payload 的 SHA-256（既有列） |
| `response_json` | 首次成功的 `{"summary": ...}` 整体 |

> **用可读键而不是三元组的哈希。** 列宽 128 字符，`task_id` 已由契约 §5.3 约束为 ≤64 字节，
> 加上前缀与两个整数远小于上限。哈希键在排障时无法从日志反查是哪张单的哪一批，
> 而这类问题恰恰要靠人翻库定位。

canonical payload hash 固定为：

```python
sha256(
    json.dumps(parsed_body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
).hexdigest()
```

**必须用解析后的对象重新序列化，不能哈希原始字节** —— 否则上游无意义的空白差异会被误判成 payload 冲突。

重放语义：

| 情形 | 行为 |
|---|---|
| 同三元组、同 hash | 返回首次保存的 HTTP status 与完整 summary，**不调用任何领域命令** |
| 同三元组、不同 hash | `409 WEBHOOK_PAYLOAD_CONFLICT` |
| 同 task、`generation` 小于水位 | `409 HANDOVER_CONFLICT` |
| 同 generation 的不同 batch | **独立执行**，不得互相重放 |

**各领域命令不再各自 claim 幂等键；由外层 M06 对整个数据库事务 claim 一次。**
嵌套的跨模块幂等记录会把部分成功暴露出来，与契约 §10.5「整事务成败一致」冲突。

generation 水位语义：

1. **preview / items** 进入后，在短事务里锁定或创建 `easyauth_handover_generations` 行；
   小于当前值立即 409，大于则推进并提交。
   **execute 不在入口做水位拒绝** —— 它的第一步是 `claim_or_replay`，命中已完成回执就直接
   返回原 summary；**只有首次 claim 成功之后**才检查并推进水位。

   > 顺序反了会这样：generation 1 成功；generation 2 的 preview 把水位推到 2；
   > 此时 generation 1 的**网络重试**到达 —— 它在查幂等回执之前就被判「迟到的旧轮次」409。
   > 上游看到的是「同一个请求上次成功、这次失败」。
2. execute 在事务外完成身份解析后，进业务事务**再次锁定**该水位；若此时已有更高 generation，立即 409；
3. 业务事务**持有水位锁直到**全部领域写入、outbox、audit 与幂等响应一起提交。

**幂等 claim 必须排在业务锁与领域命令之前**，顺序固定为：

```
锁 generation 水位行
  → IdempotencyGuard.claim_or_replay(...)      ← 命中重放立即返回已存 summary, 到此结束
  → 按 §2.2 的锁序依次加锁 projects / tasks / templates / work_records / rules
  → 调各 owner 的 system_handover
  → store_response(...)  与业务写入同事务提交
```

> **顺序反了就违背"重放不得调用任何领域命令"这条规定。** 若先加锁跑命令再发现是重放，
> 一次成功请求的重放会重新跑 snapshot 与归属校验，很可能返回 412/409 而不是那份保存好的
> 200 summary —— EasyAuth 那边看到的是"上次成功、这次失败"。

**`IdempotencyGuard` 的错误码要转译**：同键不同 hash 时它抛的是通用的
`IDEMPOTENCY_CONFLICT`（`infra/idempotency/guard.py:185`），而本 operation 冻结的是
`WEBHOOK_PAYLOAD_CONFLICT`（`09` §5.2）。**M06 捕获后自行转换，不要去改 M08 的通用错误码。**

### 2.4 审批锁

**裁定：不绕过。拒绝本批 execute，但用一个"可恢复"的状态码。**

- HTTP **`423 Locked`**，错误码 **`HANDOVER_TEMPORARILY_LOCKED`**（本 operation 新增），
  message/metadata 里保留内部原因 `PROJECT_LOCKED`。

> **不能直接把 `PROJECT_LOCKED` 改成 423。** 它是**全局**冻结码，现有项目/任务端点都在用，
> 错误向量里也写死了 409（`contracts/test-vectors/error-bodies.json:165`、
> `domain/tasks/errors.py:143`）。改全局映射会打坏一片既有端点与门禁。
>
> 正确做法：领域层照旧抛 `PROJECT_LOCKED(409)`；**M06 在边界处转译**成
> `423 HANDOVER_TEMPORARILY_LOCKED`。
> `HANDOVER_CONFLICT` 的说明里**删掉「审批锁」** —— 它只覆盖项目终态、归属变化、迟到 generation。

> **为什么不是 409。** 409 在契约里被判为**不可重试的 `failed`**。
> 而审批锁是**临时**状态：审批一结束锁就没了，这次交接完全应该能继续。
> 用 409 的话，一次正常的"执行时恰好有个项目在审批中"会把 action 永久打成失败，
> 界面上既没有重试也没有重新预演的路径，只剩超管 skip 或整单 cancel —— 那是把临时冲突
> 变成了人工事故。423 让 action 退回 `pending`，用户解除审批后重新预演即可。
- 理由：项目锁的用途就是冻结审批期间的业务写，现有 task reassign 明确检查它。
  system actor 只豁免**人类授权**检查，不能破坏审批一致性。
- **不允许**返回 200 且 `failed > 0` —— 契约要求整事务成败一致，正常情况 `failed` 恒为 0。
- EasyAuth 侧按契约 §10.6 把 409 展示出来；用户解除审批锁后重新 preview，以新的
  generation / batch 重新执行。

### 2.5 角色与 scope 校验

**豁免**（仅限这些）：

- actor 是否属于该项目/任务；
- actor 的人类角色是否有权执行 reassign；
- `x-required-permissions` 与 MANAGED/OWNED scope（该 operation 本就靠 HMAC，required permissions 为空）；
- 人类调用所需的 `expected_state_version`（改为锁内读取，§2.2）；
- 人类命令的 reason 格式（系统命令固定 reason 为
  `EasyAuth data handover <task_id>/<generation>/<batch_id>`）。

**绝不豁免**：

- HMAC、时间窗、body 上限、`event_type` 与事件头一致性；
- 来源人当前**仍**承担所选责任；
- 接收人能精确映射为 dtuid、仍 active、且不是来源本人；
- asset type 已声明、asset id 属于当前 snapshot、`release` 只用于 `releasable=true` 的类型；
- 项目审批锁、终态谓词、唯一 OWNER、复合主键合并规则、外键、事务与锁序；
- snapshot token、generation 水位、三元组幂等与 payload hash；
- WorkRecord 的 creator 不得被加入 participant 这条既有不变量。

### 2.6 通知副作用

- system handover **不调用** M10 的 `TASK_REASSIGNED`、M13 的 member-added 或任何逐对象通知 writer。
- EasyProject 只写**一条 batch 级 audit**；任务时间线仍按受影响任务各写一条 activity ——
  它是业务历史，不是消息投递。
- 接收人 / 转出方 / 上级的完成通知**由 EasyAuth** 在 action 或整单收敛后合并发送（契约 §13）。
- 若日后确实需要 EasyProject 站内通知，只允许每个
  `(handover_task_id, generation, batch_id, recipient)` 一条**聚合**消息，
  且须由 M14 新增事件目录与 dedup 规则。**本次不实施。**
