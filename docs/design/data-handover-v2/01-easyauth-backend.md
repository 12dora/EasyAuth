# 01 · EasyAuth 后端改造设计

> 基准文档：[`00-overview-and-contract.md`](00-overview-and-contract.md)（下称「契约」）。
> 本文件中出现的 D1–D13 编号、事件名、错误码、payload 形状均以契约为准，此处不重复定义，只给落地方案。
> **§6 的 HTTP API 契约是前端 agent（`02-easyauth-frontend.md`）的依赖，必须最先提交。**

---

## 1. 改造总览

| 模块 | 改动性质 | 说明 |
|---|---|---|
| `lifecycle/models.py` | 扩展 + 破坏性重构 | **新增 8 张表**：`HandoverAssetType` / `HandoverAssetOverride` / `HandoverExecutionBatch` / `HandoverDeliveryAttempt` / `HandoverExecutionLease` / `HandoverLeaseFence` / `HandoverBatchPlan` / `HandoverActionSkipRecord`；`HandoverTask` 加 7 字段（assignee / assignee_state / escalation_level / generation / escalation_deadline / last_reminded_on / escalation_deferred_at）；`HandoverAppAction` 数据接收人下沉到条目级、保留并改名 `grant_receiver`，另加 generation / snapshot_token / confirm_version / overrides_version / batch_seq / data_completed_at / blocked_reason / skip_reason / skipped_by / skipped_at / last_error_raw。<br>**`async_status_url` / `async_poll_attempts` / `preview_generation` / `attempts` 是既有列，不要写 `AddField`**（`lifecycle/models.py:207-231`，`0001_initial` 就有）—— §2.8 要求把 lifecycle 变更手写成**一个**迁移文件，照着「新增」清单写会在 `migrate` 时报 duplicate column |
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

**两条既有 CheckConstraint 必须随枚举扩容一起 `RemoveConstraint` + `AddConstraint`，
只改 Python 常量是不够的** —— 字面量已经烤进 DDL 了：

| 约束 | 位置 | 为什么必须重建 |
|---|---|---|
| `lifecycle_task_kind_supported` | `lifecycle/models.py:141-144`，`Q(kind__in=HANDOVER_KIND_VALUES)` | 本节往 `HANDOVER_KIND_VALUES` 加了 `pre_offboard` / `reassign`；不重建，建这两种单直接撞 CHECK 抛 IntegrityError |
| `lifecycle_action_status_supported` | `lifecycle/models.py:247-250`，`Q(status__in=ACTION_STATUS_VALUES)` | §2.2 往 `ACTION_STATUS_VALUES` 加了 `blocked` / `async_attention_required`；不重建，写这两个状态同样 IntegrityError |

§2.8 要求把 lifecycle 变更合并成**一个手写迁移文件**，这两条 Alter 最容易在合并时丢掉。

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

**先说四个既有列的去留**，本节下面的删除/改名/新增三张表是在此之上的增量：

| 既有列 | 去留 | 理由 |
|---|---|---|
| `preview_generation`（`models.py:207-209`） | **保留**，且 §5.3 必须继续用 | 语义是「preview 请求序号」，**与 `generation`（轮次）无关，同名不同义**。既有代码每次 preview 先 `+1` 再固化进 `_PreviewRequest.generation`（`handover.py:515-519`），落库时用 `filter(pk=..., preview_generation=...)` 条件加锁（`:554-569`）。**只按 `(action_id, generation)` 做 CAS 是降级**：那只挡得住跨轮次的迟到响应，挡不住同一轮次内的两次并发 preview（用户双击、前端重试、门户与控制台同时点）—— 两份响应都会通过，都去重建 `HandoverAssetType`（撞 `lifecycle_asset_type_unique_per_generation` 直接 500），都 `confirm_version + 1`（用户刚确认的那版立刻 stale，execute 稳定拿 `409 confirm_version_stale`）。<br>**升级时不重置**：它是全局单调序号，清零反而会让升级前的在途响应重新匹配上。<br>⚠️ 既有的 `_PreviewRequest.generation`（`handover.py:68`）指的是**这一列**，不是 `task.generation`，接字段时极易搞错 |
| `preview_payload`（`:203-206`） | **删除** | v2 的事实来源是 `HandoverAssetType` 行。留着就是第二份会漂移的真相，而 `admin_console/lifecycle_api.py:920-921` 会把它原样吐进控制台响应 —— 升级后控制台仍挂着上一轮的清单，正是 §5.1.2 要防的「用上一轮中间态污染这一轮」 |
| `result_payload`（`:210-213`） | **删除** | 同上，事实来源改为 `HandoverDeliveryAttempt.response_payload` |
| `attempts`（`:232`） | **保留为纯计数**，§5.1.2 重置为 `0` | §5.5.1 废掉了全部基于它的判断，但 `_execute_action`（`handover.py:161-170`）仍在写它。不重置就会跨轮次累加，成为一个没人负责的计数器 |

§2.8 的迁移内容要同步补上 `preview_payload` / `result_payload` 两个 `RemoveField`。

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
| `skipped_at` | `DateTimeField(null=True, blank=True)` | 强行跳过的时间，与 `skipped_by` 一起构成责任链（**当前轮次**，升级时会清空） |
| — | **新表** `HandoverActionSkipRecord`（append-only，完整定义见 §2.2.1） | **强行跳过的责任链只能靠它** —— action 上的三个字段在升级时会被清空（§5.1.2），而 `AuditLog` 有 **365 天保留期**（`config/data_retention.py:32-36`）之后会被物理删除。契约 §9.2 要求"单据上永久显示"，靠一张会过期的日志表是保证不了的。详情响应返回 `skip_history`；该表**豁免 retention**，且带 skip 历史的 task 不允许删除 |
| `approval_instance_warning` | `JSONField(null=True, blank=True)` | §4.5.3 的在途钉钉审批警示 `{message, link, recorded_at}`，建单时一次性写入，**升级与完成都不清除**。没有这一列的话 §4.5.3 的「必须持久化」根本无处可写 |
| `last_error_raw` | `TextField(blank=True)` | **新增**。下游响应体的**脱敏投影**（不是原文），UTF-8 截断 2000 字节，**只在控制台对超管展示且每次查看写审计**。既有的 `last_error`（`lifecycle/models.py:233`）改为只放「状态码 + 本地分类文案 + 白名单提取的 `code`/`message`，各截断 200 字符并脱敏」，门户与控制台都能看。口径以契约 §10.6 为准 |
| `batch_seq` | `PositiveIntegerField(default=0)` | 已分配的最大批次号。**只是分配器**；批次的事实来源是 §2.4.1 的 `HandoverExecutionBatch` 行 |
| `data_completed_at` | `DateTimeField(null=True, blank=True)` | 数据 webhook 已成功、权限尚未转授（契约 §10.5.1.1 的子状态，持久化） |
| `grant_receiver` | `FK(UserMirror, PROTECT, null=True, related_name="handover_grant_receiving")` | 权限接收人，见上 |
| ~~`execution_payload`~~ | — | **取消**。单个可更新字段无法承载多批历史，也称不上"不可变凭据"。改用 §2.4.1 的 append-only 表 |
| `blocked_reason` | `CharField(max_length=64, blank=True)` | `capability_undeclared` / `descriptor_unreachable` |
| `skip_reason` | `TextField(blank=True)` | 超管强行跳过的理由（D6） |
| `skipped_by` | `CharField(max_length=128, blank=True)` | 超管 actor id |

#### 2.2.1 `HandoverActionSkipRecord`（新表，append-only）

其余 7 张新表在 §2.3–§2.4.2 都有完整 `class` 定义，只有它原先只在上面的字段表里占一个单元格
—— 而 §2.8 说得很清楚「**迁移章节才是实现者真正会照抄的那一份**」。补齐规格：

```python
class HandoverActionSkipRecord(models.Model):
    task = FK(HandoverTask, on_delete=SET_NULL, null=True, related_name="skip_records")
    task_id_snapshot = PositiveIntegerField()     # 非空; task 被删后仍可按单号归集
    action_snapshot_id = PositiveIntegerField()   # 非空
    generation = PositiveIntegerField()
    app_key = CharField(max_length=64)
    actor_id = CharField(max_length=128)          # 超管的 OIDC sub
    reason = TextField()
    skipped_at = DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["task_id_snapshot"])]
```

- **FK 必须 `SET_NULL` + 快照列**，写法与 §4.5.2 的 `ApprovalRuleReplacementRequired` 一致。
  只留一个裸 `action_snapshot_id` 是不够的：`HandoverAppAction.task` 是 `CASCADE`
  （`lifecycle/models.py:172-176`），action 被级联删除后那个整数回指不了任何单据，
  同段声称的「**带 skip 历史的 task 不允许删除**」也就没有可查询的 task 维度列去实现。
- **retention 豁免要落到实处**：在 `config/data_retention.py` 的清理集合里显式**不加入**这张表，
  并加一条单测断言。`AuditLog` 是 365 天物理删除（`config/data_retention.py:36`
  的 `AUDIT_LOG_RETENTION_DAYS = 365`），契约 §9.2 要的是「单据上**永久**显示」，
  靠一张会过期的日志表保证不了。

**状态枚举新增两个**：`ACTION_STATUS_BLOCKED: Final = "blocked"` 与
`ACTION_STATUS_ASYNC_ATTENTION_REQUIRED: Final = "async_attention_required"`（§7 轮询超次数用），
两者都要加入 `ACTION_STATUS_CHOICES` / `_VALUES`。

> **`async_attention_required` 极易漏登记。** 它只在 §7 的一段警告里被提到，
> 不加进枚举的话，`02` 的 TS 联合类型（`02` §4）里也不会有它，
> 前端拿到这个值直接落进 `never` 分支、界面渲染不出来，而 action 已经卡在那儿了。
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

**`HandoverExecutionBatch`（**请求侧**不可变，一批一行）**

> **别把「不可变」实现成 `save()` 拦截。** 不可变的只有请求侧三列
> （`request_payload` / `request_hash` / `snapshot_token`，创建后只读，审计凭据在那里）；
> `status` / `data_completed_at` 全程都要写。
> 本仓库同一个文件里就有 `OnboardingTemplateRevision.save()` 直接 `raise ValidationError`
> 的先例（`lifecycle/models.py:481-489`），是实现者手边最近的模仿对象 ——
> 照它写，`complete_data_phase()` 第一次改状态就抛异常，整条同步 200 收尾路径挂掉，
> 连带租约不释放。用列级注释 + 单测断言表达只读，不要用 `save()` override。

```python
class HandoverExecutionBatch(models.Model):
    action = FK(HandoverAppAction, on_delete=SET_NULL, null=True, related_name="execution_batches")
    action_snapshot_id = PositiveIntegerField()   # 非空, 创建时冗余, 唯一约束建在它上面
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
                fields=["action_snapshot_id", "generation", "batch_seq"],
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
    outcome = CharField(max_length=16)            # sent | succeeded | failed
                                                  # | async_accepted | superseded
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
> 状态机固定为 **`sent → succeeded | failed | async_accepted | superseded`**。
> `superseded` 是给「发送前发现 generation 已过期、整条作废」用的（§5.5），它**没有** HTTP 响应，
> 所以库层 CHECK 要写成：
>
> ```
> outcome IN ('sent', 'superseded') OR http_status IS NOT NULL OR error_text <> ''
> ```
>
> 漏掉 `superseded` 的话，旧 generation 的 outbox 出队时那条作废记录**根本落不了库**。
>
> **`error_text <> ''` 这一段同样不能漏，它兜的是「根本没拿到 HTTP 状态码」那一类失败。**
> 现有代码里这类异常不带状态码：`webhooks/hooks.py:87-89`（连接失败 / 超时 / SSRF 拒绝）、
> `:122-124`（轮询 GET 同理）、`:141-146`（响应体不是 JSON、或不是 JSON 对象）
> 全都 `raise HookCallError(message)`，`HookCallError.status_code` 是 `None`（`:42-45`），
> 只有 `:129-131` 的非 2xx 才带状态码。
>
> 少了这一段会怎样：**下游宕机或超时**（最常见的故障，也正是租约机制存在的全部理由）时，
> 按「写 `outcome="failed"`、`http_status=NULL`」落库会**违反 CHECK 抛 IntegrityError**，
> 于是「写 failed + 同一次 CAS 释放租约」整个事务回滚 ——
> delivery 永远停在 `sent`、batch 永远停在 `executing`、`released_at` 永远是 NULL。
> 接着 §5.5.1 禁止对 `executing` batch 与未释放租约做 skip/cancel，
> 这张单**既不能执行、不能跳过、也不能取消**；而恢复任务对「网络不可达」的处置是
> 「续约后退避重试，不释放」，下游长期不可达就是无限期锁死。

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

> **`retry` 同样必须走 §2.4.2 的租约获取事务**，差别只在不新建 batch。这一条不写死，两种实现都是坏的：
>
> - 照字面「只追加 delivery 就投递」→ retry **不持有任何租约**。此时同一 subject/app 上
>   另一张 `reassign` 单的 execute 可以正常拿到租约并发送，两个 execute 同时在途，
>   直接违反契约 §10.5.2 冻结的互斥 —— 就是「先到者全搬走、后到者返回一堆 0」那个事故。
> - 严格遵守 §2.4.2 的「claim 失败就不许发网」→ 因为 action 转 `failed` 时租约已释放，
>   此刻**没有 active 租约行可 claim**，retry 永远发不出网。契约 §10.6 里 400/5xx 标注的
>   「可重试」全部落空，只剩超管强行 skip 一条路。
>
> 具体做法：`select_for_update(action)` → `HandoverLeaseFence` 取**新** fence → INSERT 租约
> （冲突即 `409 handover_execution_in_flight`）→ 把原 batch 的 `status` 从 `failed` 置回 `executing`
> → 追加 `delivery_seq + 1` 的 delivery 行 → 写 outbox → 提交。
> **`data_completed_at` 非空的纯授权重试（§5.5）同样要取租约** —— 它要写 action 终态，
> 必须在 CAS 保护下进行。

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
| **分片计划** `HandoverBatchPlan` | 收到 413 时**一次性**算好并落库 | 见下方表定义 |
| **批次行** `HandoverExecutionBatch` | **每批执行前才创建** | 该批的 `snapshot_token`、canonical payload、`request_hash` |

> **为什么不能一次建完 M 个 batch 行**：batch 上的 `snapshot_token` 与 payload 是
> **创建即不可变**的审计凭据，而第 2 批的 token **此刻还不存在** ——
> 契约 §10.5.2 规定每批必须重新 preview 取新 token（第 1 批已经改过数据，旧 token 必然失效）。
> 预建的话只有三条路：填旧 token（execute 必然 412）、填空（违反非空）、
> 或事后修改"不可变"的行（毁掉审计凭据）。三条都不行。

```python
class HandoverBatchPlan(models.Model):
    action = FK(HandoverAppAction, on_delete=SET_NULL, null=True)
    action_snapshot_id = PositiveIntegerField()      # 非空, 唯一约束建在它上面
    generation = PositiveIntegerField()
    total = PositiveIntegerField()                   # = M
    chunks = JSONField()                             # 按 plan_seq 排: [[{asset_type, ids:[...]}], ...]
    assignment_hash = CharField(max_length=64)       # 见下方「计划固化之后」
    status = CharField(max_length=16)                # active | abandoned | done
    completed_batches = PositiveIntegerField(default=0)
    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["action_snapshot_id", "generation"],
                condition=Q(status="active"),
                name="lifecycle_batch_plan_one_active",
            ),
        ]
```

`HandoverExecutionBatch` 另加 `plan = FK(HandoverBatchPlan, null=True, on_delete=SET_NULL)`
与 `plan_batch_no`（从 1 起），把批次挂回计划。

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

#### 分片计划固化之后，分配就不能随便改了

`HandoverBatchPlan` 建立时必须**一并固化 `assignment_hash`** —— 对
`default_action` / `default_to_user` / `overrides` / `grant_receiver` 取 canonical 摘要。

> **摘要范围必须排除「已被完成批次消耗掉」的 override，否则第 2 批起必然卡死。**
> 推演一遍就看得到：每批的流程是**强制**「重新 preview → 拿新 token → execute」（见上），
> 而第 1 批的 `overrides` 里正是本批要 `transfer`/`release` 的那些逐条项。
> 第 1 批搬完，这些 `asset_id` 就不再属于当事人；下一轮 preview 按 §5.3 会把它们**强制删除**；
> 重算出的摘要于是**必然**与计划里固化的值不等 → 第 2 批被 `assignment_hash` 校验拒绝
> → 而此时 `completed_batches = 1 > 0`，三个改分配端点全部 `409 batch_plan_in_progress`，
> **没有任何重建计划的入口** —— 和下面那个反面案例一字不差，只是触发者从用户换成了系统自己。
>
> 因此 `assignment_hash` 只覆盖**计划中尚未执行的 chunks 所涉及的** override，
> 加上类型级默认动作与 `grant_receiver`。同时 §5.3 的 preview 落库要写明：
> **存在 active `HandoverBatchPlan` 时，已完成批次里的 override 属于「正常消耗」**，
> 其删除既不参与 `assignment_hash`，也不计入「N 条单独指定已失效」的提示
> （否则用户每执行完一批就会看到一次假告警）。

| 状态 | 允许改分配吗 |
|---|---|
| `completed_batches == 0` | 允许。但必须在**同一事务**里把旧计划标 `abandoned` 并重新规划 |
| `completed_batches > 0` | **禁止**。`PATCH .../assets/{type}`、`PUT .../overrides`、`PATCH grant_receiver` 一律返回 `409 batch_plan_in_progress` |

**另一个更常见的在途窗口：没有分批计划、但 execute 正在途中。** 这三个端点同样必须挡住，
判定谓词与 §5.5.1 的 skip/cancel 禁令**共用同一个函数**，不要各写一份：

> 存在未释放的 `HandoverExecutionLease`，或存在 `status ∈ {pending, executing, async_pending}`
> 的 `HandoverExecutionBatch` 时，三个改分配端点一律返回 **`409 handover_execution_in_flight`**，
> **子表零写入、`confirm_version` 不递增**。
>
> 不挡的后果是**静默不一致**：execute 的入口事务已经把 canonical payload 固化进 batch，
> 真正发网在 outbox worker 里，202 异步时这个窗口能有几分钟到几十分钟。
> 用户此刻（另一个标签页、或前端某条未禁用的路径）把一条从 `transfer` 改成 `skip` ——
> 服务端返回 200、`confirm_version` +1、界面显示「已保存」，
> 而在途那批用的是固化的旧 payload，**该条照样被搬走**。
> 执行完 action 转 `done`，`completed` 的单不可重开（契约 §6.2），
> 用户看到的是「我明明改成不动了、系统也说保存成功了，数据却没了」，
> 事后还无法从 `confirm_version` 反推出发生过什么。

execute 每一批同时校验**两样**：最新的 `confirm_version`（用户看的是不是这一版）
与计划的 `assignment_hash`（要执行的还是不是同一份意图）。
每批重新 preview 会让 `confirm_version` 递增，这是正常的；但 `assignment_hash` **不得变**。

> 不定这条规则会这样：三批计划的第 1 批已经搬完，用户把第 2 批里的某条从 `transfer` 改成 `skip`。
> 计划里存的还是旧的 `transfer` —— 要么按旧计划把用户刚说"别动"的数据搬走，
> 要么被版本校验挡住而**没有任何重建计划的入口**，剩下两批就此卡死。

> **残留限制要如实说出来**：如果单是这些 `skip` 逐条项就撑爆了 256 KiB，本方案无解。
> 这时 execute 返回 `413`，界面提示「单独指定的条目过多, 请减少逐条指定后重新预演」，
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
    fence = INSERT INTO lifecycle_handoverleasefence (subject_user_id, app_id, next_fence)
            VALUES (%s, %s, 2)
            ON CONFLICT (subject_user_id, app_id)
            DO UPDATE SET next_fence = lifecycle_handoverleasefence.next_fence + 1
            RETURNING next_fence            -- 首行由本语句自己建, 不许单独 get_or_create
    INSERT HandoverExecutionLease(subject_user, app, action, generation, batch_seq,
                                  owner, fence, lease_expires_at=now+LEASE_TTL)
        ← 条件唯一约束冲突 → 立即 409 handover_execution_in_flight
    创建 HandoverExecutionBatch + 首条 DeliveryAttempt + outbox
    提交（事务回滚时租约一起回滚）
```

> **只描述租约表、不写这一步，互斥就是纸上的。** 同一 subject/app 上的离职 action 与
> reassign action 并发 execute 时，两边各锁各的 action 行，谁也不去 INSERT 租约，
> 于是两个 worker 都把请求发了出去。

**每一条终结路径都必须在同一次 fence CAS 里释放租约**，这张表是冻结的：

| execute 的结局 | 租约怎么处理 |
|---|---|
| 同步 200（最终批，授权也成功） | 写 `action.status="done"` 的那次 CAS **同时** `released_at = now` |
| 同步 200（非最终批） | 写 batch 完成的那次 CAS 同时释放 |
| **202** | **不释放**，移交 async sentinel（见下） |
| 412 / 413 / 423（退回 `pending` / 保持 `previewed`） | 写回状态的那次 CAS 同时释放 |
| **429（APP 侧限流，action 保持 `previewed`）** | **同样要释放**。这一行最容易漏：429 在契约 §10.6 里写的是「不向用户报错、退避后重试」，看着不像终结路径，但对本次 execute 而言它就是终结了 —— 不释放的话，APP 前面挂个网关限流一次，那条 `(subject, app)` 就永久锁死。<br>落库口径也要写死，否则 §2.4.1 的 delivery 状态机套不上它：**本次 delivery 记 `outcome="failed"` + `http_status=429`**（不新造 `rate_limited` 取值），batch 退回 `pending`，按 `Retry-After` 重新入队一次新 delivery（重走入口事务、重新取租约）。留在 `sent` 是不行的 —— `sent` 的 batch 属于 `executing`，会触发 §5.5.1 的 skip/cancel 禁令 |
| **400** / 409 / 422 / 401 / 403 / 5xx（`failed`） | 同上，写 `failed` 的那次 CAS 同时释放。**400 别漏** —— 契约 §10.6 把它标为「可重试的 `failed`」，看着像还没结束，但对本次 delivery 而言它已经终结了 |
| **授权转移（事务 B/C）失败** | 写 `action.status="failed"` 的那次 CAS 同时释放。**这一行不按 HTTP 状态码分，容易整个漏掉**：数据 webhook 明明返回了 200，失败发生在之后的权限转授里。不释放的话，界面会出现「已经失败了却什么都点不了」的窗口（§5.5.1 禁止对未释放租约的 action 做 skip/cancel） |
| **无响应**（连接失败 / 超时 / TLS / SSRF 拒绝 / 响应体不是 JSON） | action 置 `failed`（可重试），delivery 记终态 `outcome="failed"`、`http_status=NULL`、`error_text` 写本地分类文案，**同一次 CAS 释放租约**。<br>这一行**不按状态码分，最容易整个漏掉** —— 而它恰恰是最常见的故障，也是租约机制存在的全部理由。库层 CHECK 必须能容纳 `http_status IS NULL` 的终态行，见 §2.4.1 |
| 上表之外的任何结局 | **不存在**。注意是「结局」不是「状态码」—— 无状态码的传输失败也必须在本表里有主。`ALLOWED_BUSINESS_STATUS`（§8）与本表的状态码行必须逐一对应，加一个码就要加一行 |

> **漏掉任何一行，那条 `(subject, app)` 就被永久锁住**：条件唯一约束会让后续的 execute、
> 以及升级（§5.1.2 要求无在途租约）统统撞上 `handover_execution_in_flight`，
> 而 action 本身早已终结、界面上看不出任何异常。

**还必须有一个兜底的恢复任务**（§7 `lifecycle_recover_expired_execution_leases`，每分钟）：
worker 发完网就崩溃时，TTL 只让租约"过期"，没有任何东西会去接管它 ——
那一行会永远满足 `released_at IS NULL`，唯一约束继续挡住所有人。

**常量冻结，不由实现者自行选择**（否则同一故障下有的 worker 抢占、有的长期锁死）：

```python
LEASE_TTL: Final = timedelta(minutes=5)
LEASE_RENEW_INTERVAL: Final = LEASE_TTL / 3        # 续约周期不得超过 TTL/3
```

`lease_expires_at = now + LEASE_TTL`；worker 在长任务期间按 `LEASE_RENEW_INTERVAL`
**周期性续约**（CAS 更新 `lease_expires_at` / `renewed_at`）。
这两个常量进单元测试断言。

**fence 用取号器原子分配**：单语句 upsert（`INSERT ... ON CONFLICT DO UPDATE SET
next_fence = next_fence + 1 RETURNING next_fence`，全文见 §2.4.2 的事务 1）。
不允许用「当前最大 fence + 1」这种读后写，**也不允许先 `get_or_create` 再 `UPDATE`** ——
某个 `(subject, app)` 的第一次 execute 时那一行还不存在，裸 `UPDATE` 会影响 0 行、
`RETURNING` 空集，而补 `get_or_create` 会让两个并发的首次 execute 撞
`lifecycle_fence_unique` 抛 IntegrityError，而不是预期的 `409 handover_execution_in_flight`。

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

**续约与抢占的谓词都要写全，否则会误杀有效 worker**：

| 动作 | 条件（缺一不可） |
|---|---|
| 续约 | `owner = :me AND fence = :my_fence AND released_at IS NULL AND lease_expires_at > db_now()` —— **已过期的 owner 不许复活** |
| 抢占 | `owner = :observed_owner AND fence = :observed_fence AND released_at IS NULL AND lease_expires_at <= db_now()`，并与新 fence 取号**同事务** |

只按 `released_at IS NULL` 抢占的话，恢复者扫到过期行、而原 owner 恰好在这中间续租成功，
**有效 worker 会被误杀**。

**抢占那条 UPDATE 同时写四样东西**：新 `owner`、新 `fence`、`renewed_at`、
**以及 `lease_expires_at = now + LEASE_TTL`**。少写最后一项，新持有者刚接管就又是「已过期」，
下一个恢复者立刻再抢一次。

**A / B / C 三个事务各自都要重新 CAS 并持有租约行锁到本阶段提交**，不能只在事务 A 校验一次：
旧 worker 在写完 `data_completed` 之后被抢占，若 B/C 不再校验 fence，
它会继续把权限转掉、把 action 写成 `done`，而新 owner 的账本还在途。
事务 C 里「写 `done`」与「释放租约」必须是**同一次** CAS。

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

#### 租约要移交**两次**，第一次就在首投之前

**取得租约的是 HTTP worker，真正发 webhook 的却是 Celery outbox worker**
（execute 事务只写 outbox，提交后才由 worker 发送，见 §2.4.1）。
两者的 `owner` 不同 —— 严格 CAS 下，发送方拿到响应也写不回去：
要么丢弃响应而 batch 永远停在 `sent`，要么先发再发现 CAS 失败，**下游已经改了数据而 EasyAuth 没有结果**。

所以 sentinel 移交有**两处**，不是一处：

| 时机 | 租约 owner |
|---|---|
| execute 事务创建 delivery 时 | `delivery:{delivery.pk}` |
| outbox worker **发网之前**，以旧 owner/fence 为条件原子 claim | `sender:{worker_id}`，用 `HandoverLeaseFence` 取**全新 fence**，同时续期 |
| 收到 202 之后 | `async:{batch.pk}`（见下） |

**claim 失败就不许发网。** 所有响应写回都用 claim 得到的那一组 `owner + fence`。

#### 202 之后再移交一次给轮询 worker

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

代管授权已整体废弃（契约 §7）。这两张表**不建**，
`HANDOVER_CUSTODY` scope **不加**，`grants/managed_users.py` **不改**。

`HandoverTask` 改为直接持有上交截止时间：

| 字段 | 类型 | 说明 |
|---|---|---|
| `escalation_deadline` | `DateTimeField(null=True, blank=True)` | 建单/上交时置为 `now + HANDOVER_ESCALATION_DAYS`；单终结后置空 |
| `last_reminded_on` | `DateField(null=True, blank=True)` | 每日提醒按**上海业务日**去重（`timezone.localdate(..., Asia/Shanghai)`） |
| `creation_idempotency_key` | `CharField(max_length=128, blank=True)` | 创建 `pre_offboard` / `reassign` 时的 `Idempotency-Key` |
| `creation_payload_sha256` | `CharField(max_length=64, blank=True)` | 创建请求 canonical body 的摘要 |
| `escalation_deferred_at` | `DateTimeField(null=True, blank=True)` | 超管在**当前** `escalation_level` 内顺延过一次的时间戳；每次上交时清空。非空即禁止再次顺延（§6.3） |

```python
models.UniqueConstraint(
    fields=["created_by", "creation_idempotency_key"],
    condition=~Q(creation_idempotency_key=""),
    name="lifecycle_task_creation_idempotency_unique",
)
```

**幂等键得有载体，不能只写在 API 描述里** —— 没有字段和唯一约束，「同 key 同 body 返回原单」
就没有实现依据，并发双写也没有兜底。缺 `Idempotency-Key` 头 → `422 idempotency_key_required`；
同 key 不同 body → `409 idempotency_conflict`。

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
| `lifecycle` | `00XX_handover_v2_schema.py` | §2.1–§2.5.1 的全部 lifecycle 变更：**8 张新表**（含 §2.2.1 的 `HandoverActionSkipRecord` —— 它最容易在这里漏掉；漏了它，强行跳过的责任链就只剩会在升级时被清空的三个字段和 365 天后物理删除的 `AuditLog`，契约 §9.2 要求的「单据上永久显示」直接失效）、`HandoverTask` 的 7 个新字段、`HandoverAppAction` 的全部新字段（含 `last_error_raw`）；**`to_user` 用 `RenameField` 改名为 `grant_receiver`**；删除 `execution_to_user` / `policy` / `execution_policy` / **`preview_payload` / `result_payload`**（后两个见 §2.2 的既有列去留表）；**`RemoveConstraint` + `AddConstraint` 重建 `lifecycle_task_kind_supported` 与 `lifecycle_action_status_supported`**（§2.1、§2.2 的枚举扩容，字面量已烤进 DDL，只改常量无效）；§2.2 与 §2.4 的两个**约束触发器**用 `RunSQL` 建（含 reverse_sql）。<br>**`async_status_url` / `async_poll_attempts` / `preview_generation` / `attempts` 是既有列，不要写 `AddField`** |

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
> previous = query_approver_user_ids(access_request)      # 领域查询 helper
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
  「本应用存在未终结的钉钉审批, 无法确认其中是否有由 {离职者} 审批的条目, 请到钉钉中检查并人工转办。」
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
| `skipped_at` / `skipped_by` / `skip_reason` | → 空 | 与下方「强行跳过不继承」一致。跨轮次的责任链在 §2.2.1 的 `HandoverActionSkipRecord` 里，不受影响 |
| `attempts` | → `0` | 既有列，`_execute_action` 仍在写它（`handover.py:161-170`）。不重置就跨轮次累加，成为没人负责的计数器 |
| `preview_generation` | **不重置** | 全局单调序号（§2.2）。清零会让升级前的在途 preview 响应重新匹配上条件更新 |
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

> **`task_id` 的生成公式改为 `f"{task.id}:{app.id}"`**（契约 §5.4）——
> 现有 `handover.py:597-606` 拼的是 `app.app_key`，而 `App.app_key` 允许 64 个字符
> （`applications/models.py:102-108`），一个完全合法的 app_key 就能让 `task_id` 超过 64 字节，
> **正常创建的应用会让离职交接直接建不出单**。换成 `app.id` 之后最长 39 字节，撞不到上限。
> 建 action 时仍然断言 `^[0-9:]{1,64}$` —— 改了公式之后这条断言只会在代码写错时触发，
> 不会因为运营取了个长名字而触发。

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
> `applications/permission_template_payloads.py` 的 `LifecyclePayload` 是
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
- **发请求前固化两个序号**：`request_generation = action.generation` 与
  `request_preview_generation = action.preview_generation`（后者是既有列，见 §2.2）；
  **响应落库时按 `(pk, generation, preview_generation)` 三者做条件更新，不匹配就整份丢弃**
  —— 不写 `snapshot_token`、
  不重建资产行、不递增 `confirm_version`、不改 action 状态。

  > generation 1 的 preview 已经发出去了，单据随后升级到 generation 2 并清空 token；
  > generation 1 的响应姗姗来迟，若照写就会把旧 token、旧资产清单、旧状态盖到新一轮上，
  > 接下来的 execute 拿着旧 token 进入 412 死循环，界面上还显示着上一轮的清单。

- 用响应**重建**该 `(action, generation)` 下的 `HandoverAssetType` 行（`count`/`label_snapshot`），
  保留已存在行的 `default_action` / `default_to_user` 与其 `overrides`（重新 preview 不应清空人已做的选择）。
  **失效 override 的判定不在这里做** —— 见下方警告。
- 响应中**缺失**任何已声明类型 → action 直接 `failed`，`last_error` 写明缺了哪些类型。
  **不得补零继续**（契约 §10.3）—— 补零是把下游契约违约伪装成"这一类真的没数据"。

> **失效 override 的判定放在有明细的地方做，preview 阶段做不了。**
> 契约 §10.3 明确规定 **preview 响应不含明细**，只有 `{type, label, count}`；
> 明细只能走 §10.4 的 `items`，而 items 是**透传不落库**的（§5.6），
> EasyAuth 本地根本没有可比对的 `asset_id` 集合。
> 硬要在 preview 里判，只有三条路，全是错的：
> 不实现（失效 override 一路留到 execute，下游按契约 §10.5.1 第 4 条整体 409，
> action 判 `failed`，用户完全不知道是哪几条的问题）；
> 对每个 `detail_supported` 的类型全量翻页拉 items（一次 preview 变成上百次下游调用，
> 正是契约 §10.4 要防的读放大）；猜一个近似判据（静默默认值）。
>
> **落点统一到 `PUT .../overrides` 与 `GET .../items`** —— 那两处本来就有明细在手。
> `PUT overrides` 的响应已经有 `dropped_invalid` 字段（§6.1），语义全部收拢到它。
> preview 响应**不承诺** `dropped_invalid`，也不提示「N 条单独指定已失效」。

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
    # 事务 A(CAS 保护): batch.status = "data_completed" + batch.data_completed_at
    #                  若 batch.is_final: 同时写 action.data_completed_at   ← 必须在这里
    # 提交 A
    #
    # if not batch.is_final:                      ← 非最终批到此为止
    #     batch.status = "done"
    #     action.status 保持 "previewed"          （不是 done!）
    #     action.data_completed_at 保持 NULL
    #     更新 batch_progress, CAS 释放租约, 返回
    #
    # 事务 B: 幂等转授权限(仅 kind == offboard)
    # 事务 C: action.status = "done" + refresh_task_status_locked + CAS 释放租约
```

> **非最终批绝不能置 `done`。** 三批计划的第 1 批返回 200 就把 action 写成 `done` 的话，
> D13 会把**整张单**判成 `completed`，而 `completed` 单**不可重开**（§6.2）——
> 后两批再也没有执行入口，剩下的资产永远搬不走。

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
| `transfer`（转岗） | **不走这条路**。走既有的 `TransferPlan` 差异确认（`lifecycle/transfer.py`），按新岗位重算。**但确认时机要卡住**，见下 |
| `pre_offboard` / `reassign` | **一动不动**（D7 / D9） |

> **`GRANT_MUTATING_KINDS = (OFFBOARD, TRANSFER)` 不能用在 action 执行路径上。**
> 它表达的是"这两种单会动权限"，而 action 执行路径要问的是"要不要调
> `transfer_selected_grants`" —— 答案只有 `offboard`。
> 拿前者当后者用，转岗单会**同时**走接收人转授和 TransferPlan 差异，授权被改两遍。
>
> 执行路径用独立常量：`ACTION_GRANT_TRANSFER_KINDS: Final = (HANDOVER_KIND_OFFBOARD,)`。

#### 转岗单：`confirm_transfer_grant_diff()` 必须等数据先搬完

`confirm_transfer_grant_diff()` 锁住 task 之后**必须断言**：
全部 APP action 已经是 `done` / `skipped`，且**不存在未释放的 execution lease**；
不满足 → `409 handover_data_not_completed`，**授权零写入**。

> 不卡这一下，"权限已转、数据没搬"这个我们花大力气修掉的状态会**从转岗这条路原样回来**：
> 超管先确认岗位差异、旧岗位权限当场被撤，随后某个 APP 的 execute 失败 ——
> 单据没完成，权限却已经变了，而数据重试**不会**把权限恢复回去，
> 也没有任何子状态能表达这个中间态。
>
> 固定顺序：**全部数据 action 收敛 → 单事务应用 TransferPlan 差异 → completed**。

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

**参数上界与限流（与 `03` §3.5 / `05` 的 items 上界同规格，契约 §10.4）。**
契约写的是「**EasyAuth 与 APP 两侧都要在查询之前校验，不能只靠一边**」，
而 EasyAuth 是唯一的发起方 —— 这一侧不做，那句话就降级成了单侧校验：

| 参数 | 规则 | 越界处置 |
|---|---|---|
| `page` | `1 ≤ page ≤ 100000` | **422 `items_page_out_of_range`**，不钳制、不下发 |
| `page_size` | `1 ≤ page_size ≤ 200` | **钳制**到上界，不报错（只有它是钳制） |
| — | — | **钳制后的值才是转发给下游的值**，所以下游永远收不到越界的 `page_size`。<br>下游侧（`03` §3.5 / `05`）对三项一律 **422 不钳制** —— 那是 webhook 边界，越界只可能来自重放攻击者；而这里是 EasyAuth 自己前端的边界，把一个无害的 UI 取值打成错误没有意义。两边规则不同是有意的，不是漂移 |
| `q` | 去空白后 UTF-8 ≤ 128 字节 | **422 `items_query_too_long`**，不截断、不下发 |

**必须在向下游发请求之前校验。** 不校验就原样转发的话，下游确实会返回 422，
但 EasyAuth 拿到 422 后按契约 §10.6 判定为「载荷不被支持」→ **action 直接 `failed`** ——
一次用户误操作或前端 bug 就把 action 打成失败态。

再按 `(actor, task_id, app_id)` 限流：**窗口 60 秒、上限 120 次**（写成模块级常量并进单测断言），
超限返回 `429 rate_limited`。没有这一层，契约 §10.4 描述的读放大在 EasyAuth 这一侧完全敞开。

```python
def fetch_action_items(action, *, asset_type: str, page: int, page_size: int, q: str) -> dict
```

- 仅当该类型 `detail_supported=True` 才允许调用，否则 `400 detail_not_supported`。
- **状态门槛**：只在 task 仍 open、action 非终态、且 `data_completed_at IS NULL` 时才允许调用；
  否则 **`404`**，并且**不向下游发任何请求**。取消或完成时**同事务清空 `snapshot_token`**。

  > 没有这道门槛的话：主管 preview 之后单据被取消，`assignee` 与 `snapshot_token` 都还留着 ——
  > 他可以继续调 items 实时回源。只要归属与谓词没变，token 就一直有效，
  > 而金额、跟进记录这些**不进 token 的展示字段**会把最新值一并吐出来。
  > 历史单只展示**已落库**的 count / summary，不再实时回源。
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
> **门户与控制台必须各自注册路由与 guard**，只共享 domain service（详见 §6.3）。

| 方法 | 路径 | 可访问条件 | 说明 |
|---|---|---|---|
| GET | `/me/handover-tasks` | 登录即可 | 返回两组：`as_assignee`（我负责的）、`as_subject`（我是当事人的） |
| POST | `/handover-tasks/pre-offboard` | 登录即可，且自己无 open 的 offboard/transfer/pre_offboard 单 | 在职提前交接建单（D7），`kind=pre_offboard`，assignee=本人 |
| POST | `/handover-tasks/reassign` | 我对 `subject` 有管辖权（契约 §4 的主管链判定，**不走 `resolve_managed_users`**）且双方 active。**必带 `Idempotency-Key` 头**（≤128 字符）|

> **`kind=reassign` 的管辖权要持续复核，不能只在建单时查一次。**
> 详情、items、overrides、以及所有 mutation，都必须在 assignee 校验**之后**再按当前目录
> 重跑一次契约 §4 的判定。失权 → fail-closed（403），把单据移交 `superuser_pool`
> 并写审计 `handover_reassign_scope_revoked`。
>
> 不复核会这样：A 合法地为下属 B 建了 reassign 单；B 调岗、目录同步也更新了主管链；
> 但 A 仍然是这张单的 `assignee` —— 他照样能翻 items、改接收人、点执行，
> **把一个已经不归他管的人的资产搬走**。
>
> 超管创建或认领的单据存一个不可变的 `authority_source="superuser"`，
> **只有这一种来源豁免主管链复核**。 在职移交（D9）。body：`{"subject_user_id": "<OIDC sub>", "app_keys": ["easytrade", ...], "reason": "至少 10 字"}`。**`app_keys` 必填且非空** —— 只为列出的 APP 建 action，**不得**隐式把该员工在其他 APP 的数据也拉进来（`00` §8.4 明说同一 subject 可以有多张针对不同 APP 的 open `reassign` 单）。缺 `subject_user_id` / `app_keys` → `422`；`reason` 不足 10 字 → `422 reason_required` |
| GET | `/handover-tasks/{task_id}` | 我是 assignee 或 subject | 单据详情，含各 APP action、资产分类、距上交剩余天数 |
| GET | `/handover-tasks/{task_id}/actions/{app_key}/assets/{type}/items` | 同上 | 明细分页，query: `page`、`page_size`、`q` |
| GET | `/handover-tasks/{task_id}/actions/{app_key}/assets/{type}/overrides` | 同上 | **返回当前 generation 的完整 override 集合**与 `overrides_version`。`PUT` 是整体替换，没有这个读回入口，用户刷新页面后改一条就会把其余全部删掉 |
| PATCH | `/handover-tasks/{task_id}/actions/{app_key}/assets/{type}` | 我是 assignee | body: `{"default_action": "transfer"\|"release"\|"skip", "default_to_user_id": str\|null}` |
| PUT | `/handover-tasks/{task_id}/actions/{app_key}/assets/{type}/overrides` | 我是 assignee | body: `{"overrides_version": n, "overrides":[{"asset_id":"...","action":"transfer"\|"release"\|"skip","to_user_id":"..."\|null,"label":"..."}]}`，**整体替换**。`overrides_version` 必填，与服务端不一致返回 `409 overrides_version_stale` —— 整体替换 + 无版本号 = 后一次保存静默吃掉前一次的全部修改 |
| PATCH | `/handover-tasks/{task_id}/actions/{app_key}` | 我是 assignee | 设置**权限接收人**，body `{"grant_receiver_user_id": str\|null}`。仅 `kind=offboard` 允许非空。**门户必须有这个入口** —— 主管在门户做完数据分配却指定不了权限接收人的话，`grant_receiver` 一直是 null，授权快照全部按「只撤不转授」处理：数据搬过去了，接收人却进不了那个应用。修改后清 preview、`confirm_version + 1`，返回最新 action |
| POST | `/handover-tasks/{task_id}/actions/{app_key}/preview` | 我是 assignee | |
| POST | `/handover-tasks/{task_id}/actions/{app_key}/execute` | 我是 assignee | body **必填** `{"confirm_version": n}` —— 用户点确认时界面上显示的那一版。与服务端当前值不一致 → `409 confirm_version_stale`，**不创建 batch**，要求刷新后重新确认 |
| POST | `/handover-tasks/{task_id}/actions/{app_key}/retry` | 我是 assignee | 仅 `failed` 可重试，否则 `409 action_not_retryable`。**若 `data_completed_at` 非空，重试只重做授权转移那一步**（契约 §10.5.1.1），不重发数据 webhook |
| GET | `/handover-app-options` | 登录即可，query `subject_user_id` 必填（复用 §4 的管辖校验） | `reassign` 对话框里「应用范围」多选的**唯一数据源**。响应 `{"items": [{"app_key","app_name","handover_capability","blocked_reason"}]}`，只含 active 的 APP。<br>措辞是「该 subject **可选择**的 APP」，**不是「有数据的 APP」** —— preview 之前 EasyAuth 根本不知道下游有没有数据。没有这个端点，前端产生不出必填的 `app_keys`：借控制台 API 会 403，默认全选又违反冻结契约 |
| GET | `/handover-candidates` | 登录即可 | 选人控件数据源。query：`q`（模糊，可空）、`purpose`（枚举 `receiver` \| `reassign_subject`，**必填**）。两者都只返回 active 且非本人；`purpose=reassign_subject` 时按**契约 §4 的组织主管链**筛选（active、同 `(source_slug, corp_id)`、组织上下文非 stale 且目录同步健康、且我的 `dingtalk_userid` 在其当前 `manager_chain` 里）。**禁止调用 `resolve_managed_users`** —— 它强制要求一个 `App` 参数，而这个端点根本没有 App 可传；用它还会让团队负责人在候选列表里看到不在自己主管链上的员工（提交时才 403，但名单已经泄露出去了）。目录不可用 → `503 directory_unavailable`。**不设默认值** —— 缺 `purpose` 返回 `422 purpose_required`，否则前端漏传就会静默拿到范围过宽的人员列表 |

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
>
> **「先比较再递增」必须是一次原子 CAS，不能读一次再写一次。**
> preview 落库、`PATCH .../assets/{type}`、`PUT .../overrides`、`PATCH grant_receiver`、
> 以及 execute 的预留，**都要在同一事务里先 `select_for_update(action)`**，
> 锁内比较版本 → 改子表 → 递增版本；或者用单语句
> `UPDATE ... SET confirm_version = confirm_version + 1 WHERE id = :id AND confirm_version = :expected`，
> **影响行数不是 1 就 409 且子表零写入**。
>
> 不这么做的话：A、B 同时读到 7、各自整体替换 overrides、两边都在提交前看到 7 而都成功 ——
> 最终集合由提交时序决定，版本还可能都变成 8，A 拿着 8 去 execute，
> 服务端执行的却是 B 的接收人和条目集合。
> **下游的 `snapshot_token` 仍然只存在后端，前端不碰。**

> **`snapshot_token` 不出现在门户 API 里，前端一个字节都不用碰。** 它由 EasyAuth 在
> preview 响应中取回并存进 `HandoverAppAction.snapshot_token`（§2.2），
> items / execute 发 webhook 时由后端自动回带（契约 §10.5.1）。
> 前端只需要知道：execute 或 items 返回 **`412 snapshot_stale`** 时，要清掉本地状态并引导用户重新 preview。
> **不是 409** —— 409 会被判成不可重试的 `failed`。

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
| `PATCH .../assets/{type}` | 200 | `{"asset_type": <最新的类型对象>, "confirm_version": n+1}` —— **必须回带新的 `confirm_version`**。这个 PATCH 本身会让它 +1；不回带的话，用户改完默认接收人**立刻**点执行就稳定得到 `409 confirm_version_stale`，而他什么都没做错 |
| `GET .../overrides` | 200 | `{"overrides_version": n, "overrides": [{"asset_id","action","to_user","label"}]}` —— **完整集合**，不分页 |
| `PUT .../overrides` | 200 | `{"overrides_version": n+1, "confirm_version": m+1, "override_count": k, "dropped_invalid": j}` —— **必须回传两个新版本号**，否则前端手上还是旧值，翻到下一页再保存必然 409 |
| `POST .../preview` / `.../execute` / `.../retry` | 200 | **`{"action": <§6.2 `actions` 里的一项>}`** —— 信封键冻结，不要返回裸对象，也不要沿用既有的 `app_action`（`lifecycle_api.py:415`） |
| `GET /handover-candidates` | 200 | `{"items": [{"user_id","name","department"}]}` |

**三条硬规定**：

1. **任何 mutation 都不得返回 204。** 现有前端把非 JSON 的成功响应当异常处理
   （`frontend/src/lib/api.ts:103,107`），返回 204 会让每一次成功操作在界面上表现成失败。
2. **创建类返回 201，其余 mutation 返回 200**，都带 JSON 体。
3. **分页参数以契约为准，不是仓库默认值**：`page_size` 默认 **50**、上限 **200**
   （既有 `portal/pagination.py` 是 20/100，**不要沿用**）。超限直接钳制，不报错。
   **钳制只适用于 `page_size`。** `page` 与 `q` 越界一律 422（§5.6）——
   `03` §3.5 明写「不要钳制后继续查」，两边口径必须一致。
4. **这 14 条门户 path 必须注册在 `portal/urls.py` 的 `portal-home` 与
   `portal-react-route` 之前。** 那条 catch-all 是 `path("<path:_portal_path>", ...)`
   （`portal/urls.py:51`，`urlpatterns` 的最后一项），`<path:…>` 会吞掉含斜杠的任意路径。
   按习惯把新 API 追加在列表末尾的话，`GET /portal/api/v1/handover-tasks/137`
   会命中 SPA catch-all 返回 **200 + HTML**，而前端对非 JSON 响应体一律抛
   「服务响应格式异常，请刷新后重试。」（`frontend/src/lib/api.ts:107-108`）——
   表现既不是 404 也不是 500，排查方向完全被带偏。补一条 `resolve()` 断言测试。
   （控制台侧的同类顺序陷阱见 §6.3 的 `errors/raw`。）

**错误码**（门户专用）。**先定落法，否则下面这张表在本仓库无处安放：**

信封是 `{"error": {"code", "message", "details"}}` —— **三个字段，`details` 恒存在**
（`api/errors.py:35-46` 的 `build_error_response()` 写死了它，门户走的就是这一条，
`portal/api.py:25,271-276`）。而 `error.code` 只能取 `ErrorCode` 枚举的 **9 个大写值**
（`api/errors.py:22-32`，`@unique`）：`VALIDATION_ERROR` / `AUTHENTICATION_FAILED` /
`PERMISSION_DENIED` / `NOT_FOUND` / `CONFLICT` / `SEMANTIC_VALIDATION_ERROR` /
`INTERNAL_ERROR` / `DEPENDENCY_UNAVAILABLE` / `THROTTLED`。

**因此下表的细码一律落在 `details.reason`，不落在 `error.code`。**

```json
{"error": {"code": "CONFLICT", "message": "清单已变化, 请重新预演。",
           "details": {"reason": "snapshot_stale"}}}
```

> **不改成往 `ErrorCode` 里塞 20 多个小写成员。** 那个枚举是全 API 共用的粗分类，
> 为一个功能加一批小写值既破坏 `@unique` 之外的命名一致性，也让枚举变成功能专属。
> `details` 反正恒存在，`reason` 是天然的细化位。
>
> **这条不写死会怎样**：后端只能调 `error_response(ErrorCode.CONFLICT, …)`，
> 浏览器拿到的 `error.code` 是 `"CONFLICT"`；而前端按 `snapshot_stale` /
> `overrides_version_stale` / `out_of_managed_scope` 分支（`02` §5.3、§6.2、§7.2），
> **永远不命中** —— 412 重新预演、409 版本冲突自动重载、403 与 503 的文案区分
> 全部退化成一句通用报错，而且没有任何测试会红。
>
> `02` 的所有错误分支必须改成读 `details.reason`；`01` §6.3 的控制台错误码同规则。

| HTTP | `error.code`（粗） | `details.reason`（细，前端据此分支） | 触发 |
|---|---|---|---|
| 403 | `PERMISSION_DENIED` | `out_of_managed_scope` | reassign 的 subject 不在我的管辖范围（契约 §4） |
| 409 | `CONFLICT` | `open_task_exists` | 自助建单时已有 open 的 `offboard`/`transfer`/`pre_offboard` 单（与 §2.1 的 `lifecycle_task_one_open_lifecycle_per_subject` 同一集合）。`reassign` 单**不**触发本错误 |
| 409 | `CONFLICT` | `handover_execution_in_flight` | 该 `(subject, app)` 已有 execute 在途（含 `async_pending`），契约 §10.5.2。**不排队、不自动重试**，前端提示稍后再试 |
| **413** | `VALIDATION_ERROR` | `payload_too_large` | **不是普通失败**：只把那个超大 batch 记 `failed`，**action 保持 `previewed`**，建 `HandoverBatchPlan` 并返回 `batch_progress`。界面走「重新预演 → 执行下一批」，**不显示 [重试]**（重发同一份 payload 只会再 413） |
| **412** | `CONFLICT` | `snapshot_stale` | 下游返回 **412** 判定为快照失效，action 已退回 `pending`，需重新 preview（契约 §10.6）。**不要用 409** —— 409 会被判 `failed` |
| **423** | `CONFLICT` | `downstream_locked` | 下游返回 **423**（对象被临时锁住，如项目审批锁），action 退回 `pending`；**可重试**，但要等人解除锁 |
| 409 | `CONFLICT` | `action_not_retryable` | 对非 `failed` 状态的 action 调 `retry` |
| 422 | `SEMANTIC_VALIDATION_ERROR` | `reason_required` | reassign 未填理由或不足 10 字符 |
| 422 | `SEMANTIC_VALIDATION_ERROR` | `receiver_not_active` / `receiver_is_subject` / `receiver_required` / `asset_type_not_releasable` / `duplicate_assignment` | §5.4 |
| 400 | `VALIDATION_ERROR` | `detail_not_supported` | 该资产类型不支持明细 |
| **503** | `DEPENDENCY_UNAVAILABLE` | `directory_unavailable` | subject 的 `DingTalkUserOrgContext` 缺失、`stale=true`、或 `manager_chain` 元素畸形。**与 403 分开**：403 是"上下文健康但你不在他的主管链上"，503 是"组织目录现在不可用"。两者都 fail-closed，但审计事件与用户文案不同（前者提示联系管理员，后者提示稍后重试），运维也要能区分是越权还是依赖故障 |
| 422 | `SEMANTIC_VALIDATION_ERROR` | `purpose_required` | `/handover-candidates` 缺 `purpose` 参数 |
| 409 | `CONFLICT` | `action_blocked` | 对 `blocked` 状态的 action 调 preview/execute（未接入 APP，D6；只有超管能 skip） |
| 409 | `CONFLICT` | `confirm_version_stale` | `execute` 回带的 `confirm_version` 与服务端不一致（§2.2）。**不创建 batch** |
| 409 | `CONFLICT` | `overrides_version_stale` | `PUT overrides` 回带的 `overrides_version` 与服务端不一致（§2.2） |
| 409 | `CONFLICT` | `batch_plan_in_progress` | 存在 `completed_batches > 0` 的 `HandoverBatchPlan` 时改分配（§2.4.1.1） |
| 409 | `CONFLICT` | `idempotency_conflict` | 同一 `Idempotency-Key` 配不同 body（本节上方的幂等规则） |
| 422 | `SEMANTIC_VALIDATION_ERROR` | `idempotency_key_required` | 建单类端点缺 `Idempotency-Key` 头 |
| 422 | `SEMANTIC_VALIDATION_ERROR` | `items_page_out_of_range` / `items_query_too_long` | items 的 `page` 或 `q` 越界（§5.6）。**在下发给下游之前就拦掉** |
| 429 | `THROTTLED` | `rate_limited` | items 触发 `(actor, task_id, app_id)` 限流（§5.6） |

> 上面这 8 行不是补充说明，是**冻结契约的一部分**。它们在本文别处都有定义，
> 但 §6.1 才是 A2 建 `ApiError` 分支时照抄的那一份 —— 漏在这里，
> 前端就只能把 `confirm_version_stale` / `overrides_version_stale` 这两个**最高频的并发提示**
> 退化成「未知错误」。`batch_plan_in_progress` 尤其不能漏，`02` §4 已经在消费它了。

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
  "escalation": { "deadline": "2026-08-24T10:00:00Z", "days_left": 14, "level": 0, "deferred_at": null,
                   "defer_history": [] },   // [{escalation_level, actor_id, at, reason}], 由审计事件生成, 永久保留
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
      "skipped_by": "", "skipped_at": null, "skip_history": [],
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
      "skipped_by": "", "skipped_at": null, "skip_history": [],
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
| `allowed_actions` | `("preview"\|"execute"\|"retry"\|"skip")[]`，**由后端算好**。前端据此决定按钮，**不得解析 `last_error` 去猜可不可重试**。**直接查契约 §10.6 表的「可重试」列**，不要写成「4xx 除 400 不可重试」这种会漂移的近似规则 —— §10.6 里 423 和 429 都是 4xx 且都标着「可重试」（它们目前不落 `failed`、因而不经过 `retry` 入口，是巧合不是设计）。`failed` 且非在途 → 控制台含 `skip`（门户永远不含，D6 是超管专属） |
| `skip_history` | `{generation, actor_id, reason, skipped_at}[]`，来自 `HandoverActionSkipRecord`（§2.2）。**与 `skipped_by`/`skipped_at` 的区别是轮次**：那两个是**当前轮次**、升级时会被清空；这个是**跨轮次永久**。契约 §9.2 的「单据上永久显示」只有它保证得了 |
| `batch_progress` | 413 分批时非 null：`{"completed": 1, "total": 3, "current_batch_seq": 2}`；未分批时 null |
| `approval_instance_warning` | `{"message": str, "link": str, "recorded_at": str} \| null`。建单时一次性写死并持久化（§4.5.3），**升级与完成都不清除** |

`GET /me/handover-tasks` 的列表项是上述对象去掉 `actions`/`team_items`，另加
`pending_app_count`、`blocked_app_count`、`total_asset_count`，同样包在
`{"handover_tasks": {"as_assignee": [...], "as_subject": [...]}}` 里。

### 6.3 控制台（`/console/api/v1/lifecycle/`，超管）

既有端点**不是原样保留**，先处理两处会直接崩掉的既有形状：

- **`PATCH /console/api/v1/lifecycle/handover-tasks/{id}` 的 `app_actions` 字段整体删除**，
  只保留 `{"cancel": bool}`。该职责由下方新增的 `PATCH .../actions/{app_key}` 承接。
  > 不删就是一个「import 与属性都在、一调就 500」的端点：
  > `admin_console/lifecycle_api.py:102-105` 的 `HandoverTaskPatchPayload.app_actions`
  > → `:694 _patch_receiver_batch()` → `lifecycle/handover.py:82-115 update_action_receiver()`，
  > 直接读写 `locked.to_user`（`:107`）与 `locked.policy`（`:103,108`）——
  > 而 §2.2 把 `policy` **删了**、`to_user` 改名成了 `grant_receiver`。
  > `AGENTS.md` 禁止兼容层，所以只能删字段，不能留个转接。
- **单 action 的 mutation 响应信封冻结为 `{"action": <§6.2 actions 里的一项>}`。**
  既有的 `lifecycle_api.py:415` 返回的是 `{"app_action": ...}`，而数组已按 §6.2 改名成
  `actions`（既有是 `lifecycle_api.py:895` 的 `app_actions`）—— 单数不跟着改就自相矛盾，
  门户与控制台还会各自发明键名（裸对象 / `action` / `app_action`），
  前端共享组件拿不到统一形状。消费者一起迁。

**`GET .../handover-tasks` 列表要加参数与字段**：

- 新增 query：`assignee_state=manager|subject|superuser_pool`、`blocked=true|false`；
  非法枚举值 → `422`。**筛选必须在数据库分页之前完成** —— 在当前页做本地过滤的话，
  分页总数与后续每一页都是错的。
- 列表项新增：`assignee_state`、`escalation`、`blocked_app_count`。

新增端点：

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `.../handover-tasks/{id}/actions/{app_key}/skip` | 强行跳过（D6），body `{"reason": "..."}`，`reason` 必填且 ≥10 字符。**实现方式：扩展既有的 `operation=="skip"` 分支**（`admin_console/lifecycle_api.py:362,403`），不要新注册一条会与既有动态 operation 路由（`admin_console/urls.py:252`）重叠的 URL —— 注册在后面就永远不可达。现有 handler **完全不读 body 里的 reason**，必须补：严格解析 `{"reason": str}`、校验 ≥10 字符、传给 `skip_action(action, actor_id=..., reason=...)` |
| POST | `.../handover-tasks/{id}/actions/{app_key}/async-abandon` | **`async_attention_required` 的唯一出口**（§7）。body `{"outcome": "done"\|"failed", "reason": "...", "summary": {...}\|null}`，`reason` 必填且 ≥10 字符。语义是「超管**已在下游人工确认**该异步任务的真实结局」，因此必须二选一写死终态：`done` 时把人工确认的 summary 落库并走 `complete_data_phase()` 的授权步骤，`failed` 时写 `failed`。**同一次 fence CAS 里释放租约**，写 `handover_action_executed` 或 `handover_action_failed` 审计并在 metadata 标记 `manual_resolution=true`。<br>没有这个端点，`async_attention_required` 就是个没有任何出口的终点：不能 retry（不是 `failed`）、不能 skip / cancel（租约未释放）、没有 beat 会推进它，`(subject, app)` 永久锁死 |
| POST | `.../handover-tasks/{id}/claim` | 超管认领 `superuser_pool` 中的单：同一事务内置 `assignee`、`assignee_state=manager`、**`escalation_deadline = now + HANDOVER_ESCALATION_DAYS`**、清 `escalation_deferred_at`，并写 `handover_assignee_assigned` 审计。<br>**不重置 deadline 的话这张单会脱离所有自动上交扫描**：落池时 deadline 被清空，认领只写 assignee —— 这位超管若不再处理，beat 因 `deadline IS NULL` 永远扫不到它，而界面又按 null 显示「待超管认领」，责任人与展示互相矛盾。到期且主管链已耗尽时重新退回 `superuser_pool`（清 assignee 与 deadline），允许别人再认领。**认领人必须是 active、非 `local-admin:`、且有有效钉钉绑定的 OIDC 超管**，否则 `403 local_admin_cannot_claim` |
| POST | `.../handover-tasks/reassign` | **超管跨管辖范围建 `reassign` 单**（D9 的「跨部门走超管」路径）。body 同门户版，但**不做管辖范围校验**；仍校验双方 active、双方非本地管理员、`reason` ≥10 字符、接收人 ≠ 当事人。写审计 `handover_reassign_created`（`initiator` 记该超管） |
| POST | `.../handover-tasks/{id}/escalation/defer` | 把 `escalation_deadline` 顺延 `HANDOVER_ESCALATION_DAYS`（不改 `escalation_level`），**body `{"reason": "..."}` 必填且去空白后 ≥10 字符**（空 body → 422）。**同一 `escalation_level` 内至多一次**（靠 `escalation_deferred_at` 判定，非空即拒 `409 already_deferred`）；上交后该字段清空，新层级可再顺延一次。写审计 `handover_task_deferred`，单据上永久显示「已由 {超管} 于 {时间} 顺延：{理由}」 |
| GET | `.../approval-rule-replacements` | query `resolved=false`（默认）。响应 `{"items": [{"id", "approval_rule": {...}, "departed_user": {...}, "reason", "created_at"}], "total": n}`。**没有这个列表，§4.5.2 造出来的待办行谁都发现不了** —— 规则里仍挂着离职者，新权限申请解析不到有效审批人，而那条待办无限期没人处理。控制台按 `total > 0` 常驻计数告警 |
| POST | `.../approval-rule-replacements/{id}/resolve` | body `{"approver_user_ids": ["..."]}`（非空）。**同一事务内**锁待办与规则 → 替换审批人 → 写 `resolved_at`/`resolved_by`。并发重复 resolve 由 `resolved_at IS NULL` 的条件更新兜底，影响行数为 0 → `409 already_resolved` |
| GET | `.../handover-blocked-apps` | 未接入 APP 汇总，供控制台顶部告警条。响应 `{"app_count": n, "task_count": m, "apps": [{"app_key","app_name","blocked_task_count"}]}` |
| GET | `.../handover-app-options` | 控制台版的应用范围数据源，query `subject_user_id`。响应与门户版同形状，但走 `require_superuser()` 且**不做管辖校验**（超管跨部门 reassign 用，§6.3 的 `handover-tasks/reassign`） |
| GET | `.../handover-tasks/{id}/candidates` | **控制台专用的选人数据源**，query `q`。响应 `{"items": [{"user_id","name","department"}]}`，只含 active、非本地管理员、且**不等于本单 subject** 的用户。<br>**不要让前端把门户 URL 前缀换成控制台前缀了事** —— 现有 `/console/api/v1/user-options` 的 `purpose` 只接受 `employee` \| `approver`（`admin_console/users_api.py:66-90`），传 `receiver` 直接 422；传 `employee` 又会把当事人本人列进候选，一直到 execute 才报 `receiver_is_subject`。共享组件通过 **surface adapter** 注入 API，不做字符串替换 |
| GET | `.../handover-tasks/{id}/actions/{app_key}/assets/{type}/items` | 与门户同规格（§5.6 的参数上界与限流同样适用），但走 `require_superuser()`、**不做 assignee 校验** |
| GET | `.../handover-tasks/{id}/actions/{app_key}/assets/{type}/overrides` | 同上，返回完整 override 集合与 `overrides_version` |
| PUT | `.../handover-tasks/{id}/actions/{app_key}/assets/{type}/overrides` | 同上，整体替换，`overrides_version` 必填 |
| PATCH | `.../handover-tasks/{id}/actions/{app_key}/assets/{type}` | 同上，改类型级 `default_action` / `default_to_user_id`，回带新 `confirm_version` |
| GET | `.../handover-tasks/{id}/actions/{app_key}/errors/raw` | **超管专用**，返回 `{"last_error_raw": "..."}`。**每次读取先写审计**（谁、何时、看了哪个 action 的原始错误），再返回。该字段**禁止**出现在门户响应与普通详情响应里（契约 §10.6） |
| GET | `.../apps/{app_key}/handover-capability` | 能力标签页的**初始数据**。响应 `{"handover_capability": "declared"\|"none"\|"undeclared", "handover_asset_types": [...], "handover_url": "", "declared_by": "", "declared_at": null, "synced_at": null}`。**没有这个 GET，能力标签页打开就是空白** —— 既有 app detail 不返回三态，冻结契约里也只有两个 POST |
| PATCH | `.../handover-tasks/{id}/actions/{app_key}` | 设置**权限接收人**，body `{"grant_receiver_user_id": string\|null}`。仅 `kind=offboard` 允许非空，否则 `422`。修改后该 action 回退 `pending` 并清除上一轮 preview 结果（接收人变了，之前的预演不再代表现在的意图）。返回更新后的 action 对象 |
| POST | `.../apps/{app_key}/handover-capability` | 声明 `none`，body `{"reason": "..."}`；写 `declared_by`/`declared_at` |
| POST | `.../apps/{app_key}/handover-capability/sync` | 手动触发 §5.2 descriptor 同步 |

上面四条资产/明细端点**必须真的建出来，别只写一句「另注册一套」就算数**：
`02` §7.1 的控制台向导第 3 段直接内嵌门户那套 `AssetAllocator` 组件，
组件里写的是无前缀相对路径。冻结表里没有控制台版本的话，A2 只有两条路 ——
要么不做（控制台向导第 3 段没有后端，D10 的条目级分配在控制台完全用不了），
要么直接拼门户前缀，那正好撞上下面这条禁令，而超管不是 assignee，
门户 guard 会稳定回 404。`02` §6 的路径写法要标注由 surface adapter 注入前缀。

**`errors/raw` 是两段路径，不是 `last-error-raw` 一段，这不是风格问题。**
`admin_console/urls.py:252` 注册的是
`.../actions/<str:app_key>/<str:operation>` —— `<str:…>` 吃掉任意非空单段，
`last-error-raw` 会被当成 `operation` 命中它，然后 `lifecycle_api.py:373-374`
对非 POST 直接回 405；即使改成 POST 也会落到 `:405-406` 的
「操作必须为 preview、execute、retry 或 skip」400。
控制台「查看原始错误」按钮 100% 失败，而要求的「每次读取先写审计」一次都不会执行。
本节上面已经就 `skip` 警告过同一个陷阱，这条是对称的遗漏。

**控制台不复用门户的 URL 与 view。** 资产/明细能力在控制台下**另注册一套路径**
（`/console/api/v1/lifecycle/handover-tasks/{id}/...`），走 `require_superuser()` 且不做 assignee 校验，
两边只共享**不含任何 HTTP 身份逻辑**的 domain service。

> 早期写的"控制台复用 §6.1 的端点"与本节开头的"各自注册路由与 guard"直接冲突。
> 混在一个入口上，assignee 校验、404 防枚举、本地管理员拒绝这三条会在两条调用路径上
> 表现不一致 —— 最坏的情况是本地管理员从控制台入口拿到了门户语义。
> 统一规定：**门户一律 `require_portal_user()`（内含拒绝 `local-admin:`），
> 控制台一律 `require_superuser()`。**

### 6.4 审计事件的落点（契约 §12 全表必须有主）

契约 §12 冻结的**全部**事件（不要在这里手写数量 —— 理由见本节末尾那条自己写的警告）。
**每一个都必须有明确的写入位置，缺一个就是验收失败**
（`00` §15 第 9 条要求「§12 全部出现」）。

**先改 `record_task_event()` 的 actor 归类，否则整张表记出来的 actor 都是错的。**
现有实现是二值硬编码：`actor_type = "system" if actor_id in {LIFECYCLE_ACTOR_ID,
"directory_sync"} else "admin"`（`lifecycle/core.py:107`）—— **没有 `user` 分支**。
而 v2 里 `handover_reassign_created`、`handover_action_previewed` / `_executed` / `_failed`
主要是**门户的普通员工与主管**触发的，全会被记成 `admin`。
`actor_type` 是无枚举约束的自由 CharField（`audit/models.py:48`），不会报错，只会静默写错；
`AuditLog` 上还有 `(actor_type, actor_id, -created_at)` 索引（`audit/models.py:64`），
按 actor_type 的运维查询会全部失真，而 §6.3 的原始错误读取审计、§9 的顺延/跳过责任链、
`00` §15 第 9 条的验收，都建立在 actor 可区分之上。

改法：`record_task_event()` 增加显式 `actor_type` 参数（`system` / `user` / `admin` 三值），
门户入口一律传 `user`、控制台入口传 `admin`、beat 传 `system`；
`tests/unit/lifecycle/test_audit_events.py` 的逐事件断言同时校验 `actor_type`。
（仓库其他门户/控制台写法用的就是 `actor_type="user"`，如 `admin_console/webhook_config_api.py:106`。）

对照表：

| 事件 | 写在哪 |
|---|---|
| `handover_task_created` | `lifecycle/offboarding.py` 建单事务内；门户 `pre-offboard` / `reassign` 建单同事务 |
| `handover_task_upgraded` | §5.1.2 的升级事务内，与 `generation += 1` 同事务 |
| `handover_assignee_assigned` | **所有 assignee 变更统一走 `apply_assignee()`**：初始解析、逐级上交、**以及超管 `claim`**。与 assignee 写入同事务，记录 actor 与 reason。<br>漏掉 claim 这条路径的话，单据从超管池被认领后 assignee 已经变了，而审计里只留着「落池」那一条 —— 谁在什么时候接下了这张单，查不出来 |
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
| `handover_assignee_chain_entry_malformed` | §3 主管链解析：跳过畸形元素时 |
| `handover_reassign_scope_revoked` | §6.1 `reassign` 单的管辖权复核失败时 |

`tests/unit/lifecycle/test_audit_events.py` 逐事件断言：触发一次对应操作，
审计表出现且仅出现一行，关键字段非空。
**用例参数从契约 §12 的事件集合生成，不要手写数量** —— 手写一个数字，表格再加一行时测试仍然绿。

---

## 7. 异步任务（`tasks/lifecycle.py`，**扩展既有文件**）

| 任务 | 周期 | 逻辑 |
|---|---|---|
| `lifecycle_escalation` | beat 每 10 分钟 | 扫 `status in OPEN and escalation_deadline <= now` 的 `HandoverTask`，逐个 `escalate_overdue_task()`。PostgreSQL 下 `select_for_update(skip_locked=True)` 分批（与 `grants` 过期任务同款） |
| `lifecycle_daily_reminder` | beat 每天 09:00（Asia/Shanghai） | 对未完成且有 assignee 的单发钉钉提醒；上交前 1 天额外发"即将上交"。注意既有 beat schedule 只接受 float interval，crontab 需扩展。**去重不能只靠"读一下 `last_reminded_on` 再写回"**，见下 |
| `lifecycle_recover_expired_execution_leases` | beat 每 **1 分钟** | 扫 `released_at IS NULL AND lease_expires_at <= now` 的租约，按 §2.4.2 的「先抢占、后重放查证」协议接管。**没有这个任务，worker 发完网崩溃就是一条永久锁死的租约** —— TTL 只让它过期，不会有任何东西去接管。轮询到第 10 次（`ASYNC_POLL_MAX_ATTEMPTS`）仍非终态时 **只告警、不释放**，见 §7 的说明 |
| `lifecycle_poll_async_actions` | beat 每 **1 分钟** | 扫 `status IN (async_pending, async_attention_required)` 的 action，逐个调既有 `poll_async_action()`；后者用更长的退避周期（`ASYNC_ATTENTION_POLL_INTERVAL = 30 分钟`）继续轮询**并继续续租**。**这个任务不存在的话，202 就是个死胡同**：action 进 `async_pending` 后门户不允许 retry（在途）、也没有任何东西去 poll，永远到不了 `done`/`failed`，租约也永远不释放。<br>**上限沿用既有的 `ASYNC_POLL_MAX_ATTEMPTS = 10`**（`lifecycle/core.py:30`），不要新造一个。
**但第 10 次仍非终态时不能标 `failed`、更不能释放租约** —— 见下方警告。`Location` 头持久化在 `async_status_url` 上，每次响应带新 `Location` 就更新。拿到终态 200 后**必须走 `complete_data_phase()`**，不得直接置 `done`。<br>**第 10 次仍非终态：只写告警并把 action 置 `async_attention_required`，sentinel 继续持有并续租** |

> **轮询超次数不能释放租约。** 契约 §10.5.2 写死了「超时不得直接强解，必须先向下游确认真实状态」——
> 而"轮了 10 次还没终态"**恰恰是没确认到终态**。
>
> 释放会怎样：下游那个异步任务其实还在跑；EasyAuth 放开 `(subject, app)` 租约 →
> 新建的单取得租约、搬同一批资产 → 旧任务随后完成 → **两个不同的幂等三元组先后覆盖同一批归属**，
> 而 fence 撤不回一个已经交出去的下游任务。
>
> 正确处理：标 `async_attention_required`（新增的 action 状态）、写告警、**sentinel 继续持有并续租**。
> 只有在「原三元组重放」或「状态查询」拿到**可证明的终态**之后，才允许 CAS 释放。
> 下游长期给不出终态，就是一个需要人介入的事故 —— 让它显式停在那里，比悄悄放开锁安全。

> **但「需要人介入」必须真的有人能介入，否则它就是第 5 个死锁。** 这一条是冻结要求：
>
> 1. **要有东西继续轮询它。** 轮询任务的扫描条件必须包含 `async_attention_required`（见上表），
>    否则状态一改，`lifecycle_poll_async_actions` 立刻扫不到它 ——「sentinel 继续持有并续租」
>    就没有执行主体了。此时租约会过期，`lifecycle_recover_expired_execution_leases` 每分钟抢占一次、
>    重放一次真实 execute、拿到 202、再交还给一个永远不看它的轮询器，**变成无限重放循环**。
> 2. **要有人工出口。** 进入这个状态的 action：不能 retry（状态不是 `failed`）、
>    不能 skip 也不能 cancel（§5.5.1 禁止对未释放租约的 action 操作）、
>    没有任何 beat 会推进它。必须提供 §6.3 的 `async-abandon` 端点作为唯一出口，
>    否则这张单永久卡死，而且一直占着 `(subject, app)` 的互斥租约 ——
>    **该员工在该 APP 上此后再也建不出可执行的交接单**。
>
> §6.2 的 `409 payload conflict → 转人工告警，租约保持` 用的是同一个出口。
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
2. `lifecycle_http_response()` / `easyauth_lifecycle_router()` **必填**
   `callbacks: LifecycleCallbacks`；它是 frozen dataclass，必填字段为 `on_handover_preview`、
   `on_handover_execute`、`on_handover_items`，由 SDK 按事件分发。
3. `DEFAULT_MAX_BODY_BYTES` 由 `64 * 1024` 改为 `256 * 1024`（契约 §10.1）。
4. `fastapi.py` 的挂载 helper 同步把 `callbacks: LifecycleCallbacks` 列为必填参数，并透传
   `signature_failure_status` 与响应头（含 `Retry-After`）。
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
       def __init__(
           self,
           status_code: int,
           code: str,
           message: str,
           *,
           retry_after: int | None = None,
       ) -> None: ...

   ALLOWED_BUSINESS_STATUS: Final = frozenset({400, 409, 412, 413, 422, 423, 429})
   ```

   ``retry_after`` 可选：内核渲染为响应头 ``Retry-After``（秒）。契约 §10.6 要求
   EasyAuth 对 **429** 按该头退避；其它状态码也可携带，由发送端决定是否消费。

   内核：

   ```
   try:
       result = callback(event)
   except HandoverBusinessError as e:
       if e.status_code not in ALLOWED_BUSINESS_STATUS:
           logger.warning(...)   # 白名单外降级 500 必须写 SDK 侧告警
           return _error_response(500, "handover_callback_failed", 固定文案)
       return _error_response(e.status_code, e.code, e.message, retry_after=e.retry_after)
   except Exception:
       logger.exception(...)     # 意外异常记 exception, 响应仍用固定文案
       return _error_response(500, "handover_callback_failed", 固定文案)
   return _json_response(200, result)
   ```

   状态码**白名单**是有意的：不允许 APP 随便返回 2xx/3xx，否则 EasyAuth 的状态机会被喂进
   它无法解释的输入。白名单外的值按 500 处理并写 SDK 侧 warning。

6.2 **`WebhookVerificationError` 必须带稳定 reason，时间戳超窗与签名不匹配要分开**。
   现在 SDK 把两者一律当验签失败（`webhook.py:61-73` → `lifecycle.py:108-111` 统一 403），
   而契约 §10.6 里 **400 可重试、401/403 不可重试**：
   一次时钟偏差或请求延迟超过 300 秒，会被 EasyAuth 判成"签名校验失败, 请检查该应用的
   webhook 密钥"、隐藏重试按钮 —— 时钟恢复之后也重投不了，只能强行 skip 或取消整单，
   而数据其实一条都没交接。

   | reason | HTTP |
   |---|---|
   | `INVALID_TIMESTAMP` / `TIMESTAMP_SKEW` | **400**（不受旋钮影响） |
   | 签名不匹配、鉴权头缺失 | ``signature_failure_status``（默认 **403**；EasyProject 传 **401**） |

   **禁止解析异常文案来分支** —— reason 是结构化字段。内核把 ``reason`` 写入错误体
   ``error.reason``（与 ``code``/``message`` 并列），便于下游日志与联调对齐冻结向量。

   ``lifecycle_http_response(..., signature_failure_status: int = 403)`` 与
   FastAPI helper 同参：只作用于签名/鉴权头失败，**不**改时间戳超窗的 400。

7. **回调异常边界不得回显异常文本**（契约 §10.6）：现有
   `_error_response(500, "handover_callback_failed", f"交接回调执行失败: {error}")`
   会把 `str(error)` 拼进响应体。改为固定通用文案（「交接回调执行失败, 请查看应用日志」），
   真实异常由 APP 自己记日志；SDK 侧对意外异常调用 ``logger.exception``。
   理由：该响应体会被 EasyAuth 存下并展示给主管（普通员工）。
8. 新增 `easyauth_app_sdk/manifest.py` 的 `_validate_lifecycle()` 白名单加 `handover_asset_types`
   （契约 §9.1）。**不改这一处，两个下游连 descriptor 都生成不出来**（会抛
   `ManifestValidationError: lifecycle 含未知字段`）。
   当 `handover_asset_types` 存在时，逐项 **必填** `type`/`label`（非空字符串）与
   `detail_supported`/`releasable`（布尔，不得缺省或非 bool）。
9. **不新增目录端点** —— 现有 `get_directory_user(user_ref)` 本来就接受裸 Authentik `sub`：
   `parse_user_ref()` 对不以 `dt:` 开头的引用一律按 `kind="authentik"` 解析
   （`accounts/directory_references.py:58-60,90-105`）。
   要做的只是**把这件事写进 SDK 的 docstring 与 README**（现在的措辞让人以为只收 opaque ref），
   可以再加一个纯委托的别名提升可读性。**不要为此造第二个服务端端点。**
10. 新增包内数据资源 `easyauth_app_sdk/contract_samples/handover_v2/*.json`（§10），
    并在 `pyproject.toml` 的打包配置里显式包含（`package-data`），否则 wheel 里没有这些文件。
11. `sdk/python/CHANGELOG.md` 记为 **breaking**；版本号锁死并记录 **commit SHA 与 wheel SHA-256**
    （README「解锁凭据」）。`pyproject.toml` version、`descriptor.SDK_VERSION`、`uv.lock`、CHANGELOG
    四处取同一个值 —— 只改源码不改版本号会让下游 vendor 到不同提交而无人发现。
12. `sdk/python/README.md` 补 v2 接入示例（中文）。

### 8.1 EasyAuth 发送端的配套改造（**不在 SDK 里，但必须与 SDK 同批上线**）

**所有 webhook 发送入口在签名之前原子注入 `payload["event_type"] = event_type`。**

`webhook.test` 的**落库** payload 也必须含 `"event_type": "webhook.test"`
（`admin_console/webhook_config_api.py` 创建时写入），使控制台「原文」与签名字节一致；
发送端注入只是兜底，不得靠它才能让 SDK 过 `event_type` 校验。
新版 SDK 会在 `webhook.test` 短路之前比对该字段，缺了就 422，
而 README 的联调门禁正是「`webhook.test` 对每个 APP 返回 200」——
**不做这一步，门禁永远过不去，而且看起来像下游的问题。**

**发送端有两个真实出口，两个都要改**（只改一个的话另一半照样 422）：

| 出口 | 覆盖的事件 |
|---|---|
| `webhooks/hooks.py::signed_hook_post` | preview / items / execute |
| **`webhooks/delivery.py::attempt_delivery`** | **`webhook.test`** —— 控制台的测试按钮走 `enqueue_delivery()` 把 body 存进 `WebhookDelivery`，最终由这里原样序列化并签名，**根本不经过 `hooks.py`** |
| `webhooks/hooks.py::signed_hook_get`（**只列出来，不注入**） | 202 的异步状态查询（`lifecycle/handover.py:272-277` 调它，`event_type=HOOK_EVENT_EXECUTE`）。它 **body 是 `b""`**，没有可注入的地方 —— 列在这里是为了避免实现者以为漏改了它 |

前两处都必须**复制一份 payload**、在序列化与签名**之前**强制覆盖 `event_type`
（注入在签名之后等于没做）。

> **第三个出口带出一个真问题：SDK 现在验不了空 body 的签名请求。**
> `signed_hook_get` 同样带 `X-EasyAuth-Event` 与签名头（`hooks.py:105,109`），
> 签的是 `timestamp + "." + b""`；而 SDK 的 `verify_webhook()` 会
> `json.loads(raw_body.decode())`（`sdk/python/src/easyauth_app_sdk/webhook.py:74-79`），
> 对 `b""` 抛 `JSONDecodeError` → `WebhookVerificationError`。SDK 里也没有任何状态查询 helper。
>
> 后果：任何按 §8 用 SDK 实现 202 异步的下游，其状态查询端点**每一次轮询都会验签失败**，
> action 卡在 `async_pending` 直到轮询上限、进 `async_attention_required`，
> 而 §7 又要求那期间不释放租约 —— 「202 是个死胡同」以另一种方式成立。
>
> 因此 §8 的交付物增加一项：**`verify_webhook()` 支持空 body**（GET 分支跳过 JSON 解析，
> 只验 `timestamp + "." + b""` 的签名并返回空 payload），
> 或新增 `verify_status_request()`。契约侧在 §10.1 注明状态端点的验签口径与此一致。
> 本期若不做 202，则 §7 必须显式关掉这条路径，而不是留一个 SDK 侧实现不了的必跑 beat。
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
| `tests/unit/lifecycle/test_assignments.py` | §5.4 六条校验；三值 action 的库层 CheckConstraint；`releasable=False` 时 `skip`+逐条 `transfer` 可用（部分交接不依赖 releasable）；override 唯一约束；**`PUT .../overrides` 提交失效 `asset_id` 时被清理并计入 `dropped_invalid`**（判定落在这里，不在 preview —— preview 响应没有明细，判不了） |
| `tests/unit/lifecycle/test_upgrade.py` | pre_offboard → offboard 升级：kind 变更、generation+1、assignee 重解析、上交截止时间重置；**§5.1.2 逐字段重置**（`data_completed_at`/`snapshot_token`/`batch_seq`/`last_error` 全部清空）；上一轮超管 skip 的 APP 若仍未接入则回到 `blocked` 而非继承 `skipped`；存在未释放租约时升级返回 409 |
| `tests/unit/lifecycle/test_reassign.py` | 管辖校验、必填理由、与 offboard 单并存不违反唯一约束、三方通知 |
| `tests/integration/test_portal_handover_api.py` | §6.1 全部端点的权限边界（非 assignee 拿到 404） |
| `tests/integration/test_handover_webhook_v2.py` | payload 形状逐字段比对契约样本（读法见下）；幂等键 `(task_id, generation, batch_id)` |
| `tests/unit/test_blocked_never_completes.py` | 存在 blocked 时 `refresh_task_status` 永不返回 completed（D13） |
| `tests/integration/test_batch_plan.py` | 413 → 建计划（`total=M`、`assignment_hash`）；非最终批成功后 action 仍 `previewed`；`completed>0` 时改分配返回 409；`completed=0` 时改分配原子重规划；**三批计划里第 1 批成功并按流程重新 preview 之后，第 2 批的 `assignment_hash` 校验必须通过**（缺这一条，§2.4.1.1 那个「被消耗的 override 反而把后续批次卡死」的死锁跑测试也发现不了） |
| `tests/integration/test_execution_lease.py` | **PG lane**：并发 execute 只有一个拿到租约；**`retry` 与另一张单的 execute 并发时也只有一个拿到租约**；续约/抢占谓词；过期恢复任务「先抢占后查证」；**§2.4.2 释放表里的每一行**都真的释放（含 400 / 429 / 授权转移失败）；旧 fence 的写回影响 0 行并被丢弃 |
| `tests/integration/test_async_attention.py` | **新增**：轮询到上限 → action 转 `async_attention_required` 且租约仍持有；轮询任务仍能扫到它并继续续租；`async-abandon` 二选一写终态并在同一次 CAS 释放租约；没有该端点时 retry/skip/cancel 全部被拒（回归用例，防止出口被删掉） |
| `tests/integration/test_async_handoff.py` | 202 → sentinel 移交；poll claim/续租/移回；终态走 `complete_data_phase`；第 10 次仍非终态 → `async_attention_required` 且**租约不释放** |

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
| CI（权威门禁） | `uv sync --extra dev --frozen` 后 <br>`.venv/bin/pytest tests/unit/lifecycle tests/unit/test_blocked_never_completes.py tests/integration -q` | 单测 **+ 本章列出的全部 integration**。**只写 `tests/unit/lifecycle` 会把 integration 整段漏掉，而门禁照样是绿的** |
| **PostgreSQL lane（必须）** | `EASYAUTH_POSTGRES_PASSWORD=... docker compose up -d postgres` 后，**显式设置 `DATABASE_URL` 指向它**再跑 `.venv/bin/pytest tests/integration -q` | **约束触发器、条件唯一约束、租约并发、`SELECT ... FOR UPDATE`** |

> **PG lane 必须显式设连接串并断言真的连上了 PostgreSQL。** 不给密码或不设
> `DATABASE_URL` 时，配置会**静默回退到 SQLite**（`config/settings/base.py:116`）——
> 于是这条 lane 看起来跑过了，实际一条触发器、一次真并发都没验证。
> 在 conftest 里加一句 `assert connection.vendor == "postgresql"`。

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

### 11.1 本仓库的量偏大，建议拆成三个 agent

| 分工 | 内容 | 何时开始 |
|---|---|---|
| **A1a** | 只做 §8 的 SDK 0.4.0 发布 | 第 0 天，做完即撤 |
| **A1b** | §2 模型 + 迁移 + §5 执行链（租约、批次、两次 sentinel 移交、`complete_data_phase`、状态汇总纯函数）、**§3 `lifecycle/assignee.py`、§4 `lifecycle/escalation.py`**，以及 **§7 里要动 `lifecycle/handover.py` / `lifecycle/models.py` 的那部分**（`poll_async_action()` 改造、`async_attention_required` 常量、租约接管协议） | 与 A1a 并行 |
| **A1c** | §6 的 32 个 HTTP 端点（14 门户 + 18 控制台）+ §4.5 审批责任改派 + §7 的 beat 注册与调度壳（`tasks/lifecycle.py`） | **等 A1b 的模型层落地之后** |

> **§3 与 §4 必须显式有主。** 早先的分工只列了 §2/§5/§6/§4.5/§7，
> `lifecycle/assignee.py` 与 `lifecycle/escalation.py` 这两个**新建文件**（见 §1 改造总览）
> 落在任何一行之外 —— 而 §6.3 的 `claim` / `escalation/defer`、§6.4 的
> `handover_assignee_assigned` / `handover_task_escalated` 落点、§7 的 `lifecycle_escalation` beat
> 全都依赖它们，三方都会以为对方在做。归到 A1b：`apply_assignee()` 要与 assignee 写入同事务，
> 天然属于模型层。
>
> **§7 也必须按文件切，不能整节给 A1c。** §7 明写「拿到终态 200 后必须走
> `complete_data_phase()`」「把 action 置 `async_attention_required`」「按 §2.4.2 的协议接管租约」
> —— 这三件事分别落在 `lifecycle/handover.py`（现状 `poll_async_action` 在
> `handover.py:261-321`，直接置 `done`）与 `lifecycle/models.py` 的状态常量表，
> 正是下面那条「不能同时改同一批文件」点名的两个文件。整节给 A1c 的话，隔离承诺是纸面的。

> **A1b 与 A1c 不能真正同时改同一批文件。** §11 第 2 条要求 schema 变更与全部调用方
> **在同一个 commit** 里；两人并行改 `lifecycle/models.py` 与 `lifecycle/handover.py`
> 必然互相踩。次序是：A1b 先把模型与执行链落成一个可运行的提交，A1c 再在上面加 API 层。
>
> **A1a 与它们完全独立**（SDK 只依赖已冻结的契约，不依赖本仓库实现），可以第一天就并行。
>
> 整个项目里**并发语义最难的部分全在 A1b**：租约的取号/续约/抢占/CAS、两次 sentinel 移交、
> 413 分批计划。建议这一片**先写测试再写实现**，且租约用例必须跑真 PostgreSQL
> （SQLite 上跑过了不说明任何问题，见 §10）。

每完成一项立即单独 commit；提交后必须重建前后端并确认构建命令成功结束（`AGENTS.md`）。
后端改动后必须重启 Django 开发服务，并用目标 URL 的真实 HTTP 响应验证新代码已加载。
