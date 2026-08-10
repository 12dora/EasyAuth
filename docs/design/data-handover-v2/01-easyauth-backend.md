# 01 · EasyAuth 后端改造设计

> 基准文档：[`00-overview-and-contract.md`](00-overview-and-contract.md)（下称「契约」）。
> 本文件中出现的 D1–D13 编号、事件名、错误码、payload 形状均以契约为准，此处不重复定义，只给落地方案。
> **§6 的 HTTP API 契约是前端 agent（`02-easyauth-frontend.md`）的依赖，必须最先提交。**

---

## 1. 改造总览

| 模块 | 改动性质 | 说明 |
|---|---|---|
| `lifecycle/models.py` | 扩展 + 破坏性重构 | **新增 7 张表**：`HandoverAssetType` / `HandoverAssetOverride` / `HandoverExecutionBatch` / `HandoverDeliveryAttempt` / `HandoverExecutionLease` / `HandoverLeaseFence` / `HandoverBatchPlan`；`HandoverTask` 加 7 字段（assignee / assignee_state / escalation_level / generation / escalation_deadline / last_reminded_on / escalation_deferred_at）；`HandoverAppAction` 数据接收人下沉到条目级、保留并改名 `grant_receiver`，另加 generation / snapshot_token / confirm_version / overrides_version / batch_seq / data_completed_at / blocked_reason / skip_reason / skipped_by / skipped_at / last_error_raw / async_status_url / async_poll_attempts |
| `lifecycle/assignee.py` | **新建** | 主管链解析（契约 §8.2） |
| `lifecycle/escalation.py` | **新建** | 交接单超时上交（契约 §7.4）。~~代管授权~~已废弃 |
| `lifecycle/handover.py` | 重构 | webhook payload v2、新增 items 事件、blocked 判定 |
| `lifecycle/offboarding.py` | 扩展 | 建单时解析 assignee、置上交截止时间、升级路径 |
| `lifecycle/reassign.py` | **新建** | 在职移交建单与管辖校验（D8/D9） |
| `applications/models.py` | 扩展 | `App` 加交接能力三态与资产类型声明 |
| `webhooks/models.py` | 微调 | body 上限常量 |
| `admin_console/lifecycle_api.py` | 扩展 | 新增 skip/claim/items 端点 |
| `portal/` | **新建一组端点** | 自助交接（D1），全部非超管 |
| `tasks/lifecycle.py` | **扩展既有文件** | 到期上交、每日提醒两个 beat 任务（该文件已存在） |
| `sdk/python/.../lifecycle.py` | 扩展 | v2 事件与 items 回调 |
| `lifecycle/approvals.py` | **新建** | 审批责任改派（契约 §11.1，见 §4.5） |
| `lifecycle/core.py` | 修既有缺陷 | 状态汇总改全量纯函数、允许回退 pending |
| `docs/decisions/ADR-002` | 修订 | 仅 §36 一条（§19 已取消） |

**硬约束提醒**（`AGENTS.md`）：项目未上线，**不保留旧形态、不写兼容层**。
`execution_to_user` / `policy` / `execution_policy` 直接删除；`to_user` 走 `RenameField`
改名为 `grant_receiver`。所有文档必须中文。

**迁移与调用方必须原子提交**：`handover.py`、`transfer.py`、`admin_console/lifecycle_api.py`、
生命周期测试、`HandoverWizard.tsx`、前端类型定义与已构建的静态产物**都读这些字段**，
分开提交会产出跑不起来的中间 commit，与「每次提交后必须重建前后端并确认构建成功」冲突。

---

## 2. 数据模型变更

### 2.1 `HandoverTask`（`lifecycle/models.py:109`，修改）

新增字段：

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `assignee` | `FK(UserMirror, on_delete=PROTECT, null=True, blank=True, related_name="handover_assignments")` | 可空 | 当前负责人；`superuser_pool` 时为 `NULL` |
| `assignee_state` | `CharField(max_length=16, choices=ASSIGNEE_STATE_CHOICES, default=ASSIGNEE_STATE_SUPERUSER_POOL)` | CheckConstraint | `manager` / `subject` / `superuser_pool` |
| `escalation_level` | `PositiveSmallIntegerField(default=0)` | — | 当前 assignee 在主管链上的层级 |
| `generation` | `PositiveIntegerField(default=1)` | — | 执行轮次，升级/重新盘点时 +1（契约 §8.3） |

新增常量：

```python
ASSIGNEE_STATE_MANAGER: Final = "manager"
ASSIGNEE_STATE_SUBJECT: Final = "subject"
ASSIGNEE_STATE_SUPERUSER_POOL: Final = "superuser_pool"
ASSIGNEE_STATE_VALUES: Final[tuple[str, ...]] = (
    ASSIGNEE_STATE_MANAGER, ASSIGNEE_STATE_SUBJECT, ASSIGNEE_STATE_SUPERUSER_POOL,
)

HANDOVER_KIND_PRE_OFFBOARD: Final = "pre_offboard"  # 在职提前交接(不动权限)
HANDOVER_KIND_REASSIGN: Final = "reassign"          # 在职互转(不动权限)
# 两者都要加入 HANDOVER_KIND_CHOICES / HANDOVER_KIND_VALUES;
# 既有的 transfer 保持"转岗"原义, 继续走 TransferPlan 授权差异, 不要复用它承载提前交接。

# 会改动授权的 kind, 供 §5.5 判定
GRANT_MUTATING_KINDS: Final[tuple[str, ...]] = (HANDOVER_KIND_OFFBOARD, HANDOVER_KIND_TRANSFER)
```

**约束变更**（关键）：现有 `lifecycle_task_one_open_per_subject` 会挡住 `reassign` 与离职单并存，
必须改为只约束 `offboard`/`transfer`：

```python
models.UniqueConstraint(
    fields=["subject_user"],
    condition=Q(status__in=TASK_OPEN_STATUSES)
              & Q(kind__in=(HANDOVER_KIND_OFFBOARD, HANDOVER_KIND_TRANSFER,
                            HANDOVER_KIND_PRE_OFFBOARD)),
    name="lifecycle_task_one_open_lifecycle_per_subject",
)
```

新增约束：

```python
models.CheckConstraint(
    condition=Q(assignee_state__in=ASSIGNEE_STATE_VALUES),
    name="lifecycle_task_assignee_state_supported",
),
# superuser_pool 必须无 assignee; 其余状态必须有 assignee。
models.CheckConstraint(
    condition=(
        Q(assignee_state=ASSIGNEE_STATE_SUPERUSER_POOL, assignee__isnull=True)
        | (~Q(assignee_state=ASSIGNEE_STATE_SUPERUSER_POOL) & Q(assignee__isnull=False))
    ),
    name="lifecycle_task_assignee_shape",
),
```

### 2.2 `HandoverAppAction`（`lifecycle/models.py:163`，破坏性修改）

**删除**：`execution_to_user`、`policy`、`execution_policy`（数据接收人下沉到条目级 D10；
`policy.unowned_strategy` 被三值 `action` 取代）。

**保留并改名**：原 `to_user` → **`grant_receiver`**（契约 §10.5.1.1）。迁移用 `RenameField`，**不是** Remove+Add。它不再是「数据接收人」，
而是**权限接收人**：该 APP 上离职者的授权转给谁。

- 可为空（留空 = 只撤权、不转授，接收人自行走申请流程；这是安全默认）
- **仅 `kind=offboard` 有意义**，其余 kind 上必须为空
- 与 `HandoverAssetType.default_to_user` / `HandoverAssetOverride.to_user` 是**三个不同的字段**，
  实现时不要合并

> **这条不变量不能用 `CheckConstraint` 表达。** Django 的 `CheckConstraint` 不允许跨关联
> （`Q(task__kind=...)` 会被 system check 判 `models.E041`），PostgreSQL 的 CHECK 也不能引用别的表。
> 落法二选一，**必须二者都做**：
>
> 1. **数据库侧**：PostgreSQL 约束触发器（`CONSTRAINT TRIGGER ... DEFERRABLE INITIALLY DEFERRED`），
>    在 `HandoverAppAction` 的 INSERT/UPDATE 上校验
>    `task.kind = 'offboard' OR grant_receiver_id IS NULL`；
> 2. **领域侧**：`validate_assignments()` 与建 action 路径各自显式校验一次，给出可读错误。
>
> 只做领域侧校验不够 —— 数据修复脚本、shell、以及未来的批量导入都会绕过它。
>
> **全仓统一用约束触发器表达跨表不变量**（本节与 §2.4 的 override 那条）。
> SQLite 上的单测只验 domain / API 校验；**触发器只在 PostgreSQL lane 验证**，
> 对应用例必须显式标记为需要真库，不允许在 SQLite 上"跑过了"就算数。

> 早期版本把 `to_user` 整个删掉，导致 `transfer_selected_grants(action)` 失去输入 ——
> 该函数依赖 action 级接收人，而条目级有多个接收人时无法推断授权该给谁。`grant_receiver` 补上这个洞。

**新增**：

| 字段 | 类型 | 说明 |
|---|---|---|
| `generation` | `PositiveIntegerField(default=1)` | 建 action 时从 `task.generation` 拷贝；升级时重置 |
| `snapshot_token` | `CharField(max_length=128, blank=True)` | 最近一次 preview 返回的令牌（契约 §10.5.1），**不出现在任何 HTTP 响应里** |
| `confirm_version` | `PositiveIntegerField(default=0)` | 单调递增。**preview 成功、修改类型级 `default_action`/`default_to_user`、整体替换 overrides、修改 `grant_receiver` —— 这四件事任意一件都 +1。** execute 请求必须回带匹配值，否则 `409 confirm_version_stale`（§6.1） |
| `overrides_version` | `PositiveIntegerField(default=0)` | 单调递增，每次 override 集合被替换 +1。`PUT overrides` 必须回带匹配值，否则 409 |
| `skipped_at` | `DateTimeField(null=True, blank=True)` | 强行跳过的时间，与 `skipped_by` 一起构成责任链 |
| `last_error_raw` | `TextField(blank=True)` | **新增**。下游原始响应体，截断 2000 字符，**只在控制台对超管展示且每次查看写审计**。既有的 `last_error`（`lifecycle/models.py:233`）改为只放「状态码 + 本地分类文案 + 白名单提取的 `code`/`message`，各截断 200 字符并脱敏」，门户与控制台都能看（契约 §10.6） |
| `batch_seq` | `PositiveIntegerField(default=0)` | 已分配的最大批次号。**只是分配器**；批次的事实来源是 §2.4.1 的 `HandoverExecutionBatch` 行 |
| `data_completed_at` | `DateTimeField(null=True, blank=True)` | 数据 webhook 已成功、权限尚未转授（契约 §10.5.1.1 的子状态，持久化） |
| `grant_receiver` | `FK(UserMirror, PROTECT, null=True, related_name="handover_grant_receiving")` | 权限接收人，见上 |
| ~~`execution_payload`~~ | — | **取消**。单个可更新字段无法承载多批历史，也称不上"不可变凭据"。改用 §2.4.1 的 append-only 表 |
| `blocked_reason` | `CharField(max_length=64, blank=True)` | `capability_undeclared` / `descriptor_unreachable` |
| `skip_reason` | `TextField(blank=True)` | 超管强行跳过的理由（D6） |
| `skipped_by` | `CharField(max_length=128, blank=True)` | 超管 actor id |

**状态枚举新增**：`ACTION_STATUS_BLOCKED: Final = "blocked"`，加入 `ACTION_STATUS_CHOICES` / `_VALUES`。
`ACTION_FINISHED_STATUSES` **保持** `(done, skipped)` 不变 —— `blocked` 不是终结态，这正是 D13 的实现基础：
`refresh_task_status()`（`lifecycle/core.py:131`）用 `all(a.status in ACTION_FINISHED_STATUSES)` 判完成，
`blocked` 天然落不进去，无需改判定逻辑。

> **但有一个必须处理的副作用**：同函数 `lifecycle/core.py:144` 用
> `started = any(a.status != ACTION_STATUS_PENDING ...)` 判是否进 `in_progress`。
> 由于 `blocked` 是 action 的**初始**状态之一（§5.1），一张所有 APP 都未接入的单会在**建单当场**
> 就被判为 `in_progress`，从未经历 `pending`。这会让"待处理"筛选器漏掉这类单 —— 而它们恰恰是最需要
> 被看见的。
>
> **修法**：`refresh_task_status()` 改写成一个**全量纯函数**，算出 `next_status` 后无条件比较并保存
> —— 包括 `in_progress → pending` 的**回退**。现有实现只升不降，升级重置或 capability 恢复后
> 会停在「task 是 `in_progress`、所有 action 都是 `pending`」这种自相矛盾的状态上。
>
> ```python
> def compute_task_status(task, actions, team_items, *, plan_confirmed: bool) -> str:
>     if task.status == TASK_STATUS_CANCELLED:
>         return TASK_STATUS_CANCELLED              # 终态, 不再重算
>     actions_finished = all(a.status in ACTION_FINISHED_STATUSES for a in actions)
>     # 团队项没有 is_finished/is_started 属性, 只有 status 列
>     teams_finished = all(t.status != ITEM_STATUS_PENDING for t in team_items)
>     if actions_finished and teams_finished and plan_confirmed:
>         return TASK_STATUS_COMPLETED              # D13; 存在 blocked 时 actions_finished 必为 False
>     started = (
>         any(a.status not in (ACTION_STATUS_PENDING,
>                              ACTION_STATUS_BLOCKED,
>                              ACTION_STATUS_SKIPPED) for a in actions)
>         or any(t.status != ITEM_STATUS_PENDING for t in team_items)
>     )
>     return TASK_STATUS_IN_PROGRESS if started else TASK_STATUS_PENDING
>
> def refresh_task_status_locked(task) -> None:
>     # 调用方已在同一事务里 select_for_update 锁住 task
>     plan_confirmed = True
>     if task.kind == HANDOVER_KIND_TRANSFER:
>         plan = TransferPlan.objects.filter(task=task).first()
>         plan_confirmed = plan is not None and plan.confirmed_at is not None
>     nxt = compute_task_status(task, task.app_actions.all(), task.team_items.all(),
>                               plan_confirmed=plan_confirmed)
>     if task.status != nxt:                        # 任何方向都保存, 含回退
>         task.status = nxt
>         task.save(update_fields=["status", "updated_at"])
>         if nxt == TASK_STATUS_COMPLETED:
>             审计 handover_task_completed
>             if task.kind == HANDOVER_KIND_TRANSFER:
>                 清除 subject 的 department_changed_at   # 既有副作用, 不要丢
> ```
>
> **三处不能改写既有行为**：
>
> 1. **`plan_confirmed` 门槛必须保留。** 现有实现（`lifecycle/core.py:127-131`）对 `kind=transfer`
>    额外要求 `TransferPlan.confirmed_at` 非空。丢掉它的话，转岗单在 action 全部结束时就会被判
>    `completed`，随后 `confirm_transfer_grant_diff()` 会被 `ensure_task_open()` 拒绝 ——
>    **新岗位的授权差异永远应用不上，而单据显示已完成**。
> 2. **团队项用 `status`，没有 `is_finished` / `is_started` 这两个属性。**
>    `HandoverTeamItem` 只有 `status` 列（`lifecycle/models.py:360`），既有代码写的是
>    `item.status != ITEM_STATUS_PENDING`。照虚构属性写，离职者是团队 leader 时建单当场
>    抛 `AttributeError`，**整个建单事务回滚**。
> 3. **完成时清除 `department_changed_at`** 这个既有副作用不要丢。
>
> `started` 排除 `pending` / `blocked` / `skipped` 三种**初始态**：
> `blocked` 是未接入 APP 的初始状态，`skipped` 是 `capability="none"` 的初始状态。
> 不排除的话，一张全部未接入或全部声明无数据的单会在**建单当场**就被判成 `in_progress`，
> 从未经历 `pending` —— 而"待处理"筛选器恰恰最需要看见它们。
>
> **调用点（缺一个就会状态滞后）**：preview 成功、preview 失败、`default_action` / override 变更、
> execute 各阶段、retry、skip、capability reconcile、`apply_team_item()` 完成、升级重置。
> 现有代码在 preview 后**根本没有调用**（`handover.py:542,551`），首次 preview 完成后单据仍停在 `pending`。
>
> **必须与子状态同事务，不能"提交后再调一次"。** 网络调用仍在事务外，但**响应落库这一步**
> 要按统一锁序 `task → 子项` 加锁，并在**同一事务**里调 `refresh_task_status_locked()`：
> 子状态与汇总状态原子提交。
> 分成两个事务的话，最后一个 action 提交完、进程恰好退出，task 就**永久停在 `in_progress`** ——
> 之后再没有任何状态变化会触发修复，而提醒、列表筛选、以及"一人一张 open 单"的唯一约束
> 会一直用着这个错值。周期 reconcile 只能当兜底，不能当唯一的正确性来源。

### 2.3 `HandoverAssetType`（新表）

preview 返回的资产分类落库，同时承载"这一类归谁"的默认接收人。

```python
class HandoverAssetType(models.Model):
    action = FK(HandoverAppAction, on_delete=CASCADE, related_name="asset_types")
    generation = PositiveIntegerField()                      # 与 action.generation 一致
    type_key = CharField(max_length=64)                      # 契约 §10.3 的 type
    label_snapshot = CharField(max_length=120)
    count = PositiveIntegerField(default=0)
    detail_supported = BooleanField(default=False)
    releasable = BooleanField(default=False)
    default_action = CharField(max_length=8, choices=ASSET_ACTION_CHOICES,
                               default=ASSET_ACTION_SKIP)    # transfer | release | skip
    default_to_user = FK(UserMirror, on_delete=PROTECT, null=True, blank=True,
                         related_name="handover_default_receiving_types")
    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["action", "generation", "type_key"],
                name="lifecycle_asset_type_unique_per_generation",
            ),
        ]
        ordering = ["action_id", "generation", "type_key"]
```

追加约束：`action=transfer` 必须有接收人，其余两种必须没有。

```python
models.CheckConstraint(
    condition=(Q(default_action=ASSET_ACTION_TRANSFER, default_to_user__isnull=False)
               | (~Q(default_action=ASSET_ACTION_TRANSFER) & Q(default_to_user__isnull=True))),
    name="lifecycle_asset_type_action_shape",
),
```

新增常量：

```python
ASSET_ACTION_TRANSFER: Final = "transfer"
ASSET_ACTION_RELEASE: Final = "release"
ASSET_ACTION_SKIP: Final = "skip"
ASSET_ACTION_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    (ASSET_ACTION_TRANSFER, "transfer"),
    (ASSET_ACTION_RELEASE, "release"),
    (ASSET_ACTION_SKIP, "skip"),
)
```

- 默认值是 `skip`：**未经人明确指定的资产一律不动**，这是安全侧的默认。
- `release` 只在 `releasable=True` 时允许（§5.4 校验）。
- `default_action=skip` 的类型**仍然进** `assignments`（值为 skip），下游据此知道"这一类本轮被明确跳过"，
  与"这一类根本没出现"在审计上是同一结果但表达更清楚。

### 2.4 `HandoverAssetOverride`（新表）

逐条改派（D10）。

```python
class HandoverAssetOverride(models.Model):
    asset_type = FK(HandoverAssetType, on_delete=CASCADE, related_name="overrides")
    asset_id = CharField(max_length=128)                     # 契约 §5.3，对 EasyAuth 不透明
    label_snapshot = CharField(max_length=120, blank=True)
    action = CharField(max_length=8, choices=ASSET_ACTION_CHOICES)
    to_user = FK(UserMirror, on_delete=PROTECT, null=True, blank=True,
                 related_name="handover_override_receiving")
    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["asset_type", "asset_id"],
                name="lifecycle_asset_override_unique",
            ),
            models.CheckConstraint(
                condition=(Q(action=ASSET_ACTION_TRANSFER, to_user__isnull=False)
                           | (~Q(action=ASSET_ACTION_TRANSFER) & Q(to_user__isnull=True))),
                name="lifecycle_asset_override_action_shape",
            ),
        ]
        ordering = ["asset_type_id", "asset_id"]
```

### 2.4.1 执行记录：**两张表**，不是一张

> **早期版本用单表 `HandoverExecutionAttempt` 表达不了。** 它同时被要求
> 「append-only、只增不改」与「发送前先写 `outcome="sent"`、拿到响应后回填结果」——
> 回填就违反 append-only，追加又撞 `(action, generation, batch_seq)` 唯一约束。
> 结果是**一次请求的最终成败根本无处安放**。拆成两张即可：批次不可变，投递可重试。

**`HandoverExecutionBatch`（不可变，一批一行）**

```python
class HandoverExecutionBatch(models.Model):
    action = FK(HandoverAppAction, on_delete=PROTECT, related_name="execution_batches")
    generation = PositiveIntegerField()
    batch_seq = PositiveIntegerField()
    is_final = BooleanField(default=True)         # 见下方 413 分批
    snapshot_token = CharField(max_length=128)
    request_payload = JSONField()                 # canonical, 发出前固化, 之后只读
    request_hash = CharField(max_length=64)       # sha256(canonical payload)
    status = CharField(max_length=16)             # pending | executing | async_pending
                                                  # | data_completed | done | failed
    data_completed_at = DateTimeField(null=True, blank=True)
    created_at = DateTimeField(auto_now_add=True)

    # 单据被删时保留审计所需的快照, 见下方 PROTECT 说明
    task_snapshot = JSONField(default=dict)       # {task_id, kind, app_key, subject_user_id}

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["action", "generation", "batch_seq"],
                name="lifecycle_execution_batch_unique",
            ),
        ]
```

**`HandoverDeliveryAttempt`（一次真实 HTTP 调用一行，受控单次状态转换）**

```python
class HandoverDeliveryAttempt(models.Model):
    batch = FK(HandoverExecutionBatch, on_delete=PROTECT, related_name="deliveries")
    delivery_seq = PositiveIntegerField()
    lease_fence = PositiveBigIntegerField()       # 发起时持有的 fence, 用于丢弃陈旧写回
    outcome = CharField(max_length=16)            # sent | succeeded | failed | async_accepted
    http_status = PositiveSmallIntegerField(null=True, blank=True)
    response_payload = JSONField(default=dict, blank=True)
    error_text = TextField(blank=True)
    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["batch", "delivery_seq"],
                name="lifecycle_delivery_attempt_unique",
            ),
        ]
```

事件幂等键（outbox `event_key` 与线上 `X-EasyAuth-Delivery`）用
**`lifecycle-execute:batch:{batch.pk}:delivery:{delivery_seq}`**。

> **不能用 `batch_id`（即 `batch_seq`）拼键。** 它的作用域是 `(action, generation)`，
> 两个不同 action 的第一批都是 `batch_seq=1, delivery_seq=1`，拼出来是同一个字符串；
> 而 outbox 的 `event_key` 是**全局唯一**的（`outbox/models.py:29-35`），
> 第二次 `enqueue_task()` 会因为同键不同 payload 抛 `OutboxEventConflictError`。
> 用数据库主键 `batch.pk` 才是全局唯一的。

> **这张表不是 append-only，别把它写成 append-only。**
> 发送前必须先插入一行 `outcome="sent"`（否则"发出去了但没记账"这种失序拦不住），
> 拿到响应后又必须把 `http_status` / `response_payload` / 终态 `outcome` 存下来。
> 严格 append-only 的话，所有行会永远停在 `sent`，一次调用的成败根本无处落库。
>
> 规矩是**受控的单次转换**：
> `sent → succeeded | failed | async_accepted` **只允许发生一次**，且必须走
> §2.4.2 的 CAS（`owner + fence + released_at IS NULL`）；**终态之后禁止任何修改**。
> 请求侧字段（`batch.request_payload` / `request_hash`）在 batch 上，**创建后不可变** ——
> 审计凭据在那里，不在这里。
>
> 库层加一条 CHECK：`outcome='sent' OR http_status IS NOT NULL`，
> 让"标了终态却没有响应记录"这种行写不进去。

**FK 定死为 `SET_NULL`，不是 `PROTECT`，更不是 `CASCADE`：**

| 选项 | 为什么不行 / 行 |
|---|---|
| `CASCADE` | 「execute 真发出去了、下游真改了数据、随后超管取消并删单」会把请求 hash、下游响应、幂等证据**全部级联删掉** —— 恰恰是最需要留证的那次 |
| `PROTECT` | 契约 §6.2 明说 `cancelled` 单**可以删除**；用 `PROTECT` 的话，凡是执行过的单就永远删不掉，等于偷偷改了契约 |
| **`SET_NULL`** | ✅ 单可以删，证据留下 |

因此：`action` 与 `task` 的 FK 都是 `null=True, on_delete=SET_NULL`，
而 `task_snapshot`（JSON，含 `task_id` / `kind` / `app_key` / `subject_user_id`）**非空**，
在创建 batch 时写入。
唯一约束建在**快照键**上：`(action_snapshot_id, generation, batch_seq)`，
`action_snapshot_id` 是创建时冗余下来的整数列（非空），这样 action 行没了唯一性也还在。
`HandoverDeliveryAttempt` 对 `batch` 继续用 `PROTECT`（batch 本身不随业务单消失）。

**分配与发送必须可恢复**：在事务内分配 `batch_seq`、写入 batch（`status="pending"`）与第一条
delivery（`outcome="sent"`）、写 outbox，**提交后**才由 worker 真正发请求。
这样"先加号后崩溃"只留下一条待续跑的记录，"先发送后加号"导致的重复分配不会发生。

`retry_action` 的语义：**重放原 batch、原 payload**，只追加一条新的 `HandoverDeliveryAttempt`
（`delivery_seq + 1`），**不新建 batch**。
改动 assignment、重新 preview、或 413 分片，才创建新 `batch_seq`。

#### 2.4.1.1 413 分批：状态必须落在**批次**上，不能落在 action 上

契约 §10.6 规定 413 时「分批执行」。但如果成功一批就把 action 置 `done`
（`data_completed_at` 也挂在 action 上），第二批就**既不能 execute、也不能 retry** ——
剩余资产永远搬不走，而单据显示已完成。

规则：

- `data_completed_at` 与执行态**同时存在于批次上**（见上表）。action 上的
  `data_completed_at` 只是**最终批**的镜像，供界面与 retry 判断用；
- 非最终批（`is_final=False`）成功后，action **保持 `previewed`**，并要求
  **重新 preview 取新的 `snapshot_token`**（契约 §10.5.2：同一 token 只能用于一批）；
- 只有 `is_final=True` 的批次数据成功、且授权转移那一步也成功后，action 才转 `done`；
- 界面上要显示「已完成 N / M 批」，不能只显示一个"进行中"。

**M（总批数）在收到 413 的那一刻就要算出来，但 batch 行不能提前建。**

两件事要分开：

| | 何时固化 | 内容 |
|---|---|---|
| **分片计划** `HandoverBatchPlan` | 收到 413 时**一次性**算好并落库 | `total=M`、每一批覆盖哪些 `asset_type` 与 `asset_id`、`plan_seq` |
| **批次行** `HandoverExecutionBatch` | **每批执行前才创建** | 该批的 `snapshot_token`、canonical payload、`request_hash` |

> **为什么不能一次建完 M 个 batch 行**：batch 上的 `snapshot_token` 与 payload 是
> **创建即不可变**的审计凭据，而第 2 批的 token **此刻还不存在** ——
> 契约 §10.5.2 规定每批必须重新 preview 取新 token（第 1 批已经改过数据，旧 token 必然失效）。
> 预建的话只有三条路：填旧 token（execute 必然 412）、填空（违反非空）、
> 或事后修改"不可变"的行（毁掉审计凭据）。三条都不行。

切分口径：按「每批不超过 200 KiB」（对 256 KiB 上限留 56 KiB 余量）。
`batch_progress.total` 取自计划的 `M`，`completed` 取自已终结的 batch 数 ——
所以用户从第一批开始就能看到确定的进度，不会面对一个不知道还剩多久的"进行中"。

每批的流程固定为：**重新 preview → 拿新 token → 建该批 batch 行 → execute**。
最后一批的 batch 记 `is_final=True`，只有它成功后 action 才转 `done`。

#### 分片时 `default_action` 怎么放，是这件事最容易做错的地方

线上契约里**没有"本批范围"这个概念**：下游只看得到 `default_action` + `overrides`，
`default_action` 作用于**该类型当前全部未被 override 的条目**。因此分片规则必须这样定：

| 批次 | `default_action` | `overrides` |
|---|---|---|
| 第 1 … M-1 批 | **强制 `skip`** | 只放本批的 `transfer` / `release` 逐条项 |
| **第 M 批（最终批）** | 该类型**真实的** `default_action` | 本批剩余的 `transfer`/`release` 项 **+ 全部 `skip` 逐条项** |

两条理由：

1. **非最终批不能带真实的 `transfer` 默认值** —— 那会让下游把**整个类型**一次处理完，
   分片白分，而且 summary 的守恒校验在第一批就对不上。
2. **全部 `skip` 逐条项必须留到最终批**。`skip` 不改数据，被 skip 的条目在后续轮次的
   re-preview 里**仍然属于当事人**；如果最终批带着真实的 `transfer` 默认值而没有带上这些
   skip 项，它们会被默认动作**一起搬走** —— 用户明确说"这几条不要动"的那些。

> **残留限制要如实说出来**：如果单是这些 `skip` 逐条项就撑爆了 256 KiB，本方案无解。
> 这时 execute 返回 `413`，界面提示「单独指定的条目过多，请减少逐条指定后重新预演」，
> **不要再自动分片**。这是一个真实的能力边界，不要假装它不存在。
> （彻底的解法是给线上契约加一个签名覆盖的 `batch_scope`，那是一次跨系统契约变更，本期不做。）

### 2.4.2 `HandoverExecutionLease`（新表，契约 §10.5.2）

```python
class HandoverExecutionLease(models.Model):
    subject_user = FK(UserMirror, on_delete=PROTECT, related_name="handover_leases")
    app = FK(App, on_delete=PROTECT, related_name="handover_leases")
    action = FK(HandoverAppAction, on_delete=CASCADE, related_name="leases")
    generation = PositiveIntegerField()
    batch_seq = PositiveIntegerField()
    owner = CharField(max_length=128)             # worker 标识
    fence = PositiveBigIntegerField()             # 单调递增, 防旧持有者写脏
    acquired_at = DateTimeField(auto_now_add=True)
    lease_expires_at = DateTimeField()            # 必填, 见下
    renewed_at = DateTimeField(null=True, blank=True)
    released_at = DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["subject_user", "app"],
                condition=Q(released_at__isnull=True),
                name="lifecycle_lease_one_active_per_subject_app",
            ),
        ]


class HandoverLeaseFence(models.Model):
    """(subject_user, app) 维度的 fence 取号器, 与租约行分开, 永不删除。"""
    subject_user = FK(UserMirror, on_delete=PROTECT)
    app = FK(App, on_delete=PROTECT)
    next_fence = PositiveBigIntegerField(default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["subject_user", "app"], name="lifecycle_fence_unique"),
        ]
```

**`lease_expires_at` 必填，否则一次 worker 崩溃就永久锁死。**
条件唯一约束会让后续任何执行都拿不到租约，而没有过期时间就没有任何合法的接管入口
——只能靠人手工删行，那正是最容易删错的操作。**execute 的第一个事务就必须原子取得租约**，否则条件唯一约束根本不会被触发：

```
事务 1（execute 入口）:
    select_for_update(action)
    fence = UPDATE HandoverLeaseFence SET next_fence = next_fence + 1 RETURNING next_fence
    INSERT HandoverExecutionLease(subject_user, app, action, generation, batch_seq,
                                  owner, fence, lease_expires_at=now+LEASE_TTL)
        ← 条件唯一约束冲突 → 立即 409 handover_execution_in_flight
    创建 HandoverExecutionBatch + 首条 DeliveryAttempt + outbox
    提交（事务回滚时租约一起回滚）
```

> **只描述租约表、不写这一步，互斥就是纸上的。** 同一 subject/app 上的离职 action 与
> reassign action 并发 execute 时，两边各锁各的 action 行，谁也不去 INSERT 租约，
> 于是两个 worker 都把请求发了出去。

**常量冻结，不由实现者自行选择**（否则同一故障下有的 worker 抢占、有的长期锁死）：

```python
LEASE_TTL: Final = timedelta(minutes=5)
LEASE_RENEW_INTERVAL: Final = LEASE_TTL / 3        # 续约周期不得超过 TTL/3
```

`lease_expires_at = now + LEASE_TTL`；worker 在长任务期间按 `LEASE_RENEW_INTERVAL`
**周期性续约**（CAS 更新 `lease_expires_at` / `renewed_at`）。
这两个常量进单元测试断言。

**fence 用取号器原子分配**：`UPDATE ... SET next_fence = next_fence + 1 RETURNING next_fence`。
不允许用「当前最大 fence + 1」这种读后写。

**所有与执行相关的写回都必须是 CAS**，条件固定为：

```sql
WHERE id = :lease_id AND owner = :me AND fence = :my_fence AND released_at IS NULL
```

影响行数不为 1 时，**该 worker 必须丢弃手上的响应并退出**，不得改写 batch 状态、
delivery 结果、action 状态或 summary。异步轮询回来的那条路径同样适用。

**过期租约的接管顺序是「先抢占，后查证」**（契约 §10.5.2）：

1. 在租约仍是 active 行的前提下，**先**取新 fence 并把 `owner` 改成自己 ——
   旧持有者从这一刻起所有 CAS 都会失败；
2. **再**用原 `(task_id, generation, batch_seq)` 与原 payload 向下游查证真实状态
   （下游幂等记录是权威）；
3. 查到终态才 CAS 释放租约；**查不到或下游不可达时续约并重试**，不释放也不永久卡住。

**抢占必须是一条条件 UPDATE，同时写四样东西**：新 `owner`、新 `fence`、`renewed_at`、
**以及 `lease_expires_at = now + LEASE_TTL`**。少写最后一项的话，新持有者刚接管就又是"已过期"，
下一个恢复者立刻再抢一次。

**"向下游查证"要有可执行的动作，不能只写四个字**。协议固定为：
**用原 canonical body 重放一次 execute**（三元组不变，因此下游必然走幂等分支）：

| 下游响应 | 判定 |
|---|---|
| 200 | 首次已成功。取其 summary 走 `complete_data_phase()`，然后释放租约 |
| 202 + `Location` | 仍在途。按 §7 的轮询继续 |
| 409 payload conflict | 同三元组不同 payload —— 说明有别的东西在乱写。**转人工告警**，租约保持 |
| 网络不可达 / 5xx | 续约后按退避重试，**不释放** |

顺序反过来（先查证再抢占）会留下一个窗口：查证那几秒里旧 worker 复活，
沿原路径把 action 写成 `done`，而 fence 还没抬，拦不住它。

#### 202 之后必须把租约**移交**给轮询 worker

`async_pending` 期间租约仍要持有（否则第二个 execute 会挤进来），
但**发起 execute 的那个 worker 已经退出了**，而轮询在 beat 的另一个进程里 ——
它的 `owner` 与原持有者不同，严格 CAS 下写回恒为 0 影响行数，
**异步 action 会永远卡在 `async_pending`**；绕过 CAS 又等于把防脏写的机制关掉。

因此规定一次**显式移交**：

1. execute worker 收到 202 时，用**自己当前的 owner/fence** 做 CAS，把租约的
   `owner` 改成 sentinel `async:{batch.pk}` 并**递增 fence**，随后自己退出；
2. 每次 poll 先从该 sentinel **原子 claim**（CAS 成 `poller:{worker_id}`，fence +1）；
3. 本次 poll 仍返回 202 → 续租并**移回 sentinel**（fence 再 +1）；
4. 返回终态 200 → 在**同一 fence** 下调 `complete_data_phase()`，然后释放租约；
5. 任何一步 claim / CAS 影响行数不为 1 → **丢弃本次响应并退出**，不写任何状态。

### 2.5 ~~`CustodyGrant`~~ / ~~`CustodyGrantItem`~~ —— **已取消**

代管授权在第二轮复核后整体废弃（契约 §7、`07-review-log.md` §1.1）。这两张表**不建**，
`HANDOVER_CUSTODY` scope **不加**，`grants/managed_users.py` **不改**。

`HandoverTask` 改为直接持有上交截止时间：

| 字段 | 类型 | 说明 |
|---|---|---|
| `escalation_deadline` | `DateTimeField(null=True, blank=True)` | 建单/上交时置为 `now + HANDOVER_ESCALATION_DAYS`；单终结后置空 |
| `last_reminded_on` | `DateField(null=True, blank=True)` | 每日提醒按**上海业务日**去重（`timezone.localdate(..., Asia/Shanghai)`） |
| `escalation_deferred_at` | `DateTimeField(null=True, blank=True)` | 超管在**当前** `escalation_level` 内顺延过一次的时间戳；每次上交时清空。非空即禁止再次顺延（§6.3） |

`HANDOVER_ESCALATION_DAYS: Final = 14`（原 `CUSTODY_TTL_DAYS` 作废）。
**这个常量是硬编码的 `Final`，不接受环境变量覆盖**（D5 冻结 14 天）；唯一的例外口子是
§6.3 的超管顺延，且每层级至多一次。

### 2.5.1 `HandoverGrantItem` 补 `generation`

升级会重新快照授权（契约 §8.3）。现有 `HandoverGrantItem` 没有 generation，
重新快照只能删旧行（毁审计）或追加不可区分的行（新旧混用）。

新增 `generation = PositiveIntegerField(default=1)`。

> **但现有模型上根本没有唯一约束**（`lifecycle/models.py:334-344`），
> 所以"唯一约束加入 generation"这句话没有可加的对象 —— 必须**新建**一条，并把唯一键写死。
> 不写死的话，三个实现者会分别挑 source grant / target / scope 当键，快照去重行为互不兼容；
> 也可能干脆不建，同一条授权被重复快照后转移两次。

```python
models.UniqueConstraint(
    fields=["task", "generation", "source_grant_id",
            "target_kind_snapshot", "target_key_snapshot", "scope_key"],
    name="lifecycle_grant_item_unique_per_generation",
)
```

迁移前先断言存量数据在该键上无重复（有重复说明现有快照逻辑已经出过问题，需要人工核对，不得自动去重）。

授权转授、勾选、审计一律按精确 `generation` 过滤，历史行只读保留。

### 2.7 `App` 交接能力声明（`applications/models.py:102`，修改，契约 §9）

| 字段 | 类型 | 说明 |
|---|---|---|
| `handover_capability` | `CharField(max_length=16, choices=..., default=HANDOVER_CAPABILITY_UNDECLARED)` | `declared` / `none` / `undeclared` |
| `handover_asset_types` | `JSONField(default=list, blank=True)` | descriptor 同步下来的资产类型声明 |
| `handover_capability_declared_by` | `CharField(max_length=128, blank=True)` | 声明 `none` 时的超管 actor |
| `handover_capability_declared_at` | `DateTimeField(null=True, blank=True)` | 同上 |
| `handover_capability_synced_at` | `DateTimeField(null=True, blank=True)` | descriptor 最近一次成功同步时间 |

约束：

```python
models.CheckConstraint(
    condition=(
        Q(handover_capability=HANDOVER_CAPABILITY_NONE,
          handover_capability_declared_by__gt="", handover_capability_declared_at__isnull=False)
        | ~Q(handover_capability=HANDOVER_CAPABILITY_NONE)
    ),
    name="applications_app_handover_none_requires_declaration",
),
```

即：声明「本 APP 无用户级数据」必须留下人和时间，不能是默认值飘进来的。

### 2.8 迁移

| App | 迁移 | 内容 |
|---|---|---|
| `applications` | `00XX_app_handover_capability.py` | §2.7 五字段 + 约束 |
| `access_requests` | `00XX_approval_routing_state.py` | §4.5.1 的 `approval_routing_state` / `routing_reason` 两字段 + 默认值 |
| `lifecycle` | `00XX_approval_rule_replacement.py` | §4.5.2 的 `ApprovalRuleReplacementRequired` 表 + 条件唯一约束 |
| `lifecycle` | `00XX_handover_v2_schema.py` | §2.1–§2.5.1 的全部 lifecycle 变更：**7 张新表**、`HandoverTask` 的 7 个新字段、`HandoverAppAction` 的全部新字段（含 `last_error_raw`）；**`to_user` 用 `RenameField` 改名为 `grant_receiver`**；只删除 `execution_to_user` / `policy` / `execution_policy`；§2.2 与 §2.4 的两个**约束触发器**用 `RunSQL` 建（含 reverse_sql） |

`lifecycle` 迁移必须是**一个**迁移文件完成改名、删列与建表，避免中间态。

> **`to_user` 绝不能删。** 它改名后就是 `grant_receiver`（§2.2），是
> `transfer_selected_grants(action)` 的唯一输入 —— 删掉它，授权转移这一步直接失去接收人。
> 早期版本在这里写「直接删列」，与 §2.2 的 `RenameField` 自相矛盾，
> 而**迁移章节才是实现者真正会照抄的那一份**。
>
> 另外三个字段（`execution_to_user` / `policy` / `execution_policy`）确实是删除：
> 数据接收人已下沉到条目级，`policy.unowned_strategy` 被三值 `action` 取代。
> 存量数据不做转换（未上线）。

---

## 3. assignee 解析（`lifecycle/assignee.py`，新建）

```python
@dataclass(frozen=True, slots=True)
class AssigneeResolution:
    user: UserMirror | None
    state: str                  # ASSIGNEE_STATE_*
    level: int
    degraded: bool              # True 表示目录数据不可用而落池

def resolve_assignee(subject: UserMirror, *, start_level: int = 0) -> AssigneeResolution: ...
```

实现要点：

1. 读 `DingTalkUserOrgContext`（`accounts/models.py:219`）取 `manager_chain`（自下而上）。
2. `manager_chain` 为空 **或** `stale=True` → 返回 `(None, superuser_pool, 0, degraded=True)`，
   写审计 `handover_assignee_resolution_degraded`。
   **不 fail-closed**：离职单是自动建的，宁可落超管池也不能丢单（契约 §8.2 已说明与权限查询取舍相反的理由）。
3. 从 `start_level` 起遍历。**`manager_chain` 的每一项是映射，取 `entry["user_id"]`**；
   不是映射或取不到就写审计 `handover_assignee_chain_entry_malformed` 后跳过该项（不静默）。
   **查询必须同时限定三个字段**：

   ```python
   UserMirror.objects.filter(
       dingtalk_source_slug=subject.dingtalk_source_slug,
       dingtalk_corp_id=subject.dingtalk_corp_id,
       dingtalk_userid=manager_userid,
   ).first()
   ```

   > 钉钉 userid **只在 `(source_slug, corp_id)` 内唯一**（`accounts/models.py:61-67`）。
   > 只按 userid 查，两个企业都有 `manager01` 时会拿到另一家企业的人 ——
   > 交接单被交给一个和当事人毫无管辖关系的人。

   跳过：
   - 不存在的
   - `status != active` 的
   - `authentik_user_id` 以 `LOCAL_ADMIN_SUBJECT_PREFIX` 开头的（`accounts/local_admin.py`，break-glass 账号不参与生命周期）
   - 就是 subject 本人的
4. 找到即返回 `(user, manager, level, degraded=False)`；走完返回 `(None, superuser_pool, len(chain), False)`。
5. **不设层数上限**（D3）。

`apply_assignee(task, resolution, *, actor_id)`：写字段 + 审计 `handover_assignee_assigned` + 触发通知。

---

## 4. 超时上交（`lifecycle/escalation.py`，新建）

代管废弃后，本章只剩一件事：**单子放太久就往上交**，不涉及任何授权。

```python
def escalate_overdue_task(task: HandoverTask) -> HandoverTask:
    """上交一级; 主管链到顶则落超管池。"""
```

同事务内：

1. `select_for_update` 锁 task，复检仍 open（避免与 `cancel_task` / `refresh_task_status` 竞态）。
2. **起始层级要分情况**：

   ```python
   start = 0 if task.assignee_state == ASSIGNEE_STATE_SUBJECT else task.escalation_level + 1
   res = resolve_assignee(task.subject_user, start_level=start)
   ```

   > **固定写 `escalation_level + 1` 会跳过直属主管。** 本人自助发起的 `pre_offboard` 单
   > `assignee_state=subject`、`escalation_level=0`（那个 0 指的是"本人"，不是"主管链第 0 级"）。
   > 首次超时若从 `start_level=1` 找，`manager_chain[0]`（直属主管）被整个跳过，
   > 单子直接飞到隔级主管手里 —— 而直属主管才是最该先看到它的人。
3. `res.user` 非空 → `apply_assignee(task, res)`；否则 `assignee=None`、
   `assignee_state=superuser_pool`、`escalation_level=res.level`。
4. `escalation_deadline = now + HANDOVER_ESCALATION_DAYS`（落超管池时置空——超管池只做每日认领提醒，
   不再继续上交）。
5. 审计 `handover_task_escalated`。
6. 通知（走 outbox，出事务）：新旧 assignee 双方；落超管池则通知全体超管。

> **超管收件人的现实问题**：超管资格目前只在请求期通过 Authentik 组交集判定
> （`admin_console/authz.py`），**没有可枚举的本地超管名单**，"通知全体超管"当前无法实现。
> 本期的落地方式：落超管池时**不发个人通知**，改为在控制台顶部常驻「N 张交接单待认领」告警条
> （复用 §6.3 的 `handover-blocked-apps` 同款机制）。
> 建立权威超管收件人镜像列为独立后续项。

## 4.5 审批责任改派（契约 §11.1，`lifecycle/approvals.py` 新建）

离职建单同事务内执行，**与业务数据交接无关，不走 webhook**。

### 4.5.1 EasyAuth 自身的权限申请（必做）

`AccessRequestApprover.approver` 外键指向 `UserMirror`（`access_requests/models.py:339`），
可以直接改派：

**范围严格限定为 `AccessRequest.status == "submitted"`**（既有 `reassign_access_request()`
只接受这一种状态，`access_requests/approvals.py:177,185`）。`approved` / `grant_failed` 等
已决状态**不改写** —— 那是已完成的审批历史，改它等于伪造。

> **⚠ `reassign_access_request()` 是「整体替换」，不是「替换其中一个」。**
> 它先 `AccessRequestApprover.objects.filter(access_request=...).delete()` 删掉**全部**审批人，
> 再按传入的列表重建（`access_requests/approvals.py:193-201`）。
> 原审批人是 `[离职主管, 财务]` 时，若只传 `[新主管]`，**财务的审批责任被静默取消**。
>
> 因此必须先读全集再算差集：
>
> ```python
> previous = access_request_approver_user_ids(access_request)      # 既有 helper
> desired  = [u for u in previous if u != subject.authentik_user_id]
> if new_approver and new_approver.authentik_user_id not in desired:
>     desired.append(new_approver.authentik_user_id)               # 稳定去重, 保序
> if desired:
>     reassign_access_request(..., approver_user_ids=desired)      # 传完整集合
> else:
>     进入 approval_routing_state="superuser_pool"
> ```

```
对所有 status == "submitted" 的 AccessRequest, 其 approver 是 subject 的 AccessRequestApprover 行:
    new_approver = resolve_assignee(该申请的申请人, start_level=0).user   # 沿申请人自己的主管链
    if new_approver is None or new_approver == 申请人:
        → 删除离职者那条审批人行, 保持 status="submitted" 不变,
          并把该 AccessRequest 的 approval_routing_state 置为 "superuser_pool"
          (新增字段, 见下), 写 routing_reason
        → 绝不静默留在离职者名下, 也绝不把 status 改成任何终态
    else:
        approver = new_approver
        审计 handover_approver_reassigned
        通知申请人与新审批人
```

> **「进超管待办」不是一个已存在的状态，必须先把它造出来。**
> `AccessRequest` 现有的 status 集合里没有"待超管认领"这一档
> （`access_requests/models.py:33-59`），`AccessRequestApprover` 也只是一张审批人关联表。
> 不新增载体的话，实现者只能二选一：把离职者留在审批人位上（申请永远卡死），
> 或者自造一个互不兼容的队列。
>
> 新增两个字段到 `AccessRequest`：
>
> | 字段 | 类型 | 说明 |
> |---|---|---|
> | `approval_routing_state` | `CharField(max_length=16, default="normal")` | `normal` \| `superuser_pool` |
> | `routing_reason` | `CharField(max_length=64, blank=True)` | `no_active_manager` \| `chain_exhausted` |
>
> `status` **保持 `submitted` 不变** —— 申请本身仍在审批中，只是暂时没有指定审批人。
> 控制台按 `approval_routing_state="superuser_pool"` 查询待认领列表，
> 超管认领时**必须写入至少一名 active 审批人**并把状态改回 `normal`。

注意审批人要沿**申请人**的主管链解析，不是离职者的 —— 审批权来自"谁管这个申请人"。
唯一约束 `(access_request, approver)` 已存在（`:351`），改派后若与既有审批人重复则删除该行而非报错。
**必须调用既有的 `reassign_access_request()`，不得直接 UPDATE 审批行** —— 直接改会绕过它的
状态校验与审计写入。

### 4.5.2 钉钉审批规则的审批人替换（必做）

`ApprovalRule.approver_userids` 是 JSON 列表（`applications/models.py:717`）。

> **⚠ 这个列表里存的是 `UserMirror.authentik_user_id`，不是钉钉 userid。**
> 运行时解析器 `_ApproverResolver.resolve()` 把每一项拿去查
> `_user_id_by_authentik_user_id`（`portal/request_catalog.py:576-583`）；
> 只有 `resolve_direct_manager()` 那条独立路径才用 dtuid。
>
> 早期版本写「替换其中的离职者 dingtalk userid」，照做的话**根本匹配不到任何一项**：
> 替换静默不发生，规则里仍挂着离职者，新申请依然解析不到有效审批人 ——
> 而且不会有任何报错。
>
> 正确做法：把列表里等于 `subject.authentik_user_id` 的项替换为新主管的
> `authentik_user_id`。**钉钉 userid 只在最终调用钉钉接口时使用，绝不写进这一列。**

- 审计 `handover_approval_rule_approver_replaced`
- 这只影响**新发起**的审批
- 替换后列表为空 → **保持规则原样不动**，并写一条持久化待办（见下）

> **「快速失败并进超管待办」这两件事不能放在同一个事务里同时做。**
> 抛异常会让建单与待办一起回滚，什么都不剩；不抛又可能把空列表写进库
> （`approval_rule_rules.py:49` 要求非空，但那是 `full_clean()` 路径，直接 `save()` 绕得过去）。
>
> 裁定：解析不到替代审批人时，**规则不动**，另写一条待办事实：
>
> ```python
> class ApprovalRuleReplacementRequired(models.Model):
>     approval_rule = FK(ApprovalRule, on_delete=CASCADE)
>     task          = FK(HandoverTask, on_delete=SET_NULL, null=True)   # 单可删, 待办不能跟着没
>     task_id_snapshot = PositiveIntegerField()                          # 不可变, 溯源用
>     departed_user = FK(UserMirror, on_delete=PROTECT)
>     reason        = CharField(max_length=64)     # no_active_manager | chain_exhausted
>     resolved_at   = DateTimeField(null=True, blank=True)
>     resolved_by   = CharField(max_length=128, blank=True)
>
>     class Meta:
>         constraints = [UniqueConstraint(
>             fields=["approval_rule", "departed_user"],
>             condition=Q(resolved_at__isnull=True),
>             name="lifecycle_approval_rule_replacement_open_unique")]
> ```
>
> 控制台按 `resolved_at IS NULL` 查询并提供解决入口
> （`POST /console/api/v1/lifecycle/approval-rule-replacements/{id}/resolve`，body 带新审批人）。
> 这样"需要人处理"是**库里的一行**，不是一个抛掉就没了的异常。

### 4.5.3 在途钉钉审批实例（本期做不了，必须显式呈现）

`ApprovalInstance` 不存当前审批人，`integrations/dingtalk/api_client.py` 也没有转办接口。
本期的处理是**把问题显式暴露出来**，而不是假装不存在：

> **但"逐条精确清单"这个承诺本身也做不到，不要许下它。**
> `ApprovalInstance` 只有 `app` / `template` / `biz_key` / `originator_user` /
> `dingtalk_process_instance_id` / `status`（`workflows/models.py:147-183`）——
> **它与 `ApprovalRule` 之间没有任何关联字段**，也不存当前审批人。
> 按 APP 粗匹配出来的清单会同时漏报和误报，给出的条数 N 是个**假数字**。
> 报一个假的精确数，比报"不确定"更糟。

因此本期只做**存在性提示**：

- 建单时判定：**该 APP 存在 `status` 未终结的 `ApprovalInstance`** → 在交接单上显示警示区块：
  「本应用存在未终结的钉钉审批，无法确认其中是否有由 {离职者} 审批的条目，请到钉钉中检查并人工转办。」
  附该 APP 的钉钉审批入口链接；
- **判定条件里不要加「离职者在 `ApprovalRule.approver_userids` 里」**：钉钉审批模板可以把他配成
  审批人而本地权限规则里根本没有他，那样会**漏报**；而本地有他、钉钉实例却与他无关又会**误报**。
  两边都不准，索性只报"无法确认"；
- **不列逐条实例，不给条数**；
- **必须持久化，不能每次实时推断**：建单时把 `{message, link, recorded_at}` 写进 action
  （§6.2 的 `approval_instance_warning` 字段）。实时推断的话，实例一终结或规则一替换提示就消失了，
  与"完成后仍然保留"的要求直接冲突；
- 这些条目**不计入** action 的完成判定（它们不是 APP 资产）；
- 升级与完成都**不清除**该提示。

**解除这个降级的前置条件**（写进缺口清单）：先给 `ApprovalInstance` 持久化
`current_approver_userids`（由钉钉回调或轮询维护），或确认钉钉开放平台提供可查询当前审批人的接口。
在那之前，任何"精确清单 + 条数"的实现都是编造。

## 5. 交接执行改造（`lifecycle/handover.py`）

### 5.1 建 action 时的能力判定（契约 §9.1）

`_snapshot_app_actions()` 中，对每个 App：

| `App.handover_capability` | action 初始 status | 附加 |
|---|---|---|
| `declared` | `pending` | 按 `handover_asset_types` 预建 `HandoverAssetType` 占位（count 待 preview 填） |
| `none` | `skipped` | `skip_reason = "运营已声明本应用无用户级数据"`，`skipped_by = 声明人` |
| `undeclared` | **`blocked`** | `blocked_reason = "capability_undeclared"` |

删除 `_handover_hook_url()` 返回空串即静默成功的分支（`handover.py:590`）与
`HOOK_NOT_DECLARED_RESULT`（`handover.py:122,325`）—— 这是契约 §1.1 第 1 条要修的正确性缺陷。
`declared` 但 `AppWebhookConfig.handover_url` 为空 ⇒ **数据不一致**，直接抛
`HandoverError("declared 能力与 webhook 配置不一致")`，快速失败，不兜底。

### 5.1.1 capability 恢复（契约 §9.1.1）

`sync_handover_capability()` 把某 App 从 `undeclared` 改为 `declared` 成功后，必须在同事务内
reconcile 该 App 下所有 `blocked` 且所属 task 仍 open 的 action：
置 `pending`、清 `blocked_reason`、`generation` 对齐 `task.generation`、
写审计 `handover_action_unblocked`、`refresh_task_status(task)`，随后给这些单的 assignee 发通知。

反方向（`declared → undeclared`，通常是 descriptor 拉不到）**不得**把运行中的 action 打回 `blocked`，
只写告警。初始状态只在建单时判定。

### 5.1.2 升级时的字段重置（契约 §8.3，**遗漏会直接造成数据不一致**）

`pre_offboard → offboard` 升级会 `task.generation += 1` 并重新盘点。
`HandoverAppAction` 上有一批**按轮次**的字段，不逐个重置就会用上一轮的中间态污染这一轮：

| 字段 | 升级时 | 不重置的后果 |
|---|---|---|
| `generation` | ← `task.generation` | 新一轮的 preview/execute 带着旧轮次号发出去，下游按 §10.5.2 判为「迟到的旧 generation」直接 409 |
| `data_completed_at` | → `NULL` | **最严重的一条**：非空会让 execute 走「数据已落地，只补转授权」的续跑分支，**这两周新产生的数据一条都不会搬**，而单据显示 `done` |
| `snapshot_token` | → `""` | 拿上一轮的 token 去 execute，下游校验必然 409，整轮卡死 |
| `batch_seq` | → `0` | 批次号从旧值续接，与新 generation 组合出的幂等键仍然唯一，倒不会错乱，但审计上批次号不连续、难排查 |
| `last_error` / `last_error_raw` | → `""` | 新一轮界面上挂着上一轮的错误文案 |
| `async_status_url` / `async_poll_attempts` | → `""` / `0` | 上一轮轮了 10 次（`ASYNC_POLL_MAX_ATTEMPTS`，`lifecycle/core.py:30`）已经触顶；不清零的话新一轮第一次 202 就直接判失败 |
| `skipped_at` / `skipped_by` / `skip_reason` | → 空 | 与下方「强行跳过不继承」一致 |
| `confirm_version` / `overrides_version` | **各 +1**（不是清零） | 主动击穿上一轮浏览器里缓存的版本号：还开着旧页面的人点执行会拿到 409，而不是把上一轮的选择写进新一轮 |
| `status` / `blocked_reason` | **按 §5.1 重新判定**，不是无脑置 `pending` | 见下 |
| `skip_reason` / `skipped_by` | → `""` | 见下 |

**`status` 必须按当前 capability 重新判定，超管的强行跳过不继承。**
上一轮被超管 `skipped` 的 APP，如果至今仍未接入，这一轮要重新回到 `blocked`、由超管重新填理由跳过。
理由：那次跳过是对**第一轮数据**做的判断，而升级的全部意义就是「这两周又产生了新数据」。
让它自动继承，等于用一次两周前的判断永久豁免掉这个 APP —— 正是 D6 要消灭的「静默当作没数据」。
旧一轮的 `skip_reason` 与审计事件保留在 `AuditLog` 里，历史不丢。

**旧一轮的 `HandoverAssetType` / `HandoverAssetOverride` 行不删除**（它们带 `generation`，天然隔离），
新一轮 preview 时按新 `(action, generation)` 重建；`HandoverGrantItem` 同理（§2.5.1）。

**升级前必须确认没有在途执行**：存在未释放的 `HandoverExecutionLease` 时，升级操作返回
`409 handover_execution_in_flight`，**不得**强解租约后升级 —— 那会让一个正在下游执行的批次
带着已经作废的 generation 回写。

### 5.2 descriptor 同步

新增 `applications/handover_capability.py`：

```python
def sync_handover_capability(app: App) -> None: ...
```

> **建 action 时必须校验 `task_id` 的形态。** 它由 `f"{task.id}:{app.app_key}"` 生成，
> 而 `App.app_key` 的列宽足以让结果超过契约 §5.4 的 **64 字节**上限（一个 64 字符的合法 app_key
> 配上 task id `1` 就已经 66 字节）。
> 规则：生成后必须匹配 `^[A-Za-z0-9:_-]{1,64}$`，否则**整次建单回滚**并写持久告警 + 审计。
> 拖到发 webhook 时才发现的话，下游会拒绝或落不进幂等记录，离职 action 直接卡死。

- 拉取 `/.well-known/easyauth-app.json`，解析 **`lifecycle.capabilities` 与 `lifecycle.handover_asset_types`**
  （契约 §9.1 —— descriptor **没有**嵌套的 `lifecycle.handover` 对象，那是被废弃的早期形状，
  会被 EasyTrade 的 `_lifecycle()` 校验器直接剥掉）。
- 判定三态，与契约 §9.1 的表逐行对应：

  | 判定条件 | `handover_capability` |
  |---|---|
  | `"handover.v2" in lifecycle.capabilities` 且 `lifecycle.handover_url` 非空 | `declared` |
  | `"handover.none" in lifecycle.capabilities` 且 `handover_asset_types == []` | `none` |
  | 其余（含两个能力串同时出现、含拉取失败） | `undeclared` |

  两个能力串同时出现是 APP 的声明错误，按 `undeclared` 处理并写告警
  `handover_capability_conflict`，**不得**任选其一（那是静默兜底）。
- `declared` → 写 `handover_capability=declared`、`handover_asset_types`（取自
  `lifecycle.handover_asset_types`，逐项含 `type`/`label`/`detail_supported`/`releasable`）、
  `handover_capability_synced_at`；同步 `AppWebhookConfig.handover_url`。
- 拉取失败或 `capabilities` 里两个能力串都没有 → **不覆盖**已有的 `none` 声明；否则置 `undeclared`，
  action 建单时即 `blocked`（`blocked_reason="descriptor_unreachable"`）。
- 挂到既有 manifest 同步入口（`api/manifest_sync_views.py`）与控制台"重新同步"按钮。

> **⚠ EasyAuth 自己的解析模型会先把这个新字段扔掉。**
> `applications/permission_template_parsing.py` 的 `_LifecyclePayload` 是
> `ConfigDict(extra="forbid", frozen=True)`，字段只有
> `handover_url` / `onboard_url` / `capabilities`（`:116-124`）——
> 下游带着 `handover_asset_types` 推 manifest 上来，**这一层直接抛校验错误**。
>
> 所以「两道白名单」其实是**三道**（契约 §9.1 列了下游的两道，这是 EasyAuth 自己的第三道）：
> `_LifecyclePayload` 与 `permission_template_types.py` 的 `AppManifestLifecycleInput`
> 都必须显式加上 `handover_asset_types` 的 DTO（`tuple[_HandoverAssetTypePayload, ...]`，
> 逐项含 `type` / `label` / `detail_supported` / `releasable`）。
>
> **另外，`sync_handover_capability(app)` 这个签名是拉取式的，但它没有 base_url 也没有凭证** ——
> 光有一个 `App` 对象拉不到 descriptor。改为**在既有的 manifest push 事务内**调用：
>
> ```python
> def sync_handover_capability_from_manifest(
>     app: App, lifecycle: AppManifestLifecycleInput, *, actor_id: str
> ) -> None: ...
> ```
>
> 控制台的"重新同步"按钮走既有的 manifest 重新拉取路径（那条路径本来就有 base_url 与凭证），
> 不另造一条。

### 5.3 preview（契约 §10.3）

```python
def preview_action(action) -> HandoverAppAction
```

- payload 加 `generation`。
- 响应校验：每个 `type` 必须在 `App.handover_asset_types` 中声明过，否则 action → `failed`，
  `last_error="undeclared_asset_type: {type}"`。
- 用响应**重建**该 `(action, generation)` 下的 `HandoverAssetType` 行（`count`/`label_snapshot`），
  保留已存在行的 `default_action` / `default_to_user` 与其 `overrides`（重新 preview 不应清空人已做的选择）。
  但若某个 override 的 `asset_id` 在新一轮明细里已不存在（数据被删或已终结），该 override 行必须删除并计数，
  在响应里回报给前端提示「N 条单独指定已失效」——不得静默保留、到 execute 时打空。
- 响应中**缺失**任何已声明类型 → action 直接 `failed`，`last_error` 写明缺了哪些类型。
  **不得补零继续**（契约 §10.3）—— 补零是把下游契约违约伪装成"这一类真的没数据"。

### 5.4 execute 前置校验（契约 §10.5 语义 5）

`validate_assignments(action)` 在发请求前跑，任一不通过即 `422`，**不发 webhook**：

| 校验 | 错误码 |
|---|---|
| 任一 `action="release"` 落在 `releasable=False` 的类型上（默认或 override） | `asset_type_not_releasable` |
| `action="transfer"` 但接收人为空 | `receiver_required` |
| 任一接收人 `status != active` | `receiver_not_active` |
| 任一接收人 == `task.subject_user` | `receiver_is_subject` |
| ~~全部类型 skip~~ | **删除该校验**。全 skip 是合法的 no-op（契约把 `skip` 定义为正当动作），零资产 APP 也要靠它确认完成。改为：允许执行并返回全零 summary |
| 同一 `asset_type` 出现多次，或同一 `asset_id` 在 override 中重复 | `duplicate_assignment` |

**库层与 API 层各挡一部分，但覆盖面不一样，不要以为库约束已经全包了**：

| 不变量 | 库层落法 |
|---|---|
| `action ∈ {transfer, release, skip}` | 普通 `CheckConstraint`，`HandoverAssetType` 与 `HandoverAssetOverride` 各加一条 |
| `default_action == "transfer"` ⇒ `default_to_user` 非空 | 普通 `CheckConstraint`（同表两列） |
| `default_action == "release"` ⇒ `releasable = true` | 普通 `CheckConstraint`（`releasable` 与 `default_action` 同在 `HandoverAssetType` 上） |
| **override 的 `action == "release"` ⇒ 父类型 `releasable = true`** | **跨表，普通 CHECK 做不到**（`releasable` 在父表 `HandoverAssetType` 上）。**统一用 PostgreSQL `CONSTRAINT TRIGGER ... DEFERRABLE INITIALLY DEFERRED`**，不加 `releasable_snapshot` 冗余列 —— 冗余列要在每次 preview 重建行时同步刷新，多一条必然会漏的同步路径 |
| `grant_receiver` 仅 `offboard` | 跨表，同上（§2.2 已说明） |

早期版本写的"前两条均已被 CheckConstraint 挡在库层"是不准确的：
跨表的两条挡不住，绕过 API 直接写库就能造出非法组合，进而生成非法 webhook。
API 层的 `validate_assignments()` 仍然要有 —— 库约束保证数据不脏，API 校验保证用户拿到可读的错误。

### 5.5 execute（契约 §10.5）

- 组 payload：`assignments` 由该 `(action, generation)` 下的**全部** `HandoverAssetType`
  （含 `default_action=skip` 的）与其 `overrides` 生成，形状严格照契约 §10.5。
- **发出前必须校验 `batch.generation == action.generation == task.generation`**（`generation` 在
  `HandoverExecutionBatch` 上，**不在 delivery attempt 上**）。outbox 参数携带 **batch 主键**，
  worker 取出后加载 batch → action → task 再比对；不等则把该 delivery 标 `superseded` 并写审计，
  **不发网**。outbox 里的旧记录被 worker 延迟取出时会用当前时间重新签名，
  重放窗口拦不住；下游虽然也有「迟到的旧 generation 一律 409」的兜底（契约 §10.5.2），
  但发送方不该指望接收方兜底。
- 在事务内分配 `batch_seq`、写入 `HandoverExecutionBatch`（`status="pending"`）与首条
  `HandoverDeliveryAttempt`（`outcome="sent"`，含 canonical payload 与其 sha256）、写 outbox，
  **提交后**才由 worker 真正发请求（§2.4.1）。
- 顺序按契约 §10.5.1.1：**先数据 webhook，成功后置 `data_completed_at`，再幂等转授权限**。
  `transfer_selected_grants()` 的调用点必须从当前位置（`handover.py:182`，在 webhook 之前）
  **移到 webhook 成功之后**。这是修既有缺陷，不是新增功能。

#### 同步 200 与异步 202 必须汇合到同一个收尾函数

```python
def complete_data_phase(batch: HandoverExecutionBatch) -> None:
    # 事务 A(CAS 保护): batch.status="data_completed" + batch.data_completed_at
    #                  若 batch.is_final: 同时写 action.data_completed_at   ← 必须在这里
    # 提交 A
    # 事务 B: 幂等转授权限(仅 is_final 且 kind == offboard)
    # 事务 C: action.status = done + refresh_task_status_locked
    ...
```

> **`action.data_completed_at` 必须在授权事务之前提交。** 顺序写反了会这样：
> 最终批的数据 webhook 返回 200，只写了 batch 上的 marker；授权事务失败；
> 此时 action 上的 marker 还是 NULL —— **retry 会重新发一次数据 webhook**，
> 而不是只补做授权。数据已经搬过一次了。
>
> retry 的判定也随之写死：**先读最终批的 marker**，非空就**不创建新的 delivery、不写 outbox**，
> 只跑那个幂等的授权事务。

- 同步 200 走它；**异步 `poll_async_action()` 拿到最终 200 也必须走它**。
- **禁止 `async_pending → done` 直接跳转。** 现有 `poll_async_action()`（`handover.py:261`）
  正是直接置 `done` 的：那条路径既不会落 `data_completed_at`，也**根本不会转授权限** ——
  离职者的授权原地不动，而单据显示已完成。这是必须改掉的既有缺陷，不是新增功能。

#### 授权转移这一步必须在**一个事务**里完成

「幂等」不等于「原子」。现有实现里 grant 的变更与 `HandoverGrantItem.status` 的落库
不在同一事务（`lifecycle/transfer.py:207,261,268`）；grant 已提交而 item 状态未落库时崩溃，
重试会再次把该 item 当 pending 处理，**重复变更 grant 并再次递增 version**。

规定：同一事务内锁 action → 锁该 `(action, generation)` 下的全部 `HandoverGrantItem` →
锁目标 grant → 变更 grant 与 item 转 `done` **一起提交**。
没有 pending item 时直接成功返回，**不得再次递增 grant version**。

#### 三种 kind 的授权处理互不相同，不要用一个常量糊过去

| kind | 授权处理 |
|---|---|
| `offboard` | 走 `transfer_selected_grants(action)`，把快照授权转给 `grant_receiver` |
| `transfer`（转岗） | **不走这条路**。走既有的 `TransferPlan` 差异确认（`lifecycle/transfer.py`），按新岗位重算 |
| `pre_offboard` / `reassign` | **一动不动**（D7 / D9） |

> **`GRANT_MUTATING_KINDS = (OFFBOARD, TRANSFER)` 不能用在 action 执行路径上。**
> 它表达的是"这两种单会动权限"，而 action 执行路径要问的是"要不要调
> `transfer_selected_grants`" —— 答案只有 `offboard`。
> 拿前者当后者用，转岗单会**同时**走接收人转授和 TransferPlan 差异，授权被改两遍。
>
> 执行路径用独立常量：`ACTION_GRANT_TRANSFER_KINDS: Final = (HANDOVER_KIND_OFFBOARD,)`。

- 全部成功后：`action.status = done` → `refresh_task_status(task)`。

### 5.5.1 必须**删掉**既有的 `attempts` 禁令（否则单据死锁）

现有 `skip_action` 在 `action.attempts` 非零时拒绝（`handover.py:357,364`），
`cancel_task` 在任一 action `attempts > 0` 时拒绝（`:442,446`）。
而 401 / 403 / 413 / 422 按契约 §10.6 是**不可重试的 `failed`**，且此时 `attempts` 必然非零
—— 这张单于是**既不能跳过也不能取消**，永久死锁。

改法（契约 §6.2 已冻结）：

- **删除**两处的 `attempts` 判断；
- 改为只禁止对**真正在途**的批次操作：存在 `status ∈ {executing, async_pending}` 的
  `HandoverExecutionBatch`，或存在未释放的 `HandoverExecutionLease`；
- `failed` 状态**必须**允许超管填 reason 后转 `skipped`（写 `skip_reason` / `skipped_by` / 审计）；
- 整单**必须**允许 `cancelled`。

### 5.6 items（契约 §10.4，新增）

```python
def fetch_action_items(action, *, asset_type: str, page: int, page_size: int, q: str) -> dict
```

- 仅当该类型 `detail_supported=True` 才允许调用，否则 `400 detail_not_supported`。
- **透传不落库**（明细可能上千条，落库无意义且会过期）；前端翻页即实时回源。
- **`stale` 只在 `q` 为空串时才判**：`q` 非空时 `total` 是过滤后的数量（契约 §10.4），
  与 `HandoverAssetType.count` 本来就不该相等。
  拿过滤后的 `total` 去比全量 `count`，会让一次正常搜索（187 个客户里搜"华东"命中 2 条）
  被判成 `stale=true`，前端不停要求重新预演，搜索功能直接不可用。
- 判定式：
  - `q == ""` 且 `total != count` → `stale=true`；
  - `q != ""` 且下游返回了可选的 `unfiltered_total` 且它 `!= count` → `stale=true`；
  - 其余一律 `stale=false`。
- `stale=true` **不报错**，只在响应里带标记，前端提示"清单已变化，建议重新预演"。

---

## 6. HTTP API 契约（**前端 agent 的依赖，冻结**）

### 6.1 门户（自助，`/portal/api/v1/`，D1）

认证：既有门户会话（OIDC 登录的 active `UserMirror`），**不需要超管**。
授权：见每行的「可访问条件」。越权一律 `404`（与既有门户一致，防枚举）。

> **门户必须显式拒绝本地管理员。** break-glass 本地超管会生成 active 的
> `local-admin:` 前缀 `UserMirror`（`accounts/local_admin.py`），现有门户 guard 只检查
> "有 session 且用户 active"，因此本地超管**可以冒充员工调用全部自助 API**。
> 门户入口必须加一条：`authentik_user_id` 以 `LOCAL_ADMIN_SUBJECT_PREFIX` 开头 → 403。
> 这与既有的"本地管理员不参与生命周期"（`lifecycle/offboarding.py:_assert_lifecycle_subject`）一致。
>
> **门户与控制台必须各自注册路由与 guard**，只共享 domain service。
> 早期写的"控制台复用门户端点"会让两套身份判定混在一个入口上。

| 方法 | 路径 | 可访问条件 | 说明 |
|---|---|---|---|
| GET | `/me/handover-tasks` | 登录即可 | 返回两组：`as_assignee`（我负责的）、`as_subject`（我是当事人的） |
| POST | `/handover-tasks/pre-offboard` | 登录即可，且自己无 open 的 offboard/transfer/pre_offboard 单 | 在职提前交接建单（D7），`kind=pre_offboard`，assignee=本人 |
| POST | `/handover-tasks/reassign` | 我对 `subject` 有管辖权（契约 §4 的主管链判定，**不走 `resolve_managed_users`**）且双方 active。**必带 `Idempotency-Key` 头**（≤128 字符）| 在职移交（D9）。body：`{"subject_user_id": "<OIDC sub>", "app_keys": ["easytrade", ...], "reason": "至少 10 字"}`。**`app_keys` 必填且非空** —— 只为列出的 APP 建 action，**不得**隐式把该员工在其他 APP 的数据也拉进来（`00` §8.4 明说同一 subject 可以有多张针对不同 APP 的 open `reassign` 单）。缺 `subject_user_id` / `app_keys` → `422`；`reason` 不足 10 字 → `422 reason_required` |
| GET | `/handover-tasks/{task_id}` | 我是 assignee 或 subject | 单据详情，含各 APP action、资产分类、距上交剩余天数 |
| GET | `/handover-tasks/{task_id}/actions/{app_key}/assets/{type}/items` | 同上 | 明细分页，query: `page`、`page_size`、`q` |
| GET | `/handover-tasks/{task_id}/actions/{app_key}/assets/{type}/overrides` | 同上 | **返回当前 generation 的完整 override 集合**与 `overrides_version`。`PUT` 是整体替换，没有这个读回入口，用户刷新页面后改一条就会把其余全部删掉 |
| PATCH | `/handover-tasks/{task_id}/actions/{app_key}/assets/{type}` | 我是 assignee | body: `{"default_action": "transfer"\|"release"\|"skip", "default_to_user_id": str\|null}` |
| PUT | `/handover-tasks/{task_id}/actions/{app_key}/assets/{type}/overrides` | 我是 assignee | body: `{"overrides_version": n, "overrides":[{"asset_id":"...","action":"transfer"\|"release"\|"skip","to_user_id":"..."\|null,"label":"..."}]}`，**整体替换**。`overrides_version` 必填，与服务端不一致返回 `409 overrides_version_stale` —— 整体替换 + 无版本号 = 后一次保存静默吃掉前一次的全部修改 |
| POST | `/handover-tasks/{task_id}/actions/{app_key}/preview` | 我是 assignee | |
| POST | `/handover-tasks/{task_id}/actions/{app_key}/execute` | 我是 assignee | body **必填** `{"confirm_version": n}` —— 用户点确认时界面上显示的那一版。与服务端当前值不一致 → `409 confirm_version_stale`，**不创建 batch**，要求刷新后重新确认 |
| POST | `/handover-tasks/{task_id}/actions/{app_key}/retry` | 我是 assignee | 仅 `failed` 可重试，否则 `409 action_not_retryable`。**若 `data_completed_at` 非空，重试只重做授权转移那一步**（契约 §10.5.1.1），不重发数据 webhook |
| GET | `/handover-candidates` | 登录即可 | 选人控件数据源。query：`q`（模糊，可空）、`purpose`（枚举 `receiver` \| `reassign_subject`，**必填**）。两者都只返回 active 且非本人；`purpose=reassign_subject` 时额外限定在我的 `MANAGED_USERS` 内。**不设默认值** —— 缺 `purpose` 返回 `422 purpose_required`，否则前端漏传就会静默拿到范围过宽的人员列表 |

> **`confirm_version`：浏览器必须把"我确认的是哪一版"带回来。**
> `snapshot_token` 是 EasyAuth 与下游之间的凭据，**替代不了这件事** ——
> 它存在服务端 action 上，谁重新 preview 谁就把它覆盖成最新的。
>
> 两个故障场景，只挡住一个是不够的：
>
> | 场景 | 后果 |
> |---|---|
> | A 预演看到 187 条正在勾选，B 重新预演（服务端 token 变成对应 191 条的新值），A 点执行 | 191 条全部被搬走，其中 4 条 A 从没见过 |
> | A 打开确认框，B **没有重新预演**，只是把某类的默认接收人从张某某改成李某某 | A 点执行，后端按数据库里**最新的** assignments 执行 —— 数据转给了 A 从没确认过的人 |
>
> 第二种是只做"preview 版本号"挡不住的：preview 没变，版本号也就没变。
> 所以 `confirm_version` 的递增条件是**四件事**（见 §2.2 的字段说明）：
> preview 成功、改类型级默认、整体替换 overrides、改 `grant_receiver`。
> **任何会改变"执行下去会发生什么"的操作都要让它 +1。**
>
> 详情响应返回它，execute 必须回带；不一致 → `409 confirm_version_stale`，**且不创建任何 batch**。
> **下游的 `snapshot_token` 仍然只存在后端，前端不碰。**

> **`snapshot_token` 不出现在门户 API 里，前端一个字节都不用碰。** 它由 EasyAuth 在
> preview 响应中取回并存进 `HandoverAppAction.snapshot_token`（§2.2），
> items / execute 发 webhook 时由后端自动回带（契约 §10.5.1）。
> 前端只需要知道：execute 返回 `409 snapshot_stale` 时，要引导用户重新 preview。

> **两个创建端点都必须支持 `Idempotency-Key`。** `00` §8.4 允许同一 subject 有多张 open 的
> `reassign` 单，所以数据库层没有唯一约束能挡住重复创建 —— 201 响应在网络上丢一次、
> 浏览器重试一次，就是两张一模一样的单，而且都能被执行。
> 服务端按 `(initiator, idempotency_key)` 存 canonical body 的 hash：
> 同 key 同 body → 返回原单；同 key 不同 body → `409 idempotency_conflict`。
> 并发双写靠该组合上的数据库唯一约束兜底。

**成功响应（与错误码同等冻结，前端据此建类型）**：

| 端点 | 成功码 | 响应体 |
|---|---|---|
| `GET /me/handover-tasks` | 200 | `{"handover_tasks": {"as_assignee": [<列表项>], "as_subject": [<列表项>]}}`（与详情同样带信封）。列表项 = §6.2 的详情对象去掉 `actions`/`team_items`，另加 `pending_app_count` / `blocked_app_count` / `total_asset_count` |
| `POST /handover-tasks/pre-offboard` | **201** | `{"handover_task": <§6.2 详情对象>}` |
| `POST /handover-tasks/reassign` | **201** | `{"handover_task": <§6.2 详情对象>}` |
| `GET /handover-tasks/{id}` | 200 | `{"handover_task": <§6.2 详情对象>}` |
| `GET .../items` | 200 | `{"items": [{"id","label","hint"}], "page": 1, "page_size": 50, "total": 0, "unfiltered_total": null, "stale": false}` |
| `PATCH .../assets/{type}` | 200 | 该 `asset_type` 的最新对象（§6.2 `asset_types` 里的一项） |
| `GET .../overrides` | 200 | `{"overrides_version": n, "overrides": [{"asset_id","action","to_user","label"}]}` —— **完整集合**，不分页 |
| `PUT .../overrides` | 200 | `{"overrides_version": n+1, "confirm_version": m+1, "override_count": k, "dropped_invalid": j}` —— **必须回传两个新版本号**，否则前端手上还是旧值，翻到下一页再保存必然 409 |
| `POST .../preview` / `.../execute` / `.../retry` | 200 | 该 action 的最新对象（§6.2 `actions` 里的一项） |
| `GET /handover-candidates` | 200 | `{"items": [{"user_id","name","department"}]}` |

**三条硬规定**：

1. **任何 mutation 都不得返回 204。** 现有前端把非 JSON 的成功响应当异常处理
   （`frontend/src/lib/api.ts:103,107`），返回 204 会让每一次成功操作在界面上表现成失败。
2. **创建类返回 201，其余 mutation 返回 200**，都带 JSON 体。
3. **分页参数以契约为准，不是仓库默认值**：`page_size` 默认 **50**、上限 **200**
   （既有 `portal/pagination.py` 是 20/100，**不要沿用**）。超限直接钳制，不报错。

**错误码**（门户专用，均为 `{"error":{"code","message"}}`）：

| HTTP | code | 触发 |
|---|---|---|
| 403 | `out_of_managed_scope` | reassign 的 subject 不在我的管辖范围（契约 §4） |
| 409 | `open_task_exists` | 自助建单时已有 open 的 `offboard`/`transfer`/`pre_offboard` 单（与 §2.1 的 `lifecycle_task_one_open_lifecycle_per_subject` 同一集合）。`reassign` 单**不**触发本错误 |
| 409 | `handover_execution_in_flight` | 该 `(subject, app)` 已有 execute 在途（含 `async_pending`），契约 §10.5.2。**不排队、不自动重试**，前端提示稍后再试 |
| **412** | `snapshot_stale` | 下游返回 **412** 判定为快照失效，action 已退回 `pending`，需重新 preview（契约 §10.6）。**不要用 409** —— 409 会被判 `failed` |
| **423** | `downstream_locked` | 下游返回 **423**（对象被临时锁住，如项目审批锁），action 退回 `pending`；**可重试**，但要等人解除锁 |
| 409 | `action_not_retryable` | 对非 `failed` 状态的 action 调 `retry` |
| 422 | `reason_required` | reassign 未填理由或不足 10 字符 |
| 422 | `receiver_not_active` / `receiver_is_subject` / `receiver_required` / `asset_type_not_releasable` / `duplicate_assignment` | §5.4 |
| 400 | `detail_not_supported` | 该资产类型不支持明细 |
| **503** | `directory_unavailable` | subject 的 `DingTalkUserOrgContext` 缺失、`stale=true`、或 `manager_chain` 元素畸形。**与 403 分开**：403 是"上下文健康但你不在他的主管链上"，503 是"组织目录现在不可用"。两者都 fail-closed，但审计事件与用户文案不同（前者提示联系管理员，后者提示稍后重试），运维也要能区分是越权还是依赖故障 |
| 422 | `purpose_required` | `/handover-candidates` 缺 `purpose` 参数 |
| 409 | `action_blocked` | 对 `blocked` 状态的 action 调 preview/execute（未接入 APP，D6；只有超管能 skip） |

### 6.2 交接单详情响应体（前端据此建类型）

```json
{
  "id": 137,
  "kind": "offboard",
  "status": "in_progress",
  "generation": 1,
  "subject": { "user_id": "3f1a…", "name": "王某某", "department": "华东销售部", "status": "departed" },
  "assignee": { "user_id": "8c44…", "name": "李某某" },
  "assignee_state": "manager",
  "escalation_level": 0,
  "escalation": { "deadline": "2026-08-24T10:00:00Z", "days_left": 14, "level": 0, "deferred_at": null },
  // deadline/days_left 为 null 表示已落超管池, 不再上交; deferred_at 非空表示本层级已顺延过一次
  "reason": "目录同步检出离职",
  "created_at": "2026-08-10T10:00:00Z",
  "actions": [
    {
      "app_key": "easytrade",
      "app_name": "EasyTrade",
      "status": "previewed",
      "blocked_reason": "",
      "skip_reason": "",
      "last_error": "",
      "grant_receiver": { "user_id": "8c44…", "name": "李某某" },
      "summary": null,
      "data_completed_at": null,
      "confirm_version": 3,
      "overrides_version": 7,
      "skipped_by": "", "skipped_at": null,
      "approval_instance_warning": null,
      "allowed_actions": ["preview", "execute"],
      "batch_progress": null,
      "asset_types": [
        {
          "type": "customer", "label": "名下客户", "count": 187,
          "detail_supported": true, "releasable": true,
          "default_action": "transfer",
          "default_to_user": { "user_id": "d017…", "name": "张某某" },
          "override_count": 2
        }
      ]
    },
    {
      "app_key": "easyproject",
      "app_name": "EasyProject",
      "status": "blocked",
      "blocked_reason": "capability_undeclared",
      "skip_reason": "",
      "last_error": "",
      "grant_receiver": null,
      "summary": null,
      "data_completed_at": null,
      "confirm_version": 0,
      "overrides_version": 0,
      "skipped_by": "", "skipped_at": null,
      "approval_instance_warning": null,
      "allowed_actions": [],
      "batch_progress": null,
      "asset_types": []
    }
  ],
  "team_items": [ /* 既有形状不变 */ ]
}
```

整个详情**包在信封里**返回：`{"handover_task": { ...上述对象... }}`。

> **信封与字段名都要与既有控制台对齐，不能各写各的。** 现有控制台读的是
> `response.handover_task`（`admin_console/lifecycle_api.py:245-260`、
> `frontend/src/pages/console/lifecycle/HandoverTaskDetail.tsx:58-64`），
> 而 action 数组既有名字是 `app_actions`。
> v2 统一为：**保留 `handover_task` 信封**（改动面小），**数组统一改名 `actions`**，
> 并在**同一次改造里**把既有控制台消费者一起迁过来。
> 一半新一半旧的话，`task` 会直接是 `undefined`。

三个新字段的语义：

| 字段 | 语义 |
|---|---|
| `skipped_by` / `skipped_at` | 强行跳过的**责任链**。契约 §9.2 要求单据上永久显示「已由 {谁} 于 {何时} 强行跳过：{理由}」，只有 `skip_reason` 是匿名的，满足不了 |
| `allowed_actions` | `("preview"\|"execute"\|"retry"\|"skip")[]`，**由后端算好**。前端据此决定按钮，**不得解析 `last_error` 去猜可不可重试**。按契约 §10.6：4xx（除 400）不可重试 → 不含 `retry`；`failed` 且非在途 → 控制台含 `skip`（门户永远不含，D6 是超管专属） |
| `batch_progress` | 413 分批时非 null：`{"completed": 1, "total": 3, "current_batch_seq": 2}`；未分批时 null |
| `approval_instance_warning` | `{"message": str, "link": str, "recorded_at": str} \| null`。建单时一次性写死并持久化（§4.5.3），**升级与完成都不清除** |

`GET /me/handover-tasks` 的列表项是上述对象去掉 `actions`/`team_items`，另加
`pending_app_count`、`blocked_app_count`、`total_asset_count`，同样包在
`{"handover_tasks": {"as_assignee": [...], "as_subject": [...]}}` 里。

### 6.3 控制台（`/console/api/v1/lifecycle/`，超管）

既有端点保留。新增：

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `.../handover-tasks/{id}/actions/{app_key}/skip` | 强行跳过（D6），body `{"reason": "..."}`，`reason` 必填且 ≥10 字符。**实现方式：扩展既有的 `operation=="skip"` 分支**（`admin_console/lifecycle_api.py:362,403`），不要新注册一条会与既有动态 operation 路由（`admin_console/urls.py:252`）重叠的 URL —— 注册在后面就永远不可达。现有 handler **完全不读 body 里的 reason**，必须补：严格解析 `{"reason": str}`、校验 ≥10 字符、传给 `skip_action(action, actor_id=..., reason=...)` |
| POST | `.../handover-tasks/{id}/claim` | 超管认领 `superuser_pool` 中的单，assignee 置为该超管，`assignee_state=manager`。**认领人必须是 active、非 `local-admin:`、且有有效钉钉绑定的 OIDC 超管**，否则 `403 local_admin_cannot_claim` |
| POST | `.../handover-tasks/reassign` | **超管跨管辖范围建 `reassign` 单**（D9 的「跨部门走超管」路径）。body 同门户版，但**不做管辖范围校验**；仍校验双方 active、双方非本地管理员、`reason` ≥10 字符、接收人 ≠ 当事人。写审计 `handover_reassign_created`（`initiator` 记该超管） |
| POST | `.../handover-tasks/{id}/escalation/defer` | 把 `escalation_deadline` 顺延 `HANDOVER_ESCALATION_DAYS`（不改 `escalation_level`），必填 `reason` ≥10 字符。**同一 `escalation_level` 内至多一次**（靠 `escalation_deferred_at` 判定，非空即拒 `409 already_deferred`）；上交后该字段清空，新层级可再顺延一次。写审计 `handover_task_deferred`，单据上永久显示「已由 {超管} 于 {时间} 顺延：{理由}」 |
| GET | `.../handover-blocked-apps` | 未接入 APP 汇总，供控制台顶部告警条。响应 `{"app_count": n, "task_count": m, "apps": [{"app_key","app_name","blocked_task_count"}]}` |
| GET | `.../apps/{app_key}/handover-capability` | 能力标签页的**初始数据**。响应 `{"handover_capability": "declared"\|"none"\|"undeclared", "handover_asset_types": [...], "handover_url": "", "declared_by": "", "declared_at": null, "synced_at": null}`。**没有这个 GET，能力标签页打开就是空白** —— 既有 app detail 不返回三态，冻结契约里也只有两个 POST |
| PATCH | `.../handover-tasks/{id}/actions/{app_key}` | 设置**权限接收人**，body `{"grant_receiver_user_id": string\|null}`。仅 `kind=offboard` 允许非空，否则 `422`。修改后该 action 回退 `pending` 并清除上一轮 preview 结果（接收人变了，之前的预演不再代表现在的意图）。返回更新后的 action 对象 |
| POST | `.../apps/{app_key}/handover-capability` | 声明 `none`，body `{"reason": "..."}`；写 `declared_by`/`declared_at` |
| POST | `.../apps/{app_key}/handover-capability/sync` | 手动触发 §5.2 descriptor 同步 |

**控制台不复用门户的 URL 与 view。** 资产/明细能力在控制台下**另注册一套路径**
（`/console/api/v1/lifecycle/handover-tasks/{id}/...`），走 `require_superuser()` 且不做 assignee 校验，
两边只共享**不含任何 HTTP 身份逻辑**的 domain service。

> 早期写的"控制台复用 §6.1 的端点"与本节开头的"各自注册路由与 guard"直接冲突。
> 混在一个入口上，assignee 校验、404 防枚举、本地管理员拒绝这三条会在两条调用路径上
> 表现不一致 —— 最坏的情况是本地管理员从控制台入口拿到了门户语义。
> 统一规定：**门户一律 `require_portal_user()`（内含拒绝 `local-admin:`），
> 控制台一律 `require_superuser()`。**

### 6.4 审计事件的落点（契约 §12 全表必须有主）

契约 §12 冻结了 16 个事件。**每一个都必须有明确的写入位置，缺一个就是验收失败**
（`00` §15 第 9 条要求「§12 全部出现」）。对照表：

| 事件 | 写在哪 |
|---|---|
| `handover_task_created` | `lifecycle/offboarding.py` 建单事务内；门户 `pre-offboard` / `reassign` 建单同事务 |
| `handover_task_upgraded` | §5.1.2 的升级事务内，与 `generation += 1` 同事务 |
| `handover_assignee_assigned` | `lifecycle/assignee.py` 解析成功后，与 assignee 落库同事务 |
| `handover_assignee_resolution_degraded` | 同上，落超管池分支 |
| `handover_task_escalated` | `lifecycle/escalation.py` 上交事务内 |
| `handover_task_deferred` | §6.3 的 `escalation/defer` 端点事务内 |
| `handover_action_previewed` | §5.3 preview 成功后 |
| `handover_action_executed` | §5.5 execute 成功后（含 summary 摘要） |
| `handover_action_failed` | §5.5 失败分支 |
| `handover_action_blocked` | §5.1 建 action 判定为 `blocked` 时，与建 action 同事务 |
| `handover_action_unblocked` | §5.1.1 capability 恢复 reconcile 事务内 |
| `handover_action_skipped` | §6.3 的 `skip` 端点事务内 |
| `handover_task_completed` | `refresh_task_status()` 判定为 `completed` 的那一次 |
| `handover_reassign_created` | 门户 `reassign` 与 §6.3 超管跨范围 `reassign` 两个入口**都要写** |
| `handover_approver_reassigned` | §4.5.1 |
| `handover_approval_rule_approver_replaced` | §4.5.2 |
| `handover_capability_conflict` | §5.2 两个能力串同时出现时（告警性质，仍入审计） |

`tests/unit/lifecycle/test_audit_events.py` 逐事件断言：触发一次对应操作，
审计表出现且仅出现一行，关键字段非空。

---

## 7. 异步任务（`tasks/lifecycle.py`，**扩展既有文件**）

| 任务 | 周期 | 逻辑 |
|---|---|---|
| `lifecycle_escalation` | beat 每 10 分钟 | 扫 `status in OPEN and escalation_deadline <= now` 的 `HandoverTask`，逐个 `escalate_overdue_task()`。PostgreSQL 下 `select_for_update(skip_locked=True)` 分批（与 `grants` 过期任务同款） |
| `lifecycle_daily_reminder` | beat 每天 09:00（Asia/Shanghai） | 对未完成且有 assignee 的单发钉钉提醒；上交前 1 天额外发"即将上交"。注意既有 beat schedule 只接受 float interval，crontab 需扩展。**去重不能只靠"读一下 `last_reminded_on` 再写回"**，见下 |
| `lifecycle_poll_async_actions` | beat 每 **1 分钟** | 扫 `status=async_pending` 的 action，逐个调既有 `poll_async_action()`。**这个任务不存在的话，202 就是个死胡同**：action 进 `async_pending` 后门户不允许 retry（在途）、也没有任何东西去 poll，永远到不了 `done`/`failed`，租约也永远不释放。<br>**上限沿用既有的 `ASYNC_POLL_MAX_ATTEMPTS = 10`**（`lifecycle/core.py:30`），不要新造一个：第 10 次仍非终态 → CAS 标 `failed`、`last_error` 写固定文案「下游超过 10 次轮询仍未返回终态」、释放租约。`Location` 头持久化在 `async_status_url` 上，每次响应带新 `Location` 就更新。拿到终态 200 后**必须走 `complete_data_phase()`**，不得直接置 `done` |
| ~~`lifecycle_superuser_pool_reminder`~~ | — | **本期不做**，见下 |
| ~~`lifecycle_blocked_apps_digest`~~ | — | **本期不做**，见下 |

> **两个"向全体超管推送"的任务本期删除，不是延后实现。**
> §4 已经查清：超管资格只在请求期通过 Authentik 组交集判定（`admin_console/authz.py`），
> **没有可枚举的本地超管名单**。留着这两个任务，实现者只有三条路：不发（任务形同虚设）、
> 扫描猜测（漏发）、或扩大广播范围（把离职交接信息发给无权限的人）。三条都比不做更糟。
>
> 本期的替代：控制台顶部常驻告警条（§6.3 的 `handover-blocked-apps` 与超管池计数），
> 超管登录即见。等建立了权威的超管收件人镜像，再恢复这两个推送任务。

> **通知发送方的身份必须先定下来。** `notify/acceptance.py` 的 `accept_notify_message()`
> 要求 App、channel、credential 三者齐全（`:46,48,57,113`）。
> 生命周期通知**不属于任何业务 APP**，随便借用一个会把配额、审计归属、收件范围全搞错。
>
> 因此需要**先建一个 EasyAuth 内部的生命周期通知身份**，并且要有具体交付物，
> 不能只写一句"需要一个身份"：
>
> | 交付物 | 内容 |
> |---|---|
> | 固定 app key | `easyauth-lifecycle`（内部保留，不对外注册，不参与交接自身的 App 清单） |
> | 数据迁移 | 建该 App 记录 + 一条 active 的钉钉 notification channel + credential 引用 |
> | 启动健康检查 | 断言三者齐全且 channel active；缺失**只告警**，不阻断启动 |
> | 模板 | `notify/messages.py` 里 §13 的全部文案，key 前缀 `lifecycle.` |
> | 测试 | `tests/unit/lifecycle/test_notifications.py`：每种通知的收件人与去重键；配置缺失时**告警且不发送**，**不借用业务 APP**，**不静默丢消息** |

> `src/easyauth/tasks/lifecycle.py` **已经存在**，本节是扩展而非新建。
> 另外两点与既有实现不符，需一并处理：beat 目前是**直接投递任务**，不经 outbox；
> beat schedule 只接受 float interval，**crontab 需要扩展 schedule 类型**才能表达"每天 09:00"。

> **每日提醒的去重要原子，否则两个 beat 实例会把全量单据各提醒一遍。**
> "读 `last_reminded_on` → 发消息 → 写回今天"这个写法在两个实例同时跑时，两边都读到昨天，
> 两边都发。规矩：
>
> 1. 扫描用 `select_for_update(skip_locked=True)` 分批；
> 2. 在**同一事务**里做条件更新 `UPDATE ... WHERE last_reminded_on < :business_date`，
>    **影响行数为 1 才继续**，为 0 说明别人已经领走了；
> 3. 同事务写通知 outbox，dedup key 用稳定串
>    `handover:{task_id}:{business_date}:{daily|deadline_soon}`；
> 4. 通知表上的唯一约束作为最后一道兜底。

业务扫描由 beat 直接触发即可；**只有网络副作用（钉钉通知）走 outbox**，
遵循既有「网络副作用出事务」的约定。
通知内容与收件人见契约 §13，模板放 `notify/messages.py`。

---

## 8. SDK 改造（`sdk/python/src/easyauth_app_sdk/lifecycle.py`）

1. 新增事件常量 `HANDOVER_ITEMS_EVENT: Final = "lifecycle.handover.items"`。
2. `lifecycle_http_response()` 增参 `on_handover_items: HandoverCallback`，按事件分发。
3. `DEFAULT_MAX_BODY_BYTES` 由 `64 * 1024` 改为 `256 * 1024`（契约 §10.1）。
4. `fastapi.py` 的挂载 helper 同步增加 items 回调参数。
5. 新增 `easyauth_app_sdk/handover_payloads.py`：v2 请求/响应的 `TypedDict` 定义
   （`PreviewRequest`/`PreviewResponse`/`ItemsRequest`/`ItemsResponse`/`ExecuteRequest`/`ExecuteResponse`），
   下游 APP 直接 import 使用，杜绝字段名手抄出错。**每个 Request 都含 `event_type` 字段。**
6. **`event_type` 一致性校验，位置必须在 `webhook.test` 短路之前**（契约 §10.1 的强制补偿）：

   ```
   event = verify_webhook(...)                       # 验签
   body  = json.loads(raw_body)
   if body.get("event_type") != event.event_type:    # ← 新增, 必须在这里
       return 422 event_type_mismatch
   if event.event_type == WEBHOOK_TEST_EVENT:        # 现有短路
       return 200 {"ok": true}
   ...
   ```

   > **顺序不能反。** 现有实现（`sdk/.../lifecycle.py`）验签后**第一件事**就是判
   > `event.event_type == WEBHOOK_TEST_EVENT` 直接回 `{"ok": true}`，完全不看 body。
   > 由于事件头不在签名覆盖范围内，把一次真实 execute 请求的事件头改成 `webhook.test`，
   > 就能让下游回一句"好的"而什么都不做 —— 而 EasyAuth 把 200 当成功。
   > 校验必须挡在短路前面。

6.1 **回调必须能表达非 200 的业务状态码 —— 现在完全表达不了。**

   `HandoverCallback = Callable[[WebhookEvent], dict[str, Any]]`
   （`sdk/.../lifecycle.py:35`）**只返回一个 dict**；内核把它一律包成
   `_json_response(200, result)`，任何异常一律 `_error_response(500, ...)`。

   也就是说，一个用 `lifecycle_http_response()` 的 APP **根本发不出**
   409（身份无法识别 / 投递冲突 / 迟到 generation）、**412**（快照失效）、
   413（体积超限）、422（资产类型未声明 / event_type 不一致）——
   这些全部会变成 200 或 500。而契约 §10.6 的整张状态码表正是建立在这些码上的：
   EasyAuth 只看状态码决定 action 状态与可否重试。

   **不修这一条，v2 的错误语义在两个下游都无法实现。**

   改法：SDK 定义一个业务异常，内核捕获后按其携带的状态码渲染：

   ```python
   class HandoverBusinessError(Exception):
       def __init__(self, status_code: int, code: str, message: str) -> None: ...

   ALLOWED_BUSINESS_STATUS: Final = frozenset({400, 409, 412, 413, 422, 423})
   ```

   内核：

   ```
   try:
       result = callback(event)
   except HandoverBusinessError as e:
       assert e.status_code in ALLOWED_BUSINESS_STATUS   # 不在白名单内按 500 处理
       return _error_response(e.status_code, e.code, e.message)
   except Exception:
       return _error_response(500, "handover_callback_failed", 固定文案)
   return _json_response(200, result)
   ```

   状态码**白名单**是有意的：不允许 APP 随便返回 2xx/3xx，否则 EasyAuth 的状态机会被喂进
   它无法解释的输入。白名单外的值按 500 处理并写 SDK 侧告警。

7. **回调异常边界不得回显异常文本**（契约 §10.6）：现有
   `_error_response(500, "handover_callback_failed", f"交接回调执行失败: {error}")`
   会把 `str(error)` 拼进响应体。改为固定通用文案（如「交接回调执行失败，请查看应用日志」），
   真实异常由 APP 自己记日志。理由：该响应体会被 EasyAuth 存下并展示给主管（普通员工）。
8. 新增 `easyauth_app_sdk/manifest.py` 的 `_validate_lifecycle()` 白名单加 `handover_asset_types`
   （契约 §9.1）。**不改这一处，两个下游连 descriptor 都生成不出来**（会抛
   `ManifestValidationError: lifecycle 含未知字段`）。
9. 新增目录接口 `get_directory_user_by_authentik_sub(sub: str) -> DirectoryUser | None`。
   现有 client 只接受目录返回过的 **opaque `user_ref`**，把裸 Authentik `sub` 塞进去会被 EasyAuth
   判 422 —— 而 EasyProject 的 P2（从未登录过的员工解析 dtuid）**必然**走这条路径（`05` §2.1）。
   EasyAuth 侧同时提供对应的目录端点。
10. 新增包内数据资源 `easyauth_app_sdk/contract_samples/handover_v2/*.json`（§10），
    并在 `pyproject.toml` 的打包配置里显式包含（`package-data`），否则 wheel 里没有这些文件。
11. `sdk/python/CHANGELOG.md` 记为 **breaking**；版本号锁死并记录 **commit SHA 与 wheel SHA-256**
    （README「解锁凭据」）。`pyproject.toml` version、`descriptor.SDK_VERSION`、`uv.lock`、CHANGELOG
    四处取同一个值 —— 只改源码不改版本号会让下游 vendor 到不同提交而无人发现。
12. `sdk/python/README.md` 补 v2 接入示例（中文）。

### 8.1 EasyAuth 发送端的配套改造（**不在 SDK 里，但必须与 SDK 同批上线**）

**所有 webhook 发送入口在签名之前原子注入 `payload["event_type"] = event_type`。**

现有 `webhook.test` 的 body 是 `{"message": ..., "app_key": ...}`
（`admin_console/webhook_config_api.py:99`），**没有 `event_type`**。
新版 SDK 会在 `webhook.test` 短路之前发现缺字段并返回 422，
而 README 的联调门禁正是「`webhook.test` 对每个 APP 返回 200」——
**不做这一步，门禁永远过不去，而且看起来像下游的问题。**

**发送端有两个真实出口，两个都要改**（只改一个的话另一半照样 422）：

| 出口 | 覆盖的事件 |
|---|---|
| `webhooks/hooks.py::signed_hook_post` | preview / items / execute |
| **`webhooks/delivery.py::attempt_delivery`** | **`webhook.test`** —— 控制台的测试按钮走 `enqueue_delivery()` 把 body 存进 `WebhookDelivery`，最终由这里原样序列化并签名，**根本不经过 `hooks.py`** |

两处都必须**复制一份 payload**、在序列化与签名**之前**强制覆盖 `event_type`
（注入在签名之后等于没做）。
补**字节级**的 sender-side 测试：断言四种事件发出的 raw body 里都含正确的 `event_type`，
且签名是对注入之后的字节算的。

---

## 9. ADR 修订（契约 §3.1）

### ~~ADR-002 修订点 1（§19）~~ —— **已取消**

代管废弃后，`MANAGED_USERS` 不再需要容纳非 active 用户，该条款**保持原样**。

### ADR-002 修订点 2（§36）

原「审批人必须严格为申请人的 active 直属主管；缺少可解析的直属主管时禁止提交」改为：

> 审批人按 `manager_chain` **逐级向上**取第一个 active 主管，跳过
> departed / disabled / 本地管理员（`local-admin:` 前缀）/ 申请人本人。
> 钉钉 userid 只在 `(source_slug, corp_id)` 内唯一，查询必须带上这两个维度。
>
> 整条链走完仍无可用主管时，**不禁止提交**：申请照常进入 `submitted`，
> 但 `approval_routing_state` 置为 `superuser_pool`（见 §4.5.1），由超管在控制台认领并指定审批人。
>
> 仍然**禁止**手动改填 App owner 或任意其他用户来绕过主管链。

> **这条修订与 §8.2 建单时的降级取舍方向一致，但与权限查询相反**，修订说明里要写明：
> 权限查询宁可 503 也不能少给或多给；而"谁来审批"和"谁来交接"这两件事宁可先落到超管池，
> 也不能把申请或单据丢掉。目录 `stale` 时**不 fail-closed**。

新增 ADR-005「数据交接 v2 的能力声明与阻塞语义」，记录 D6 的决策与"静默成功"缺陷的修复，
以及本次新增的 `approval_routing_state`（审批人无解时的落点）。

---

## 10. 测试

| 文件 | 覆盖 |
|---|---|
| `tests/unit/lifecycle/test_assignee.py` | 主管链正常/跳过离职主管/整链失效落池/stale 落池/本地管理员跳过/不设层数上限 |
| `tests/unit/lifecycle/test_escalation.py` | 到期上交一级；跳过已离职主管继续向上；到顶落超管池且 `escalation_deadline` 置空；**回归测试：整个流程不产生任何 `AccessGrant` 变更**（代管已废弃，权限面必须零变化）；每业务日只提醒一次且跨时区正确 |
| `tests/unit/lifecycle/test_capability.py` | 三态 → action 初始状态；`declared` 但无 URL 抛错；`none` 缺声明人被约束拒绝 |
| `tests/unit/lifecycle/test_assignments.py` | §5.4 六条校验；三值 action 的库层 CheckConstraint；`releasable=False` 时 `skip`+逐条 `transfer` 可用（部分交接不依赖 releasable）；override 唯一约束；失效 override 被清理并计数 |
| `tests/unit/lifecycle/test_upgrade.py` | pre_offboard → offboard 升级：kind 变更、generation+1、assignee 重解析、上交截止时间重置；**§5.1.2 逐字段重置**（`data_completed_at`/`snapshot_token`/`batch_seq`/`last_error` 全部清空）；上一轮超管 skip 的 APP 若仍未接入则回到 `blocked` 而非继承 `skipped`；存在未释放租约时升级返回 409 |
| `tests/unit/lifecycle/test_reassign.py` | 管辖校验、必填理由、与 offboard 单并存不违反唯一约束、三方通知 |
| `tests/integration/test_portal_handover_api.py` | §6.1 全部端点的权限边界（非 assignee 拿到 404） |
| `tests/integration/test_handover_webhook_v2.py` | payload 形状逐字段比对契约样本（读法见下）；幂等键 `(task_id, generation, batch_id)` |
| `tests/unit/test_blocked_never_completes.py` | 存在 blocked 时 `refresh_task_status` 永不返回 completed（D13） |

#### 契约样本只有一份，就放在 SDK 包里

新增 **`sdk/python/src/easyauth_app_sdk/contract_samples/handover_v2/`**：
`preview_request.json`、`preview_response.json`、`items_request.json`、`items_response.json`、
`execute_request.json`、`execute_response.json`。

- **EasyAuth 自己的契约测试也用 `importlib.resources` 从这个包读**，不在 `tests/` 下另放一份副本。
  两份副本必然漂移，而漂移的那一天没有任何测试会失败 —— 这正是本次改造要消灭的那类问题。
- 三个仓库因此比对的是**同一批字节**，随 SDK 版本一起分发。
- 样本变更 = SDK 版本变更 = 全部下游契约测试同时失败。这是跨仓库对齐的机械保证。
- **样本缺失必须让测试失败，不允许 skip 通过。**

### 执行方式

**两条 lane，用途不同，都要跑：**

| lane | 命令 | 覆盖 |
|---|---|---|
| CI（权威门禁） | `uv sync --extra dev --frozen` 后 `.venv/bin/pytest tests/unit/lifecycle -q`（与 `.github/workflows/docker-build.yml` 一致） | 全部单测 |
| **PostgreSQL lane（必须）** | 起 `docker compose up -d postgres` 后跑集成用例 | **约束触发器、条件唯一约束、租约并发、`SELECT ... FOR UPDATE`** |

> **第二条不是可选项。** 本次新增的两个跨表不变量靠**约束触发器**、执行互斥靠
> **条件唯一约束**、接管靠 `FOR UPDATE` —— 这四样在 SQLite 上要么不生效、要么语义不同，
> 在 SQLite 上"跑过了"完全不说明问题。相关用例必须显式标记为需要真库。

> 本机开发若 host `.venv` 不可用，用 `docker compose run --rm` 走 compose 里已定义的
> 服务执行同样的命令；**不要在文档里写 `<image>` 这类占位 tag**，照抄跑不了。

---

## 11. 交付顺序（本仓库内部）

0. **最先做**：§8 的 SDK vNext 打包发布（三事件内核 + `handover_payloads` 类型 +
   **契约样本打进包内**）。它是 A3/A5 两个下游的开工前提，且只依赖已冻结的契约，不依赖本仓库实现。
1. **然后提交 §6**（API 契约章节）→ 解锁前端 agent。
2. §2 模型 + 迁移。**schema 变更与全部调用方必须在同一个 commit 里** ——
   先删 `HandoverAppAction.policy` 再改 `handover.py` 会产出一个**跑不起来的中间提交**，
   与「每次提交后必须重建前后端并确认构建成功」直接冲突。原子提交，`makemigrations --check` 无漂移。
3. §3 assignee → §4 超时上交 → §5 handover 执行链。
4. §7 异步任务 → §9 ADR。
5. §10 测试补齐。

每完成一项立即单独 commit；提交后必须重建前后端并确认构建命令成功结束（`AGENTS.md`）。
后端改动后必须重启 Django 开发服务，并用目标 URL 的真实 HTTP 响应验证新代码已加载。
