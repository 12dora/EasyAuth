# 01 · EasyAuth 后端改造设计

> 基准文档：[`00-overview-and-contract.md`](00-overview-and-contract.md)（下称「契约」）。
> 本文件中出现的 D1–D13 编号、事件名、错误码、payload 形状均以契约为准，此处不重复定义，只给落地方案。
> **§6 的 HTTP API 契约是前端 agent（`02-easyauth-frontend.md`）的依赖，必须最先提交。**

---

## 1. 改造总览

| 模块 | 改动性质 | 说明 |
|---|---|---|
| `lifecycle/models.py` | 扩展 + 破坏性重构 | 新增 4 张表，`HandoverTask` 加 4 字段，`HandoverAppAction` 去掉接收人字段改为条目级 |
| `lifecycle/assignee.py` | **新建** | 主管链解析（契约 §8.2） |
| `lifecycle/escalation.py` | **新建** | 交接单超时上交（契约 §7.4）。~~代管授权~~已废弃 |
| `lifecycle/handover.py` | 重构 | webhook payload v2、新增 items 事件、blocked 判定 |
| `lifecycle/offboarding.py` | 扩展 | 建单时解析 assignee、置上交截止时间、升级路径 |
| `lifecycle/reassign.py` | **新建** | 在职移交建单与管辖校验（D8/D9） |
| `applications/models.py` | 扩展 | `App` 加交接能力三态与资产类型声明 |
| `webhooks/models.py` | 微调 | body 上限常量 |
| `admin_console/lifecycle_api.py` | 扩展 | 新增 skip/claim/items 端点 |
| `portal/` | **新建一组端点** | 自助交接（D1），全部非超管 |
| `tasks/lifecycle.py` | **新建** | 到期上交、每日提醒两个 beat 任务 |
| `sdk/python/.../lifecycle.py` | 扩展 | v2 事件与 items 回调 |
| `docs/decisions/ADR-002` | 修订 | 契约 §3.1 两条 |

**硬约束提醒**（`AGENTS.md`）：项目未上线，**不保留旧形态、不写兼容层**。
`HandoverAppAction.to_user` / `execution_to_user` 直接删除，不做双写、不留过渡字段；
相关迁移直接改列，不保留旧列。所有文档必须中文。

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

**保留并改名**：原 `to_user` → **`grant_receiver`**（契约 §7.2.1）。迁移用 `RenameField`，**不是** Remove+Add。它不再是「数据接收人」，
而是**权限接收人**：该 APP 上离职者的授权转给谁。

- 可为空（留空 = 只撤权、不转授，接收人自行走申请流程；这是安全默认）
- **仅 `kind=offboard` 有意义**，其余 kind 上必须为空
- 与 `HandoverAssetType.default_to_user` / `HandoverAssetOverride.to_user` 是**三个不同的字段**，
  实现时不要合并

```python
models.CheckConstraint(
    condition=Q(task__kind=HANDOVER_KIND_OFFBOARD) | Q(grant_receiver__isnull=True),
    name="lifecycle_action_grant_receiver_only_offboard",
),
```

> 早期版本把 `to_user` 整个删掉，导致 `transfer_selected_grants(action)` 失去输入 ——
> 该函数依赖 action 级接收人，而条目级有多个接收人时无法推断授权该给谁。`grant_receiver` 补上这个洞。

**新增**：

| 字段 | 类型 | 说明 |
|---|---|---|
| `generation` | `PositiveIntegerField(default=1)` | 建 action 时从 `task.generation` 拷贝；升级时重置 |
| `snapshot_token` | `CharField(max_length=128, blank=True)` | preview 响应带回的不透明令牌，execute 时回传（契约 §10.5.1） |
| `batch_seq` | `PositiveIntegerField(default=0)` | 已发出的 execute 批次号，每发一批 +1，作幂等键第三元 |
| `grant_receiver` | `FK(UserMirror, PROTECT, null=True, related_name="handover_grant_receiving")` | 权限接收人，见上 |
| `execution_payload` | `JSONField(default=dict, blank=True)` | 实际发出的 execute 请求体快照，不可变审计凭据 |
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
> **修法**：`started` 的判定改为 `any(a.status not in (ACTION_STATUS_PENDING, ACTION_STATUS_BLOCKED) ...)`，
> 即 `blocked` 与 `pending` 一样不算"有进展"。同时 `skipped`（`capability="none"` 的初始状态）
> 也应排除在 `started` 之外，否则一张全是 `none` 声明的单同样会跳过 `pending`。
> 最终判定：`started = any(a.status not in (PENDING, BLOCKED, SKIPPED) for a in actions) or 团队项有进展`。

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

### 2.5 ~~`CustodyGrant`~~ / ~~`CustodyGrantItem`~~ —— **已取消**

代管授权在第二轮复核后整体废弃（契约 §7、`07-review-log.md` §1.1）。这两张表**不建**，
`HANDOVER_CUSTODY` scope **不加**，`grants/managed_users.py` **不改**。

`HandoverTask` 改为直接持有上交截止时间：

| 字段 | 类型 | 说明 |
|---|---|---|
| `escalation_deadline` | `DateTimeField(null=True, blank=True)` | 建单/上交时置为 `now + HANDOVER_ESCALATION_DAYS`；单终结后置空 |
| `last_reminded_on` | `DateField(null=True, blank=True)` | 每日提醒按**上海业务日**去重（`timezone.localdate(..., Asia/Shanghai)`） |

`HANDOVER_ESCALATION_DAYS: Final = 14`（原 `CUSTODY_TTL_DAYS` 作废）。

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
| `lifecycle` | `00XX_handover_v2_schema.py` | §2.1–§2.6 全部；删除 `HandoverAppAction.to_user`/`execution_to_user`/`policy`/`execution_policy` |

`lifecycle` 迁移必须是**一个**迁移文件完成删列与建表，避免中间态。
数据迁移：存量 `HandoverAppAction.to_user` 不做转换（未上线，无需保留），迁移里直接删列。

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
3. 从 `start_level` 起遍历，逐个用 `dingtalk_userid` 查 `UserMirror`；跳过：
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
2. `res = resolve_assignee(task.subject_user, start_level=task.escalation_level + 1)`（§3）。
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

```
对所有「未终结的 AccessRequest」且其 approver 是 subject 的 AccessRequestApprover 行:
    new_approver = resolve_assignee(该申请的申请人, start_level=0).user   # 沿申请人自己的主管链
    if new_approver is None or new_approver == 申请人:
        → 标记该申请为「需超管处理」并进超管待办, 不静默留在离职者名下
    else:
        approver = new_approver
        审计 handover_approver_reassigned
        通知申请人与新审批人
```

注意审批人要沿**申请人**的主管链解析，不是离职者的 —— 审批权来自"谁管这个申请人"。
唯一约束 `(access_request, approver)` 已存在（`:351`），改派后若与既有审批人重复则删除该行而非报错。

### 4.5.2 钉钉审批规则的审批人替换（必做）

`ApprovalRule.approver_userids` 是 JSON 列表（`applications/models.py:717`）。
离职时把其中的离职者 dingtalk userid 替换为新主管的：

- 替换后列表为空 → **快速失败**并进超管待办（`approval_rule_rules.py:49` 要求非空列表）
- 审计 `handover_approval_rule_approver_replaced`
- 这只影响**新发起**的审批

### 4.5.3 在途钉钉审批实例（本期做不了，必须显式呈现）

`ApprovalInstance` 不存当前审批人，`integrations/dingtalk/api_client.py` 也没有转办接口。
本期的处理是**把问题显式暴露出来**，而不是假装不存在：

- 建单时查出所有 `status` 未终结、且该离职者在其 `ApprovalRule.approver_userids` 里的
  `ApprovalInstance`，作为交接单上的一个**只读清单区块**展示；
- 每条给出钉钉审批的跳转链接与「需人工转办」标记；
- 这些条目**不计入** action 的完成判定（它们不是 APP 资产），但在单据完成时提示
  「仍有 N 条在途审批需在钉钉中人工转办」。

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

### 5.2 descriptor 同步

新增 `applications/handover_capability.py`：

```python
def sync_handover_capability(app: App) -> None: ...
```

- 拉取 `/.well-known/easyauth-app.json`，解析 `lifecycle.handover`（契约 §9.1）。
- 成功 → 写 `handover_capability=declared`、`handover_asset_types`、`handover_capability_synced_at`；
  同步 `AppWebhookConfig.handover_url`。
- 拉取失败或缺 `lifecycle.handover` → **不覆盖**已有的 `none` 声明；否则置 `undeclared`，
  action 建单时即 `blocked`（`blocked_reason="descriptor_unreachable"`）。
- 挂到既有 manifest 同步入口（`api/manifest_sync_views.py`）与控制台"重新同步"按钮。

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

前两条已被 §2.3/§2.4 的 CheckConstraint 挡在库层，此处是 API 层的第二道防线：
库约束保证数据不脏，API 校验保证用户拿到可读的错误。两者都要有。

### 5.5 execute（契约 §10.5）

- 组 payload：`assignments` 由该 `(action, generation)` 下的**全部** `HandoverAssetType`
  （含 `default_action=skip` 的）与其 `overrides` 生成，形状严格照契约 §10.5。
- 把完整请求体写入 `action.execution_payload`（不可变审计凭据），替代原 `execution_to_user`/`execution_policy`。
- `transfer_selected_grants(action)` 的调用条件收紧：**仅 `kind == offboard` 时执行**。
  `pre_offboard` 与 `reassign` 一律不动权限（D7/D9）；`transfer`（转岗）走的是**另一条路** ——
  既有的 `TransferPlan` 差异确认（`lifecycle/transfer.py`），不经过 `transfer_selected_grants`
  的接收人转移语义。三者不可混为一谈，实现时用 `GRANT_MUTATING_KINDS` 与显式分支区分。
- 成功后：`action.status = done` → `refresh_task_status(task)`。

### 5.6 items（契约 §10.4，新增）

```python
def fetch_action_items(action, *, asset_type: str, page: int, page_size: int, q: str) -> dict
```

- 仅当该类型 `detail_supported=True` 才允许调用，否则 `400 detail_not_supported`。
- **透传不落库**（明细可能上千条，落库无意义且会过期）；前端翻页即实时回源。
- 校验 `total` 与同 generation 的 `HandoverAssetType.count` 一致；不一致时**不报错**但在响应里带
  `stale=true`，前端提示"清单已变化，建议重新预演"。

---

## 6. HTTP API 契约（**前端 agent 的依赖，冻结**）

### 6.1 门户（自助，`/portal/api/v1/`，D1）

认证：既有门户会话（OIDC 登录的 active `UserMirror`），**不需要超管**。
授权：见每行的「可访问条件」。越权一律 `404`（与既有门户一致，防枚举）。

| 方法 | 路径 | 可访问条件 | 说明 |
|---|---|---|---|
| GET | `/me/handover-tasks` | 登录即可 | 返回两组：`as_assignee`（我负责的）、`as_subject`（我是当事人的） |
| POST | `/handover-tasks/pre-offboard` | 登录即可，且自己无 open 的 offboard/transfer/pre_offboard 单 | 在职提前交接建单（D7），`kind=pre_offboard`，assignee=本人 |
| POST | `/handover-tasks/reassign` | `subject ∈ 我的 MANAGED_USERS` 且双方 active | 在职移交（D9），必填 `reason`（≥10 字符），否则 `422 reason_required` |
| GET | `/handover-tasks/{task_id}` | 我是 assignee 或 subject | 单据详情，含各 APP action、资产分类、距上交剩余天数 |
| GET | `/handover-tasks/{task_id}/actions/{app_key}/assets/{type}/items` | 同上 | 明细分页，query: `page`、`page_size`、`q` |
| PATCH | `/handover-tasks/{task_id}/actions/{app_key}/assets/{type}` | 我是 assignee | body: `{"default_action": "transfer"\|"release"\|"skip", "default_to_user_id": str\|null}` |
| PUT | `/handover-tasks/{task_id}/actions/{app_key}/assets/{type}/overrides` | 我是 assignee | body: `{"overrides":[{"asset_id":"...","action":"transfer"\|"release"\|"skip","to_user_id":"..."\|null,"label":"..."}]}`，**整体替换** |
| POST | `/handover-tasks/{task_id}/actions/{app_key}/preview` | 我是 assignee | |
| POST | `/handover-tasks/{task_id}/actions/{app_key}/execute` | 我是 assignee | |
| POST | `/handover-tasks/{task_id}/actions/{app_key}/retry` | 我是 assignee | 仅 `failed` 可重试 |
| GET | `/handover-candidates` | 登录即可 | 选人控件数据源，query `q`；只返回 active 且非本人；`kind=reassign` 时限定在我的 `MANAGED_USERS` 内 |

**错误码**（门户专用，均为 `{"error":{"code","message"}}`）：

| HTTP | code | 触发 |
|---|---|---|
| 403 | `out_of_managed_scope` | reassign 的 subject 不在我的管辖范围（契约 §4） |
| 409 | `open_task_exists` | 自助建单时已有 open 的 offboard/transfer 单 |
| 422 | `reason_required` | reassign 未填理由或不足 10 字符 |
| 422 | `receiver_not_active` / `receiver_is_subject` / `receiver_required` / `asset_type_not_releasable` / `duplicate_assignment` | §5.4 |
| 400 | `detail_not_supported` | 该资产类型不支持明细 |

### 6.2 交接单详情响应体（前端据此建类型）

```json
{
  "id": 137,
  "kind": "offboard",
  "status": "in_progress",
  "generation": 1,
  "subject": { "user_id": "3f1a…", "name": "王某某", "department": "华东销售部", "status": "departed" },
  "assignee": { "user_id": "8c44…", "name": "李某某", "state": "manager", "escalation_level": 0 },
  "custody": { "expires_at": "2026-08-24T10:00:00Z", "days_left": 14, "active": true },
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
      "asset_types": []
    }
  ],
  "team_items": [ /* 既有形状不变 */ ]
}
```

`GET /me/handover-tasks` 的列表项是上述对象去掉 `actions`/`team_items`，另加
`pending_app_count`、`blocked_app_count`、`total_asset_count`。

### 6.3 控制台（`/console/api/v1/lifecycle/`，超管）

既有端点保留。新增：

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `.../handover-tasks/{id}/actions/{app_key}/skip` | 强行跳过（D6），body `{"reason": "..."}`，`reason` 必填且 ≥10 字符 |
| POST | `.../handover-tasks/{id}/claim` | 超管认领 `superuser_pool` 中的单，assignee 置为该超管，`assignee_state=manager` |
| POST | `.../handover-tasks/{id}/custody/extend` | 手动续 14 天（不改 `escalation_level`），必填理由 |
| GET | `.../handover-blocked-apps` | 未接入 APP 汇总，供控制台顶部告警条 |
| POST | `.../apps/{app_key}/handover-capability` | 声明 `none`，body `{"reason": "..."}`；写 `declared_by`/`declared_at` |
| POST | `.../apps/{app_key}/handover-capability/sync` | 手动触发 §5.2 descriptor 同步 |

控制台复用 §6.1 的资产/明细端点，但走 `require_superuser` 且不做 assignee 校验。

---

## 7. 异步任务（`tasks/lifecycle.py`，新建）

| 任务 | 周期 | 逻辑 |
|---|---|---|
| `lifecycle_escalation` | beat 每 10 分钟 | 扫 `status in OPEN and escalation_deadline <= now` 的 `HandoverTask`，逐个 `escalate_overdue_task()`。PostgreSQL 下 `select_for_update(skip_locked=True)` 分批（与 `grants` 过期任务同款） |
| `lifecycle_daily_reminder` | beat 每天 09:00（Asia/Shanghai） | 对未完成且有 assignee 的单发钉钉提醒；`last_reminded_on` 用 `timezone.localdate(..., Asia/Shanghai)` 去重保证每业务日一次；上交前 1 天额外发"即将上交"。注意既有 beat schedule 只接受 float interval，crontab 需扩展 |
| `lifecycle_superuser_pool_reminder` | beat 每天 09:05 | `assignee_state=superuser_pool` 且未完成的单，向全体超管推认领通知 |
| `lifecycle_blocked_apps_digest` | beat 每周一 09:10 | 汇总 `blocked` action，向超管推周报 |

全部通过 `outbox.enqueue_task` 入队，遵循既有「网络副作用出事务」的约定。
通知内容与收件人见契约 §13，模板放 `notify/messages.py`。

---

## 8. SDK 改造（`sdk/python/src/easyauth_app_sdk/lifecycle.py`）

1. 新增事件常量 `HANDOVER_ITEMS_EVENT: Final = "lifecycle.handover.items"`。
2. `lifecycle_http_response()` 增参 `on_handover_items: HandoverCallback`，按事件分发。
3. `DEFAULT_MAX_BODY_BYTES` 由 `64 * 1024` 改为 `256 * 1024`（契约 §10.1）。
4. `fastapi.py` 的挂载 helper 同步增加 items 回调参数。
5. 新增 `easyauth_app_sdk/handover_payloads.py`：v2 请求/响应的 `TypedDict` 定义
   （`PreviewRequest`/`PreviewResponse`/`ItemsRequest`/`ItemsResponse`/`ExecuteRequest`/`ExecuteResponse`），
   下游 APP 直接 import 使用，杜绝字段名手抄出错。
6. `sdk/python/CHANGELOG.md` 记为 **breaking**，版本号 minor 升级（未上线，不做兼容分支）。
7. `sdk/python/README.md` 补 v2 接入示例（中文）。

---

## 9. ADR 修订（契约 §3.1）

### ~~ADR-002 修订点 1（§19）~~ —— **已取消**

代管废弃后，`MANAGED_USERS` 不再需要容纳非 active 用户，该条款**保持原样**。

### ADR-002 修订点 2（§36）

原「审批人必须严格为申请人的 active 直属主管；缺少可解析的直属主管时禁止提交」改为：

> 审批人按 `manager_chain` 逐级向上取第一个 active 主管（跳过 departed/disabled/本地管理员/申请人本人）。
> 整条链不可用时进入超管待认领池，由超管审批。仍然**禁止**手动改填 App owner 或任意其他用户绕过。

新增 ADR-005「数据交接 v2 的能力声明与阻塞语义」，记录 D6 的决策与"静默成功"缺陷的修复。

---

## 10. 测试

| 文件 | 覆盖 |
|---|---|
| `tests/unit/lifecycle/test_assignee.py` | 主管链正常/跳过离职主管/整链失效落池/stale 落池/本地管理员跳过/不设层数上限 |
| `tests/unit/lifecycle/test_escalation.py` | 到期上交一级；跳过已离职主管继续向上；到顶落超管池且 `escalation_deadline` 置空；**回归测试：整个流程不产生任何 `AccessGrant` 变更**（代管已废弃，权限面必须零变化）；每业务日只提醒一次且跨时区正确 |
| `tests/unit/lifecycle/test_capability.py` | 三态 → action 初始状态；`declared` 但无 URL 抛错；`none` 缺声明人被约束拒绝 |
| `tests/unit/lifecycle/test_assignments.py` | §5.4 六条校验；三值 action 的库层 CheckConstraint；`releasable=False` 时 `skip`+逐条 `transfer` 可用（部分交接不依赖 releasable）；override 唯一约束；失效 override 被清理并计数 |
| `tests/unit/lifecycle/test_upgrade.py` | pre_offboard → offboard 升级：kind 变更、generation+1、action 重置、assignee 重解析、上交截止时间重置 |
| `tests/unit/lifecycle/test_reassign.py` | 管辖校验、必填理由、与 offboard 单并存不违反唯一约束、三方通知 |
| `tests/integration/test_portal_handover_api.py` | §6.1 全部端点的权限边界（非 assignee 拿到 404） |
| `tests/integration/test_handover_webhook_v2.py` | payload 形状逐字段比对 `tests/contract_samples/` 下的 golden JSON；幂等键 `(task_id, generation, batch_id)` |
| `tests/unit/test_blocked_never_completes.py` | 存在 blocked 时 `refresh_task_status` 永不返回 completed（D13） |

新增 `tests/contract_samples/handover_v2/`：`preview_request.json`、`preview_response.json`、
`items_request.json`、`items_response.json`、`execute_request.json`、`execute_response.json`。
**EasyTrade 与 EasyProject 的契约测试直接复用这批样本**，这是跨仓库对齐的机械保证。

### 执行方式

后端测试走 Docker + uv（host `.venv` 不可用）：

```bash
docker run --rm -v "$PWD":/w -w /w <image> uv run --frozen pytest tests/unit/lifecycle -q
```

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
