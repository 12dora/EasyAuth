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
| `project_members` | 删除来源关系行；目标不存在时插入目标行并**原样继承**来源行的 `added_by_dingtalk_user_id` / `created_at`；目标已存在时只调整 `role` | **M13 命令**。复合主键 + `uq_project_members_one_owner` 部分唯一索引（`alembic/versions/m13_001_project_tables.py:135-142`）要求在同一命令内合并 |
| `tasks` | `assignee_dingtalk_user_id`、`assigner_dingtalk_user_id`、`assignment_version`、`version`、`updated_at`；**明确不改** `status`、`state_version` | **M10 命令** |
| `task_collaborators` | 删除来源行；目标不存在时插入并继承 `added_by` / `created_at` | **M10 命令**。复合主键 `(task_id, dingtalk_user_id)` |
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
    *, authentik_sub: str, directory: EasyAuthDirectoryPort,
    users: DirectoryUserRepository, now: datetime,
) -> str: ...

# backend/app/domain/identity/directory_repo.py
async def bind_verified_authentik_sub(
    self, *, dingtalk_user_id: str, authentik_user_id: str, now: datetime,
) -> DirectoryUserRecord: ...
```

保证：只做精确 sub↔dtuid 映射（禁止姓名/邮箱模糊匹配，契约 §5.2）；冲突或解析不到抛
`IdentityUnmappedError` → API 映射 `409 IDENTITY_UNMAPPED`；**不得修改任何登录时间戳**；目标用户仍须 active。

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
- OWNER 转移顺序固定：**删除/降级旧 OWNER → flush → 升级或插入目标 OWNER → 最后同步
  `projects.owner_dingtalk_user_id`**（部分唯一索引非 deferrable，顺序反了立刻撞约束）；
- 保持「每项目恰有一个 OWNER」；成员关系的 `added_by` / `created_at` 历史元数据**继承不改写**；
- 项目终态、审批锁、来源已非 owner/member、目标 inactive、snapshot 不匹配 → 抛
  `ProjectHandoverConflict` → `409 HANDOVER_CONFLICT`；
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
- collaborator 目标已存在 → 删除来源行并计入 `merged`；否则转移关系并保留历史 `added_by` / `created_at`；
- 写一条 M11 activity（actor 为 NULL，payload 带三元组）；
- **不写** `task_state_transitions`，**不发** `TASK_REASSIGNED` 通知；
- 审批锁、终态、来源不再匹配、目标 inactive、版本或唯一约束竞争 → `TaskHandoverConflict` →
  `409 HANDOVER_CONFLICT`。

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
- 旧 PENDING occurrence 标 `SKIPPED` / `HANDOVER_SUPERSEDED`，再用既有计算器生成新 occurrence 并推进规则游标；
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
**目标不得等于 creator**（既有 participant 归一化会排除 creator）；
**不得修改** `created_by_dingtalk_user_id`；冲突 → `409 HANDOVER_CONFLICT`。

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

保证：在 M10 的业务事务内**只写 durable outbox**；唯一键为三元组 + `task_id`；
worker 在事务外更新 OpenProject 的 `assignee_dtuid` / `collaborators_dtuid` 两个 CF；
成功后用短事务更新锚点列；失败可重试，最终写 M32 的 `APPLY_FAILED` 冲突台账。
**不得依赖 M34 对账自动修复** —— 它明确不回写人员字段。

### 1.4 迁移与 revision 裁定

当前唯一 Alembic head 是 `m46_001_record_task_order`。需要**三个并行 revision**，各由自己的 owner 创建：

| revision | down_revision | 内容 | owner |
|---|---|---|---|
| `m06_003_handover_generation_watermarks` | `m46_001_record_task_order` | 建 `easyauth_handover_generations(task_key_sha256 CHAR(64) PK, task_id TEXT NOT NULL, max_generation INTEGER NOT NULL, updated_at TIMESTAMPTZ NOT NULL)` | M06 |
| `m10_002_task_handover_actor` | `m46_001_record_task_order` | 仅把 `task_assignment_history.changed_by_dingtalk_user_id` 改为 **nullable** | M10 |
| `m32_002_handover_projection_outbox` | `m46_001_record_task_order` | 建 `op_handover_projection_outbox` 及唯一约束 `(handover_task_key_sha256, generation, batch_id, task_id)` | M32 |

三条并行分支落地后，**由 AG-00 创建** merge revision：

```python
revision = "m00_004_data_handover_v2_heads"
down_revision = (
    "m06_003_handover_generation_watermarks",
    "m10_002_task_handover_actor",
    "m32_002_handover_projection_outbox",
)
```

`idempotency_records` **不需要迁移**（既有列已够用），但**不得**用一条固定的
`handover:{task_id}:maxgen` 记录来维护水位 —— 通用幂等记录是**永久墓碑**，
`COMPLETED` 之后 `store_response` 直接返回，**不可更新**（`infra/idempotency/guard.py:136-175`）。
水位必须走 M06 自己的 `easyauth_handover_generations` 表 + 行锁。

**downgrade 的前置条件**：确认没有 NULL 的 assignment-history actor、没有未消费的 OP outbox 行。
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
    → projects（UUID 升序）
    → tasks（UUID 升序）
    → recurring_task_templates（UUID 升序）
    → work_records（UUID 升序）
    → task_reminder_rules（UUID 升序）
    → 幂等响应行
  ```

- 锁内重新校验：来源人仍拥有该角色、对象仍满足终态谓词、目标仍 active、snapshot 仍匹配、审批锁未出现。
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

1. preview / items / execute 进入后，在短事务里锁定或创建 `easyauth_handover_generations` 行；
   小于当前值立即 409，大于则推进并提交；
2. execute 在事务外完成身份解析后，进业务事务**再次锁定**该水位；若此时已有更高 generation，立即 409；
3. 业务事务**持有水位锁直到**全部领域写入、outbox、audit 与幂等响应一起提交。

### 2.4 审批锁

**裁定：不绕过。拒绝本批 execute。**

- HTTP `409 HANDOVER_CONFLICT`，标准错误体的 message/metadata 里保留内部原因 `PROJECT_LOCKED`；
  **不把 `PROJECT_LOCKED` 提升为跨系统冻结错误码**。
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
